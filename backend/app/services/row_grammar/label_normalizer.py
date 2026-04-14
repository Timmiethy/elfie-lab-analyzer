"""Shared analyte-label normalization helpers."""

from __future__ import annotations


def normalize_text(value: str | None) -> str:
    from app.services.parser import _normalize_text

    return _normalize_text(value)


def normalize_measurement_label(
    label: str,
    *,
    raw_unit_string: str | None,
) -> str:
    from app.services.parser import _normalize_measurement_label

    return _normalize_measurement_label(label, raw_unit_string=raw_unit_string)
