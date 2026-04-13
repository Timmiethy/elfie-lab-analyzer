"""RowAssemblerV2: turns PageParseArtifactV3 into typed candidate rows."""

from .v2 import RowAssemblerV2, VALID_ROW_TYPES, NORMALIZABLE_ROW_TYPES, FENCED_BLOCK_TYPES

__all__ = ["RowAssemblerV2", "VALID_ROW_TYPES", "NORMALIZABLE_ROW_TYPES", "FENCED_BLOCK_TYPES"]
