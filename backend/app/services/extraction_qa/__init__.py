"""Extraction quality assurance checks."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from app.services.parser import classify_candidate_text

_ALLOWED_ROW_TYPES = {"measured_analyte_row", "derived_analyte_row"}


class ExtractionQA:
    """Validate extraction results before observation building."""

    def validate(self, extracted_rows: list[dict[str, Any]]) -> dict[str, Any]:
        clean_rows: list[dict[str, Any]] = []
        rejected_rows: list[dict[str, Any]] = []

        for row in extracted_rows:
            normalized_row = deepcopy(row)
            raw_label = str(normalized_row.get("raw_analyte_label") or "").strip()
            raw_text = str(normalized_row.get("raw_text") or raw_label)
            row_type = str(normalized_row.get("row_type") or "").strip()
            if not row_type:
                row_type = classify_candidate_text(
                    raw_text,
                    page_class=str(normalized_row.get("page_class") or "unknown"),
                    family_adapter_id=str(normalized_row.get("family_adapter_id") or "generic_layout"),
                )["row_type"]

            if not raw_label:
                rejected_rows.append(
                    {
                        "row_hash": normalized_row.get("row_hash"),
                        "reason": "missing_analyte_label",
                        "row": normalized_row,
                    }
                )
                continue

            normalized_row["raw_analyte_label"] = raw_label
            normalized_row["row_type"] = row_type

            if row_type not in _ALLOWED_ROW_TYPES:
                rejected_rows.append(
                    {
                        "row_hash": normalized_row.get("row_hash"),
                        "reason": str(normalized_row.get("failure_code") or row_type or "excluded_row"),
                        "row": normalized_row,
                    }
                )
                continue

            if (
                normalized_row.get("parsed_numeric_value") is None
                and normalized_row.get("raw_value_string") in (None, "")
                and normalized_row.get("primary_result") in (None, {})
            ):
                rejected_rows.append(
                    {
                        "row_hash": normalized_row.get("row_hash"),
                        "reason": str(
                            normalized_row.get("failure_code")
                            or "missing_result_value"
                        ),
                        "row": normalized_row,
                    }
                )
                continue

            raw_value_string = str(normalized_row.get("raw_value_string") or "").strip("() ").lower()
            if (
                row_type == "derived_analyte_row"
                and normalized_row.get("parsed_numeric_value") is None
                and not normalized_row.get("source_observation_ids")
            ) or (
                normalized_row.get("parsed_numeric_value") is None
                and raw_value_string
                and raw_value_string == raw_label.lower()
            ):
                rejected_rows.append(
                    {
                        "row_hash": normalized_row.get("row_hash"),
                        "reason": str(
                            normalized_row.get("failure_code")
                            or "missing_result_value"
                        ),
                        "row": normalized_row,
                    }
                )
                continue

            clean_rows.append(normalized_row)

        rejection_counts = Counter(rejection["reason"] for rejection in rejected_rows)
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
