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

_VALUE_TOKEN_RE = re.compile(r"(?:<=|>=|<|>|≤|≥)?\s*\d[\d,]*(?:\.\d+)?")
_RANGE_TOKEN_RE = re.compile(
    r"(?:<=|>=|<|>|≤|≥)?\s*\d[\d,]*(?:\.\d+)?\s*(?:-|–|to)\s*(?:<=|>=|<|>|≤|≥)?\s*\d[\d,]*(?:\.\d+)?"
)
_UNKNOWN_BLOCK_UNIT_HINTS = (
    "mg/dl",
    "g/dl",
    "g/l",
    "mmol/l",
    "umol/l",
    "mmol/mol",
    "iu/l",
    "u/l",
    "%",
    "ng/ml",
    "ng/l",
    "pg",
    "fl",
)
_UNKNOWN_BLOCK_NON_RESULT_HINTS = (
    "guideline",
    "interpretation",
    "clinical history",
    "gross description",
    "microscopic",
    "final diagnosis",
    "specimen",
    "patient",
    "dob",
    "mrn",
    "accession",
    "report printed",
    "ordered",
    "received",
    "page ",
    "address",
    "jalan",
    "wisma",
    "flr",
    "pathology",
    "histopathology",
    "gross description",
    "microscopic",
    "final diagnosis",
    "ultrasound",
    "radiology",
    "echocardiogram",
    "x-ray",
)
_UNKNOWN_BLOCK_NARRATIVE_MARKERS = (
    "guideline",
    "interpretation",
    "clinical",
    "history",
    "diagnosis",
    "specimen",
    "recommend",
    "comment",
    "note",
    "pathology",
    "ultrasound",
    "radiology",
)
_UNKNOWN_BLOCK_THRESHOLD_MARKERS = (
    "prediabetes",
    "risk",
    "cut off",
    "cutoff",
    "threshold",
    "target range",
    "castelli",
    "ifg",
    "very high",
    "moderate",
)
_UNKNOWN_BLOCK_CITATION_MARKERS = (
    "clin chem",
    "lab med",
    "et al",
    "doi",
    "jama",
)
_UNKNOWN_BLOCK_LABEL_STOPWORDS = {
    "result",
    "results",
    "unit",
    "units",
    "reference",
    "range",
    "normal",
    "high",
    "low",
    "risk",
    "threshold",
    "note",
    "clinical",
    "patient",
    "specimen",
    "report",
    "page",
    "section",
    "table",
    "value",
}
_PREPARSE_RISK_MARKERS = (
    "risk",
    "cut off",
    "cutoff",
    "threshold",
    "prediabetes",
    "target range",
    "castelli",
    "ifg",
)
_PREPARSE_NOTE_MARKERS = (
    "note",
    "guideline",
    "interpretation",
    "clinical",
    "history",
    "recommended",
)
_PREPARSE_CITATION_MARKERS = (
    "et al",
    "doi",
    "clin chem",
    "lab med",
    "jama",
)
_HEADING_ONLY_HINTS = (
    "biochemistry",
    "haematology",
    "hematology",
    "chemistry",
    "test name in range out of range reference range lab",
    "lipid function",
    "lipid panel standard",
    "comprehensive metabolic panel",
    "cbc includes diff/plt",
    "thyroid panel with tsh t3 uptake",
    "electrolytes",
    "serum/plasma glucose",
    "albumin and creatinine ratio (acr)",
)


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

            if node.block_role == BlockRoleV1.UNKNOWN_BLOCK and not _is_result_like_unknown_block(
                node_text=node.text,
                metadata=node.metadata,
            ):
                rows.append(
                    _excluded_row(
                        artifact=artifact,
                        source_block_id=node.block_id,
                        raw_text=node.text,
                        family_adapter_id=family_adapter_id,
                        page_class=page_class,
                        block_role=BlockRoleV1.UNKNOWN_BLOCK,
                        reason_code="unknown_block_non_result",
                    )
                )
                continue

            line_values = [line.strip() for line in list(node.lines or []) if str(line).strip()]
            if not line_values:
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

                if _should_preparse_suppress_candidate(candidate_text):
                    rows.append(
                        _excluded_row(
                            artifact=artifact,
                            source_block_id=node.block_id,
                            raw_text=candidate_text,
                            family_adapter_id=family_adapter_id,
                            page_class=page_class,
                            block_role=node.block_role,
                            reason_code="preparse_threshold_note_citation_row",
                        )
                    )
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

        if page_class == "analyte_table_page" and _should_use_bbox_row_fallback(block_graph.nodes):
            for index, fallback in enumerate(_build_bbox_row_candidates(block_graph.nodes), start=1):
                candidate_text = _sanitize_candidate_text(fallback["text"])
                if not candidate_text:
                    continue

                if _should_preparse_suppress_candidate(candidate_text):
                    rows.append(
                        _excluded_row(
                            artifact=artifact,
                            source_block_id=fallback["source_block_id"],
                            raw_text=candidate_text,
                            family_adapter_id=family_adapter_id,
                            page_class=page_class,
                            block_role=BlockRoleV1.UNKNOWN_BLOCK,
                            reason_code="preparse_threshold_note_citation_row",
                        )
                    )
                    continue

                parsed = self._row_field_parser.parse(
                    candidate_text,
                    RowFieldParseInput(
                        document_id=artifact.page_id,
                        page_id=artifact.page_id,
                        source_page=artifact.page_number,
                        source_block_id=fallback["source_block_id"],
                        family_adapter_id=family_adapter_id,
                        page_class=page_class,
                        parser_backend=artifact.backend_id,
                        parser_backend_version=artifact.backend_version,
                        source_kind="bbox_row_merge",
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

    if _is_heading_only_candidate(text):
        return ""

    text = re.sub(r"m\s+([23])\b", r"m\1", text, flags=re.I)
    return " ".join(text.split())


def _is_result_like_unknown_block(*, node_text: str, metadata: dict[str, object]) -> bool:
    normalized = " ".join(str(node_text or "").lower().split())
    if not normalized:
        return False

    if any(marker in normalized for marker in _UNKNOWN_BLOCK_NON_RESULT_HINTS):
        return False

    evidence = metadata.get("block_classification_evidence") if isinstance(metadata, dict) else None
    if not isinstance(evidence, dict):
        evidence = {}

    numeric_density = _safe_float(evidence.get("numeric_token_density"))
    has_value_token = _VALUE_TOKEN_RE.search(normalized) is not None
    has_analyte_like_label = _has_analyte_label_evidence(normalized)
    has_unit_or_reference = _has_unit_or_reference_evidence(normalized)

    token_count = max(1, len(_tokenize(normalized)))
    threshold_density = max(
        _safe_float(evidence.get("threshold_pattern_density")),
        _marker_density(normalized, _UNKNOWN_BLOCK_THRESHOLD_MARKERS, token_count),
    )
    narrative_density = _marker_density(normalized, _UNKNOWN_BLOCK_NARRATIVE_MARKERS, token_count)
    citation_density = _marker_density(normalized, _UNKNOWN_BLOCK_CITATION_MARKERS, token_count)

    if not has_value_token:
        return False
    if not has_analyte_like_label:
        return False
    if not has_unit_or_reference:
        return False
    if numeric_density < 0.08:
        return False
    if narrative_density >= 0.08:
        return False
    if threshold_density >= 0.08:
        return False
    if citation_density >= 0.06:
        return False

    return True


def _is_heading_only_candidate(value: str) -> bool:
    compact = " ".join(str(value or "").split())
    normalized = compact.lower()
    if not normalized:
        return False
    if _VALUE_TOKEN_RE.search(normalized):
        return False
    if any(hint == normalized or normalized.startswith(f"{hint} ") for hint in _HEADING_ONLY_HINTS):
        return True
    return compact.isupper() and len(normalized.split()) <= 8


def _should_preparse_suppress_candidate(value: str) -> bool:
    normalized = " ".join(str(value or "").lower().split())
    if not normalized:
        return False

    has_threshold_or_note_marker = any(marker in normalized for marker in _PREPARSE_RISK_MARKERS) or any(
        marker in normalized for marker in _PREPARSE_NOTE_MARKERS
    )
    has_citation_marker = any(marker in normalized for marker in _PREPARSE_CITATION_MARKERS)
    if not has_threshold_or_note_marker and not has_citation_marker:
        return False

    return not _is_strict_measurement_candidate(normalized)


def _is_strict_measurement_candidate(normalized: str) -> bool:
    if not _VALUE_TOKEN_RE.search(normalized):
        return False
    if not _has_analyte_label_evidence(normalized):
        return False
    if not _has_unit_or_reference_evidence(normalized):
        return False

    token_count = max(1, len(_tokenize(normalized)))
    if _marker_density(normalized, _UNKNOWN_BLOCK_CITATION_MARKERS, token_count) >= 0.12:
        return False
    if _marker_density(normalized, _UNKNOWN_BLOCK_NARRATIVE_MARKERS, token_count) >= 0.2:
        return False
    return True


def _has_unit_or_reference_evidence(normalized: str) -> bool:
    if _RANGE_TOKEN_RE.search(normalized):
        return True
    if "reference range" in normalized or "reference interval" in normalized:
        return True
    if any(unit in normalized for unit in _UNKNOWN_BLOCK_UNIT_HINTS):
        return True
    return bool(
        re.search(
            r"\b(?:mg|g|mmol|umol|ng|pg|iu|u|ml|dl|l|mm|cm|fl)(?:/[a-z0-9]+)?\b",
            normalized,
        )
    )


def _has_analyte_label_evidence(normalized: str) -> bool:
    tokens = _tokenize(normalized)
    alpha_tokens = [token for token in tokens if any(char.isalpha() for char in token)]
    informative_tokens = [
        token
        for token in alpha_tokens
        if token not in _UNKNOWN_BLOCK_LABEL_STOPWORDS and len(token) > 2
    ]
    return len(informative_tokens) >= 1


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9%/().+-]+", value.lower())


def _marker_density(value: str, markers: tuple[str, ...], token_count: int) -> float:
    if token_count <= 0:
        return 0.0
    hits = sum(1 for marker in markers if marker in value)
    return hits / token_count


def _should_use_bbox_row_fallback(nodes: list[object]) -> bool:
    bbox_nodes = [
        node
        for node in nodes
        if getattr(node, "bbox", None) is not None and str(getattr(node, "text", "") or "").strip()
    ]
    if len(bbox_nodes) < 16:
        return False

    short_fragment_count = sum(
        1 for node in bbox_nodes if len(str(getattr(node, "text", "") or "").split()) <= 3
    )
    value_only_count = sum(
        1
        for node in bbox_nodes
        if len(str(getattr(node, "text", "") or "").split()) <= 2
        and _VALUE_TOKEN_RE.search(str(getattr(node, "text", "") or "").lower()) is not None
    )
    fragmentation_ratio = short_fragment_count / max(1, len(bbox_nodes))
    return fragmentation_ratio >= 0.45 and value_only_count >= 6


def _build_bbox_row_candidates(nodes: list[object]) -> list[dict[str, str]]:
    entries: list[dict[str, object]] = []
    for node in nodes:
        bbox = getattr(node, "bbox", None)
        if bbox is None:
            continue
        text = " ".join(str(getattr(node, "text", "") or "").split())
        if not text:
            continue
        y_center = (float(bbox.y0) + float(bbox.y1)) / 2.0
        entries.append(
            {
                "source_block_id": str(getattr(node, "block_id", "bbox-row")),
                "text": text,
                "y_center": y_center,
                "x0": float(getattr(bbox, "x0", 0.0) or 0.0),
                "reading_order": int(getattr(node, "reading_order", 0) or 0),
            }
        )

    entries.sort(
        key=lambda item: (
            float(item["y_center"]),
            float(item["x0"]),
        )
    )

    clusters: list[dict[str, object]] = []
    for entry in entries:
        y_center = float(entry["y_center"])
        if clusters and abs(y_center - float(clusters[-1]["y_center"])) <= 4.5:
            current_entries = list(clusters[-1]["entries"])  # type: ignore[arg-type]
            current_entries.append(entry)
            clusters[-1]["entries"] = current_entries
            clusters[-1]["y_center"] = sum(float(item["y_center"]) for item in current_entries) / max(
                1,
                len(current_entries),
            )
            continue

        clusters.append({"y_center": y_center, "entries": [entry]})

    candidates: list[dict[str, str]] = []
    for cluster in clusters:
        cluster_entries = list(cluster["entries"])  # type: ignore[arg-type]
        ordered_entries = sorted(
            cluster_entries,
            key=lambda item: (
                float(item["x0"]),
                int(item["reading_order"]),
            ),
        )

        parts = [
            " ".join(str(item["text"] or "").split())
            for item in ordered_entries
            if str(item["text"] or "").strip()
        ]
        line_text = " ".join(" ".join(parts).split())
        if not line_text or len(line_text.split()) < 2:
            continue

        candidates.append(
            {
                "source_block_id": str(ordered_entries[0]["source_block_id"]),
                "text": line_text,
            }
        )

    return candidates


def _safe_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
