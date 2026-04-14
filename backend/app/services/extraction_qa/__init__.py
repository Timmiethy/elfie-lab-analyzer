"""Extraction quality assurance checks."""

from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from typing import Any

from app.services.row_grammar import classify_candidate_text
from app.services.row_grammar.row_types import RowTypeV1

_ALLOWED_ROW_TYPES = {
    RowTypeV1.MEASURED_ANALYTE_ROW.value,
    RowTypeV1.DERIVED_ANALYTE_ROW.value,
    RowTypeV1.QUALITATIVE_RESULT_ROW.value,
}
_EXCLUDED_ROW_TYPES = {
    RowTypeV1.ADMIN_METADATA_ROW.value,
    RowTypeV1.THRESHOLD_REFERENCE_ROW.value,
    RowTypeV1.NARRATIVE_GUIDANCE_ROW.value,
    RowTypeV1.HEADER_FOOTER_ROW.value,
    RowTypeV1.TEST_REQUEST_ROW.value,
    RowTypeV1.UNPARSED_ROW.value,
}
_QUALITATIVE_VALUES = {
    "positive",
    "negative",
    "reactive",
    "nonreactive",
    "detected",
    "not detected",
    "present",
    "absent",
    "trace",
    "none",
    "normal",
    "abnormal",
    "dnr",
    "ldnr",
    "oor",
}
_ADMIN_OR_NARRATIVE_MARKERS = (
    "dob",
    "date of birth",
    "report printed",
    "collected",
    "referred",
    "requisition",
    "reference range",
    "guideline",
    "notes",
)
_REFERENCE_FRAGMENT_RE = re.compile(
    r"^(?:[<>]=?|≤|≥)?\s*\d[\d,]*(?:\.\d+)?\s*(?:-|–|to)\s*(?:[<>]=?|≤|≥)?\s*\d[\d,]*(?:\.\d+)?$",
    re.I,
)

_EXTRACTION_QA_CONTRACT_VERSION = "extraction-qa-report-v2"
_LEAK_REPORT_VERSION = "leak-report-v1"
_LINKAGE_REPORT_VERSION = "linkage-report-v1"

# v12: accepted parser backends that may appear on extraction rows.
# These are passive fields; unknown backends are recorded but not hard-rejected
# so older or experimental extraction paths do not silently break the funnel.
_KNOWN_PARSER_BACKENDS = {"pymupdf", "qwen_vl_ocr", "pdfplumber_debug"}


