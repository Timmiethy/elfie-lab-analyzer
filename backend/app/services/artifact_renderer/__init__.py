"""Artifact renderer: patient and clinician artifact generation."""

from __future__ import annotations

from uuid import UUID

from app.schemas.artifact import SupportBanner, TrustStatus
from app.schemas.finding import FindingSchema, NextStepClass, SeverityClass

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


def _make_flagged_cards(findings: list[dict], context: dict) -> list[dict]:
    cards: list[dict] = []
    for finding in findings:
        severity = SeverityClass(finding["severity_class"])
        if finding.get("suppression_active") or severity == SeverityClass.S0:
            continue
        display = (
            finding.get("explanatory_scaffold_id") or finding["rule_id"].replace("_", " ").title()
        )
        cards.append(
            {
                "analyte_display": context.get("analyte_display", display),
                "value": str(context.get("value", "n/a")),
                "unit": str(context.get("unit", "")),
                "finding_sentence": context.get(
                    "finding_sentence",
                    f"{display} requires clinical review.",
                ),
                "threshold_provenance": finding["threshold_source"],
                "severity_chip": severity,
            }
        )
    return cards


def _make_not_assessed(findings: list[dict], observations: list[dict] | None = None) -> list[dict]:
    items: list[dict] = []
    finding_obs_ids: set[str] = set()
    for finding in findings:
        if finding.get("suppression_active") or (
            SeverityClass(finding["severity_class"]) == SeverityClass.SX
        ):
            items.append(
                {
                    "raw_label": finding["rule_id"],
                    "reason": finding.get("suppression_reason") or "insufficient_support",
                }
            )
        for obs_id in finding.get("observation_ids", []):
            finding_obs_ids.add(str(obs_id))

    if observations:
        for observation in observations:
            support_state = observation.get("support_state")
            if hasattr(support_state, "value"):
                support_state = support_state.value
            if str(support_state or "").lower() != "supported":
                obs_id = str(observation.get("id", ""))
                if obs_id not in finding_obs_ids:
                    items.append(
                        {
                            "raw_label": observation.get("raw_analyte_label", "unknown"),
                            "reason": "insufficient_support",
                        }
                    )
    return items


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

    return [
        *items,
        {
            "raw_label": raw_label,
            "reason": "comparable_history_unavailable",
        },
    ]


def _normalize_comparable_history_label(comparable_history: dict) -> str:
    return str(comparable_history.get("analyte_display") or "unknown analyte").strip().lower()


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
        not_assessed = _apply_comparable_history_not_assessed(
            _make_not_assessed(normalized_findings, observations),
            comparable_history,
        )

        return {
            "job_id": _coerce_uuid(context["job_id"]),
            "support_banner": _coerce_support_banner(
                context.get("support_banner", SupportBanner.FULLY_SUPPORTED)
            ),
            "trust_status": _coerce_trust_status(context.get("trust_status", TrustStatus.TRUSTED)),
            "overall_severity": highest_severity,
            "flagged_cards": _make_flagged_cards(normalized_findings, context),
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
