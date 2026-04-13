"""PyMuPDF-backed born-digital parser for trusted PDF lane.

Primary extraction path in the refactored document system:
BornDigitalSubstrate -> PageParseArtifactV4 -> compatibility adapter -> PageParseArtifactV3.

The parser never emits canonical observations directly.
"""

from __future__ import annotations

from app.services.document_system.born_digital_substrate import (
    BACKEND_ID,
    BACKEND_VERSION,
    BornDigitalSubstrate,
)
from app.services.document_system.contracts import BlockRoleV1, PageKindV2, PageParseArtifactV4

from .page_parse_artifact_v3 import PageParseArtifactV3, PageParseBlockV3

LANE_TYPE = "trusted_pdf"


class BornDigitalParser:
    """PyMuPDF parser that returns PageParseArtifactV3 for compatibility.

    Internal extraction uses the new V4 substrate contract. This class adapts
    V4 output to V3 so existing callers can migrate incrementally.
    """

    backend_id: str = BACKEND_ID
    backend_version: str = BACKEND_VERSION
    lane_type: str = LANE_TYPE

    def __init__(self) -> None:
        self._substrate = BornDigitalSubstrate()

    def parse(
        self,
        file_bytes: bytes,
        *,
        source_file_path: str = "unknown",
        max_pages: int | None = None,
    ) -> list[PageParseArtifactV3]:
        artifacts_v4 = self._substrate.parse(
            file_bytes,
            source_file_path=source_file_path,
            max_pages=max_pages,
        )
        return [
            _artifact_v4_to_v3(artifact_v4, source_file_path=source_file_path)
            for artifact_v4 in artifacts_v4
        ]

    def parse_v4(
        self,
        file_bytes: bytes,
        *,
        source_file_path: str = "unknown",
        max_pages: int | None = None,
    ) -> list[PageParseArtifactV4]:
        return self._substrate.parse(
            file_bytes,
            source_file_path=source_file_path,
            max_pages=max_pages,
        )


def _artifact_v4_to_v3(
    artifact: PageParseArtifactV4,
    *,
    source_file_path: str,
) -> PageParseArtifactV3:
    blocks = [
        PageParseBlockV3(
            block_id=block.block_id,
            block_type=_block_role_to_v3_type(block.block_role),
            bbox=(
                block.bbox.x0,
                block.bbox.y0,
                block.bbox.x1,
                block.bbox.y1,
            )
            if block.bbox is not None
            else None,
            lines=list(block.lines) if block.lines else ([block.raw_text] if block.raw_text else []),
            metadata=dict(block.metadata),
        )
        for block in artifact.blocks
    ]

    return PageParseArtifactV3(
        page_id=artifact.page_id,
        source_file_path=source_file_path,
        page_number=artifact.page_number,
        lane_type=artifact.lane_type,
        backend_id=artifact.backend_id,
        backend_version=artifact.backend_version,
        page_kind=_page_kind_to_v3(artifact.page_kind),
        text_extractability=_extractability_to_v3(artifact.text_extractability),
        language_candidates=list(artifact.language_candidates),
        blocks=blocks,
        tables=list(artifact.tables),
        images=list(artifact.images),
        raw_text=artifact.raw_text,
        parse_errors=list(artifact.warnings),
        warnings=list(artifact.warnings),
        metadata=dict(artifact.metadata),
    )


def _block_role_to_v3_type(block_role: BlockRoleV1) -> str:
    mapping = {
        BlockRoleV1.RESULT_BLOCK: "result_table",
        BlockRoleV1.THRESHOLD_BLOCK: "threshold_table",
        BlockRoleV1.ADMIN_BLOCK: "admin_meta",
        BlockRoleV1.NARRATIVE_BLOCK: "narrative",
        BlockRoleV1.HEADER_FOOTER_BLOCK: "footer",
        BlockRoleV1.UNKNOWN_BLOCK: "unknown",
    }
    return mapping.get(block_role, "unknown")


def _page_kind_to_v3(page_kind: PageKindV2) -> str:
    mapping = {
        PageKindV2.LAB_RESULTS: "lab_results",
        PageKindV2.THRESHOLD_REFERENCE: "threshold_table",
        PageKindV2.ADMIN_METADATA: "admin_meta",
        PageKindV2.NARRATIVE_GUIDANCE: "narrative",
        PageKindV2.INTERPRETED_SUMMARY: "narrative",
        PageKindV2.NON_LAB_MEDICAL: "narrative",
        PageKindV2.FOOTER_HEADER: "footer",
        PageKindV2.UNKNOWN: "unknown",
    }
    return mapping.get(page_kind, "unknown")


def _extractability_to_v3(value: float) -> str:
    if value >= 0.8:
        return "high"
    if value >= 0.4:
        return "medium"
    if value > 0.0:
        return "low"
    return "none"
