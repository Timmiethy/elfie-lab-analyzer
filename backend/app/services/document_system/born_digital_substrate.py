from __future__ import annotations

import importlib.metadata
from dataclasses import asdict
from typing import Any

from .config_registry import FamilyConfigRegistry, get_family_config_registry
from .contracts import BlockRoleV1, PageParseArtifactV4, PageParseBlockV4, SourceSpanV1
from .page_classifier import PageClassifier

BACKEND_ID = "pymupdf"


def _resolve_backend_version() -> str:
    try:
        return importlib.metadata.version("PyMuPDF")
    except importlib.metadata.PackageNotFoundError:
        try:
            import fitz  # type: ignore[import-untyped]

            return str(getattr(fitz, "__version__", "unknown"))
        except Exception:  # pragma: no cover
            return "unknown"


BACKEND_VERSION = _resolve_backend_version()


class BornDigitalSubstrate:
    """PyMuPDF extraction substrate that emits PageParseArtifactV4 only."""

    def __init__(self, registry: FamilyConfigRegistry | None = None) -> None:
        self._registry = registry or get_family_config_registry()
        self._page_classifier = PageClassifier(self._registry)

    def parse(
        self,
        file_bytes: bytes,
        *,
        source_file_path: str = "unknown",
        max_pages: int | None = None,
    ) -> list[PageParseArtifactV4]:
        if not file_bytes:
            raise ValueError("unsupported_pdf: empty input")

        import fitz  # type: ignore[import-untyped]

        try:
            document = fitz.open("pdf", file_bytes)
        except Exception as exc:  # pragma: no cover
            raise ValueError("unsupported_pdf: unable to open PDF") from exc

        try:
            if len(document) == 0:
                raise ValueError("unsupported_pdf: empty PDF")

            page_limit = max_pages if max_pages is not None else len(document)
            artifacts: list[PageParseArtifactV4] = []
            for index in range(min(len(document), page_limit)):
                page_number = index + 1
                page = document[index]
                artifacts.append(
                    self._extract_page(
                        page,
                        page_number=page_number,
                        source_file_path=source_file_path,
                    )
                )
            return artifacts
        finally:
            document.close()

    def _extract_page(
        self,
        page: Any,
        *,
        page_number: int,
        source_file_path: str,
    ) -> PageParseArtifactV4:
        page_dict = _safe_get_text_dict(page)
        raw_text = _safe_get_text(page)
        words = _safe_extract_words(page)
        tables = _extract_tables(page)

        page_height = float(page.rect.height)
        blocks = self._extract_blocks(
            page_dict,
            page_number=page_number,
            page_height=page_height,
        )
        block_texts = [block.raw_text for block in blocks]
        page_classification = self._page_classifier.classify(raw_text, block_texts=block_texts)
        page_kind = page_classification.page_kind

        text_chars = len(raw_text.strip())
        text_extractability = 1.0 if text_chars >= 100 else (0.5 if text_chars > 0 else 0.0)
        warnings: list[str] = []
        if page_classification.ambiguous:
            warnings.append("ambiguous_page_classification")

        return PageParseArtifactV4(
            page_id=f"{source_file_path}:page-{page_number}",
            page_number=page_number,
            backend_id=BACKEND_ID,
            backend_version=BACKEND_VERSION,
            lane_type="trusted_pdf",
            page_kind=page_kind,
            text_extractability=text_extractability,
            language_candidates=_detect_languages(raw_text),
            blocks=blocks,
            tables=tables,
            images=_extract_images(page),
            raw_text=raw_text,
            warnings=warnings,
            metadata={
                "source_file_path": source_file_path,
                "width": float(page.rect.width),
                "height": float(page.rect.height),
                "rotation": int(page.rotation),
                "words": words,
                "page_classification_reason_codes": page_classification.reason_codes,
                "page_classification_ambiguous": page_classification.ambiguous,
                "page_classification_evidence": asdict(page_classification.evidence),
            },
        )

    def _extract_blocks(
        self,
        page_dict: dict[str, Any],
        *,
        page_number: int,
        page_height: float,
    ) -> list[PageParseBlockV4]:
        blocks: list[PageParseBlockV4] = []
        raw_blocks = page_dict.get("blocks", []) if isinstance(page_dict, dict) else []
        total_blocks = max(
            1,
            sum(1 for entry in raw_blocks if entry.get("type") == 0),
        )

        for block_index, block in enumerate(raw_blocks):
            if block.get("type") != 0:
                continue
            lines = _block_lines(block)
            if not lines:
                continue
            raw_text = "\n".join(lines).strip()
            bbox_value = block.get("bbox")
            bbox = None
            if isinstance(bbox_value, (list, tuple)) and len(bbox_value) == 4:
                bbox = SourceSpanV1(
                    x0=float(bbox_value[0]),
                    y0=float(bbox_value[1]),
                    x1=float(bbox_value[2]),
                    y1=float(bbox_value[3]),
                )

            block_classification = self._page_classifier.classify_block(
                raw_text,
                bbox=bbox,
                page_height=page_height,
                reading_order=block_index,
                total_blocks=total_blocks,
            )

            blocks.append(
                PageParseBlockV4(
                    block_id=f"page-{page_number}:block-{block_index:03d}",
                    block_role=block_classification.block_role,
                    raw_text=raw_text,
                    lines=lines,
                    bbox=bbox,
                    reading_order=block_index,
                    language_tags=_detect_languages(raw_text),
                    source_spans=[bbox] if bbox is not None else [],
                    metadata={
                        "source": "pymupdf",
                        "block_classification_reason_codes": block_classification.reason_codes,
                        "block_classification_ambiguous": block_classification.ambiguous,
                        "block_classification_evidence": asdict(block_classification.evidence),
                    },
                )
            )

        if not blocks:
            blocks.append(
                PageParseBlockV4(
                    block_id=f"page-{page_number}:block-000",
                    block_role=BlockRoleV1.UNKNOWN_BLOCK,
                    raw_text="",
                    lines=[],
                    reading_order=0,
                    language_tags=["en"],
                    source_spans=[],
                    metadata={
                        "source": "pymupdf-empty-fallback",
                        "block_classification_ambiguous": True,
                    },
                )
            )

        return blocks


