"""Deterministic reference selection service."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict


class ReferenceConflictCode(StrEnum):
    CONTEXT_CONFLICTED = "context_conflicted"
    CONTEXT_MISSING = "context_missing"
    REFERENCE_MISSING = "reference_missing"


class ReferenceDecisionV1(TypedDict):
    source_type: str
    selected_rule: str | None
    required_context: list[str]
    conflict_state: str
    unresolved_reason: str | None


class ReferenceSelectionService:
    """Select reproducible reference context for observations."""

    def select_for_observations(
        self,
        observations: list[dict[str, Any]],
        patient_context: dict[str, Any],
    ) -> dict[str, ReferenceDecisionV1]:
        decisions: dict[str, ReferenceDecisionV1] = {}
        context_status = str(patient_context.get("context_status") or "missing")
        missing_reasons = list(patient_context.get("missing_reason_codes") or [])

        for observation in observations:
            observation_id = str(observation.get("id") or observation.get("row_hash") or "")
            if not observation_id:
                continue

            raw_reference = str(observation.get("raw_reference_range") or "").strip()
            required_context: list[str] = []
            unresolved_reason: str | None = None
            conflict_state = "none"

            if context_status == "conflicted":
                conflict_state = ReferenceConflictCode.CONTEXT_CONFLICTED.value
                unresolved_reason = ReferenceConflictCode.CONTEXT_CONFLICTED.value
            elif context_status == "missing" and missing_reasons:
                required_context = list(missing_reasons)
                conflict_state = ReferenceConflictCode.CONTEXT_MISSING.value

            if raw_reference:
                selected_rule = "raw_reference_range"
                source_type = "observation_reference_range"
            else:
                selected_rule = None
                source_type = "none"
                unresolved_reason = unresolved_reason or ReferenceConflictCode.REFERENCE_MISSING.value

            decisions[observation_id] = {
                "source_type": source_type,
                "selected_rule": selected_rule,
                "required_context": required_context,
                "conflict_state": conflict_state,
                "unresolved_reason": unresolved_reason,
            }

        return decisions
