"""Shared reference range parsing helpers."""

from __future__ import annotations


def extract_reference_range(text: str) -> str | None:
    from app.services.parser import _extract_reference_range

    return _extract_reference_range(text)


def normalize_reference_range_tokens(tokens: list[str]) -> str | None:
    from app.services.parser import _normalize_reference_range

    return _normalize_reference_range(tokens)
