from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

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
    async def fake_parse(self, file_bytes: bytes, *, max_pages: int | None = None) -> list[dict]:
        return [_supported_row(document_id=uuid4())]

    monkeypatch.setattr("app.workers.pipeline.TrustedPdfParser.parse", fake_parse)
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
    assert result["lineage"]["parser_version"] == "trusted-pdf-v1"
    assert result["lineage"]["ocr_version"] is None
    assert result["lineage"]["terminology_release"] == "loinc-phase-28"


def test_phase_28_image_beta_lane_keeps_beta_render_and_lineage_contracts(monkeypatch) -> None:
    async def fake_extract(
        self,
        file_bytes: bytes,
        *,
        document_id,
        language_id: str,
    ) -> list[dict]:
        return [_supported_row(document_id=document_id, language_id=language_id)]

    monkeypatch.setattr("app.workers.pipeline.OcrAdapter.extract", fake_extract)
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
    assert result["lineage"]["parser_version"] == "image-beta-bypass"
    assert result["lineage"]["ocr_version"] == "beta-adapter-v1"
    assert result["lineage"]["terminology_release"] == "loinc-phase-28"


def test_phase_28_pipeline_persistence_bundle_stays_json_safe(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    async def fake_parse(self, file_bytes: bytes, *, max_pages: int | None = None) -> list[dict]:
        return [_supported_row(document_id=uuid4())]

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

    monkeypatch.setattr("app.workers.pipeline.TrustedPdfParser.parse", fake_parse)
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
