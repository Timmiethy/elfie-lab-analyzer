from __future__ import annotations

import re
from hashlib import sha256

from ..contracts import (
    BlockGraphV1,
    BlockRoleV1,
    CandidateRowTypeV3,
    CandidateRowV3,
    PageParseArtifactV4,
    SuppressionReportV1,
)
from .line_classifier import LineClassifier
from .row_arbitration import RowArbitration
from .row_field_parser import RowFieldParseInput, RowFieldParser
from .row_grouping import group_lines


class RowAssemblerV3:
    """Modular row assembler using line classification, grouping, parsing, arbitration."""

    def __init__(self) -> None:
        self._line_classifier = LineClassifier()
        self._row_field_parser = RowFieldParser()
        self._row_arbitration = RowArbitration()

    def assemble(
        self,
        *,
        block_graph: BlockGraphV1,
        artifact: PageParseArtifactV4,
        family_adapter_id: str,
        page_class: str,
    ) -> tuple[list[CandidateRowV3], SuppressionReportV1]:
        rows: list[CandidateRowV3] = []

        for node in block_graph.nodes:
            if bool((node.metadata or {}).get("block_classification_ambiguous")):
                rows.append(
                    _excluded_row(
                        artifact=artifact,
                        source_block_id=node.block_id,
                        raw_text=node.text,
                        family_adapter_id=family_adapter_id,
                        page_class=page_class,
                        block_role=BlockRoleV1.UNKNOWN_BLOCK,
                        reason_code="ambiguous_block_classification",
                    )
                )
                continue

            if node.block_role in {
                BlockRoleV1.ADMIN_BLOCK,
                BlockRoleV1.NARRATIVE_BLOCK,
                BlockRoleV1.THRESHOLD_BLOCK,
                BlockRoleV1.HEADER_FOOTER_BLOCK,
            }:
                rows.append(
                    _excluded_row(
                        artifact=artifact,
                        source_block_id=node.block_id,
                        raw_text=node.text,
                        family_adapter_id=family_adapter_id,
                        page_class=page_class,
                        block_role=node.block_role,
                    )
                )
                continue

            line_values = [line.strip() for line in node.text.splitlines() if line.strip()]
            if not line_values and node.text.strip():
                line_values = [node.text.strip()]
            if not line_values:
                continue

            line_items = [
                self._line_classifier.classify_line(
                    line,
                    page_class=page_class,
                    family_adapter_id=family_adapter_id,
                )
                for line in line_values
            ]

            grouped = group_lines(
                line_items,
                is_excluded_label_group=lambda group_lines: _all_excluded(
                    group_lines,
                    line_classifier=self._line_classifier,
                    page_class=page_class,
                    family_adapter_id=family_adapter_id,
                ),
            )

            for index, group in enumerate(grouped, start=1):
                candidate_text = _sanitize_candidate_text(" ".join(group.lines).strip())
                if not candidate_text:
                    continue

                parsed = self._row_field_parser.parse(
                    candidate_text,
                    RowFieldParseInput(
                        document_id=artifact.page_id,
                        page_id=artifact.page_id,
                        source_page=artifact.page_number,
                        source_block_id=node.block_id,
                        family_adapter_id=family_adapter_id,
                        page_class=page_class,
                        parser_backend=artifact.backend_id,
                        parser_backend_version=artifact.backend_version,
                        source_kind="block_graph",
                        segment_index=index,
                    ),
                )
                rows.append(parsed)

        return self._row_arbitration.arbitrate(
            page_id=artifact.page_id,
            page_number=artifact.page_number,
            rows=rows,
        )


