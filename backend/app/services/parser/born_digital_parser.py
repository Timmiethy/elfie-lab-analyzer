"""PyMuPDF-backed born-digital parser for the v12 trusted PDF lane.

This is the primary parser substrate for machine-generated PDFs in v12.
It extracts text, words, blocks, tables, and images via PyMuPDF 1.27.x
and emits PageParseArtifactV3 instances. It never emits CanonicalObservation.
"""

from __future__ import annotations

import importlib.metadata
import re
from typing import Any

from .page_parse_artifact_v3 import PageParseArtifactV3, PageParseBlockV3

# ---------------------------------------------------------------------------
# Backend identification
# ---------------------------------------------------------------------------

BACKEND_ID = "pymupdf"
LANE_TYPE = "trusted_pdf"


def _resolve_version() -> str:
    """Return the installed PyMuPDF / fitz version string."""
    try:
        return importlib.metadata.version("PyMuPDF")
    except importlib.metadata.PackageNotFoundError:
        try:
            import fitz  # type: ignore[import-untyped]

            return getattr(fitz, "__version__", "unknown")
        except Exception:
            return "unknown"


BACKEND_VERSION: str = _resolve_version()

# ---------------------------------------------------------------------------
# Public parser class
# ---------------------------------------------------------------------------


class BornDigitalParser:
    """PyMuPDF-backed born-digital PDF parser.

    Usage::

        parser = BornDigitalParser()
        artifacts: list[PageParseArtifactV3] = parser.parse(file_bytes)

    The parser extracts the full document and returns one PageParseArtifactV3
    per page. Callers feed those artifacts into RowAssemblerV2.
    """

    backend_id: str = BACKEND_ID
    backend_version: str = BACKEND_VERSION
    lane_type: str = LANE_TYPE

    def parse(
        self,
        file_bytes: bytes,
        *,
        source_file_path: str = "unknown",
        max_pages: int | None = None,
    ) -> list[PageParseArtifactV3]:
        """Parse a machine-generated PDF into PageParseArtifactV3 artifacts.

        Args:
            file_bytes: Raw PDF bytes.
            source_file_path: Logical source path for lineage tracing.
            max_pages: Optional page ceiling.  When set, the parser returns
                at most this many artifacts (truncation, not an error).

        Returns:
            Ordered list of PageParseArtifactV3, one per page.

        Raises:
            ValueError: On empty input or empty PDF.
        """
        if not file_bytes:
            raise ValueError("unsupported_pdf: empty input")

        import fitz  # type: ignore[import-untyped]

        try:
            doc = fitz.open("pdf", file_bytes)
        except Exception as exc:  # pragma: no cover
            raise ValueError("unsupported_pdf: unable to open PDF") from exc

        try:
            if len(doc) == 0:
                raise ValueError("unsupported_pdf: empty PDF")

            page_limit = max_pages if max_pages is not None else len(doc)
            artifacts: list[PageParseArtifactV3] = []
            for page_idx in range(min(len(doc), page_limit)):
                page_number = page_idx + 1
                fitz_page = doc[page_idx]
                artifact = _extract_page_artifact(
                    fitz_page,
                    source_file_path=source_file_path,
                    page_number=page_number,
                )
                artifacts.append(artifact)
            return artifacts
        finally:
            doc.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Block-type classification hints — aligned with v12 delta plan block types
_TABLE_BLOCK_KEYWORDS = {
    "analyte", "result", "unit", "ref", "range", "reference",
    "test", "value", "flag", "method",
}
_ADMIN_BLOCK_KEYWORDS = {
    "dob", "collected", "report printed", "ref :", "patient",
    "lab no", "sex/age", "registration", "approved on", "printed on",
    "ordering physician", "accession", "mrn", "npi", "clia",
}
_NARRATIVE_BLOCK_KEYWORDS = {
    "note:", "recommend", "interpret", "guideline", "should be",
    "clinical presentation", "source:", "kdigo", "kfre",
    "risk calculation", "desirable range",
}
_THRESHOLD_BLOCK_KEYWORDS = {
    "normal", "ifg", "prediabetes", "t2dm", "target range",
    "risk category", "biological ref", "cut-off",
}
_HEADER_FOOTER_KEYWORDS = {
    "page ", "laboratory report", "all rights reserved",
    "enterprise report version",
}

