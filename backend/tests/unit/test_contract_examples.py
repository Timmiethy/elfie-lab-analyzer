"""Validate shared contract examples against backend schemas."""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.artifact import ClinicianArtifactSchema, PatientArtifactSchema
from app.schemas.lineage import LineageBundleSchema


ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_EXAMPLES = ROOT / "contracts" / "examples"


def _load_json(filename: str) -> dict:
    return json.loads((CONTRACTS_EXAMPLES / filename).read_text())


def test_patient_artifact_example_matches_schema() -> None:
    payload = _load_json("patient_artifact_supported.json")
    parsed = PatientArtifactSchema.model_validate(payload)

    assert parsed.support_banner == "fully_supported"
    assert parsed.language_id == "en"


def test_clinician_artifact_example_matches_schema() -> None:
    payload = _load_json("clinician_artifact_supported.json")
    parsed = ClinicianArtifactSchema.model_validate(payload)

    assert parsed.support_coverage == "fully_supported"
    assert parsed.nextstep_classes


def test_lineage_example_matches_schema() -> None:
    payload = _load_json("lineage_example.json")
    parsed = LineageBundleSchema.model_validate(payload)

    assert parsed.parser_version
    assert parsed.rule_pack_version
