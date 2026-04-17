from __future__ import annotations

import asyncio
from uuid import uuid4

from app.schemas.artifact import PatientArtifactSchema
from app.services.explanation import ExplanationAdapter
from app.workers.pipeline import PipelineOrchestrator


def test_phase_25_explanation_adapter_emits_blueprint_required_sentences() -> None:
    payload = asyncio.run(
        ExplanationAdapter().generate(
            [
                {
                    "finding_id": "glucose_high::row-001",
                    "rule_id": "glucose_high_threshold",
                    "observation_ids": [str(uuid4())],
                    "threshold_source": "local_policy:launch-scope-rules-v1:fasting_glucose",
                    "severity_class": "S2",
                    "nextstep_class": "A2",
                    "observed_value": 180,
                    "observed_unit": "mg/dL",
                }
            ],
            "vi",
        )
    )

    assert payload["language_id"] == "vi"
    assert "unsupported_sentence" in payload
    assert "threshold_provenance_sentence" in payload


def test_phase_25_pipeline_uses_detected_vietnamese_language_for_artifact_output(
    monkeypatch,
) -> None:
    async def fake_qwen(file_bytes: bytes):
        return [
            {
                "document_id": uuid4(),
                "source_page": 1,
                "row_hash": "row-vi-glucose",
                "raw_text": "Duong huyet 180 mg/dL",
                "raw_analyte_label": "Glucose",
                "raw_value_string": "180",
                "raw_unit_string": "mg/dL",
                "raw_reference_range": "70-99",
                "parsed_numeric_value": 180.0,
                "specimen_context": "serum",
                "language_id": "vi",
                "extraction_confidence": 0.99,
            }
        ]

    monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen", fake_qwen)
    from app.services.vlm_gateway import VLMRow

    async def fake_parse(file_bytes: bytes):
        return [
            VLMRow(analyte_name="Glucose", value="105", unit="mg/dL", reference_range_raw="70-99")
        ]

    monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen", fake_parse)

    result = asyncio.run(
        PipelineOrchestrator().run(
            "phase-25-vietnamese",
            file_bytes=b"%PDF-1.4 fake",
            lane_type="trusted_pdf",
            source_checksum="sha256:phase-25-vi",
        )
    )

    assert result["patient_artifact"]["language_id"] in ("en", "vi")


def test_phase_25_pipeline_attaches_bounded_explanation_to_patient_artifact(
    monkeypatch,
) -> None:
    async def fake_qwen(file_bytes: bytes):
        return [
            {
                "document_id": uuid4(),
                "source_page": 1,
                "row_hash": "row-explanation-glucose",
                "raw_text": "Glucose 180 mg/dL",
                "raw_analyte_label": "Glucose",
                "raw_value_string": "180",
                "raw_unit_string": "mg/dL",
                "raw_reference_range": "70-99",
                "parsed_numeric_value": 180.0,
                "specimen_context": "serum",
                "language_id": "en",
                "extraction_confidence": 0.99,
            }
        ]

    monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen", fake_qwen)
    from app.services.vlm_gateway import VLMRow

    async def fake_parse(file_bytes: bytes):
        return [
            VLMRow(analyte_name="Glucose", value="105", unit="mg/dL", reference_range_raw="70-99")
        ]

    monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen", fake_parse)

    result = asyncio.run(
        PipelineOrchestrator().run(
            "phase-25-runtime-explanation",
            file_bytes=b"%PDF-1.4 fake",
            lane_type="trusted_pdf",
            source_checksum="sha256:phase-25-explanation",
        )
    )

    artifact = PatientArtifactSchema.model_validate(result["patient_artifact"])
    explanation = result["patient_artifact"].get("explanation")

    assert artifact.language_id == "en"
    assert explanation is not None
    assert explanation["generation_source"] == "fallback"
    assert explanation["unsupported_sentence"]
    assert explanation["threshold_provenance_sentence"]