# v12: keywords that indicate a block is a mixed measurement/result block
# rather than a pure threshold table, even if threshold keywords are present.
_MEASUREMENT_BLOCK_HINTS = {
    "absolute", "basophils", "eosinophils", "lymphocytes", "neutrophils",
    "magnesium", "rbc", "rbmc", "sed rate", "westergren",
    "cells/ul", "cells/u", "/ul", "/u",
    "hba1c", "glucose", "creatinine", "sodium", "potassium",
    "hemoglobin", "wbc", "platelet", "mch", "mchc", "mcv", "rdw",
    "calcium", "chloride", "bicarbonate", "phosphate", "albumin",
    "bilirubin", "alt", "ast", "alkaline", "amylase", "lipase",
}

# Page-kind hints
_RESULT_PAGE_HINTS = {
    "analyte", "result", "reference", "hba1c", "glucose", "hemoglobin",
    "creatinine", "urea", "sodium", "potassium", "wbc", "platelet",
    "cholesterol",
}
_THRESHOLD_PAGE_HINTS = {
    "normal", "ifg", "prediabetes", "dm", "t2dm", "target range",
    "reference interval", "risk category", "biological ref",
    "cut-off", "cut off", "optimal", "moderate", "high", "low",
    "very high", "n/a", "levels", "kdigo",
}
_NARRATIVE_PAGE_HINTS = {
    "note:", "recommend", "interpret", "guideline", "guidelines",
    "should be interpreted", "clinical presentation", "source:",
    "not valid for", "result should be",
}
_ADMIN_PAGE_HINTS = {
    "ref :", "dob :", "age :", "collected :", "referred :",
    "report printed :", "patient details", "lab no",
}
_HEADER_PAGE_HINTS = {
    "laboratory report", "analytes results units ref. ranges",
    "page ", "all rights reserved",
}


def _classify_block(text: str) -> str:
    """Infer a v12 block type from its raw text content.

    Returns one of: result_table, threshold_table, admin_meta,
    narrative, footer, header, unknown.

    v12 fix: measurement blocks that contain threshold keywords (e.g. "normal",
    reference ranges) alongside real analyte names and values are classified as
    ``result_table``, not ``threshold_table``.  Pure threshold tables (e.g. KDIGO
    staging grids) still type as ``threshold_table`` because they lack analyte
    measurement signals.
    """
    lowered = text.lower()
    if not lowered.strip():
        return "unknown"
    if _any_in(lowered, _HEADER_FOOTER_KEYWORDS):
        return "header"
    if _any_in(lowered, _ADMIN_BLOCK_KEYWORDS):
        return "admin_meta"
    if _any_in(lowered, _NARRATIVE_BLOCK_KEYWORDS):
        return "narrative"
    # v12: if threshold keywords are present, also check for measurement signals.
    # Real measurement blocks should not be typed as threshold_table.
    if _any_in(lowered, _THRESHOLD_BLOCK_KEYWORDS) and _has_multiple_ranges(lowered):
        # Only classify as threshold_table if there are no measurement signals
        if not _any_in(lowered, _MEASUREMENT_BLOCK_HINTS):
            return "threshold_table"
    if _any_in(lowered, _TABLE_BLOCK_KEYWORDS):
        return "result_table"
    # v12: unknown blocks that contain measurement hints should be treated as
    # result_table so they are NOT fenced and can participate in candidate recovery.
    if _any_in(lowered, _MEASUREMENT_BLOCK_HINTS):
        return "result_table"
    return "unknown"


def _classify_page_kind(raw_text: str) -> str:
    """Infer the page kind from the full page text."""
    lowered = raw_text.lower()
    if _any_in(lowered, _RESULT_PAGE_HINTS):
        return "lab_results"
    if _any_in(lowered, _THRESHOLD_PAGE_HINTS) and _has_multiple_ranges(lowered):
        return "threshold_table"
    if _any_in(lowered, _NARRATIVE_PAGE_HINTS):
        return "narrative"
    if _any_in(lowered, _ADMIN_PAGE_HINTS):
        return "admin_meta"
    if _any_in(lowered, _HEADER_PAGE_HINTS):
        return "footer"
    return "unknown"


def _estimate_text_extractability(raw_text: str, block_count: int) -> str:
    """Estimate text extractability quality from raw text and block count."""
    if block_count > 3 and len(raw_text.strip()) > 100:
        return "high"
    if block_count > 0 and raw_text.strip():
        return "medium"
    if raw_text.strip():
        return "low"
    return "none"


def _detect_languages(raw_text: str) -> list[str]:
    """Detect candidate languages in the text."""
    langs: list[str] = ["en"]
    if re.search(r"[\u4e00-\u9fff]", raw_text):
        langs.append("zh")
    return langs


def _has_multiple_ranges(text: str) -> bool:
    """Return True if the text appears to contain multiple numeric ranges."""
    return len(re.findall(r"\d[\d,.]*\s*[-–]\s*\d[\d,.]*", text)) >= 2


