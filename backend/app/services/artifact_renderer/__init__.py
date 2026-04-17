"""Artifact renderer: patient and clinician artifact generation."""

from __future__ import annotations

import markupsafe
from uuid import UUID

from app.schemas.artifact import SupportBanner, TrustStatus, UnsupportedReason
from app.schemas.finding import FindingSchema, NextStepClass, SeverityClass


def _safe_text(value: object) -> str:
    """HTML-escape a string derived from OCR output to prevent XSS in downstream renderers."""
    return markupsafe.escape(str(value or ""))

_SEVERITY_ORDER = {
    SeverityClass.S0: 0,
    SeverityClass.S1: 1,
    SeverityClass.S2: 2,
    SeverityClass.S3: 3,
    SeverityClass.S4: 4,
    SeverityClass.SX: 5,
}

_NEXTSTEP_COPY = {
    NextStepClass.A0: ("Routine self-monitoring", "No immediate action is needed."),
    NextStepClass.A1: (
        "Review at next planned visit",
        "Keep the finding on the next routine review.",
    ),
    NextStepClass.A2: (
        "Schedule routine follow-up",
        "Arrange a follow-up appointment at a convenient time.",
    ),
    NextStepClass.A3: (
        "Contact clinician soon",
        "The finding warrants timely clinical follow-up.",
    ),
    NextStepClass.A4: ("Seek urgent review", "The finding needs urgent attention."),
    NextStepClass.AX: (
        "Next step could not be determined safely",
        "The artifact should not overstate a recommendation.",
    ),
}

_NEXTSTEP_ORDER = {
    NextStepClass.A0: 0,
    NextStepClass.A1: 1,
    NextStepClass.A2: 2,
    NextStepClass.A3: 3,
    NextStepClass.A4: 4,
    NextStepClass.AX: 5,
}

_NOT_ASSESSED_ALLOWED_KEYS = frozenset({"raw_label", "reason"})
_NOT_ASSESSED_REASON_VALUES = {reason.value for reason in UnsupportedReason}
_NOT_ASSESSED_HARD_MAX = 1000


def _coerce_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _coerce_support_banner(value: SupportBanner | str) -> SupportBanner:
    return value if isinstance(value, SupportBanner) else SupportBanner(str(value))


def _coerce_trust_status(value: TrustStatus | str) -> TrustStatus:
    return value if isinstance(value, TrustStatus) else TrustStatus(str(value))


def _normalize_findings(findings: list[dict]) -> list[dict]:
    return [FindingSchema.model_validate(finding).model_dump(mode="json") for finding in findings]


def _severity_rank(severity: SeverityClass) -> int:
    return _SEVERITY_ORDER[severity]


def _highest_severity(findings: list[dict]) -> SeverityClass:
    if not findings:
        return SeverityClass.S0
    return max(
        (SeverityClass(finding["severity_class"]) for finding in findings),
        key=_severity_rank,
    )


def _highest_nextstep(findings: list[dict]) -> NextStepClass:
    if not findings:
        return NextStepClass.A0
    return max(
        (NextStepClass(finding["nextstep_class"]) for finding in findings),
        key=lambda value: _NEXTSTEP_ORDER[value],
    )


def _make_flagged_cards(
    findings: list[dict],
    context: dict,
    observations: list[dict] | None = None,
) -> list[dict]:
    # Build obs lookup so each flagged card displays the actual raw analyte label,
    # observed value, and unit from its originating observation(s) — not a shared
    # placeholder that shows "n/a" for every row.
    obs_by_id: dict[str, dict] = {}
    if observations:
        for obs in observations:
            obs_id = str(obs.get("id") or "")
            if obs_id:
                obs_by_id[obs_id] = obs

    cards: list[dict] = []
    for finding in findings:
        severity = SeverityClass(finding["severity_class"])
        if finding.get("suppression_active") or severity == SeverityClass.S0:
            continue

        linked_obs: dict | None = None
        for oid in finding.get("observation_ids", []) or []:
            linked_obs = obs_by_id.get(str(oid))
            if linked_obs is not None:
                break

        default_display = (
            finding.get("explanatory_scaffold_id") or finding["rule_id"].replace("_", " ").title()
        )
        if linked_obs is not None:
            analyte_display = (
                linked_obs.get("accepted_analyte_display")
                or linked_obs.get("raw_analyte_label")
                or default_display
            )
            value = (
                linked_obs.get("canonical_value")
                if linked_obs.get("canonical_value") is not None
                else linked_obs.get("parsed_numeric_value")
            )
            if value is None:
                value = linked_obs.get("raw_value_string")
            unit = (
                linked_obs.get("canonical_unit")
                or linked_obs.get("raw_unit_string")
                or ""
            )
        else:
            analyte_display = context.get("analyte_display", default_display)
            value = context.get("value", "n/a")
            unit = context.get("unit", "")

        cards.append(
            {
                "analyte_display": _safe_text(analyte_display),
                "value": _safe_text(value if value is not None else "n/a"),
                "unit": _safe_text(unit or ""),
                "finding_sentence": context.get(
                    "finding_sentence",
                    f"{_safe_text(analyte_display)} requires clinical review.",
                ),
                "threshold_provenance": finding["threshold_source"],
                "severity_chip": severity,
            }
        )
    return cards


