from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.parser import classify_candidate_text


_COMPARATOR_RE = re.compile(r"^(?:<=|>=|<|>|<=|>=)\s*\d")
_NUMERIC_RE = re.compile(r"(?:^|\s)(?:<=|>=|<|>)?\s*\d[\d.,]*(?:\s|$)")
_UNIT_ONLY_RE = re.compile(r"^(?:%|[a-zA-Z]+/[a-zA-Z0-9/]+|[a-zA-Z]{1,4}\d*)$")
_REF_RANGE_RE = re.compile(r"^[\[(]?\s*(?:<=|>=|<|>)?\s*\d[\d.,]*\s*[-–]\s*(?:<=|>=|<|>)?\s*\d[\d.,]*\s*[\])]?$")


@dataclass(frozen=True)
class LineClassification:
    line: str
    line_type: str
    row_type: str
    support_code: str
    failure_code: str | None


class LineClassifier:
    def classify_line(
        self,
        line: str,
        *,
        page_class: str,
        family_adapter_id: str,
    ) -> LineClassification:
        cleaned = " ".join(str(line or "").split())
        if not cleaned:
            return LineClassification(
                line=cleaned,
                line_type="empty",
                row_type="unparsed_row",
                support_code="excluded",
                failure_code="empty_or_noise",
            )

        parsed = classify_candidate_text(
            cleaned,
            page_class=page_class,
            family_adapter_id=family_adapter_id,
        )

        if parsed["row_type"] in {
            "admin_metadata_row",
            "narrative_guidance_row",
            "threshold_reference_row",
            "header_footer_row",
            "test_request_row",
        }:
            return LineClassification(
                line=cleaned,
                line_type="excluded",
                row_type=str(parsed["row_type"]),
                support_code=str(parsed.get("support_code") or "excluded"),
                failure_code=parsed.get("failure_code"),
            )

        if is_value_bearing_line(cleaned):
            return LineClassification(
                line=cleaned,
                line_type="value",
                row_type=str(parsed["row_type"]),
                support_code=str(parsed.get("support_code") or "supported"),
                failure_code=parsed.get("failure_code"),
            )

        continuation = classify_continuation(cleaned)
        if continuation is not None:
            return LineClassification(
                line=cleaned,
                line_type=f"continuation:{continuation}",
                row_type=str(parsed["row_type"]),
                support_code=str(parsed.get("support_code") or "supported"),
                failure_code=parsed.get("failure_code"),
            )

        return LineClassification(
            line=cleaned,
            line_type="label",
            row_type=str(parsed["row_type"]),
            support_code=str(parsed.get("support_code") or "supported"),
            failure_code=parsed.get("failure_code"),
        )


def is_value_bearing_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return False
    if _COMPARATOR_RE.match(text):
        return True
    return _NUMERIC_RE.search(text) is not None


def classify_continuation(line: str) -> str | None:
    text = line.strip()
    if not text:
        return None
    if _UNIT_ONLY_RE.match(text):
        return "unit"
    if _REF_RANGE_RE.match(text):
        return "reference_range"
    if text.lower() in {"high", "low", "normal", "abnormal", "h", "l", "trace", "positive", "negative"}:
        return "flag"
    if re.match(r"^\d{1,2}$", text):
        return "sample_index"
    return None
