"""Trusted PDF parser using pdfplumber for machine-generated PDFs."""


class TrustedPdfParser:
    """Extract structured rows from supported PDF layout families.

    Uses pdfplumber only. No OCR in the trusted lane.
    """

    async def parse(self, file_bytes: bytes) -> list[dict]:
        raise NotImplementedError
