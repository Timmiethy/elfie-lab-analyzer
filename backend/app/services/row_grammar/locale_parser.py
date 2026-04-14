"""Shared locale parsing helpers."""

from __future__ import annotations

from typing import Any


def parse_locale_from_numeric(value: str) -> dict[str, Any]:
    from app.services.parser import _normalize_numeric_string

    _, locale = _normalize_numeric_string(value)
    return locale


def compact_locale_descriptor(value: object) -> str | None:
    if isinstance(value, dict):
        decimal_separator = str(value.get("decimal_separator") or "").strip()
        thousands_separator = str(value.get("thousands_separator") or "").strip()
        normalized = bool(value.get("normalized"))
        parts: list[str] = []
        if decimal_separator == ",":
            parts.append("decimal_comma")
        elif decimal_separator == ".":
            parts.append("decimal_dot")
        if thousands_separator == ",":
            parts.append("thousands_comma")
        elif thousands_separator == ".":
            parts.append("thousands_dot")
        if normalized:
            parts.append("normalized")
        return "+".join(parts) or None
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None
