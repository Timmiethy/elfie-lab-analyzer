"""Shared row-grammar interfaces used by parser and row assembly.

Phase 4 introduces this package as the stable import boundary for
classification and parsing helpers that were previously imported directly
from the parser root module.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def classify_candidate_text(
    raw_text: str,
    *,
    page_class: str = "unknown",
    family_adapter_id: str = "generic_layout",
) -> dict[str, Any]:
    from app.services.parser import classify_candidate_text as _classify_candidate_text

    return _classify_candidate_text(
        raw_text,
        page_class=page_class,
        family_adapter_id=family_adapter_id,
    )


def parse_measurement_text(
    raw_text: str,
    *,
    page_class: str = "unknown",
    family_adapter_id: str = "generic_layout",
    source_kind: str = "text",
    page_number: int = 1,
    block_id: str | None = None,
    segment_index: int = 0,
    source_bounds: dict[str, float] | None = None,
) -> dict[str, Any]:
    from app.services.parser import parse_measurement_text as _parse_measurement_text

    return _parse_measurement_text(
        raw_text,
        page_class=page_class,
        family_adapter_id=family_adapter_id,
        source_kind=source_kind,
        page_number=page_number,
        block_id=block_id,
        segment_index=segment_index,
        source_bounds=source_bounds,
    )


def parse_numeric_token(token: str) -> tuple[float | None, dict[str, Any]]:
    from app.services.parser import parse_numeric_token as _parse_numeric_token

    return _parse_numeric_token(token)


def locate_value_token(
    tokens: list[str],
) -> tuple[int | None, str | None, float | None, str | None, dict[str, Any]]:
    from app.services.parser import _locate_value_token

    return _locate_value_token(tokens)


def iter_candidates(
    text: str,
    words: list[dict[str, Any]],
    tables: list[list[list[str | None]]],
    *,
    page_number: int,
    page_class: str,
    family_adapter_id: str,
) -> Iterator[tuple[str, str, dict[str, float] | None, str, int]]:
    from app.services.parser import (
        GenericLayoutAdapter,
        InnoquestBilingualGeneralAdapter,
        _iter_candidates,
    )

    if family_adapter_id == "innoquest_bilingual_general":
        adapter: GenericLayoutAdapter = InnoquestBilingualGeneralAdapter()
    else:
        adapter = GenericLayoutAdapter()

    return _iter_candidates(
        text,
        words,
        tables,
        page_number=page_number,
        page_class=page_class,
        adapter=adapter,
    )


__all__ = [
    "classify_candidate_text",
    "iter_candidates",
    "locate_value_token",
    "parse_measurement_text",
    "parse_numeric_token",
]
