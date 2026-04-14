"""Shared unit parsing helpers."""

from __future__ import annotations


def normalize_measurement_unit(raw_unit_string: str | None) -> str | None:
    from app.services.parser import _normalize_measurement_unit_string

    return _normalize_measurement_unit_string(raw_unit_string)


def looks_like_unit_token(token: str) -> bool:
    from app.services.parser import _looks_like_unit_token

    return _looks_like_unit_token(token)
