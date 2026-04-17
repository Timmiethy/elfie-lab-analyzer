"""Deterministic severity policy engine (blueprint section 3.9)."""

from __future__ import annotations

from copy import deepcopy

from app.config import settings


def _coerce_text(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


class SeverityPolicyEngine:
    def assign(self, findings: list[dict], patient_context: dict) -> list[dict]:
        age_years = patient_context.get("age_years")
        # Treat unknown age as adult for severity assessment. Forcing SX when the
        # upload form didn't collect age produces "Cannot assess" for every finding
        # even though the rule thresholds are adult defaults that are still the best
        # available signal. Findings that *require* demographics set
        # suppression_active=True upstream (rule_engine.missing_overlay path).
        is_child = isinstance(age_years, (int, float)) and age_years < 18

        assigned_findings: list[dict] = []
        for finding in findings:
            updated = deepcopy(finding)
            base_class = _coerce_text(updated.get("severity_class_candidate")) or _coerce_text(
                updated.get("severity_class")
            )
            if updated.get("suppression_active"):
                updated["severity_class"] = "SX"
            elif is_child:
                updated["severity_class"] = "SX"
            else:
                updated["severity_class"] = self._apply_urgent_gate(base_class or "SX")
            assigned_findings.append(updated)
        return assigned_findings

    @staticmethod
    def _apply_urgent_gate(severity_class: str) -> str:
        if severity_class == "S4" and not settings.critical_value_source_signed_off:
            return "S3"
        return severity_class
