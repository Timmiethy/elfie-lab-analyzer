from __future__ import annotations

import re
from collections import defaultdict

from ..contracts import (
    CandidateRowV3,
    NORMALIZABLE_ROW_TYPES_V3,
    SuppressionRecordV1,
    SuppressionReportV1,
)


_HEADING_SHADOW_MARKERS = {
    "reference",
    "ranges",
    "ref.",
    "diagnostic",
    "values",
    "sample",
    "report",
    "page",
}
_THRESHOLD_SHADOW_MARKERS = {
    "prediabetes",
    "ifg",
    "risk",
    "cut off",
    "threshold",
    "very high",
    "moderate",
}


class RowArbitration:
    def arbitrate(
        self,
        *,
        page_id: str,
        page_number: int,
        rows: list[CandidateRowV3],
    ) -> tuple[list[CandidateRowV3], SuppressionReportV1]:
        suppression_records: list[SuppressionRecordV1] = []

        candidates = [
            row
            for row in rows
            if _not_giant_hybrid(row, suppression_records)
        ]

        grouped: dict[str, list[CandidateRowV3]] = defaultdict(list)
        passthrough: list[CandidateRowV3] = []

        for row in candidates:
            row_type = row.row_type.value
            if row_type not in NORMALIZABLE_ROW_TYPES_V3:
                passthrough.append(row)
                continue
            grouped[_group_key(row)].append(row)

        kept: list[CandidateRowV3] = []

        for _, group in grouped.items():
            if len(group) == 1:
                row = group[0]
                if _is_threshold_shadow(row):
                    suppression_records.append(
                        SuppressionRecordV1(
                            row_id=row.row_id,
                            reason_code="threshold_shadow_row",
                            detail=row.raw_text[:160],
                        )
                    )
                    continue
                kept.append(row)
                continue

            scored = sorted(group, key=_score, reverse=True)
            winner = scored[0]
            kept.append(winner)

            for loser in scored[1:]:
                suppression_records.append(
                    SuppressionRecordV1(
                        row_id=loser.row_id,
                        reason_code="overlap_shadow_row",
                        detail=f"winner={winner.row_id}",
                    )
                )

        final_rows = passthrough + kept

        return (
            final_rows,
            SuppressionReportV1(
                page_id=page_id,
                page_number=page_number,
                suppression_records=suppression_records,
            ),
        )


def _group_key(row: CandidateRowV3) -> str:
    label = " ".join(row.raw_label.lower().split())
    key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", label).strip()
    if not key:
        key = "unknown"
    return f"{row.source_page}:{key}"


def _score(row: CandidateRowV3) -> tuple[int, int, int, int]:
    text = row.raw_text.lower()
    heading_penalty = sum(1 for marker in _HEADING_SHADOW_MARKERS if marker in text)

    value_score = 10 if row.raw_value not in (None, "") else 0
    unit_score = 4 if row.raw_unit not in (None, "") else 0
    reference_score = 2 if row.raw_reference_range not in (None, "") else 0
    support_score = 3 if row.support_code in {"supported", "partial"} else 0

    return (
        value_score + unit_score + reference_score + support_score - heading_penalty,
        1 if row.parsed_numeric_value is not None else 0,
        1 if row.parsed_comparator is not None else 0,
        len(row.raw_text),
    )


def _is_threshold_shadow(row: CandidateRowV3) -> bool:
    if row.raw_value not in (None, ""):
        return False
    text = " ".join(row.raw_text.lower().split())
    return any(marker in text for marker in _THRESHOLD_SHADOW_MARKERS)


def _not_giant_hybrid(row: CandidateRowV3, suppression_records: list[SuppressionRecordV1]) -> bool:
    token_count = len(row.raw_text.split())
    if token_count <= 48:
        return True
    suppression_records.append(
        SuppressionRecordV1(
            row_id=row.row_id,
            reason_code="giant_hybrid_row",
            detail=f"token_count={token_count}",
        )
    )
    return False