class ExtractionQA:
    """Validate extraction results before observation building."""

    def validate(self, extracted_rows: list[dict[str, Any]]) -> dict[str, Any]:
        clean_rows: list[dict[str, Any]] = []
        rejected_rows: list[dict[str, Any]] = []
        leak_counts: Counter[str] = Counter()

        linkage_counts = {
            "candidate_rows": 0,
            "analyte_value_linked": 0,
            "value_unit_linked": 0,
            "value_reference_linked": 0,
        }

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

            if row_type in _EXCLUDED_ROW_TYPES:
                rejection_reason = str(normalized_row.get("failure_code") or row_type or "excluded_row")
                rejected_rows.append(
                    {
                        "row_hash": normalized_row.get("row_hash"),
                        "reason": rejection_reason,
                        "row": normalized_row,
                    }
                )
                leak_counts[row_type] += 1
                continue

            if row_type not in _ALLOWED_ROW_TYPES:
                rejected_rows.append(
                    {
                        "row_hash": normalized_row.get("row_hash"),
                        "reason": str(normalized_row.get("failure_code") or "invalid_row_type"),
                        "row": normalized_row,
                    }
                )
                leak_counts["invalid_row_type"] += 1
                continue

            if _is_admin_or_narrative_contamination(raw_text):
                rejected_rows.append(
                    {
                        "row_hash": normalized_row.get("row_hash"),
                        "reason": "contaminated_row_text",
                        "row": normalized_row,
                    }
                )
                leak_counts["contaminated_row_text"] += 1
                continue

            has_numeric = _has_numeric_result(normalized_row)
            has_qualitative = _has_qualitative_result(normalized_row)

            if _looks_like_reference_fragment_misparsed_as_value(normalized_row):
                rejected_rows.append(
                    {
                        "row_hash": normalized_row.get("row_hash"),
                        "reason": "reference_fragment_row",
                        "row": normalized_row,
                    }
                )
                leak_counts["reference_fragment_row"] += 1
                continue

            if not has_numeric and not has_qualitative:
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
                leak_counts["missing_result_value"] += 1
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
                leak_counts["missing_result_value"] += 1
                continue

            linkage_counts["candidate_rows"] += 1
            value_present = has_numeric or has_qualitative
            unit_present = str(normalized_row.get("raw_unit_string") or "").strip() != ""
            reference_present = str(normalized_row.get("raw_reference_range") or "").strip() != ""
            if raw_label and value_present:
                linkage_counts["analyte_value_linked"] += 1
            if value_present and unit_present:
                linkage_counts["value_unit_linked"] += 1
            if value_present and reference_present:
                linkage_counts["value_reference_linked"] += 1

            clean_rows.append(normalized_row)

        rejection_counts = Counter(rejection["reason"] for rejection in rejected_rows)
        total_rows = len(extracted_rows)
        clean_count = len(clean_rows)
        rejected_count = len(rejected_rows)
        linkage_denominator = max(linkage_counts["candidate_rows"], 1)

        linkage_report = {
            "contract_version": _LINKAGE_REPORT_VERSION,
            "counts": linkage_counts,
            "ratios": {
                "analyte_value_linkage_ratio": round(
                    linkage_counts["analyte_value_linked"] / linkage_denominator,
                    4,
                ),
                "value_unit_linkage_ratio": round(
                    linkage_counts["value_unit_linked"] / linkage_denominator,
                    4,
                ),
                "value_reference_linkage_ratio": round(
                    linkage_counts["value_reference_linked"] / linkage_denominator,
                    4,
                ),
            },
        }

        leak_report = {
            "contract_version": _LEAK_REPORT_VERSION,
            "counts": dict(leak_counts),
            "total": int(sum(leak_counts.values())),
        }

        return {
            "contract_version": _EXTRACTION_QA_CONTRACT_VERSION,
            "passed": rejected_count == 0,
            "clean_rows": clean_rows,
            "rejected_rows": rejected_rows,
            "leak_report": leak_report,
            "linkage_report": linkage_report,
            "metrics": {
                "total_rows": total_rows,
                "clean_rows": clean_count,
                "rejected_rows": rejected_count,
                "pass_rate": (clean_count / total_rows) if total_rows else 0.0,
                "rejection_counts": dict(rejection_counts),
                "leak_counts": dict(leak_counts),
                "linkage_counts": linkage_counts,
            },
        }


def _has_numeric_result(row: dict[str, Any]) -> bool:
    if row.get("parsed_numeric_value") is not None:
        return True
    value = str(row.get("raw_value_string") or "").strip()
    if not value:
        return False
    try:
        float(value.replace(",", ""))
        return True
    except ValueError:
        return False


def _has_qualitative_result(row: dict[str, Any]) -> bool:
    value = str(row.get("raw_value_string") or "").strip().lower()
    if value in _QUALITATIVE_VALUES:
        return True
    primary_result = row.get("primary_result")
    if isinstance(primary_result, dict):
        raw_value = str(primary_result.get("raw_value") or primary_result.get("raw_token_string") or "").strip().lower()
        if raw_value in _QUALITATIVE_VALUES:
            return True
    return False


def _looks_like_reference_fragment_misparsed_as_value(row: dict[str, Any]) -> bool:
    raw_value = str(row.get("raw_value_string") or "").strip()
    raw_reference = str(row.get("raw_reference_range") or "").strip()
    if not raw_value:
        return False
    if _REFERENCE_FRAGMENT_RE.match(raw_value):
        return True
    if raw_reference and raw_value and raw_value in raw_reference:
        return True
    return False


def _is_admin_or_narrative_contamination(raw_text: str) -> bool:
    normalized = " ".join(str(raw_text or "").strip().lower().split())
    if not normalized:
        return False
    return any(marker in normalized for marker in _ADMIN_OR_NARRATIVE_MARKERS)
