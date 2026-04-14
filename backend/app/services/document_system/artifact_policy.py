from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .config_registry import FamilyConfigRegistry, get_family_config_registry


@dataclass(frozen=True)
class ArtifactPolicyResult:
    not_assessed: list[dict[str, str]]
    grouped_counts: dict[str, int]


class ArtifactPolicy:
    """Final safety backstop for patient-visible unsupported/not-assessed payloads."""

    def __init__(self, registry: FamilyConfigRegistry | None = None) -> None:
        self._registry = registry or get_family_config_registry()

    def sanitize_not_assessed(self, items: list[dict[str, object]]) -> ArtifactPolicyResult:
        visible_reason_map = self._registry.visible_unsupported_categories()
        hidden_markers = self._registry.hidden_markers()

        sanitized: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        grouped = Counter()

        for item in items:
            raw_label_original = _clean(str(item.get("raw_label") or "unknown"))
            raw_label = _normalize(raw_label_original)
            raw_reason = _normalize(str(item.get("reason") or "unreadable_value"))
            canonical_reason = visible_reason_map.get(raw_reason, raw_reason)

            if _contains_hidden_marker(raw_label, hidden_markers):
                if canonical_reason == "threshold_conflict":
                    raw_label_original = "threshold_conflict"
                    raw_label = "threshold_conflict"
                else:
                    continue
            if _contains_hidden_marker(raw_reason, hidden_markers) and canonical_reason not in {
                *visible_reason_map.keys(),
                *visible_reason_map.values(),
            }:
                continue

            if not canonical_reason:
                canonical_reason = "unreadable_value"

            dedupe_key = (raw_label, canonical_reason)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            sanitized.append(
                {
                    "raw_label": raw_label_original,
                    "reason": canonical_reason,
                }
            )
            grouped[canonical_reason] += 1

        return ArtifactPolicyResult(
            not_assessed=sanitized,
            grouped_counts=dict(grouped),
        )


def _contains_hidden_marker(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())
