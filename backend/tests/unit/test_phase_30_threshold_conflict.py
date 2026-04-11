from __future__ import annotations

import asyncio
from uuid import uuid4

from app.services.nextstep_policy import NextStepPolicyEngine
from app.services.rule_engine import RuleEngine
from app.services.severity_policy import SeverityPolicyEngine
from app.workers.pipeline import PipelineOrchestrator


def _supported_observation(value: float, *, raw_reference_range: str) -> dict:
    return {
        "id": uuid4(),
        "document_id": uuid4(),
        "source_page": 1,
        "row_hash": f"glucose-{value}",
        "raw_analyte_label": "Glucose",
        "raw_value_string": str(value),
        "raw_unit_string": "mg/dL",
        "parsed_numeric_value": value,
        "canonical_value": value,
        "canonical_unit": "mg/dL",
        "accepted_analyte_code": "2345-7",
        "accepted_analyte_display": "Glucose",
        "specimen_context": "serum",
        "raw_reference_range": raw_reference_range,
        "support_state": "supported",
    }


def test_phase_30_rule_engine_emits_threshold_conflict_when_printed_range_and_policy_disagree(
) -> None:
    rule_engine = RuleEngine()
    severity_policy = SeverityPolicyEngine()
    nextstep_policy = NextStepPolicyEngine()

    findings = rule_engine.evaluate(
        [_supported_observation(95, raw_reference_range="60-90")],
        {"age_years": 42, "sex": "female", "language_id": "en"},
    )
    findings = severity_policy.assign(findings, {"age_years": 42, "sex": "female"})
    findings = nextstep_policy.assign(findings, {"age_years": 42, "sex": "female"})

    assert len(findings) == 1
    assert findings[0]["rule_id"] == "glucose_threshold_conflict"
    assert findings[0]["threshold_source"] == "conflicting_threshold_sources"
    assert findings[0]["suppression_active"] is True
    assert findings[0]["suppression_reason"] == "threshold_conflict"
    assert findings[0]["severity_class"] == "SX"
    assert findings[0]["nextstep_class"] == "AX"


def test_phase_30_rule_engine_keeps_policy_stricter_than_printed_range_actionable() -> None:
    rule_engine = RuleEngine()
    severity_policy = SeverityPolicyEngine()
    nextstep_policy = NextStepPolicyEngine()

    findings = rule_engine.evaluate(
        [_supported_observation(105, raw_reference_range="70-110")],
        {"age_years": 42, "sex": "female", "language_id": "en"},
    )
    findings = severity_policy.assign(findings, {"age_years": 42, "sex": "female"})
    findings = nextstep_policy.assign(findings, {"age_years": 42, "sex": "female"})

    assert len(findings) == 1
    assert findings[0]["rule_id"] == "glucose_high_threshold"
    assert findings[0]["suppression_active"] is False
    assert findings[0]["severity_class"] == "S1"
    assert findings[0]["nextstep_class"] == "A1"


def test_phase_30_pipeline_surfaces_threshold_conflict_in_patient_artifact(monkeypatch) -> None:
    async def fake_extract_rows(job_uuid, *, file_bytes, lane_type):
        return [
            {
                "document_id": job_uuid,
                "source_page": 1,
                "row_hash": "row-glucose-threshold-conflict",
                "raw_text": "Glucose 95 mg/dL 60-90",
                "raw_analyte_label": "Glucose",
                "raw_value_string": "95",
                "raw_unit_string": "mg/dL",
                "raw_reference_range": "60-90",
                "parsed_numeric_value": 95.0,
                "specimen_context": "serum",
                "language_id": "en",
                "extraction_confidence": 0.99,
            }
        ]

    monkeypatch.setattr("app.workers.pipeline._extract_rows", fake_extract_rows)

    result = asyncio.run(
        PipelineOrchestrator().run(
            "phase-30-threshold-conflict",
            file_bytes=b"trusted-pdf",
            lane_type="trusted_pdf",
            source_checksum="sha256:phase30",
        )
    )

    assert result["patient_artifact"]["support_banner"] == "could_not_assess"
    assert result["patient_artifact"]["flagged_cards"] == []
    assert {item["reason"] for item in result["patient_artifact"]["not_assessed"]} >= {
        "threshold_conflict"
    }
    assert result["findings"][0]["rule_id"] == "glucose_threshold_conflict"
