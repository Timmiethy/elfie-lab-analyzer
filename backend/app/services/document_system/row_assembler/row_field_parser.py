from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.services.row_grammar import parse_measurement_text

from ..contracts import CandidateRowTypeV3, CandidateRowV3


@dataclass(frozen=True)
class RowFieldParseInput:
    document_id: str
    page_id: str
    source_page: int
    source_block_id: str
    family_adapter_id: str
    page_class: str
    parser_backend: str
    parser_backend_version: str
    source_kind: str
    segment_index: int


class RowFieldParser:
    def parse(self, candidate_text: str, context: RowFieldParseInput) -> CandidateRowV3:
        parsed = parse_measurement_text(
            candidate_text,
            page_class=context.page_class,
            family_adapter_id=context.family_adapter_id,
            source_kind=context.source_kind,
            page_number=context.source_page,
            block_id=context.source_block_id,
            segment_index=context.segment_index,
        )

        row_type = _to_row_type(parsed.get("row_type"))
        row_id = _stable_row_id(
            page_id=context.page_id,
            block_id=context.source_block_id,
            row_type=row_type.value,
            raw_text=candidate_text,
        )

        return CandidateRowV3(
            row_id=row_id,
            document_id=context.document_id,
            source_page=context.source_page,
            source_block_id=context.source_block_id,
            row_type=row_type,
            raw_text=candidate_text,
            raw_label=str(parsed.get("raw_analyte_label") or candidate_text.split()[0] if candidate_text.split() else candidate_text),
            raw_value=parsed.get("raw_value_string"),
            raw_unit=parsed.get("raw_unit_string"),
            raw_reference_range=parsed.get("raw_reference_range"),
            parsed_numeric_value=parsed.get("parsed_numeric_value"),
            parsed_comparator=parsed.get("parsed_comparator"),
            parsed_locale=dict(parsed.get("parsed_locale") or {}),
            secondary_result=parsed.get("secondary_result"),
            support_state=str(parsed.get("support_code") or "excluded"),
            support_code=str(parsed.get("support_code") or "excluded"),
            failure_code=parsed.get("failure_code"),
            confidence=float(parsed.get("extraction_confidence") or 0.0),
            family_adapter_id=context.family_adapter_id,
            page_class=context.page_class,
            source_kind=context.source_kind,
            source_bounds=parsed.get("source_bounds"),
            candidate_trace={
                "page_id": context.page_id,
                "source_block_id": context.source_block_id,
                "segment_index": context.segment_index,
                "source_kind": context.source_kind,
            },
            parser_backend=context.parser_backend,
            parser_backend_version=context.parser_backend_version,
        )


def _to_row_type(value: object) -> CandidateRowTypeV3:
    raw = str(value or "unparsed_row")
    for row_type in CandidateRowTypeV3:
        if row_type.value == raw:
            return row_type
    if raw in {"footer_or_header_row"}:
        return CandidateRowTypeV3.HEADER_FOOTER_ROW
    return CandidateRowTypeV3.UNPARSED_ROW


def _stable_row_id(*, page_id: str, block_id: str, row_type: str, raw_text: str) -> str:
    source = f"{page_id}:{block_id}:{row_type}:{raw_text}"
    return sha256(source.encode("utf-8")).hexdigest()
