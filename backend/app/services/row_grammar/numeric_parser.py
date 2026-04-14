"""Shared numeric parsing helpers."""

from __future__ import annotations

from typing import Any


def normalize_numeric_string(value: str) -> tuple[str | None, dict[str, Any]]:
    from app.services.parser import _normalize_numeric_string

    return _normalize_numeric_string(value)


def parse_numeric_token(token: str) -> tuple[float | None, dict[str, Any]]:
    from app.services.parser import parse_numeric_token as _parse_numeric_token

    return _parse_numeric_token(token)
