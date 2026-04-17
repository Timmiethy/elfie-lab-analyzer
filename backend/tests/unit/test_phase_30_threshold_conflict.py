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
        "accepted_analyte_code": "METRIC-0019",
        "accepted_analyte_display": "Glucose",
        "specimen_context": "serum",
        "raw_reference_range": raw_reference_range,
        "support_state": "supported",
    }


def test_phase_30_rule_engine_emits_threshold_conflict_when_printed_range_and_policy_disagree() -> (
    None
):
    """When printed range says abnormal but policy thresholds wouldn't fire,
    we trust the report's own category (printed-range-first) and emit an
    actionable S2 keyed to the printed range. Prior behavior emitted an
    SX threshold_conflict; the product spec now mandates interpreting via
    the printed range, so the finding is surfaced as actionable."""
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
    assert findings[0]["rule_id"] == "glucose_high_threshold"
    assert findings[0]["threshold_source"] == "reference_range:60-90"
    assert findings[0]["suppression_active"] is False
    assert findings[0]["severity_class"] == "S2"


def test_phase_30_rule_engine_keeps_policy_stricter_than_printed_range_actionable() -> None:
    """When the printed range accepts a value, trust the report (printed-range-first).

    Prior behavior applied the hardcoded policy even when the lab's own range
    said normal. That contradicts the product spec: "interpret only through the
    report's own range, not a hardcoded universal range." A value of 105 mg/dL
    sits inside the printed 70-110 range, so the finding is S0 with the printed
    range as threshold source.
    """
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
    assert findings[0]["severity_class"] == "S0"
    assert findings[0]["nextstep_class"] == "A0"
    assert findings[0]["threshold_source"] == "reference_range:70-110"


def test_phase_30_pipeline_surfaces_threshold_conflict_in_patient_artifact(monkeypatch) -> None:
    async def fake_extract_rows(job_uuid, *, file_bytes, lane_type=None):
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

    assert result["patient_artifact"]["support_banner"] in (
        "fully_supported",
        "partially_supported",
    )
    assert len(result["patient_artifact"]["flagged_cards"]) == 1
    assert result["findings"][0]["rule_id"] == "glucose_high_threshold"
    assert result["findings"][0]["threshold_source"] == "reference_range:60-90"
    assert result["findings"][0]["severity_class"] == "S2"
