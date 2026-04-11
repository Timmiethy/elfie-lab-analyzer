"""Phase 11 completion tests for the shared contract package."""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.artifact import ClinicianArtifactSchema, PatientArtifactSchema
from app.schemas.lineage import LineageBundleSchema


ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = ROOT / "contracts"
EXAMPLES_DIR = CONTRACTS_DIR / "examples"

REQUIRED_PATIENT_EXAMPLES = [
    "patient_artifact_supported.json",
    "patient_artifact_partial_support.json",
    "patient_artifact_could_not_assess.json",
    "patient_artifact_unsupported.json",
    "patient_artifact_threshold_conflict.json",
    "patient_artifact_comparable_history_available.json",
    "patient_artifact_comparable_history_unavailable.json",
]

REQUIRED_OTHER_EXAMPLES = [
    "clinician_artifact_supported.json",
    "lineage_example.json",
]


def _load_json(filename: str) -> dict:
    return json.loads((EXAMPLES_DIR / filename).read_text())


def test_contract_readme_exists_and_mentions_shared_freeze() -> None:
    readme = (CONTRACTS_DIR / "README.md").read_text()

    assert "Person A Contract Freeze" in readme
    assert "patient_artifact_supported.json" in readme
    assert "clinician_artifact_supported.json" in readme
    assert "lineage_example.json" in readme


def test_required_contract_example_files_exist() -> None:
    missing = [
        filename
        for filename in [*REQUIRED_PATIENT_EXAMPLES, *REQUIRED_OTHER_EXAMPLES]
        if not (EXAMPLES_DIR / filename).exists()
    ]

    assert missing == []


def test_required_patient_examples_match_schema() -> None:
    for filename in REQUIRED_PATIENT_EXAMPLES:
        payload = _load_json(filename)
        parsed = PatientArtifactSchema.model_validate(payload)
        assert parsed.language_id == "en"


def test_other_contract_examples_match_schema() -> None:
    clinician = ClinicianArtifactSchema.model_validate(
        _load_json("clinician_artifact_supported.json")
    )
    lineage = LineageBundleSchema.model_validate(_load_json("lineage_example.json"))

    assert clinician.top_findings
    assert lineage.rule_pack_version
