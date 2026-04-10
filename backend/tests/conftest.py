"""Shared test fixtures."""

import pytest


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Placeholder for test PDF bytes."""
    return b""


@pytest.fixture
def sample_extracted_rows() -> list[dict]:
    """Placeholder for test extracted rows."""
    return []
