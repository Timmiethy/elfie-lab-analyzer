from __future__ import annotations

from typing import Any

from .contracts import BlockRoleV1, PageKindV2, PageParseArtifactV4, PageParseBlockV4, SourceSpanV1
from .page_classifier import PageClassifier


class OcrSubstrate:
    """Image/scanned substrate that emits PageParseArtifactV4.

    This substrate never upgrades OCR output into trusted born-digital status.
    """

    def __init__(self, page_classifier: PageClassifier | None = None) -> None:
        self._page_classifier = page_classifier or PageClassifier()

    def artifact_from_text(
        self,
        *,
        page_text: str,
        page_number: int,
        document_id: str,
        backend_id: str,
        backend_version: str,
        blocks: list[dict[str, Any]] | None = None,
        tables: list[dict[str, Any]] | None = None,
        images: list[dict[str, Any]] | None = None,
        language_candidates: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> PageParseArtifactV4:
        structured_blocks = _materialize_ocr_blocks(blocks, page_text)
        block_texts = [entry["text"] for entry in structured_blocks if entry["text"]]
        classification = self._page_classifier.classify(page_text, block_texts=block_texts)

        parsed_blocks: list[PageParseBlockV4] = []
        for index, block_entry in enumerate(structured_blocks):
            block_text = block_entry["text"]
            block_classification = self._page_classifier.classify(block_text)
            block_role = _role_from_page_kind(block_classification.page_kind)
            lines = [line.strip() for line in block_text.splitlines() if line.strip()]
            if not lines and block_text.strip():
                lines = [block_text.strip()]

            bbox = _to_source_span(block_entry.get("bbox"))
            block_languages = block_entry.get("language_tags") or _language_candidates(block_text)
            metadata = {
                "source": "ocr",
                "page_kind_confidence": classification.confidence,
                "block_kind": block_classification.page_kind.value,
                "block_kind_confidence": block_classification.confidence,
                "ocr_confidence": block_entry.get("confidence"),
                **dict(block_entry.get("metadata") or {}),
            }

            parsed_blocks.append(
                PageParseBlockV4(
                    block_id=f"ocr-page-{page_number}:block-{index:03d}",
                    block_role=block_role,
                    raw_text=block_text,
                    lines=lines,
                    bbox=bbox,
                    reading_order=int(block_entry.get("reading_order", index)),
                    language_tags=list(block_languages),
                    source_spans=[bbox] if bbox is not None else [],
                    metadata=metadata,
                )
            )

        effective_languages = _unique_languages(language_candidates or _language_candidates(page_text))

        return PageParseArtifactV4(
            page_id=f"ocr:{document_id}:page-{page_number}",
            page_number=page_number,
            backend_id=backend_id,
            backend_version=backend_version,
            lane_type="image_beta",
            page_kind=classification.page_kind,
            text_extractability=0.25 if page_text.strip() else 0.0,
            language_candidates=effective_languages,
            blocks=parsed_blocks,
            tables=list(tables or []),
            images=list(images or [{"source": "ocr_lane"}]),
            raw_text=page_text,
            warnings=list(warnings or []),
            metadata={"reason_codes": classification.reason_codes},
        )

    def artifact_from_backend_result(
        self,
        *,
        backend_result: Any,
        page_number: int,
        document_id: str,
        backend_id: str,
        backend_version: str,
    ) -> PageParseArtifactV4:
        text = _extract_text_from_backend_result(backend_result)
        warnings = _extract_warnings_from_backend_result(backend_result)
        blocks = _extract_blocks_from_backend_result(backend_result, text)
        tables = _extract_tables_from_backend_result(backend_result)
        images = _extract_images_from_backend_result(backend_result)
        language_candidates = _extract_language_candidates_from_backend_result(backend_result, text)
        return self.artifact_from_text(
            page_text=text,
            page_number=page_number,
            document_id=document_id,
            backend_id=backend_id,
            backend_version=backend_version,
            blocks=blocks,
            tables=tables,
            images=images,
            language_candidates=language_candidates,
            warnings=warnings,
        )


def _role_from_page_kind(page_kind: PageKindV2) -> BlockRoleV1:
    if page_kind == PageKindV2.LAB_RESULTS:
        return BlockRoleV1.RESULT_BLOCK
    if page_kind == PageKindV2.THRESHOLD_REFERENCE:
        return BlockRoleV1.THRESHOLD_BLOCK
    if page_kind == PageKindV2.ADMIN_METADATA:
        return BlockRoleV1.ADMIN_BLOCK
    if page_kind in {PageKindV2.NARRATIVE_GUIDANCE, PageKindV2.INTERPRETED_SUMMARY, PageKindV2.NON_LAB_MEDICAL}:
        return BlockRoleV1.NARRATIVE_BLOCK
    if page_kind == PageKindV2.FOOTER_HEADER:
        return BlockRoleV1.HEADER_FOOTER_BLOCK
    return BlockRoleV1.UNKNOWN_BLOCK


def _extract_text_from_backend_result(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "raw_text", "content", "ocr_text"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text
        lines = value.get("lines")
        if isinstance(lines, list):
            return "\n".join(str(line) for line in lines if str(line).strip())
    if isinstance(value, list):
        return "\n".join(str(line) for line in value if str(line).strip())
    return ""


def _extract_warnings_from_backend_result(value: Any) -> list[str]:
    if isinstance(value, dict):
        warnings = value.get("warnings")
        if isinstance(warnings, list):
            return [str(item) for item in warnings]
    return []


def _extract_blocks_from_backend_result(value: Any, text: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        blocks = value.get("blocks")
        if isinstance(blocks, list):
            return _materialize_ocr_blocks(blocks, text)

        lines = value.get("lines")
        if isinstance(lines, list):
            line_blocks = [{"text": str(line), "reading_order": index} for index, line in enumerate(lines)]
            return _materialize_ocr_blocks(line_blocks, text)

    if isinstance(value, list):
        return _materialize_ocr_blocks([{"text": str(line), "reading_order": index} for index, line in enumerate(value)], text)

    return _materialize_ocr_blocks([], text)


def _extract_tables_from_backend_result(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        tables = value.get("tables")
        if isinstance(tables, list):
            return [table for table in tables if isinstance(table, dict)]
    return []


def _extract_images_from_backend_result(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        images = value.get("images")
        if isinstance(images, list):
            return [image for image in images if isinstance(image, dict)]
    return [{"source": "ocr_lane"}]


def _extract_language_candidates_from_backend_result(value: Any, text: str) -> list[str]:
    if isinstance(value, dict):
        for key in ("language_candidates", "languages"):
            raw = value.get(key)
            if isinstance(raw, list):
                languages = [str(item).strip().lower() for item in raw if str(item).strip()]
                if languages:
                    return _unique_languages(languages)

        language = value.get("language")
        if isinstance(language, str) and language.strip():
            return _unique_languages([language.strip().lower()])

    return _language_candidates(text)


def _materialize_ocr_blocks(blocks: list[dict[str, Any]] | list[Any], fallback_text: str) -> list[dict[str, Any]]:
    materialized: list[dict[str, Any]] = []

    for index, block in enumerate(blocks):
        block_text = _extract_block_text(block)
        if not block_text:
            continue
        materialized.append(
            {
                "text": block_text,
                "bbox": _extract_block_bbox(block),
                "reading_order": _extract_block_reading_order(block, index),
                "confidence": _extract_block_confidence(block),
                "language_tags": _extract_block_languages(block, block_text),
                "metadata": _extract_block_metadata(block),
            }
        )

    if materialized:
        return materialized

    lines = [line.strip() for line in str(fallback_text or "").splitlines() if line.strip()]
    return [
        {
            "text": line,
            "bbox": None,
            "reading_order": index,
            "confidence": None,
            "language_tags": _language_candidates(line),
            "metadata": {"source": "ocr-line-fallback"},
        }
        for index, line in enumerate(lines)
    ]


def _extract_block_text(block: Any) -> str:
    if isinstance(block, dict):
        for key in ("text", "raw_text", "content", "line"):
            value = block.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    value = getattr(block, "text", "")
    return str(value or "").strip()


def _extract_block_bbox(block: Any) -> list[float] | tuple[float, float, float, float] | None:
    if isinstance(block, dict):
        value = block.get("bbox") or block.get("box")
    else:
        value = getattr(block, "bbox", None)

    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return [float(value[0]), float(value[1]), float(value[2]), float(value[3])]
        except (TypeError, ValueError):
            return None
    return None


def _extract_block_reading_order(block: Any, default_index: int) -> int:
    if isinstance(block, dict):
        value = block.get("reading_order")
        if value is None:
            value = block.get("line_no")
    else:
        value = getattr(block, "reading_order", None)

    try:
        return int(value) if value is not None else default_index
    except (TypeError, ValueError):
        return default_index


def _extract_block_confidence(block: Any) -> float | None:
    if isinstance(block, dict):
        value = block.get("confidence")
    else:
        value = getattr(block, "confidence", None)

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_block_languages(block: Any, text: str) -> list[str]:
    if isinstance(block, dict):
        raw = block.get("language_tags") or block.get("languages")
        if isinstance(raw, list):
            languages = [str(item).strip().lower() for item in raw if str(item).strip()]
            if languages:
                return _unique_languages(languages)
    return _language_candidates(text)


def _extract_block_metadata(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        metadata = block.get("metadata")
        if isinstance(metadata, dict):
            return dict(metadata)
        return {}
    return {}


def _to_source_span(value: list[float] | tuple[float, float, float, float] | None) -> SourceSpanV1 | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return SourceSpanV1(
            x0=float(value[0]),
            y0=float(value[1]),
            x1=float(value[2]),
            y1=float(value[3]),
        )
    except (TypeError, ValueError):
        return None


def _language_candidates(text: str) -> list[str]:
    value = str(text or "")
    cjk_count = sum(1 for ch in value if "\u4e00" <= ch <= "\u9fff")
    latin_count = sum(1 for ch in value if ("a" <= ch.lower() <= "z"))

    if cjk_count == 0 and latin_count == 0:
        return ["und"]

    languages: list[str] = []
    if cjk_count >= latin_count and cjk_count > 0:
        languages.append("zh")
    if latin_count > 0:
        languages.append("en")
    if cjk_count > 0 and "zh" not in languages:
        languages.append("zh")
    return _unique_languages(languages)


def _unique_languages(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = str(value or "").strip().lower()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered or ["und"]
