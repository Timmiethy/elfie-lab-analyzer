from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .line_classifier import LineClassification


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

        pending_labels.extend(group.lines)

    return merged