def _safe_get_text_dict(page: Any) -> dict[str, Any]:
    try:
        import fitz  # type: ignore[import-untyped]

        return page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    except Exception:
        return {"blocks": []}


def _safe_get_text(page: Any) -> str:
    try:
        return str(page.get_text("text") or "")
    except Exception:
        return ""


def _safe_extract_words(page: Any) -> list[dict[str, Any]]:
    try:
        values = page.get_text("words") or []
    except Exception:
        return []

    words: list[dict[str, Any]] = []
    for value in values:
        if len(value) < 5:
            continue
        text = str(value[4]).strip()
        if not text:
            continue
        words.append(
            {
                "text": text,
                "x0": float(value[0]),
                "y0": float(value[1]),
                "x1": float(value[2]),
                "y1": float(value[3]),
                "block_no": int(value[5]) if len(value) > 5 else 0,
            }
        )
    return words


def _extract_tables(page: Any) -> list[dict[str, Any]]:
    try:
        table_finder = page.find_tables()
        extracted = table_finder.extract() or []
    except Exception:
        return []

    result: list[dict[str, Any]] = []
    for table_index, table in enumerate(extracted):
        if not table:
            continue
        rows: list[list[str | None]] = []
        for row in table:
            cleaned = [None if cell is None else str(cell).strip() for cell in row]
            if any(cleaned):
                rows.append(cleaned)
        if rows:
            result.append({"table_index": table_index, "rows": rows})
    return result


def _extract_images(page: Any) -> list[dict[str, Any]]:
    try:
        images = page.get_images(full=True) or []
    except Exception:
        return []

    extracted: list[dict[str, Any]] = []
    for image in images:
        if not image:
            continue
        try:
            xref = int(image[0])
        except (TypeError, ValueError, IndexError):
            xref = -1
        extracted.append({"xref": xref})
    return extracted


def _block_lines(block: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        text = " ".join(span.get("text", "") for span in spans if span.get("text", "").strip())
        text = text.strip()
        if text:
            lines.append(text)
    return lines


def _detect_languages(text: str) -> list[str]:
    languages = ["en"]
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        languages.append("zh")
    return languages
