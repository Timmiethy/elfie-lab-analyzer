from __future__ import annotations

from uuid import uuid4

from app.schemas.artifact import ClinicianArtifactSchema, PatientArtifactSchema
from app.services.artifact_renderer import ArtifactRenderer
from app.services.benchmark import BenchmarkRecorder
from app.services.lineage import LineageLogger


def _supported_finding(observation_id) -> dict:
    return {
        "finding_id": "glucose_high::row-001",
        "rule_id": "glucose_high_threshold",
        "observation_ids": [observation_id],
        "threshold_source": "adult_fasting_default_70_99",
        "severity_class": "S2",
        "nextstep_class": "A2",
        "suppression_active": False,
        "suppression_reason": None,
        "explanatory_scaffold_id": "glucose_high_v1",
    }


def _observation(raw_label: str, *, support_state: str, observation_id) -> dict:
    return {
        "id": observation_id,
        "document_id": uuid4(),
        "source_page": 1,
        "row_hash": f"row-{raw_label.lower().replace(' ', '-')}",
        "raw_analyte_label": raw_label,
        "raw_value_string": "n/a",
        "raw_unit_string": None,
        "parsed_numeric_value": None,
        "specimen_context": None,
        "method_context": None,
        "raw_reference_range": None,
        "canonical_unit": None,
        "canonical_value": None,
        "language_id": "en",
        "support_state": support_state,
        "suppression_reasons": [],
    }


def test_phase_37_artifact_runtime_hides_admin_threshold_leaks_and_keeps_honest_unsupported_rows(
) -> None:
    renderer = ArtifactRenderer()
    job_id = uuid4()

    supported_observation_id = uuid4()
    patient = PatientArtifactSchema.model_validate(
        renderer.render_patient(
            [_supported_finding(supported_observation_id)],
            {
                "job_id": job_id,
                "support_banner": "partially_supported",
                "trust_status": "trusted",
                "report_date": "2026-04-12",
            },
            observations=[
                _observation("Glucose", support_state="supported", observation_id=supported_observation_id),
                _observation("MysteryMarker", support_state="partial", observation_id=uuid4()),
                _observation("DOB :", support_state="partial", observation_id=uuid4()),
                _observation("Collected :", support_state="partial", observation_id=uuid4()),
                _observation("Report Printed :", support_state="partial", observation_id=uuid4()),
                _observation("Threshold Table: HbA1c", support_state="partial", observation_id=uuid4()),
            ],
        )
    )
    clinician = ClinicianArtifactSchema.model_validate(
        renderer.render_clinician(
            [_supported_finding(supported_observation_id)],
            {
                "job_id": job_id,
                "support_banner": "partially_supported",
                "trust_status": "trusted",
                "report_date": "2026-04-12",
                "provenance_link": f"/api/jobs/{job_id}/proof-pack",
            },
            observations=[
                _observation("Glucose", support_state="supported", observation_id=supported_observation_id),
                _observation("MysteryMarker", support_state="partial", observation_id=uuid4()),
                _observation("DOB :", support_state="partial", observation_id=uuid4()),
                _observation("Collected :", support_state="partial", observation_id=uuid4()),
                _observation("Report Printed :", support_state="partial", observation_id=uuid4()),
                _observation("Threshold Table: HbA1c", support_state="partial", observation_id=uuid4()),
            ],
        )
    )

    assert {item.raw_label for item in patient.not_assessed} == {"MysteryMarker"}
    assert {item.raw_label for item in clinician.not_assessed} == {"MysteryMarker"}
    assert {item.reason.value for item in patient.not_assessed} == {"unreadable_value"}
    assert {item.reason.value for item in clinician.not_assessed} == {"unreadable_value"}
    assert all("DOB" not in item.raw_label for item in patient.not_assessed)
    assert all("Collected" not in item.raw_label for item in patient.not_assessed)
    assert all("Report Printed" not in item.raw_label for item in patient.not_assessed)
    assert all("Threshold Table" not in item.raw_label for item in patient.not_assessed)

    lineage = LineageLogger().record(
        str(job_id),
        {
            "source_checksum": "checksum-phase-37",
            "parser_version": "trusted-pdf-v1",
            "ocr_version": None,
            "family_adapter_version": "innoquest-bilingual-adapter-v11",
            "row_assembly_version": "geometry-row-assembler-v11",
            "terminology_release": "loinc-2026-04",
            "mapping_threshold_config": {"default": 0.9},
            "unit_engine_version": "ucum-v1",
            "rule_pack_version": "rules-v1",
            "severity_policy_version": "severity-v1",
            "nextstep_policy_version": "nextstep-v1",
            "template_version": "templates-v1",
            "model_version": None,
            "build_commit": "abc123",
        },
    )
    benchmark = BenchmarkRecorder().record(
        lineage_id=str(lineage["id"]),
        report_type="v11_artifact_runtime",
        metrics={
            "processing_ms": 19,
            "parser_precision": 0.991,
            "family_precision": 0.987,
        },
        family_benchmarks={
            "innoquest_bilingual_general": {
                "result_row_recall": 0.98,
                "row_assembly_f1": 0.97,
                "leak_rate": 0.0,
            }
        },
        trace_refs={
            "parser_trace": f"/api/artifacts/{job_id}/parser-trace",
            "normalization_trace": f"/api/artifacts/{job_id}/normalization-trace",
        },
    )
    proof_pack = BenchmarkRecorder().build_proof_pack(
        benchmark=benchmark,
        lineage=lineage,
        artifact_refs={
            "patient_artifact": f"/api/artifacts/{job_id}/patient",
            "clinician_artifact": f"/api/artifacts/{job_id}/clinician",
            "clinician_pdf": f"/api/artifacts/{job_id}/clinician/pdf",
            "parser_trace": f"/api/artifacts/{job_id}/parser-trace",
            "normalization_trace": f"/api/artifacts/{job_id}/normalization-trace",
            "suppression_report": f"/api/artifacts/{job_id}/suppression-report",
        },
        report_metadata={
            "corpus_id": "pdfs_by_difficulty",
            "lane_id": "trusted_pdf",
            "language_id": "en",
            "timestamp": "2026-04-12T00:00:00Z",
        },
    )

    assert proof_pack["trace_refs"] == {
        "parser_trace": f"/api/artifacts/{job_id}/parser-trace",
        "normalization_trace": f"/api/artifacts/{job_id}/normalization-trace",
        "suppression_report": f"/api/artifacts/{job_id}/suppression-report",
    }
    assert proof_pack["family_benchmarks"]["innoquest_bilingual_general"]["leak_rate"] == 0.0
    assert proof_pack["lineage"]["family_adapter_version"] == "innoquest-bilingual-adapter-v11"
    assert proof_pack["lineage"]["row_assembly_version"] == "geometry-row-assembler-v11"