def candidate_row_to_legacy(row: CandidateRowV3, *, trust_level: str) -> dict[str, object]:
    return {
        "document_id": row.document_id,
        "source_page": row.source_page,
        "block_id": row.source_block_id,
        "row_hash": row.row_id,
        "raw_text": row.raw_text,
        "raw_analyte_label": row.raw_label,
        "raw_value_string": row.raw_value,
        "raw_unit_string": row.raw_unit,
        "raw_reference_range": row.raw_reference_range,
        "parsed_numeric_value": row.parsed_numeric_value,
        "parsed_locale": row.parsed_locale,
        "parsed_comparator": row.parsed_comparator,
        "row_type": row.row_type.value,
        "measurement_kind": None,
        "support_code": row.support_code,
        "failure_code": row.failure_code,
        "family_adapter_id": row.family_adapter_id,
        "page_class": row.page_class,
        "source_kind": row.source_kind,
        "source_bounds": row.source_bounds,
        "candidate_trace": row.candidate_trace,
        "source_observation_ids": [],
        "secondary_result": row.secondary_result,
        "extraction_confidence": row.confidence,
        "source_file_path": "",
        "trust_level": trust_level,
        "backend_id": row.parser_backend,
        "backend_version": row.parser_backend_version,
        "parser_backend": row.parser_backend,
        "parser_backend_version": row.parser_backend_version,
        "row_assembly_version": "row-assembly-v2",
    }


def _excluded_row(
    *,
    artifact: PageParseArtifactV4,
    source_block_id: str,
    raw_text: str,
    family_adapter_id: str,
    page_class: str,
    block_role: BlockRoleV1,
    reason_code: str | None = None,
) -> CandidateRowV3:
    row_type_map = {
        BlockRoleV1.ADMIN_BLOCK: CandidateRowTypeV3.ADMIN_METADATA_ROW,
        BlockRoleV1.NARRATIVE_BLOCK: CandidateRowTypeV3.NARRATIVE_GUIDANCE_ROW,
        BlockRoleV1.THRESHOLD_BLOCK: CandidateRowTypeV3.THRESHOLD_REFERENCE_ROW,
        BlockRoleV1.HEADER_FOOTER_BLOCK: CandidateRowTypeV3.HEADER_FOOTER_ROW,
    }
    row_type = row_type_map.get(block_role, CandidateRowTypeV3.UNPARSED_ROW)
    row_id = sha256(f"{artifact.page_id}:{source_block_id}:{row_type.value}:{raw_text}".encode()).hexdigest()

    return CandidateRowV3(
        row_id=row_id,
        document_id=artifact.page_id,
        source_page=artifact.page_number,
        source_block_id=source_block_id,
        row_type=row_type,
        raw_text=raw_text,
        raw_label=(raw_text.split()[0] if raw_text.split() else raw_text),
        support_state="excluded",
        support_code="excluded",
        failure_code=reason_code or row_type.value,
        confidence=0.0,
        family_adapter_id=family_adapter_id,
        page_class=page_class,
        source_kind="block_graph",
        candidate_trace={
            "page_id": artifact.page_id,
            "source_block_id": source_block_id,
            "block_role": block_role.value,
        },
        parser_backend=artifact.backend_id,
        parser_backend_version=artifact.backend_version,
    )


def _all_excluded(
    lines: list[str],
    *,
    line_classifier: LineClassifier,
    page_class: str,
    family_adapter_id: str,
) -> bool:
    if not lines:
        return False
    for line in lines:
        classification = line_classifier.classify_line(
            line,
            page_class=page_class,
            family_adapter_id=family_adapter_id,
        )
        if classification.line_type != "excluded":
            return False
    return True


def _sanitize_candidate_text(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""

    text = re.sub(r"^(?:biochemistry|haematology|hematology|chemistry)\s+", "", text, flags=re.I)
    text = re.sub(r"^albumin\s+and\s+creatinine\s+ratio\s*\(acr\)\s+", "", text, flags=re.I)
    text = re.sub(r"^(?:test\s+name\s+in\s+range\s+out\s+of\s+range\s+reference\s+range\s+lab)\s+", "", text, flags=re.I)
    text = re.sub(r"^(?:lipid\s+function|lipid\s+panel\s+standard|comprehensive\s+metabolic\s+panel|cbc\s+includes\s+diff/plt|thyroid\s+panel\s+with\s+tsh\s+t3\s+uptake|electrolytes|serum/plasma\s+glucose)\s+", "", text, flags=re.I)
    text = re.sub(r"m\s+([23])\b", r"m\1", text, flags=re.I)
    return " ".join(text.split())
