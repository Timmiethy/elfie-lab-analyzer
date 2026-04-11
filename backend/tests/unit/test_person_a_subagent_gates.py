"""Phase-based acceptance gates for Person A delegated work.

These tests are intentionally strict and are expected to start red while the
truth engine is still scaffolded. Each test is a concrete pass/fail gate for a
subagent-owned phase from tasks/todo.md.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.schemas.artifact import ClinicianArtifactSchema, PatientArtifactSchema
from app.schemas.finding import FindingSchema, NextStepClass, SeverityClass
from app.schemas.lineage import LineageBundleSchema
from app.schemas.observation import MappingCandidateSchema, ObservationSchema, SupportState
from app.services.analyte_resolver import AnalyteResolver
from app.services.artifact_renderer import ArtifactRenderer
from app.services.benchmark import BenchmarkRecorder
from app.services.extraction_qa import ExtractionQA
from app.services.input_gateway import InputGateway
from app.services.lineage import LineageLogger
from app.services.nextstep_policy import NextStepPolicyEngine
from app.services.observation_builder import ObservationBuilder
from app.services.rule_engine import RuleEngine
from app.services.severity_policy import SeverityPolicyEngine
from app.services.ucum import UcumEngine
from app.workers.pipeline import PipelineOrchestrator


def _sample_extracted_rows() -> list[dict]:
    document_id = uuid4()
    return [
        {
            "document_id": document_id,
            "source_page": 1,
            "row_hash": "row-glucose",
            "raw_text": "Glucose 180 mg/dL",
            "raw_analyte_label": "Glucose",
            "raw_value_string": "180",
            "raw_unit_string": "mg/dL",
            "raw_reference_range": "70-99",
            "extraction_confidence": 0.99,
        },
        {
            "document_id": document_id,
            "source_page": 1,
            "row_hash": "row-hba1c",
            "raw_text": "HbA1c 6.8 %",
            "raw_analyte_label": "HbA1c",
            "raw_value_string": "6.8",
            "raw_unit_string": "%",
            "raw_reference_range": "<5.7",
            "extraction_confidence": 0.98,
        },
    ]


def _sample_patient_context() -> dict:
    return {
        "patient_id": str(uuid4()),
        "age_years": 42,
        "sex": "female",
        "language_id": "en",
    }


def test_phase_1_input_gateway_classifies_supported_pdf() -> None:
    gateway = InputGateway()

    result = asyncio.run(
        gateway.classify(
            file_bytes=b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n",
            filename="baseline-labs.pdf",
            mime_type="application/pdf",
        )
    )

    assert result["lane_type"] == "trusted_pdf"
    assert result["mime_type"] == "application/pdf"
    assert result["file_size_bytes"] > 0
    assert result["sanitized_filename"] == "baseline-labs.pdf"
    assert isinstance(result["checksum"], str)
    assert result["checksum"]


def test_phase_1_input_gateway_rejects_unsupported_extension() -> None:
    gateway = InputGateway()

    with pytest.raises(ValueError):
        asyncio.run(
            gateway.classify(
                file_bytes=b"not-a-lab-report",
                filename="malware.exe",
                mime_type="application/octet-stream",
            )
        )


def test_phase_2_extraction_qa_and_observation_builder_promote_clean_rows() -> None:
    rows = _sample_extracted_rows()

    qa_result = ExtractionQA().validate(rows)

    assert qa_result["passed"] is True
    assert qa_result["rejected_rows"] == []
    assert qa_result["metrics"]["total_rows"] == len(rows)

    observations = ObservationBuilder().build(qa_result["clean_rows"])
    parsed = [ObservationSchema.model_validate(observation) for observation in observations]

    assert len(parsed) == 2
    assert all(observation.support_state == SupportState.PARTIAL for observation in parsed)
    assert all(observation.contract_version == "observation-contract-v1" for observation in parsed)
    assert {observation.raw_analyte_label for observation in parsed} == {"Glucose", "HbA1c"}


def test_phase_2_extraction_qa_rejects_rows_missing_analyte_label() -> None:
    qa_result = ExtractionQA().validate(
        [
            {
                "document_id": uuid4(),
                "source_page": 1,
                "row_hash": "row-missing-label",
                "raw_text": "180 mg/dL",
                "raw_analyte_label": "",
                "raw_value_string": "180",
                "raw_unit_string": "mg/dL",
            }
        ]
    )

    assert qa_result["passed"] is False
    assert qa_result["clean_rows"] == []
    assert qa_result["rejected_rows"][0]["reason"] == "missing_analyte_label"


def test_phase_3_analyte_resolver_accepts_high_confidence_match() -> None:
    result = AnalyteResolver().resolve(
        raw_label="Glucose",
        context={"specimen_context": "serum", "language_id": "en"},
    )

    candidates = [MappingCandidateSchema.model_validate(candidate) for candidate in result["candidates"]]
    accepted_candidate = result["accepted_candidate"]

    assert candidates
    assert accepted_candidate is not None
    assert accepted_candidate["score"] >= accepted_candidate["threshold_used"]
    assert any(candidate.accepted for candidate in candidates)
    assert result["support_state"] == SupportState.SUPPORTED.value


def test_phase_3_analyte_resolver_abstains_below_threshold() -> None:
    result = AnalyteResolver().resolve(
        raw_label="Totally Unknown Biomarker",
        context={"specimen_context": "serum", "language_id": "en"},
    )

    candidates = [MappingCandidateSchema.model_validate(candidate) for candidate in result["candidates"]]

    assert result["accepted_candidate"] is None
    assert all(candidate.accepted is False for candidate in candidates)
    assert result["support_state"] in {
        SupportState.PARTIAL.value,
        SupportState.UNSUPPORTED.value,
    }


def test_phase_3_ucum_engine_preserves_supported_units_and_rejects_unknown_units() -> None:
    engine = UcumEngine()

    supported = engine.validate_and_convert(180.0, "mg/dL", "mg/dL")

    assert supported["canonical_value"] == pytest.approx(180.0)
    assert supported["canonical_unit"] == "mg/dL"

    with pytest.raises(ValueError):
        engine.validate_and_convert(180.0, "bananas", "mg/dL")


def test_phase_4_rule_and_policy_engines_emit_closed_classes() -> None:
    observation = ObservationSchema(
        id=uuid4(),
        document_id=uuid4(),
        source_page=1,
        row_hash="row-glucose",
        raw_analyte_label="Glucose",
        raw_value_string="180",
        raw_unit_string="mg/dL",
        parsed_numeric_value=180.0,
        accepted_analyte_code="2345-7",
        accepted_analyte_display="Glucose [Mass/volume] in Serum or Plasma",
        specimen_context="serum",
        method_context=None,
        raw_reference_range="70-99",
        canonical_unit="mg/dL",
        canonical_value=180.0,
        language_id="en",
        support_state=SupportState.SUPPORTED,
        suppression_reasons=[],
    )

    patient_context = _sample_patient_context()
    rule_findings = RuleEngine().evaluate([observation.model_dump()], patient_context)
    severity_applied = SeverityPolicyEngine().assign(rule_findings, patient_context)
    fully_classified = NextStepPolicyEngine().assign(severity_applied, patient_context)
    parsed = [FindingSchema.model_validate(finding) for finding in fully_classified]

    assert parsed
    assert {finding.severity_class for finding in parsed} <= set(SeverityClass)
    assert {finding.nextstep_class for finding in parsed} <= set(NextStepClass)
    assert all(finding.rule_id for finding in parsed)
    assert all(finding.observation_ids for finding in parsed)


def test_phase_5_artifact_and_provenance_outputs_are_schema_valid() -> None:
    job_id = uuid4()
    finding = FindingSchema(
        finding_id="glucose-high",
        rule_id="glucose_high_threshold",
        observation_ids=[uuid4()],
        threshold_source="adult_fasting_default",
        severity_class=SeverityClass.S2,
        nextstep_class=NextStepClass.A2,
        suppression_conditions=None,
        suppression_active=False,
        suppression_reason=None,
        explanatory_scaffold_id="glucose_high_v1",
    )
    render_context = {
        "job_id": job_id,
        "language_id": "en",
        "support_banner": "fully_supported",
        "report_date": "2026-04-10",
    }

    renderer = ArtifactRenderer()
    patient = PatientArtifactSchema.model_validate(
        renderer.render_patient([finding.model_dump()], render_context)
    )
    clinician = ClinicianArtifactSchema.model_validate(
        renderer.render_clinician([finding.model_dump()], render_context)
    )

    lineage = LineageBundleSchema.model_validate(
        LineageLogger().record(
            str(job_id),
            {
                "source_checksum": "checksum-123",
                "parser_version": "trusted-pdf-v1",
                "ocr_version": None,
                "terminology_release": "loinc-2026-01",
                "mapping_threshold_config": {"default": 0.92},
                "unit_engine_version": "ucum-v1",
                "rule_pack_version": "rules-v1",
                "severity_policy_version": "severity-v1",
                "nextstep_policy_version": "nextstep-v1",
                "template_version": "templates-v1",
                "model_version": None,
                "build_commit": "abc123",
            },
        )
    )

    benchmark = BenchmarkRecorder().record(
        lineage_id=str(lineage.id),
        report_type="subagent_phase_eval",
        metrics={"strict_pass_rate": 1.0},
    )

    assert patient.job_id == job_id
    assert clinician.job_id == job_id
    assert lineage.job_id == job_id
    assert benchmark["lineage_id"] == str(lineage.id)
    assert benchmark["report_type"] == "subagent_phase_eval"
    assert benchmark["metrics"]["strict_pass_rate"] == pytest.approx(1.0)


def test_phase_6_pipeline_orchestrator_returns_completion_bundle() -> None:
    result = asyncio.run(PipelineOrchestrator().run("job-phase-6"))

    assert result["job_id"] == "job-phase-6"
    assert result["status"] in {"completed", "partial"}
    assert "patient_artifact" in result
    assert "clinician_artifact" in result
    assert "lineage" in result
    PatientArtifactSchema.model_validate(result["patient_artifact"])
    ClinicianArtifactSchema.model_validate(result["clinician_artifact"])
    LineageBundleSchema.model_validate(result["lineage"])
