"""Extraction quality assurance checks."""


class ExtractionQA:
    """Validate extraction results before observation building.

    Checks: row completeness, duplicate detection, coverage metrics.
    """

    def validate(self, extracted_rows: list[dict]) -> dict:
        raise NotImplementedError
