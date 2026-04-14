from __future__ import annotations

from dataclasses import dataclass

from app.services.row_grammar import classify_candidate_text
from app.services.row_grammar.continuation_rules import (
    classify_continuation,
    is_value_bearing_line,
)


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

        continuation = classify_continuation(cleaned)
        if continuation == "sample_index" and is_value_bearing_line(cleaned):
            continuation = None
        if continuation is not None:
            return LineClassification(
                line=cleaned,
                line_type=f"continuation:{continuation}",
                row_type=str(parsed["row_type"]),
                support_code=str(parsed.get("support_code") or "supported"),
                failure_code=parsed.get("failure_code"),
            )

        if (
            parsed.get("measurement_kind") == "categorical"
            and parsed["row_type"] in {"measured_analyte_row", "derived_analyte_row"}
        ):
            return LineClassification(
                line=cleaned,
                line_type="value",
                row_type=str(parsed["row_type"]),
                support_code=str(parsed.get("support_code") or "supported"),
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

        return LineClassification(
            line=cleaned,
            line_type="label",
            row_type=str(parsed["row_type"]),
            support_code=str(parsed.get("support_code") or "supported"),
            failure_code=parsed.get("failure_code"),
        )
