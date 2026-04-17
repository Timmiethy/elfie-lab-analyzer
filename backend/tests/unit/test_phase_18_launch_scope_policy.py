"""Phase 18 launch-scope analyte and policy coverage tests."""

from __future__ import annotations

from uuid import uuid4

from app.schemas.finding import NextStepClass, SeverityClass
from app.services.analyte_resolver import AnalyteResolver
from app.services.nextstep_policy import NextStepPolicyEngine
from app.services.panel_reconstructor import PanelReconstructor
from app.services.rule_engine import RuleEngine
from app.services.severity_policy import SeverityPolicyEngine
from app.workers.pipeline import PipelineOrchestrator


def _supported_observation(
    raw_analyte_label: str,
    *,
    value: float,
    unit: str,
    accepted_analyte_code: str | None = None,
    accepted_analyte_display: str | None = None,
    raw_reference_range: str | None = None,
    specimen_context: str = "serum",
) -> dict:
    return {
        "id": uuid4(),
        "document_id": uuid4(),
        "source_page": 1,
        "row_hash": f"{raw_analyte_label.lower().replace(' ', '-')}-{value}",
        "raw_analyte_label": raw_analyte_label,
        "raw_value_string": str(value),
        "raw_unit_string": unit,
        "parsed_numeric_value": value,
        "canonical_value": value,
        "canonical_unit": unit,
        "accepted_analyte_code": accepted_analyte_code,
        "accepted_analyte_display": accepted_analyte_display or raw_analyte_label,
        "specimen_context": specimen_context,
        "raw_reference_range": raw_reference_range,
        "support_state": "supported",
    }


def test_phase_18_analyte_resolver_supports_required_launch_scope_analytes() -> None:
    resolver = AnalyteResolver()

    launch_scope_cases = [
        ("Fasting glucose", {"specimen_context": "serum", "language_id": "en"}),
        ("HbA1c", {"specimen_context": "blood", "language_id": "en"}),
        ("Creatinine", {"specimen_context": "serum", "language_id": "en"}),
        ("eGFR", {"specimen_context": "serum", "language_id": "en"}),
        ("Total cholesterol", {"specimen_context": "serum", "language_id": "en"}),
        ("LDL-C", {"specimen_context": "serum", "language_id": "en"}),
        ("HDL-C", {"specimen_context": "serum", "language_id": "en"}),
        ("Triglycerides", {"specimen_context": "serum", "language_id": "en"}),
    ]

    for raw_label, context in launch_scope_cases:
        resolved = resolver.resolve(raw_label, context)
        assert resolved["support_state"] == "supported"
        assert resolved["accepted_candidate"] is not None
        assert resolved["accepted_candidate"]["candidate_display"]


def test_phase_18_panel_reconstructor_groups_lipid_and_kidney_panels() -> None:
    reconstructor = PanelReconstructor()
    observations = [
        _supported_observation("Glucose", value=110, unit="mg/dL", accepted_analyte_code="METRIC-0019"),
        _supported_observation("LDL-C", value=170, unit="mg/dL", accepted_analyte_code="METRIC-0053"),
        _supported_observation("HDL-C", value=35, unit="mg/dL", accepted_analyte_code="METRIC-0052"),
        _supported_observation(
            "Triglycerides", value=220, unit="mg/dL", accepted_analyte_code="METRIC-0054"
        ),
        _supported_observation(
            "eGFR", value=52, unit="mL/min/1.73 m2", accepted_analyte_code="METRIC-0030"
        ),
    ]

    panels = reconstructor.reconstruct(observations)

    assert {panel["panel_key"] for panel in panels} == {"glycemia", "lipid", "kidney"}


def test_phase_18_rule_engine_emits_multiple_lipid_findings_and_skips_unsupported_rows() -> None:
    rule_engine = RuleEngine()
    severity_policy = SeverityPolicyEngine()
    nextstep_policy = NextStepPolicyEngine()
    patient_context = {"age_years": 42, "sex": "female", "language_id": "en"}
    observations = [
        _supported_observation(
            "Total cholesterol", value=250, unit="mg/dL", accepted_analyte_code="METRIC-0051"
        ),
        _supported_observation("LDL-C", value=170, unit="mg/dL", accepted_analyte_code="METRIC-0053"),
        _supported_observation("HDL-C", value=35, unit="mg/dL", accepted_analyte_code="METRIC-0052"),
        _supported_observation(
            "Triglycerides", value=220, unit="mg/dL", accepted_analyte_code="METRIC-0054"
        ),
        {
            **_supported_observation("MysteryMarker", value=7.2, unit="zz"),
            "support_state": "unsupported",
            "accepted_analyte_code": None,
            "accepted_analyte_display": None,
        },
    ]

    findings = rule_engine.evaluate(observations, patient_context)
    findings = severity_policy.assign(findings, patient_context)
    findings = nextstep_policy.assign(findings, patient_context)

    print("\nXXX", [(f.get("rule_id"), f.get("suppression_reason")) for f in findings], "\n")

    assert {finding["rule_id"] for finding in findings} == {
        "total_cholesterol_high_threshold",
        "ldl_high_threshold",
        "hdl_low_threshold",
        "triglycerides_high_threshold",
        "unsupported_analyte",
    }
    assert {finding["severity_class"] for finding in findings} <= {"S1", "S2", "S3", "SX"}
    assert {finding["nextstep_class"] for finding in findings} <= {"A1", "A2", "A3", "AX"}


