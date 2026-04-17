"""Terminology loading: LOINC artifact and alias tables.

The service must boot fail-fast if the configured terminology snapshot is missing.
"""

import json
from pathlib import Path

_loaded_snapshot_metadata: dict | None = None


def get_loaded_snapshot_metadata() -> dict | None:
    return _loaded_snapshot_metadata


class TerminologyLoader:
    """Load and validate local LOINC artifact and alias tables."""

    def load_loinc(self, path: str) -> dict:
        global _loaded_snapshot_metadata
        snapshot_dir = Path(path)
        metadata_path = snapshot_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"terminology metadata not found at {metadata_path}")
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)
        _loaded_snapshot_metadata = metadata
        return metadata

    def load_alias_tables(self, path: str) -> dict:
        raise NotImplementedError
