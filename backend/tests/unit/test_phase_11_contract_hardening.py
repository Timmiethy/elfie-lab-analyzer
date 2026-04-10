"""Contract hardening tests derived from the source-of-truth split rules."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from app.schemas.artifact import (
    ClinicianArtifactSchema,
    PatientArtifactSchema,
    SupportBanner,
    TrustStatus,
    UnsupportedReason,
)
from app.schemas.finding import FindingSchema, NextStepClass, SeverityClass
from app.schemas.lineage import CONTRACT_VERSION as LINEAGE_CONTRACT_VERSION
from app.schemas.lineage import LineageBundleSchema
from app.schemas.observation import CONTRACT_VERSION as OBSERVATION_CONTRACT_VERSION
from app.schemas.observation import ObservationSchema, SupportState
from app.services.artifact_renderer import ArtifactRenderer
from app.workers.pipeline import PipelineOrchestrator


ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = ROOT / "contracts" / "examples"


def _load_json(filename: str) -> dict:
    return json.loads((EXAMPLES_DIR / filename).read_text())


def test_phase_11_contract_examples_are_explicitly_versioned_and_taxonomized() -> None:
    patient_payload = _load_json("patient_artifact_supported.json")
    clinician_payload = _load_json("clinician_artifact_supported.json")
    lineage_payload = _load_json("lineage_example.json")

    patient = PatientArtifactSchema.model_validate(patient_payload)
    clinician = ClinicianArtifactSchema.model_validate(clinician_payload)
    lineage = LineageBundleSchema.model_validate(lineage_payload)

    assert patient_payload["contract_version"] == OBSERVATION_CONTRACT_VERSION
    assert clinician_payload["contract_version"] == OBSERVATION_CONTRACT_VERSION
    assert lineage_payload["contract_version"] == LINEAGE_CONTRACT_VERSION
    assert patient.contract_version == OBSERVATION_CONTRACT_VERSION
    assert clinician.contract_version == OBSERVATION_CONTRACT_VERSION
    assert lineage.contract_version == LINEAGE_CONTRACT_VERSION
    assert patient.support_banner is SupportBanner.FULLY_SUPPORTED
    assert clinician.support_coverage is SupportBanner.FULLY_SUPPORTED


def test_phase_11_contract_examples_use_closed_unsupported_reason_taxonomy() -> None:
    filenames = [
        "patient_artifact_partial_support.json",
        "patient_artifact_could_not_assess.json",
        "patient_artifact_unsupported.json",
        "patient_artifact_threshold_conflict.json",
        "patient_artifact_comparable_history_unavailable.json",
    ]

    for filename in filenames:
        patient = PatientArtifactSchema.model_validate(_load_json(filename))
        for item in patient.not_assessed:
            assert isinstance(item.reason, UnsupportedReason)


def test_phase_11_contract_examples_include_image_beta_non_trusted_example() -> None:
    patient = PatientArtifactSchema.model_validate(
        _load_json("patient_artifact_image_beta_non_trusted.json")
    )

    assert patient.trust_status is TrustStatus.NON_TRUSTED_BETA
    assert patient.support_banner is SupportBanner.PARTIALLY_SUPPORTED
    assert patient.not_assessed


def test_phase_11_observation_and_finding_contracts_expose_versions() -> None:
    observation = ObservationSchema.model_validate(
        {
            "id": str(uuid4()),
            "document_id": str(uuid4()),
            "source_page": 1,
            "row_hash": "row-001",
            "raw_analyte_label": "Glucose",
            "support_state": "supported",
        }
    )
    finding = FindingSchema.model_validate(
        {
            "finding_id": "glucose_high::row-001",
            "rule_id": "glucose_high_threshold",
            "observation_ids": [str(uuid4())],
            "threshold_source": "adult_fasting_default_70_99",
            "severity_class": "S2",
            "nextstep_class": "A2",
        }
    )

    assert observation.contract_version == OBSERVATION_CONTRACT_VERSION
    assert finding.contract_version == OBSERVATION_CONTRACT_VERSION
    assert observation.support_state is SupportState.SUPPORTED
    assert finding.severity_class is SeverityClass.S2
    assert finding.nextstep_class is NextStepClass.A2


def test_phase_11_artifact_renderer_emits_explicit_trust_status() -> None:
    renderer = ArtifactRenderer()
    findings = [
        {
            "finding_id": "glucose_high::row-001",
            "rule_id": "glucose_high_threshold",
            "observation_ids": [uuid4()],
            "threshold_source": "adult_fasting_default_70_99",
            "severity_class": "S2",
            "nextstep_class": "A2",
        }
    ]

    trusted_patient = PatientArtifactSchema.model_validate(
        renderer.render_patient(
            findings,
            {
                "job_id": str(uuid4()),
                "support_banner": "fully_supported",
                "trust_status": "trusted",
            },
        )
    )
    beta_patient = PatientArtifactSchema.model_validate(
        renderer.render_patient(
            findings,
            {
                "job_id": str(uuid4()),
                "support_banner": "partially_supported",
                "trust_status": "non_trusted_beta",
            },
        )
    )

    assert trusted_patient.trust_status is TrustStatus.TRUSTED
    assert beta_patient.trust_status is TrustStatus.NON_TRUSTED_BETA


def test_phase_11_pipeline_marks_image_beta_artifacts_as_non_trusted(monkeypatch) -> None:
    async def fake_extract(self, file_bytes: bytes, *, document_id, language_id: str) -> list[dict]:
        return [
            {
                "document_id": document_id,
                "source_page": 1,
                "row_hash": "row-image-glucose",
                "raw_text": "Glucose 180 mg/dL",
                "raw_analyte_label": "Glucose",
                "raw_value_string": "180",
                "raw_unit_string": "mg/dL",
                "raw_reference_range": "70-99",
                "parsed_numeric_value": 180.0,
                "specimen_context": "serum",
                "language_id": language_id,
                "extraction_confidence": 0.93,
            }
        ]

    monkeypatch.setattr("app.workers.pipeline.OcrAdapter.extract", fake_extract)

    result = asyncio.run(
        PipelineOrchestrator().run(
            "phase-11-image-beta",
            file_bytes=b"fake-image",
            lane_type="image_beta",
            source_checksum="sha256:image-beta",
        )
    )

    patient = PatientArtifactSchema.model_validate(result["patient_artifact"])
    clinician = ClinicianArtifactSchema.model_validate(result["clinician_artifact"])

    assert patient.trust_status is TrustStatus.NON_TRUSTED_BETA
    assert clinician.trust_status is TrustStatus.NON_TRUSTED_BETA
    assert result["lane_type"] == "image_beta"
