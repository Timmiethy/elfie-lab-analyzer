"""Deterministic rule engine (blueprint section 3.8)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from uuid import UUID


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().lower()
    return str(value).strip().lower()


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _as_uuid_list(value: object) -> list[UUID]:
    if isinstance(value, UUID):
        return [value]
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        result: list[UUID] = []
        for item in value:
            if isinstance(item, UUID):
                result.append(item)
            else:
                result.append(UUID(str(item)))
        return result
    return [UUID(str(value))]


_SEVERITY_RANK = {
    "S0": 0,
    "S1": 1,
    "S2": 2,
    "S3": 3,
    "S4": 4,
    "SX": 5,
}

_NEXTSTEP_BY_SEVERITY = {
    "S0": "A0",
    "S1": "A1",
    "S2": "A2",
    "S3": "A3",
    "S4": "A4",
    "SX": "AX",
}


class RuleEngine:
    """Fire deterministic rules against launch-scope observations."""

    def evaluate(self, observations: list[dict], patient_context: dict) -> list[dict]:
        findings: list[dict] = []

        for observation in observations:
            support_state = observation.get("support_state")
            if hasattr(support_state, "value"):
                support_state = support_state.value
            if str(support_state or "").lower() != "supported":
                continue

            observed_value = (
                _coerce_float(observation.get("canonical_value"))
                or _coerce_float(observation.get("parsed_numeric_value"))
                or _coerce_float(observation.get("raw_value_string"))
            )
            if observed_value is None:
                continue

            analyte_key = _observation_analyte_key(observation)
            if analyte_key is None:
                continue

            for rule in _load_launch_scope_rules()["rules"]:
                if analyte_key not in rule["analyte_keys"]:
                    continue

                finding = _build_finding(
                    rule=rule,
                    observation=observation,
                    observed_value=observed_value,
                    patient_context=patient_context,
                )
                if finding is not None:
                    findings.append(finding)
                break

        return findings


def _build_finding(
    *,
    rule: dict,
    observation: dict,
    observed_value: float,
    patient_context: dict,
) -> dict | None:
    raw_reference_range = observation.get("raw_reference_range")
    threshold_source = str(rule.get("threshold_source") or "")
    if rule["rule_id"] == "glucose_high_threshold" and raw_reference_range:
        threshold_source = f"reference_range:{raw_reference_range}"

    policy_severity_candidate = _severity_for_rule(rule, observed_value, patient_context)
    threshold_conflict = _build_threshold_conflict_finding(
        rule=rule,
        observation=observation,
        observed_value=observed_value,
        policy_severity_candidate=policy_severity_candidate,
    )
    if threshold_conflict is not None:
        return threshold_conflict

    missing_overlay = [
        field
        for field in rule.get("requires_overlay", [])
        if patient_context.get(field) in (None, "")
    ]

    if missing_overlay:
        severity_candidate = "SX"
        nextstep_candidate = "AX"
        suppression_reason = "missing_demographics_overlay"
        suppression_active = True
    else:
        severity_candidate = policy_severity_candidate
        if severity_candidate is None:
            return None
        nextstep_candidate = _NEXTSTEP_BY_SEVERITY[severity_candidate]
        suppression_reason = None
        suppression_active = False

    row_hash = observation.get("row_hash") or str(observation.get("id"))
    return {
        "finding_id": f"{rule['finding_prefix']}::{row_hash}",
        "rule_id": rule["rule_id"],
        "observation_ids": _as_uuid_list(observation.get("id")),
        "threshold_source": threshold_source,
        "severity_class": severity_candidate,
        "nextstep_class": nextstep_candidate,
        "suppression_conditions": (
            {"missing_overlay": missing_overlay} if missing_overlay else None
        ),
        "suppression_active": suppression_active,
        "suppression_reason": suppression_reason,
        "explanatory_scaffold_id": rule["explanatory_scaffold_id"],
        "observed_value": observed_value,
        "observed_unit": observation.get("canonical_unit") or observation.get("raw_unit_string"),
        "reference_range": raw_reference_range,
        "specimen_context": observation.get("specimen_context"),
        "method_context": observation.get("method_context"),
        "severity_class_candidate": severity_candidate,
        "nextstep_class_candidate": nextstep_candidate,
    }


def _build_threshold_conflict_finding(
    *,
    rule: dict,
    observation: dict,
    observed_value: float,
    policy_severity_candidate: str | None,
) -> dict | None:
    raw_reference_range = observation.get("raw_reference_range")
    if raw_reference_range is None:
        return None
    if policy_severity_candidate is not None:
        return None
    if not _printed_range_flags_abnormal(rule, observed_value, str(raw_reference_range)):
        return None

    analyte_prefix = str(rule["finding_prefix"]).split("_high", 1)[0].split("_low", 1)[0]
    row_hash = observation.get("row_hash") or str(observation.get("id"))
    return {
        "finding_id": f"{analyte_prefix}_threshold_conflict::{row_hash}",
        "rule_id": f"{analyte_prefix}_threshold_conflict",
        "observation_ids": _as_uuid_list(observation.get("id")),
        "threshold_source": "conflicting_threshold_sources",
        "severity_class": "SX",
        "nextstep_class": "AX",
        "suppression_conditions": {
            "conflict": "printed_range_vs_policy",
            "printed_range": raw_reference_range,
            "policy_threshold": rule.get("threshold_source"),
        },
        "suppression_active": True,
        "suppression_reason": "threshold_conflict",
        "explanatory_scaffold_id": "threshold_conflict_v1",
        "observed_value": observed_value,
        "observed_unit": observation.get("canonical_unit") or observation.get("raw_unit_string"),
        "reference_range": raw_reference_range,
        "specimen_context": observation.get("specimen_context"),
        "method_context": observation.get("method_context"),
        "severity_class_candidate": "SX",
        "nextstep_class_candidate": "AX",
    }


def _severity_for_rule(rule: dict, observed_value: float, patient_context: dict) -> str | None:
    if rule["comparison"] == "gte":
        matched = [
            threshold["severity_class"]
            for threshold in rule["thresholds"]
            if observed_value >= float(threshold["value"])
        ]
        if not matched:
            return None
        return max(matched, key=lambda value: _SEVERITY_RANK[value])

    if rule["comparison"] == "lte":
        thresholds = rule["thresholds"]
        sex_thresholds = rule.get("sex_thresholds") or {}
        if sex_thresholds:
            sex_key = _normalize_text(patient_context.get("sex"))
            thresholds = sex_thresholds.get(sex_key) or sex_thresholds.get("default") or thresholds
        matched = [
            threshold["severity_class"]
            for threshold in thresholds
            if observed_value <= float(threshold["value"])
        ]
        if not matched:
            return None
        return max(matched, key=lambda value: _SEVERITY_RANK[value])

    return None


def _printed_range_flags_abnormal(
    rule: dict,
    observed_value: float,
    raw_reference_range: str,
) -> bool:
    reference_range = _parse_reference_range(raw_reference_range)
    if reference_range is None:
        return False

    if rule["comparison"] == "gte":
        high = reference_range.get("high")
        return high is not None and observed_value > float(high)

    if rule["comparison"] == "lte":
        low = reference_range.get("low")
        return low is not None and observed_value < float(low)

    return False


def _parse_reference_range(raw_reference_range: str) -> dict[str, float] | None:
    text = _normalize_text(raw_reference_range)
    if not text:
        return None

    if "-" in text:
        lower_text, upper_text = [part.strip() for part in text.split("-", 1)]
        lower = _coerce_float(lower_text)
        upper = _coerce_float(upper_text)
        if lower is None or upper is None:
            return None
        return {"low": lower, "high": upper}

    if text.startswith(("<=", "≤", "<")):
        high = _coerce_float(text.lstrip("<=≤ ").strip())
        if high is None:
            return None
        return {"high": high}

    if text.startswith((">=", "≥", ">")):
        low = _coerce_float(text.lstrip(">=≥> ").strip())
        if low is None:
            return None
        return {"low": low}

    return None


def _observation_analyte_key(observation: dict) -> str | None:
    metadata = _load_launch_scope_rules()["metadata"]
    labels = (
        observation.get("accepted_analyte_display"),
        observation.get("accepted_analyte_code"),
        observation.get("raw_analyte_label"),
        observation.get("raw_text"),
    )
    normalized_values = {_normalize_text(value) for value in labels if value is not None}
    for analyte_key, aliases in metadata["aliases_by_analyte"].items():
        if normalized_values & aliases:
            return analyte_key
    return None


@lru_cache(maxsize=1)
def _load_launch_scope_rules() -> dict:
    rules_path = (
        Path(__file__).resolve().parents[4] / "data" / "policy_tables" / "launch_scope_rules.json"
    )
    payload = json.loads(rules_path.read_text(encoding="utf-8"))

    aliases_by_analyte: dict[str, set[str]] = {}
    for analyte in payload.get("analytes", []):
        analyte_key = _normalize_text(analyte.get("canonical_label"))
        aliases = {_normalize_text(analyte_key)}
        aliases.update(_normalize_text(alias) for alias in analyte.get("aliases", []))
        aliases.update(_normalize_text(code) for code in analyte.get("codes", []))
        aliases_by_analyte[analyte_key] = {alias for alias in aliases if alias}

    normalized_rules = []
    for rule in payload.get("rules", []):
        normalized_rules.append(
            {
                "rule_id": str(rule["rule_id"]),
                "finding_prefix": str(rule["finding_prefix"]),
                "analyte_keys": [_normalize_text(key) for key in rule.get("analyte_keys", [])],
                "comparison": str(rule["comparison"]),
                "thresholds": [
                    {
                        "value": float(threshold["value"]),
                        "severity_class": str(threshold["severity_class"]),
                    }
                    for threshold in rule.get("thresholds", [])
                ],
                "sex_thresholds": {
                    _normalize_text(sex): [
                        {
                            "value": float(threshold["value"]),
                            "severity_class": str(threshold["severity_class"]),
                        }
                        for threshold in thresholds
                    ]
                    for sex, thresholds in rule.get("sex_thresholds", {}).items()
                },
                "threshold_source": str(rule["threshold_source"]),
                "requires_overlay": list(rule.get("requires_overlay", [])),
                "explanatory_scaffold_id": str(rule["explanatory_scaffold_id"]),
            }
        )

    payload["metadata"] = {"aliases_by_analyte": aliases_by_analyte}
    payload["rules"] = normalized_rules
    return payload
