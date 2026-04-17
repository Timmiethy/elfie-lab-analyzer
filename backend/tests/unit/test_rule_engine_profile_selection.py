import json
from uuid import uuid4

import pytest

from app.services.metric_resolver import MetricResolver
from app.services.rule_engine import RuleEngine, _normalize_sex_thresholds


@pytest.fixture
def mock_resolver(tmp_path):
    catalog_file = tmp_path / "test_metrics.json"
    metrics = [
        {
            "metric_id": "glucose",
            "canonical_name": "Glucose",
            "aliases": ["fasting glucose"],
            "result_type": "numeric",
            "default_reference_profiles": [
                {
                    "profile_id": "glucose_adult",
                    "metric_id": "glucose",
                    "source_type": "canonical_default",
                    "priority": 5,
                    "ref_high": 100.0,
                    "applies_to": {"age_low": 18, "age_high": 120},
                },
                {
                    "profile_id": "glucose_pregnant",
                    "metric_id": "glucose",
                    "source_type": "canonical_default",
                    "priority": 1,
                    "ref_high": 95.0,
                    "applies_to": {"pregnancy": True},
                },
            ],
        }
    ]
    catalog_file.write_text(json.dumps(metrics))
    return MetricResolver(catalog_path=catalog_file)


def test_rule_engine_uses_profile_bounds(mock_resolver):
    # RuleEngine uses MetricResolver internally or as passed in.
    # We pass the mock_resolver to control the data.
    engine = RuleEngine(metric_resolver=mock_resolver)

    # Adult, non-pregnant: matches glucose_adult (ref_high 100). Value 105 -> S1
    obs = {
        "id": uuid4(),
        "accepted_analyte_display": "Glucose",
        "canonical_value": 105.0,
        "support_state": "supported",
    }
    patient = {"age_years": 30, "pregnancy_status": False}
    findings = engine.evaluate([obs], patient)

    assert len(findings) == 1
    # Note: rule_id might be glucose_high_threshold if it matches launch_scope_rules
    assert findings[0]["severity_class"] == "S1"
    assert "profile:glucose_adult" in findings[0]["threshold_source"]

    # Pregnant: matches glucose_pregnant (ref_high 95). Value 97 -> S1
    patient_pregnant = {"age_years": 30, "pregnancy_status": True}
    findings_pregnant = engine.evaluate([obs], patient_pregnant)
    assert len(findings_pregnant) == 1
    assert findings_pregnant[0]["severity_class"] == "S1"
    assert "profile:glucose_pregnant" in findings_pregnant[0]["threshold_source"]


def test_rule_engine_abstains_on_missing_profile(mock_resolver):
    engine = RuleEngine(metric_resolver=mock_resolver)

    # Minor, non-pregnant: no matching profile in our mock catalog
    obs = {
        "id": uuid4(),
        "accepted_analyte_display": "Glucose",
        "canonical_value": 105.0,
        "support_state": "supported",
    }
    patient = {"age_years": 10, "pregnancy_status": False}
    findings = engine.evaluate([obs], patient)

    assert len(findings) == 1
    assert findings[0]["severity_class"] == "SX"
    assert findings[0]["suppression_active"] is True
    assert findings[0]["suppression_reason"] == "unresolved_reference_profile"


def test_rule_engine_keeps_unsupported_rows_visible(mock_resolver):
    engine = RuleEngine(metric_resolver=mock_resolver)

    obs = {
        "id": uuid4(),
        "raw_analyte_label": "MysteryMarker",
        "canonical_value": 7.2,
        "support_state": "unsupported",
    }
    findings = engine.evaluate([obs], {"age_years": 30})

    assert len(findings) == 1
    assert findings[0]["rule_id"] == "unsupported_analyte"
    assert findings[0]["severity_class"] == "SX"
    assert findings[0]["suppression_active"] is True
    assert findings[0]["suppression_reason"] == "unsupported_analyte"


def test_rule_engine_keeps_supported_non_launch_scope_rows_without_forced_unsupported() -> None:
    engine = RuleEngine()

    obs = {
        "id": uuid4(),
        "raw_analyte_label": "WBC",
        "accepted_analyte_display": "WBC",
        "accepted_analyte_code": "METRIC-0001",
        "canonical_value": 7.2,
        "support_state": "supported",
    }
    findings = engine.evaluate([obs], {"age_years": 30, "sex": "female"})

    assert findings == []


def test_rule_engine_preserves_non_supported_reason_for_known_analytes() -> None:
    engine = RuleEngine()

    obs = {
        "id": uuid4(),
        "raw_analyte_label": "hba1c",
        "accepted_analyte_code": "METRIC-0063",
        "accepted_analyte_display": "HbA1c",
        "canonical_value": 6.8,
        "support_state": "partial",
        "suppression_reasons": ["low_extraction_confidence"],
    }
    findings = engine.evaluate([obs], {"age_years": 42, "sex": "female"})

    assert len(findings) == 1
    assert findings[0]["rule_id"] == "unsupported_analyte"
    assert findings[0]["suppression_reason"] == "low_extraction_confidence"


def test_normalize_sex_thresholds_accepts_and_normalizes_case() -> None:
    normalized = _normalize_sex_thresholds(
        {
            "Female": [{"value": 50, "severity_class": "S2"}],
            "MALE": [{"value": 40, "severity_class": "S2"}],
            "Default": [{"value": 45, "severity_class": "S2"}],
        },
        rule_id="hdl_low_threshold",
    )

    assert set(normalized) == {"female", "male", "default"}
    assert normalized["female"][0]["value"] == 50.0


def test_normalize_sex_thresholds_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="unsupported sex_thresholds key"):
        _normalize_sex_thresholds(
            {"unknown": [{"value": 40, "severity_class": "S2"}]},
            rule_id="hdl_low_threshold",
        )


def test_normalize_sex_thresholds_rejects_collision_after_normalization() -> None:
    with pytest.raises(ValueError, match="duplicate sex_thresholds key"):
        _normalize_sex_thresholds(
            {
                "Male": [{"value": 40, "severity_class": "S2"}],
                "male": [{"value": 41, "severity_class": "S2"}],
            },
            rule_id="hdl_low_threshold",
        )
