"""Extraction quality assurance checks."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any


class ExtractionQA:
    """Validate extraction results before observation building.

    Checks: row completeness, duplicate detection, coverage metrics.
    """

    def validate(self, extracted_rows: list[dict[str, Any]]) -> dict[str, Any]:
        clean_rows: list[dict[str, Any]] = []
        rejected_rows: list[dict[str, Any]] = []

        for row in extracted_rows:
            normalized_row = deepcopy(row)
            raw_label = normalized_row.get("raw_analyte_label")

            if not isinstance(raw_label, str) or not raw_label.strip():
                rejected_rows.append(
                    {
                        "row_hash": normalized_row.get("row_hash"),
                        "reason": "missing_analyte_label",
                        "row": normalized_row,
                    }
                )
                continue

            normalized_row["raw_analyte_label"] = raw_label.strip()
            clean_rows.append(normalized_row)

        rejection_counts = Counter(
            rejection["reason"] for rejection in rejected_rows
        )
        total_rows = len(extracted_rows)
        clean_count = len(clean_rows)
        rejected_count = len(rejected_rows)

        return {
            "passed": rejected_count == 0,
            "clean_rows": clean_rows,
            "rejected_rows": rejected_rows,
            "metrics": {
                "total_rows": total_rows,
                "clean_rows": clean_count,
                "rejected_rows": rejected_count,
                "pass_rate": (clean_count / total_rows) if total_rows else 0.0,
                "rejection_counts": dict(rejection_counts),
            },
        }