def test_phase_18_kidney_rules_require_overlay_and_suppress_when_missing() -> None:
    rule_engine = RuleEngine()
    severity_policy = SeverityPolicyEngine()
    nextstep_policy = NextStepPolicyEngine()
    egfr_observation = _supported_observation(
        "eGFR",
        value=52,
        unit="mL/min/1.73 m2",
        accepted_analyte_code="METRIC-0030",
        raw_reference_range=">=60",
    )

    with_overlay = nextstep_policy.assign(
        severity_policy.assign(
            rule_engine.evaluate([egfr_observation], {"age_years": 62, "sex": "female"}),
            {"age_years": 62, "sex": "female"},
        ),
        {"age_years": 62, "sex": "female"},
    )
    without_overlay = nextstep_policy.assign(
        severity_policy.assign(
            rule_engine.evaluate([egfr_observation], {"age_years": 62}),
            {"age_years": 62},
        ),
        {"age_years": 62},
    )

    assert len(with_overlay) == 1
    print("\nYYY", with_overlay[0])
    assert with_overlay[0]["rule_id"] == "egfr_low_threshold"
    assert with_overlay[0]["suppression_active"] is False
    assert with_overlay[0]["severity_class"] == "S2"
    assert with_overlay[0]["nextstep_class"] == "A2"

    assert len(without_overlay) == 1
    assert without_overlay[0]["rule_id"] == "egfr_low_threshold"
    assert without_overlay[0]["suppression_active"] is True
    assert without_overlay[0]["suppression_reason"] == "missing_demographics_overlay"
    assert without_overlay[0]["severity_class"] == "SX"
    assert without_overlay[0]["nextstep_class"] == "AX"


def test_phase_18_urgent_classes_are_disabled_without_signed_off_critical_source() -> None:
    rule_engine = RuleEngine()
    severity_policy = SeverityPolicyEngine()
    nextstep_policy = NextStepPolicyEngine()
    glucose = _supported_observation(
        "Glucose", value=320, unit="mg/dL", accepted_analyte_code="METRIC-0019"
    )

    findings = rule_engine.evaluate([glucose], {"age_years": 42, "sex": "female"})
    findings = severity_policy.assign(findings, {"age_years": 42, "sex": "female"})
    findings = nextstep_policy.assign(findings, {"age_years": 42, "sex": "female"})

    assert len(findings) == 1
    assert findings[0]["severity_class"] == SeverityClass.S3
    assert findings[0]["nextstep_class"] == NextStepClass.A3


async def test_phase_18_pipeline_handles_launch_scope_non_glycemia_report(monkeypatch) -> None:
    async def fake_extract_rows(job_uuid, *, file_bytes, lane_type=None):
        return [
            {
                "document_id": job_uuid,
                "source_page": 1,
                "row_hash": "row-total-chol",
                "raw_text": "Total cholesterol 250 mg/dL",
                "raw_analyte_label": "Total cholesterol",
                "raw_value_string": "250",
                "raw_unit_string": "mg/dL",
                "raw_reference_range": "<200",
                "parsed_numeric_value": 250.0,
                "specimen_context": "serum",
                "language_id": "en",
                "extraction_confidence": 0.99,
            },
            {
                "document_id": job_uuid,
                "source_page": 1,
                "row_hash": "row-ldl",
                "raw_text": "LDL-C 170 mg/dL",
                "raw_analyte_label": "LDL-C",
                "raw_value_string": "170",
                "raw_unit_string": "mg/dL",
                "raw_reference_range": "<100",
                "parsed_numeric_value": 170.0,
                "specimen_context": "serum",
                "language_id": "en",
                "extraction_confidence": 0.99,
            },
            {
                "document_id": job_uuid,
                "source_page": 1,
                "row_hash": "row-egfr",
                "raw_text": "eGFR 52 mL/min/1.73 m2",
                "raw_analyte_label": "eGFR",
                "raw_value_string": "52",
                "raw_unit_string": "mL/min/1.73 m2",
                "raw_reference_range": ">=60",
                "parsed_numeric_value": 52.0,
                "specimen_context": "serum",
                "language_id": "en",
                "extraction_confidence": 0.99,
            },
        ]

    monkeypatch.setattr("app.workers.pipeline._extract_rows", fake_extract_rows)

    result = await PipelineOrchestrator().run(
        "phase-18-launch-scope",
        file_bytes=b"trusted-pdf",
        lane_type="trusted_pdf",
        source_checksum="sha256:phase18",
    )

    assert {finding["rule_id"] for finding in result["findings"]} == {
        "total_cholesterol_high_threshold",
        "ldl_high_threshold",
        "egfr_low_threshold",
    }
    assert result["status"] == "partial"