def _make_not_assessed(findings: list[dict], observations: list[dict] | None = None) -> list[dict]:
    items: list[dict] = []
    finding_obs_ids: set[str] = set()
    suppressed_count = 0

    obs_map = {}
    if observations:
        for obs in observations:
            obs_id = str(obs.get("id"))
            if obs_id and obs.get("raw_analyte_label"):
                obs_map[obs_id] = str(obs["raw_analyte_label"])

    for finding in findings:
        for obs_id in finding.get("observation_ids", []):
            finding_obs_ids.add(str(obs_id))

        if finding.get("suppression_active"):
            suppressed_count += 1

            raw_label = finding.get("rule_id", "unknown")
            obs_ids = finding.get("observation_ids", [])
            for obs_id in obs_ids:
                if str(obs_id) in obs_map:
                    raw_label = obs_map[str(obs_id)]
                    break

            items.append(
                {
                    "raw_label": raw_label,
                    "reason": _coerce_not_assessed_reason(finding.get("suppression_reason")),
                }
            )

    unmatched_observation_count = 0
    if observations:
        for observation in observations:
            support_state = observation.get("support_state")
            if hasattr(support_state, "value"):
                support_state = support_state.value
            if str(support_state or "").lower() != "supported":
                obs_id = str(observation.get("id", ""))
                if obs_id not in finding_obs_ids:
                    unmatched_observation_count += 1
                    suppression_reasons = observation.get("suppression_reasons") or []
                    items.append(
                        {
                            "raw_label": observation.get("raw_analyte_label", "unknown"),
                            "reason": _coerce_not_assessed_reason(
                                suppression_reasons[0] if suppression_reasons else None
                            ),
                        }
                    )

    deduped_items = _dedupe_not_assessed_items(items)
    _validate_not_assessed_items(
        deduped_items,
        max_items=suppressed_count + unmatched_observation_count,
    )
    return deduped_items


def _apply_comparable_history_not_assessed(
    items: list[dict],
    comparable_history: dict | None,
) -> list[dict]:
    if comparable_history is None:
        return items
    if comparable_history.get("comparability_status") != "unavailable":
        return items

    raw_label = f"prior {_normalize_comparable_history_label(comparable_history)} trend"
    if any(
        item.get("reason") == "comparable_history_unavailable"
        and item.get("raw_label") == raw_label
        for item in items
    ):
        return items

    next_items = [
        *items,
        {
            "raw_label": raw_label,
            "reason": "comparable_history_unavailable",
        },
    ]
    _validate_not_assessed_items(next_items, max_items=len(items) + 1)
    return next_items


def _normalize_comparable_history_label(comparable_history: dict) -> str:
    return str(comparable_history.get("analyte_display") or "unknown analyte").strip().lower()


def _coerce_not_assessed_reason(reason: object) -> str:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return UnsupportedReason.INSUFFICIENT_SUPPORT.value
    if normalized in _NOT_ASSESSED_REASON_VALUES:
        return normalized
    if normalized in {"unsupported_alias", "unsupported_analyte", "unsupported_analyte_family"}:
        return UnsupportedReason.UNSUPPORTED_ANALYTE_FAMILY.value
    if normalized.startswith("unsupported_unit") or normalized == "unresolved_reference_profile":
        return UnsupportedReason.UNSUPPORTED_UNIT_OR_REFERENCE_RANGE.value
    if normalized in {"missing_demographics_overlay", "missing_numeric_value"}:
        return UnsupportedReason.INSUFFICIENT_SUPPORT.value
    return UnsupportedReason.INSUFFICIENT_SUPPORT.value


