from __future__ import annotations

import asyncio
import json

from app.schemas.artifact import PatientArtifactSchema
from app.services.input_gateway import InputGateway
from app.workers.pipeline import PipelineOrchestrator


def test_phase_27_input_gateway_classifies_fhir_json_as_structured_lane() -> None:
    payload = asyncio.run(
        InputGateway().classify(
            b'{\"resourceType\":\"DiagnosticReport\",\"status\":\"final\"}',
            "diagnostic-report.json",
            "application/fhir+json",
        )
    )

    assert payload["lane_type"] == "structured"
    assert payload["extension"] == ".json"


def test_phase_27_pipeline_accepts_structured_import_without_parser_or_ocr() -> None:
    structured_payload = {
        "language_id": "en",
        "observations": [
            {
                "source_page": 1,
                "row_hash": "structured-row-glucose",
                "raw_text": "Glucose 180 mg/dL",
                "raw_analyte_label": "Glucose",
                "raw_value_string": "180",
                "raw_unit_string": "mg/dL",
                "parsed_numeric_value": 180.0,
                "raw_reference_range": "70-99",
                "specimen_context": "serum",
                "language_id": "en",
                "extraction_confidence": 1.0,
            }
        ],
    }

    result = asyncio.run(
        PipelineOrchestrator().run(
            "phase-27-structured",
            file_bytes=json.dumps(structured_payload).encode("utf-8"),
            lane_type="structured",
            source_checksum="sha256:structured-import",
        )
    )

    artifact = PatientArtifactSchema.model_validate(result["patient_artifact"])

    assert result["lane_type"] == "structured"
    assert artifact.support_banner.value == "fully_supported"
