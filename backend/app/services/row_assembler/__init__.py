"""RowAssemblerV2: turns PageParseArtifactV3 into typed candidate rows."""

from app.services.document_system.row_assembler import RowAssemblerV3

from .v2 import FENCED_BLOCK_TYPES, NORMALIZABLE_ROW_TYPES, VALID_ROW_TYPES, RowAssemblerV2

__all__ = [
    "RowAssemblerV2",
    "RowAssemblerV3",
    "VALID_ROW_TYPES",
    "NORMALIZABLE_ROW_TYPES",
    "FENCED_BLOCK_TYPES",
]
