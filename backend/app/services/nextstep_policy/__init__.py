"""Deterministic next-step policy engine (blueprint section 3.10)."""

from __future__ import annotations

from copy import deepcopy

from app.config import settings


class NextStepPolicyEngine:
    def assign(self, findings: list[dict], patient_context: dict) -> list[dict]:
        assigned_findings: list[dict] = []
        for finding in findings:
            updated = deepcopy(finding)
            updated["nextstep_class"] = self._assign_next_step(updated)
            assigned_findings.append(updated)
        return assigned_findings

    def _assign_next_step(self, finding: dict) -> str:
        if finding.get("suppression_active"):
            return "AX"

        severity_class = finding.get("severity_class")
        if hasattr(severity_class, "value"):
            severity_class = severity_class.value
        if severity_class == "S4" and not settings.critical_value_source_signed_off:
            severity_class = "S3"

        table = {
            "S0": "A0",
            "S1": "A1",
            "S2": "A2",
            "S3": "A3",
            "S4": "A4",
            "SX": "AX",
        }
        return table.get(str(severity_class), "AX")
