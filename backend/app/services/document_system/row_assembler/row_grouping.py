from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from .line_classifier import LineClassification

_HEADING_HINTS = {
    "biochemistry",
    "haematology",
    "hematology",
    "chemistry",
    "analytes",
    "results",
    "reference",
    "ranges",
    "ratio",
    "profile",
    "section",
}


@dataclass(frozen=True)
class GroupedRowLines:
    lines: list[str]
    has_value: bool


def group_lines(
    line_items: list[LineClassification],
    *,
    is_excluded_label_group: Callable[[list[str]], bool] | None = None,
) -> list[GroupedRowLines]:
    groups: list[GroupedRowLines] = []
    current_lines: list[str] = []
    has_value = False

    for item in line_items:
        if item.line_type == "empty":
            continue

        if item.line_type == "excluded":
            if current_lines and has_value:
                groups.append(GroupedRowLines(lines=current_lines, has_value=True))
            current_lines = []
            has_value = False
            continue

        if item.line_type == "value":
            if has_value and current_lines:
                if _is_value_sidecar_line(item.line):
                    current_lines.append(item.line)
                    continue
                groups.append(GroupedRowLines(lines=current_lines, has_value=True))
                current_lines = [item.line]
            else:
                current_lines.append(item.line)
            has_value = True
            continue

        if item.line_type.startswith("continuation:"):
            if current_lines:
                current_lines.append(item.line)
            else:
                current_lines = [item.line]
            continue

        # label line
        if has_value and current_lines:
            groups.append(GroupedRowLines(lines=current_lines, has_value=True))
            current_lines = [item.line]
            has_value = False
        else:
            current_lines.append(item.line)

    if current_lines:
        groups.append(GroupedRowLines(lines=current_lines, has_value=has_value))

    # Merge label-only groups into subsequent value groups, unless excluded.
    merged: list[GroupedRowLines] = []
    pending_labels: list[str] = []

    for group in groups:
        if group.has_value:
            if pending_labels:
                merged_lines = pending_labels + group.lines
                pending_labels = []
                merged.append(GroupedRowLines(lines=merged_lines, has_value=True))
            else:
                merged.append(group)
            continue

        if is_excluded_label_group is not None and is_excluded_label_group(group.lines):
            pending_labels = []
            continue

        if _is_heading_label_group(group.lines):
            pending_labels = []
            continue

        pending_labels.extend(group.lines)

    return merged


def _is_heading_label_group(lines: list[str]) -> bool:
    if not lines:
        return False
    normalized = " ".join(" ".join(lines).lower().split())
    if not normalized:
        return False
    if any(ch.isdigit() for ch in normalized):
        return False
    if any(hint in normalized for hint in _HEADING_HINTS):
        return True
    return all(str(line).strip().isupper() for line in lines) and len(normalized.split()) <= 6


def _is_value_sidecar_line(line: str) -> bool:
    normalized = " ".join(str(line or "").lower().split())
    if not normalized:
        return False

    if re.fullmatch(r"\d{1,2}", normalized):
        return True

    if re.fullmatch(r"%(?:\s+\d{1,2})?", normalized):
        return True

    return bool(
        re.match(
            r"^(?:<\s*or\s*=|>\s*or\s*=|<=|>=|<|>|≤|≥)?\s*\d",
            normalized,
        )
    )
