"""Terminology loading: LOINC artifact and alias tables.

The service must boot fail-fast if the configured terminology snapshot is missing.
"""


class TerminologyLoader:
    """Load and validate local LOINC artifact and alias tables."""

    def load_loinc(self, path: str) -> dict:
        raise NotImplementedError

    def load_alias_tables(self, path: str) -> dict:
        raise NotImplementedError