def _dedupe_not_assessed_items(items: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            deduped.append(item)
            continue
        raw_label = str(item.get("raw_label", ""))
        reason = str(item.get("reason", ""))
        key = (raw_label, reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _validate_not_assessed_items(items: list[dict], *, max_items: int | None) -> None:
    if len(items) > _NOT_ASSESSED_HARD_MAX:
        raise ValueError(f"not_assessed_hard_limit_exceeded:{len(items)}")
    if max_items is not None and len(items) > max_items:
        raise ValueError(f"not_assessed_cardinality_exceeds_runtime_max:{len(items)}>{max_items}")

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"not_assessed_item_not_object:{index}")
        if set(item.keys()) != _NOT_ASSESSED_ALLOWED_KEYS:
            raise ValueError(f"not_assessed_item_keys_invalid:{index}")

        raw_label = item.get("raw_label")
        reason = item.get("reason")
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise ValueError(f"not_assessed_raw_label_invalid:{index}")
        if not isinstance(reason, str) or reason not in _NOT_ASSESSED_REASON_VALUES:
            raise ValueError(f"not_assessed_reason_invalid:{index}")


class ArtifactRenderer:
    """Render patient artifact (Screen C) and clinician-share artifact (Screen F).

    Both derived from the same structured findings packet.
    """

    def render_patient(
        self,
        findings: list[dict],
        context: dict,
        observations: list[dict] | None = None,
    ) -> dict:
        normalized_findings = _normalize_findings(findings)
        highest_severity = _highest_severity(normalized_findings)
        highest_nextstep = _highest_nextstep(normalized_findings)
        nextstep_title, nextstep_reason = _NEXTSTEP_COPY[highest_nextstep]
        comparable_history = context.get("comparable_history")
        not_assessed = _make_not_assessed(normalized_findings, observations)

        return {
            "job_id": _coerce_uuid(context["job_id"]),
            "support_banner": _coerce_support_banner(
                context.get("support_banner", SupportBanner.FULLY_SUPPORTED)
            ),
            "trust_status": _coerce_trust_status(context.get("trust_status", TrustStatus.TRUSTED)),
            "overall_severity": highest_severity,
            "flagged_cards": _make_flagged_cards(normalized_findings, context, observations),
            "reviewed_not_flagged": [
                finding["rule_id"]
                for finding in normalized_findings
                if SeverityClass(finding["severity_class"]) == SeverityClass.S0
            ],
            "nextstep_title": nextstep_title,
            "nextstep_timing": context.get("nextstep_timing")
            or {
                NextStepClass.A0: "Routine monitoring",
                NextStepClass.A1: "At the next planned visit",
                NextStepClass.A2: "Within the next few weeks",
                NextStepClass.A3: "Within the next few days",
                NextStepClass.A4: "Immediately",
                NextStepClass.AX: "Not available",
            }[highest_nextstep],
            "nextstep_reason": context.get("nextstep_reason") or nextstep_reason,
            "not_assessed": not_assessed,
            "findings": normalized_findings,
            "language_id": context.get("language_id", "en"),
            "comparable_history": comparable_history,
        }

    def render_clinician(
        self,
        findings: list[dict],
        context: dict,
        observations: list[dict] | None = None,
    ) -> dict:
        normalized_findings = _normalize_findings(findings)
        severity_classes = sorted(
            {SeverityClass(finding["severity_class"]) for finding in normalized_findings},
            key=_severity_rank,
            reverse=True,
        )
        nextstep_classes = sorted(
            {NextStepClass(finding["nextstep_class"]) for finding in normalized_findings},
            key=lambda value: value.value,
        )

        return {
            "job_id": _coerce_uuid(context["job_id"]),
            "report_date": context.get("report_date", "1970-01-01"),
            "top_findings": normalized_findings,
            "severity_classes": severity_classes,
            "nextstep_classes": nextstep_classes,
            "support_coverage": _coerce_support_banner(
                context.get("support_banner", SupportBanner.FULLY_SUPPORTED)
            ),
            "trust_status": _coerce_trust_status(context.get("trust_status", TrustStatus.TRUSTED)),
            "not_assessed": _make_not_assessed(normalized_findings, observations),
            "provenance_link": context.get("provenance_link"),
        }
