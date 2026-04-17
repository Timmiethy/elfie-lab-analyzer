from __future__ import annotations

from app.services.vlm_gateway import VLMRow


def _qwen_row(*, document_id=None):
    return VLMRow(
        analyte_name="Glucose",
        value="180",
        unit="mg/dL",
        reference_range_raw="70-99",
        confidence_score=99,
    )


import asyncio
import json
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from app.config import settings
from app.schemas.artifact import ClinicianArtifactSchema, PatientArtifactSchema, TrustStatus
from app.workers import pipeline as pipeline_module


def _supported_row(*, document_id, language_id: str = "en") -> dict:
    return {
        "document_id": document_id,
        "source_page": 1,
        "row_hash": f"row-{language_id}-glucose",
        "raw_text": "Glucose 180 mg/dL",
        "raw_analyte_label": "Glucose",
        "raw_value_string": "180",
        "raw_unit_string": "mg/dL",
        "raw_reference_range": "70-99",
        "parsed_numeric_value": 180.0,
        "specimen_context": "serum",
        "language_id": language_id,
        "extraction_confidence": 0.99,
    }


def test_phase_28_trusted_pdf_lane_keeps_render_and_lineage_contracts(monkeypatch) -> None:
    async def fake_qwen(file_bytes: bytes):
        return [_qwen_row()]

    monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen", fake_qwen)
    monkeypatch.setattr(
        pipeline_module,
        "get_loaded_snapshot_metadata",
        lambda: {"release": "loinc-phase-28"},
    )

    result = asyncio.run(
        pipeline_module.PipelineOrchestrator().run(
            "phase-28-trusted",
            file_bytes=b"%PDF-1.4 fake",
            lane_type="trusted_pdf",
            source_checksum="sha256:phase-28-trusted",
        )
    )

    patient = PatientArtifactSchema.model_validate(result["patient_artifact"])

    assert patient.trust_status is TrustStatus.TRUSTED
    assert result["lineage"]["parser_version"] == "vlm-parser-v2"
    assert result["lineage"]["ocr_version"] is None
    assert result["lineage"]["terminology_release"] == "loinc-phase-28"


def test_phase_28_image_beta_lane_keeps_beta_render_and_lineage_contracts(monkeypatch) -> None:
    monkeypatch.setattr(settings, "image_beta_enabled", True)

    async def fake_qwen(file_bytes: bytes):
        return [_qwen_row()]

    monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen", fake_qwen)
    monkeypatch.setattr(
        pipeline_module,
        "get_loaded_snapshot_metadata",
        lambda: {"release": "loinc-phase-28"},
    )

    result = asyncio.run(
        pipeline_module.PipelineOrchestrator().run(
            "phase-28-image-beta",
            file_bytes=b"fake-image",
            lane_type="image_beta",
            source_checksum="sha256:phase-28-image-beta",
        )
    )

    patient = PatientArtifactSchema.model_validate(result["patient_artifact"])
    clinician = ClinicianArtifactSchema.model_validate(result["clinician_artifact"])

    assert patient.trust_status is TrustStatus.NON_TRUSTED_BETA
    assert clinician.trust_status is TrustStatus.NON_TRUSTED_BETA
    assert result["lineage"]["parser_version"] == "vlm-parser-v2"
    assert result["lineage"]["ocr_version"] is None
    assert result["lineage"]["terminology_release"] == "loinc-phase-28"


def test_phase_28_image_beta_lane_uses_vlm_backend_once(monkeypatch) -> None:
    captured = {"calls": 0}

    async def fake_process_image_with_qwen(image_bytes: bytes) -> list[VLMRow]:
        captured["calls"] += 1
        return [
            VLMRow(analyte_name="Glucose", value="180", unit="mg/dL", reference_range_raw="70-99")
        ]

    monkeypatch.setattr(settings, "image_beta_enabled", True)
    monkeypatch.setattr(
        "app.services.mineru_adapter.process_image_with_qwen", fake_process_image_with_qwen
    )
    monkeypatch.setattr(
        pipeline_module,
        "get_loaded_snapshot_metadata",
        lambda: {"release": "loinc-phase-28"},
    )

    result = asyncio.run(
        pipeline_module.PipelineOrchestrator().run(
            "phase-28-image-beta-vlm",
            file_bytes=b"fake-image",
            lane_type="image_beta",
            source_checksum="sha256:phase-28-image-beta-vlm",
        )
    )

    patient = PatientArtifactSchema.model_validate(result["patient_artifact"])

    assert captured["calls"] == 1
    assert result["qa"]["clean_rows"]
    assert result["lineage"]["ocr_version"] is None
    assert patient.trust_status is TrustStatus.NON_TRUSTED_BETA


def test_phase_28_pipeline_persistence_bundle_stays_json_safe(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    async def fake_parse(file_bytes: bytes) -> list[VLMRow]:
        return [_qwen_row()]

    class FakeStore:
        def __init__(self, session: object) -> None:
            self.session = session

        async def create_extracted_row(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_observation(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_mapping_candidate(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_rule_event(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_policy_event(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def persist_top_level_bundle(self, **kwargs):
            captured.update(kwargs)
            return None

    monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen", fake_parse)
    monkeypatch.setattr(pipeline_module, "TopLevelLifecycleStore", FakeStore)

    asyncio.run(
        pipeline_module.PipelineOrchestrator().run(
            "phase-28-json-safe",
            file_bytes=b"%PDF-1.4 fake",
            lane_type="trusted_pdf",
            db_session=object(),
            source_checksum="sha256:phase-28-json-safe",
        )
    )

    expected_job_id = str(uuid5(NAMESPACE_URL, "job:phase-28-json-safe"))
    patient_payload = captured["patient_artifact"]["content"]
    clinician_payload = captured["clinician_artifact"]["content"]

    assert captured["status"] == "completed"
    assert patient_payload["job_id"] == expected_job_id
    assert patient_payload["trust_status"] == "trusted"
    assert patient_payload["support_banner"] == "fully_supported"
    assert clinician_payload["job_id"] == expected_job_id
    assert clinician_payload["trust_status"] == "trusted"


def test_phase_28_structured_lane_rejects_non_list_observations_payload() -> None:
    payload = json.dumps({"observations": {"row": "invalid"}}).encode()

    with pytest.raises(ValueError, match="structured_observations_not_list"):
        asyncio.run(
            pipeline_module._extract_rows(
                uuid4(),
                file_bytes=payload,
                lane_type="structured",
            )
        )


def test_phase_28_structured_lane_rejects_missing_required_fields() -> None:
    payload = json.dumps(
        {
            "observations": [
                {
                    "source_page": 1,
                    "raw_value_string": "96",
                }
            ]
        }
    ).encode()

    with pytest.raises(ValueError, match="structured_observation_missing_fields"):
        asyncio.run(
            pipeline_module._extract_rows(
                uuid4(),
                file_bytes=payload,
                lane_type="structured",
            )
        )
