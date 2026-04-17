from app.services.severity_policy import PEDIATRIC_AGE_THRESHOLD_YEARS, SeverityPolicyEngine


def test_severity_policy_abstains_on_minor():
    engine = SeverityPolicyEngine()
    findings = [
        {"severity_class": "S1", "severity_class_candidate": "S1", "suppression_active": False}
    ]
    # Minor: age 10
    result = engine.assign(findings, {"age_years": 10})
    assert result[0]["severity_class"] == "SX"


def test_severity_policy_respects_rule_engine_abstain():
    engine = SeverityPolicyEngine()
    findings = [
        {
            "severity_class": "SX",
            "severity_class_candidate": "SX",
            "suppression_active": True,
            "suppression_reason": "unresolved_reference_profile",
        }
    ]
    # Adult but already abstained
    result = engine.assign(findings, {"age_years": 30})
    assert result[0]["severity_class"] == "SX"
    assert result[0]["suppression_active"] is True


def test_severity_policy_passes_through_adult_normal_finding():
    engine = SeverityPolicyEngine()
    findings = [
        {"severity_class": "S0", "severity_class_candidate": "S0", "suppression_active": False}
    ]
    result = engine.assign(findings, {"age_years": 30})
    assert result[0]["severity_class"] == "S0"


def test_severity_policy_applies_urgent_gate():
    engine = SeverityPolicyEngine()
    findings = [{"severity_class_candidate": "S4", "suppression_active": False}]
    # Default settings.critical_value_source_signed_off is False
    result = engine.assign(findings, {"age_years": 30})
    assert result[0]["severity_class"] == "S3"


def test_severity_policy_abstains_just_below_pediatric_cutoff() -> None:
    engine = SeverityPolicyEngine()
    findings = [
        {"severity_class": "S1", "severity_class_candidate": "S1", "suppression_active": False}
    ]

    result = engine.assign(findings, {"age_years": PEDIATRIC_AGE_THRESHOLD_YEARS - 0.01})
    assert result[0]["severity_class"] == "SX"


def test_severity_policy_keeps_adult_logic_at_pediatric_cutoff() -> None:
    engine = SeverityPolicyEngine()
    findings = [
        {"severity_class": "S1", "severity_class_candidate": "S1", "suppression_active": False}
    ]

    result = engine.assign(findings, {"age_years": float(PEDIATRIC_AGE_THRESHOLD_YEARS)})
    assert result[0]["severity_class"] == "S1"
