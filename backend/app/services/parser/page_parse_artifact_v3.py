"""PageParseArtifactV3 contract for v12 parser migration.

This is the single output contract for ALL parser backends (PyMuPDF trusted,
qwen-vl-ocr image-beta, pdfplumber debug). No parser backend may emit
CanonicalObservation directly. Parser backends emit PageParseArtifactV3,
which RowAssemblerV2 then turns into typed CandidateRowArtifactV2 rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PageParseBlockV3:
    """A single text block extracted from a page.

    Attributes
        block_id: Unique identifier for the block within the page.
        block_type: Semantic type hint.
            One of: result_table, threshold_table, admin_meta, narrative,
            footer, header, unknown.
        bbox: Bounding box as (x0, y0, x1, y1) in page coordinates.
        lines: Ordered list of raw text lines within this block.
        metadata: Backend-specific metadata (fonts, spacing, etc.).
    """

    block_id: str = ""
    block_type: str = "unknown"
    bbox: tuple[float, float, float, float] | None = None
    lines: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Concatenated text of all lines in this block."""
        return " ".join(self.lines).strip()


@dataclass(frozen=True)
class PageParseArtifactV3:
    """Unified parser output for a single page.

    This artifact is the ONLY thing a parser backend is allowed to emit.
    It carries enough structure for RowAssemblerV2 to reconstruct typed
    candidate rows without the parser needing to know about normalization
    or observation semantics.

    Attributes per v12 delta plan §4.3:
        page_id: Unique page identifier.
        backend_id: One of pymupdf, qwen_ocr, pdfplumber_debug.
        backend_version: Concrete backend version string.
        lane_type: One of trusted_pdf, image_beta, debug.
        page_kind: One of lab_results, threshold_table, admin_meta,
            narrative, footer, unknown.
        text_extractability: One of high, medium, low, none.
        language_candidates: Detected language codes.
        block_count: Number of blocks in this artifact.
        blocks: Ordered list of structured text blocks.
        tables: Extracted table data.
        images: Image metadata extracted from the page.
        warnings: Parser warnings for this page.
    """

    page_id: str = ""
    backend_id: str = "unknown"
    backend_version: str = "unknown"
    lane_type: str = "trusted_pdf"
    page_kind: str = "unknown"
    text_extractability: str = "medium"
    language_candidates: list[str] = field(default_factory=list)
    block_count: int = 0
    blocks: list[PageParseBlockV3] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Backwards-compatible aliases so existing callers using the
    # first-draft field names are not broken.
    source_file_path: str = ""
    page_number: int = 0
    trust_level: str = ""
    raw_text: str = ""
    parse_errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lane_type not in {"trusted_pdf", "image_beta", "debug"}:
            raise ValueError(
                f"lane_type must be one of 'trusted_pdf', 'image_beta', 'debug'; "
                f"got '{self.lane_type}'"
            )
        # Backwards-compat: sync trust_level from lane_type
        object.__setattr__(self, "trust_level", self.lane_type)
        # Backwards-compat: derive page_id if not set
        if not self.page_id and self.source_file_path and self.page_number:
            object.__setattr__(
                self,
                "page_id",
                f"{self.source_file_path}:page-{self.page_number}",
            )
        # Backwards-compat: sync backend_id
        if self.backend_id == "unknown" and self.source_file_path:
            object.__setattr__(self, "backend_id", "pymupdf")
        # Sync block_count
        object.__setattr__(self, "block_count", len(self.blocks))

    @property
    def has_errors(self) -> bool:
        return len(self.parse_errors) > 0 or len(self.warnings) > 0

    @property
    def has_content(self) -> bool:
        return len(self.blocks) > 0 or len(self.raw_text.strip()) > 0