def _any_in(text: str, keywords: set[str]) -> bool:
    return any(kw in text for kw in keywords)


def _extract_page_artifact(
    fitz_page: Any,
    *,
    source_file_path: str,
    page_number: int,
) -> PageParseArtifactV3:
    """Extract a single PageParseArtifactV3 from a PyMuPDF page."""
    # --- text via get_text("dict") for block-level structure ---
    page_dict = _safe_get_text_dict(fitz_page)
    raw_text = _safe_get_text(fitz_page)

    blocks: list[PageParseBlockV3] = []
    for block_idx, block in enumerate(page_dict.get("blocks", [])):
        if block.get("type") != 0:  # 0 == text block
            continue
        lines = _block_lines(block)
        if not lines:
            continue
        block_text = " ".join(lines)
        block_type = _classify_block(block_text)
        bbox_tuple: tuple[float, float, float, float] | None = None
        if "bbox" in block:
            b = block["bbox"]
            bbox_tuple = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
        blocks.append(PageParseBlockV3(
            block_id=f"page-{page_number}:block-{block_idx:03d}",
            block_type=block_type,
            bbox=bbox_tuple,
            lines=lines,
            metadata={"source": "pymupdf-get_text_dict"},
        ))

    # Extract words for downstream geometry-based assembly
    words_data = _safe_extract_words(fitz_page)

    # Extract tables via find_tables() where available
    tables_data = _extract_tables(fitz_page)

    # If block-level extraction yields nothing, fall back to full raw text
    # as a single unknown block so downstream assembly still has content.
    if not blocks and raw_text.strip():
        blocks.append(PageParseBlockV3(
            block_id=f"page-{page_number}:block-000",
            block_type="unknown",
            bbox=None,
            lines=[raw_text.strip()],
            metadata={"source": "pymupdf-fallback-raw"},
        ))

    page_kind = _classify_page_kind(raw_text)
    extractability = _estimate_text_extractability(raw_text, len(blocks))
    language_candidates = _detect_languages(raw_text)

    return PageParseArtifactV3(
        source_file_path=source_file_path,
        page_number=page_number,
        lane_type=LANE_TYPE,
        backend_id=BACKEND_ID,
        backend_version=BACKEND_VERSION,
        blocks=blocks,
        raw_text=raw_text,
        parse_errors=[],
        metadata={
            "width": float(fitz_page.rect.width),
            "height": float(fitz_page.rect.height),
            "rotation": int(fitz_page.rotation),
            "words": words_data,
            "tables": tables_data,
        },
        page_kind=page_kind,
        text_extractability=extractability,
        language_candidates=language_candidates,
        tables=tables_data,
    )


def _safe_get_text_dict(fitz_page: Any) -> dict[str, Any]:
    """Safely call get_text('dict') and return a sane default."""
    try:
        import fitz  # type: ignore[import-untyped]

        return fitz_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    except Exception:
        return {"blocks": []}


def _safe_get_text(fitz_page: Any) -> str:
    """Safely call get_text() and return empty string on failure."""
    try:
        return fitz_page.get_text("text")
    except Exception:
        return ""


def _safe_extract_words(fitz_page: Any) -> list[dict[str, Any]]:
    """Safely extract word-level data from a PyMuPDF page."""
    try:
        raw_words = fitz_page.get_text("words") or []
    except Exception:
        return []
    return [
        {
            "text": str(w[4]),
            "x0": float(w[0]),
            "y0": float(w[1]),
            "x1": float(w[2]),
            "y1": float(w[3]),
            "block_no": int(w[5]) if len(w) > 5 else 0,
        }
        for w in raw_words
        if str(w[4]).strip()
    ]


def _extract_tables(fitz_page: Any) -> list[dict[str, Any]]:
    """Extract tables from a PyMuPDF page via find_tables() where available."""
    try:
        tab_finder = fitz_page.find_tables()
        tables = tab_finder.extract() or []
    except Exception:
        return []
    result: list[dict[str, Any]] = []
    for table_idx, table in enumerate(tables):
        if not table:
            continue
        rows: list[list[str | None]] = []
        for row in table:
            if not row:
                continue
            cleaned = [None if cell is None else str(cell).strip() for cell in row]
            if any(cleaned):
                rows.append(cleaned)
        if rows:
            result.append({"table_index": table_idx, "rows": rows})
    return result


def _block_lines(block: dict[str, Any]) -> list[str]:
    """Extract individual lines of text from a PyMuPDF text block dict."""
    lines: list[str] = []
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        line_text = " ".join(span.get("text", "") for span in spans if span.get("text", "").strip())
        if line_text.strip():
            lines.append(line_text.strip())
    return lines
