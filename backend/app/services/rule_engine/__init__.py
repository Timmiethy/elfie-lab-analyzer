"""Deterministic rule engine (blueprint section 3.8)."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from uuid import UUID

from app.schemas.metric import ReferenceProfile
from app.schemas.patient_context import PatientContext
from app.services.data_paths import resolve_data_file
from app.services.metric_resolver import MetricResolver

_LOGGER = logging.getLogger(__name__)


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

    def __init__(self, metric_resolver: MetricResolver | None = None):
        self.metric_resolver = metric_resolver or MetricResolver()

    def evaluate(
        self,
        observations: list[dict],
        patient_context: dict | PatientContext,
    ) -> list[dict]:
        findings: list[dict] = []
        if isinstance(patient_context, dict):
            p_ctx = PatientContext(**patient_context)
            p_dict = patient_context
        else:
            p_ctx = patient_context
            p_dict = p_ctx.model_dump()

        for observation in observations:
            support_state = observation.get("support_state")
            if hasattr(support_state, "value"):
                support_state = support_state.value
            is_supported = str(support_state or "").lower() == "supported"

            observed_value = (
                _coerce_float(observation.get("canonical_value"))
                or _coerce_float(observation.get("parsed_numeric_value"))
                or _coerce_float(observation.get("raw_value_string"))
            )
            if observed_value is None:
                # Qualitative / textual result rows (e.g. urinalysis dipstick
                # "Absent"/"Present (+)", morphology "Normochromic Normocytic",
                # blood group "A", ABO type, parasites "not detected"). Evaluate
                # these deterministically against the printed reference string.
                qualitative = _build_qualitative_finding(observation)
                if qualitative is not None:
                    findings.append(qualitative)
                continue

            analyte_key = _observation_analyte_key(observation)

            if not is_supported:
                findings.append(self._build_unsupported_finding(observation, observed_value))
                continue

            # Supported rows can be outside the launch-scope policy table.
            # Fall back to a generic printed-range check so every supported analyte
            # with a printed reference range gets a deterministic S0/S? finding.
            launch_scope_analyte = analyte_key in {
                k for rule in _load_launch_scope_rules()["rules"] for k in rule["analyte_keys"]
            } if analyte_key else False
            if not analyte_key or not launch_scope_analyte:
                generic_finding = _build_generic_range_finding(observation, observed_value)
                if generic_finding is not None:
                    findings.append(generic_finding)
                continue

            profile = self.metric_resolver.resolve_profile(analyte_key, p_ctx)

            rule_matched = False
            rule_returned_finding = False
            for rule in _load_launch_scope_rules()["rules"]:
                if analyte_key not in rule["analyte_keys"]:
                    continue
                rule_matched = True
                finding = _build_finding(
                    rule=rule,
                    observation=observation,
                    observed_value=observed_value,
                    patient_context=p_dict,
                    profile=profile,
                )
                if finding is not None:
                    findings.append(finding)
                    rule_returned_finding = True
                break

            if not rule_returned_finding:
                # The launch-scope rule was unit-gated or returned None. The VLM may
                # have picked a wrong reference range row for this analyte (e.g. a
                # nearby diagnostic-band table), so trust the rule's silence over a
                # potentially noisy generic range finding.
                continue

        return findings

    def _build_unsupported_finding(self, observation: dict, observed_value: float) -> dict:
        row_hash = observation.get("row_hash") or str(observation.get("id"))
        observed_unit = observation.get("canonical_unit") or observation.get("raw_unit_string")
        suppression_reasons = observation.get("suppression_reasons") or []
        suppression_reason = str(suppression_reasons[0]) if suppression_reasons else "unsupported_analyte"
        return {
            "finding_id": f"unsupported_analyte::{row_hash}",
            "rule_id": "unsupported_analyte",
            "observation_ids": _as_uuid_list(observation.get("id")),
            "threshold_source": "none",
            "severity_class": "SX",
            "nextstep_class": "AX",
            "suppression_conditions": None,
            "suppression_active": True,
            "suppression_reason": suppression_reason,
            "explanatory_scaffold_id": "unsupported_analyte_v1",
            "observed_value": observed_value,
            "observed_unit": observed_unit,
            "reference_range": observation.get("raw_reference_range"),
            "specimen_context": observation.get("specimen_context"),
            "method_context": observation.get("method_context"),
            "severity_class_candidate": "SX",
            "nextstep_class_candidate": "AX",
        }


def _build_qualitative_finding(observation: dict) -> dict | None:
    """Evaluate a textual/qualitative result row against its printed reference.

    Emits S0 when the observed text matches the printed reference (or a
    recognized normal verdict), S2 when it clearly does not, None otherwise.
    Never suppressed — this lets qualitative rows appear in the artifact
    without the row being dumped into not_assessed.
    """
    raw_value_string = observation.get("raw_value_string")
    if raw_value_string is None:
        return None
    raw_text = str(raw_value_string).strip()
    if not raw_text:
        return None

    normalized_value = raw_text.lower()
    raw_reference_range = observation.get("raw_reference_range")
    ref_text = str(raw_reference_range or "").strip().lower()

    # Blood group / Rh typing results are reported as "A"/"O"/"Positive"/"Negative"
    # but those tokens are NOT clinical severity indicators there — a "Positive"
    # Rh type is a normal identification, not an abnormal finding. Treat these
    # rows as always-normal qualitative reports.
    analyte_label_lower = str(
        observation.get("accepted_analyte_display")
        or observation.get("raw_analyte_label")
        or ""
    ).lower()
    is_blood_group_row = any(
        tok in analyte_label_lower
        for tok in ("abo", "rh ", "rh(", "rh type", "blood group")
    )

    # Normalize common dipstick / morphology tokens.
    def _norm(value: str) -> str:
        return " ".join(value.replace("(", " ").replace(")", " ").replace(",", " ").split())

    value_norm = _norm(normalized_value)
    ref_norm = _norm(ref_text)

    abnormal_tokens = (
        "present",
        "positive",
        "reactive",      # non-reactive handled below
        "detected",      # "not detected" handled below
        "abnormal",
        "many",
        "numerous",
        "++",
        "+++",
    )
    normal_tokens = (
        "absent",
        "negative",
        "non reactive",
        "non-reactive",
        "nonreactive",
        "not detected",
        "nil",
        "normal",
        "within normal",
        "clear",
        "pale yellow",
        "yellow",
        "normochromic",
        "normocytic",
        "adequate",
    )

    def _has(tokens: tuple[str, ...], text: str) -> bool:
        return any(tok in text for tok in tokens)

    is_value_normal_token = _has(normal_tokens, value_norm) and not _has(
        ("non nil",), value_norm
    )
    is_value_abnormal_token = (
        _has(abnormal_tokens, value_norm)
        and "non reactive" not in value_norm
        and "non-reactive" not in value_norm
        and "not detected" not in value_norm
    )

    # Exact (case-insensitive) match with the printed reference -> normal.
    verdict: str | None = None
    if is_blood_group_row:
        verdict = "normal"
    elif ref_norm and value_norm == ref_norm:
        verdict = "normal"
    elif is_value_normal_token and not is_value_abnormal_token:
        verdict = "normal"
    elif is_value_abnormal_token and not is_value_normal_token:
        # Printed reference says "Absent"/"Normal"/"Negative" but value is
        # "Present"/"Positive"/"Reactive" -> abnormal.
        if ref_norm and _has(normal_tokens, ref_norm):
            verdict = "abnormal"
        else:
            verdict = "abnormal"

    if verdict is None:
        # "1-2" (microscopy count) against "0 - 2" range: try numeric upper
        # bound comparison.
        import re as _re

        m = _re.match(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$", raw_text)
        if m and ref_norm:
            rng = _parse_reference_range(ref_norm)
            if rng is not None:
                upper = float(m.group(2))
                low = rng.get("low")
                high = rng.get("high")
                if (low is None or upper >= low) and (high is None or upper <= high):
                    verdict = "normal"
                else:
                    verdict = "abnormal"

    if verdict is None:
        # Fallback: report the row but don't assert a severity claim.
        verdict = "normal"  # conservative — report's own ambiguous text

    row_hash = observation.get("row_hash") or str(observation.get("id"))
    analyte_display = (
        observation.get("accepted_analyte_display")
        or observation.get("raw_analyte_label")
        or "analyte"
    )
    prefix = (
        str(analyte_display).strip().lower().replace(" ", "_").replace("/", "_")
        or "analyte"
    )
    severity = "S0" if verdict == "normal" else "S2"
    nextstep = _NEXTSTEP_BY_SEVERITY[severity]
    threshold_source = (
        f"reference_range:{raw_reference_range}" if raw_reference_range else "qualitative_report"
    )
    return {
        "finding_id": f"{prefix}_qual::{row_hash}",
        "rule_id": f"{prefix}_qualitative",
        "observation_ids": _as_uuid_list(observation.get("id")),
        "threshold_source": threshold_source,
        "severity_class": severity,
        "nextstep_class": nextstep,
        "suppression_conditions": None,
        "suppression_active": False,
        "suppression_reason": None,
        "explanatory_scaffold_id": f"{prefix}_qualitative_v1",
        "observed_value": None,
        "observed_unit": observation.get("canonical_unit") or observation.get("raw_unit_string"),
        "reference_range": raw_reference_range,
        "specimen_context": observation.get("specimen_context"),
        "method_context": observation.get("method_context"),
        "severity_class_candidate": severity,
        "nextstep_class_candidate": nextstep,
    }


def _build_generic_range_finding(
    observation: dict,
    observed_value: float,
) -> dict | None:
    """Evaluate a supported observation against its printed reference range.

    Emits a deterministic S0 (in-range) or S2 (out-of-range) finding so analytes
    without a launch-scope policy still appear in the artifact with a status.
    Returns None when the observation has no parseable range.
    """
    raw_reference_range = observation.get("raw_reference_range")
    if raw_reference_range is None:
        return None
    within = _value_within_printed_range(observed_value, raw_reference_range)
    if within is None:
        return None

    row_hash = observation.get("row_hash") or str(observation.get("id"))
    analyte_display = (
        observation.get("accepted_analyte_display")
        or observation.get("raw_analyte_label")
        or "analyte"
    )
    prefix = str(analyte_display).strip().lower().replace(" ", "_") or "analyte"
    severity = "S0" if within else "S2"
    nextstep = _NEXTSTEP_BY_SEVERITY[severity]

    return {
        "finding_id": f"{prefix}_range::{row_hash}",
        "rule_id": f"{prefix}_range",
        "observation_ids": _as_uuid_list(observation.get("id")),
        "threshold_source": f"reference_range:{raw_reference_range}",
        "severity_class": severity,
        "nextstep_class": nextstep,
        "suppression_conditions": None,
        "suppression_active": False,
        "suppression_reason": None,
        "explanatory_scaffold_id": f"{prefix}_range_v1",
        "observed_value": observed_value,
        "observed_unit": observation.get("canonical_unit") or observation.get("raw_unit_string"),
        "reference_range": raw_reference_range,
        "specimen_context": observation.get("specimen_context"),
        "method_context": observation.get("method_context"),
        "severity_class_candidate": severity,
        "nextstep_class_candidate": nextstep,
    }


def _build_finding(
    *,
    rule: dict,
    observation: dict,
    observed_value: float,
    patient_context: dict,
    profile: ReferenceProfile | None = None,
) -> dict | None:
    raw_reference_range = observation.get("raw_reference_range")
    threshold_source = str(rule.get("threshold_source") or "")
    if rule["rule_id"] == "glucose_high_threshold" and raw_reference_range:
        threshold_source = f"reference_range:{raw_reference_range}"

    # Unit gate: when the rule declares expected_units, the observation MUST be in
    # one of those units to flag a value as abnormal. We still allow IN-range S0
    # findings through any unit (a value inside a printed range is normal regardless
    # of unit channel — units only matter when we'd raise alarm).
    rule_units = rule.get("expected_units") or []
    obs_unit = (
        observation.get("canonical_unit") or observation.get("raw_unit_string") or ""
    ).strip().lower()
    unit_matches_rule = (
        not rule_units
        or not obs_unit
        or any(obs_unit == u.lower() for u in rule_units)
    )

    # Printed-range-first: if the report prints its own reference range AND the value
    # falls inside it, trust the report and mark normal (S0). This matches spec:
    # "use the printed report range/category, not a hardcoded universal range."
    printed_normal = _value_within_printed_range(observed_value, raw_reference_range)
    if printed_normal is True:
        row_hash = observation.get("row_hash") or str(observation.get("id"))
        return {
            "finding_id": f"{rule['finding_prefix']}::{row_hash}",
            "rule_id": rule["rule_id"],
            "observation_ids": _as_uuid_list(observation.get("id")),
            "threshold_source": f"reference_range:{raw_reference_range}",
            "severity_class": "S0",
            "nextstep_class": "A0",
            "suppression_conditions": None,
            "suppression_active": False,
            "suppression_reason": None,
            "explanatory_scaffold_id": rule["explanatory_scaffold_id"],
            "observed_value": observed_value,
            "observed_unit": observation.get("canonical_unit") or observation.get("raw_unit_string"),
            "reference_range": raw_reference_range,
            "specimen_context": observation.get("specimen_context"),
            "method_context": observation.get("method_context"),
            "severity_class_candidate": "S0",
            "nextstep_class_candidate": "A0",
        }
    # Printed range explicitly outside normal (e.g. LDL 100.39 vs
    # "Optimal <100; Near to above optimal 100-129; ..."). If rule thresholds
    # would not fire (100.39 < policy S2 threshold of 130), still emit an S2
    # via the printed range so the row is surfaced, matching spec "trust the
    # report's own category over hardcoded universal thresholds".
    if printed_normal is False and unit_matches_rule:
        policy_check = _severity_for_rule(
            rule, observed_value, patient_context, profile=profile
        )
        if policy_check is None:
            row_hash = observation.get("row_hash") or str(observation.get("id"))
            return {
                "finding_id": f"{rule['finding_prefix']}::{row_hash}",
                "rule_id": rule["rule_id"],
                "observation_ids": _as_uuid_list(observation.get("id")),
                "threshold_source": f"reference_range:{raw_reference_range}",
                "severity_class": "S2",
                "nextstep_class": "A2",
                "suppression_conditions": None,
                "suppression_active": False,
                "suppression_reason": None,
                "explanatory_scaffold_id": rule["explanatory_scaffold_id"],
                "observed_value": observed_value,
                "observed_unit": observation.get("canonical_unit") or observation.get("raw_unit_string"),
                "reference_range": raw_reference_range,
                "specimen_context": observation.get("specimen_context"),
                "method_context": observation.get("method_context"),
                "severity_class_candidate": "S2",
                "nextstep_class_candidate": "A2",
            }

    # Past this point we would emit a non-S0 finding. If the unit doesn't match
    # the rule's expected units, abort: rule thresholds (e.g. HbA1c 5.7% vs
    # mmol/mol) are not unit-translated, and the printed range for a mismatched
    # unit row is frequently a mis-picked diagnostic-band row.
    if not unit_matches_rule:
        return None

    policy_severity_candidate = _severity_for_rule(
        rule, observed_value, patient_context, profile=profile
    )
    if profile:
        threshold_source = f"profile:{profile.profile_id}"

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

    if profile is None:
        severity_candidate = "SX"
        nextstep_candidate = "AX"
        suppression_reason = "unresolved_reference_profile"
        suppression_active = True
        _LOGGER.info(
            "rule_engine_suppress_no_profile rule=%s analyte_keys=%s "
            "age=%s sex=%s observed=%s",
            rule.get("rule_id"),
            rule.get("analyte_keys"),
            patient_context.get("age_years"),
            patient_context.get("sex"),
            observed_value,
        )
    elif missing_overlay:
        severity_candidate = "SX"
        nextstep_candidate = "AX"
        suppression_reason = "missing_demographics_overlay"
        suppression_active = True
        _LOGGER.info(
            "rule_engine_suppress_missing_overlay rule=%s missing=%s",
            rule.get("rule_id"),
            missing_overlay,
        )
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


def _severity_for_rule(
    rule: dict,
    observed_value: float,
    patient_context: dict,
    profile: ReferenceProfile | None = None,
) -> str | None:
    if profile:
        if rule["comparison"] == "gte":
            if profile.ref_high is not None:
                return "S1" if observed_value >= profile.ref_high else None
            # Fallback to rule thresholds if no profile ref_high
        elif rule["comparison"] == "lte":
            if profile.ref_low is not None:
                return "S1" if observed_value <= profile.ref_low else None
            # Fallback to rule thresholds if no profile ref_low

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

    # Strip parens/brackets commonly wrapping ranges e.g. "(135-145)" or "[135-145]"
    text = text.strip("()[]").strip()

    if "-" in text and not text.startswith("-"):
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


def _value_within_printed_range(
    observed_value: float,
    raw_reference_range: object,
) -> bool | None:
    """Return True if value is inside the printed range, False if outside, None if no range.

    Also returns True when the printed reference is a recognized "normal" verdict
    string (e.g. "Normal", "Within normal limits"), since the report itself is
    asserting normality without giving a numeric interval.
    """
    if raw_reference_range is None:
        return None
    text = str(raw_reference_range).strip().lower()
    if not text:
        return None
    # Recognized normal-verdict strings the report uses in lieu of a numeric range.
    if text in {"normal", "wnl", "within normal limits", "within normal range", "negative", "non-reactive", "nonreactive", "absent"}:
        return True
    parsed = _parse_reference_range(text)
    if parsed is None:
        # Try parsing as a multi-band category table (lipid panel, vitamin D,
        # LDL bands etc.). We classify the value into its named band and treat
        # the first band (canonically the "optimal"/"desirable"/"normal"
        # category) as in-range; any other band as out-of-range.
        band = _classify_category_band(observed_value, text)
        if band is None:
            return None
        return band == "normal"
    low = parsed.get("low")
    high = parsed.get("high")
    if low is None and high is None:
        return None
    if low is not None and observed_value < low:
        return False
    if high is not None and observed_value > high:
        return False
    return True


_ABNORMAL_BAND_KEYWORDS = (
    "high",
    "low",
    "borderline",
    "critical",
    "deficien",     # deficiency / deficient
    "insufficien",  # insufficiency / insufficient
    "toxic",
    "reactive",     # serology positive band; "non-reactive" is caught by normal pass
    "positive",
    "elevated",
    "abnormal",
    "prediabetes",
    "pre-diabetes",
    "diabetes",
    "dm",
    "very high",
    "above optimal",
    "near to above optimal",
    "poor control",
)


def _classify_category_band(observed_value: float, raw_text: str) -> str | None:
    """Classify a numeric value into a printed multi-band category table.

    Returns "normal" if the value maps to an optimal/desirable/normal/adult-range
    band, "abnormal" otherwise, or None if no band can be parsed. We trust any
    band label that does NOT contain an abnormal keyword (high/low/borderline/
    deficiency/critical/toxic/positive/elevated/diabetes/etc.) — this correctly
    handles demographic-overlay bands like "Children >16 | Adult 20-50" where
    the label names a demographic group rather than a severity.

    Accepts formats such as:
      "Desirable: <200; Borderline: 200-239; High: >240"
      "Optimal <100; Near to above optimal 100-129; Borderline High 130-159"
      "Deficiency <10; Insufficiency 10-30; Sufficiency 30-100; Toxicity >100"
      "Children : >16; Adult : 20 - 50"
    """
    import re

    text = raw_text.lower()
    # Normalize separators: newlines, semicolons, pipes all become semicolons
    text = re.sub(r"[\n|]+", ";", text)
    bands = [b.strip() for b in text.split(";") if b.strip()]
    if len(bands) < 2:
        return None

    band_re = re.compile(
        r"(?P<label>[a-z][a-z /\-()]*?)\s*[:\-]?\s*"
        r"(?:(?P<lt><=?|≤)\s*(?P<lt_val>-?\d+(?:\.\d+)?)"
        r"|(?P<gt>>=?|≥)\s*(?P<gt_val>-?\d+(?:\.\d+)?)"
        r"|(?P<low>-?\d+(?:\.\d+)?)\s*[-–]\s*(?P<high>-?\d+(?:\.\d+)?))"
    )

    matched_band_label: str | None = None
    for band_text in bands:
        m = band_re.search(band_text)
        if not m:
            continue
        label = (m.group("label") or "").strip(" -:/")
        lt = m.group("lt_val")
        gt = m.group("gt_val")
        low = m.group("low")
        high = m.group("high")
        inside = False
        try:
            if lt is not None:
                threshold = float(lt)
                strict = m.group("lt") in ("<",)
                inside = observed_value < threshold if strict else observed_value <= threshold
            elif gt is not None:
                threshold = float(gt)
                strict = m.group("gt") in (">",)
                inside = observed_value > threshold if strict else observed_value >= threshold
            elif low is not None and high is not None:
                inside = float(low) <= observed_value <= float(high)
        except ValueError:
            continue
        if inside:
            matched_band_label = label
            break

    if matched_band_label is None:
        return None

    label_lower = matched_band_label.lower()
    # "non reactive"/"non-reactive" must NOT be classified as abnormal even
    # though it contains the substring "reactive". Same for "non diabetic".
    if any(tok in label_lower for tok in ("non reactive", "non-reactive", "nonreactive", "non diabetes", "non-diabetes", "non diabetic", "non-diabetic")):
        return "normal"
    if any(keyword in label_lower for keyword in _ABNORMAL_BAND_KEYWORDS):
        return "abnormal"
    return "normal"


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
    rules_path = resolve_data_file(
        __file__,
        "policy_tables",
        "launch_scope_rules.json",
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
                "expected_units": list(rule.get("expected_units", [])),
                "explanatory_scaffold_id": str(rule["explanatory_scaffold_id"]),
            }
        )

    payload["metadata"] = {"aliases_by_analyte": aliases_by_analyte}
    payload["rules"] = normalized_rules
    return payload
