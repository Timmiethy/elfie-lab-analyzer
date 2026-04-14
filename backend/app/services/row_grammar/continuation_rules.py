"""Shared continuation rules used by row grouping."""

from __future__ import annotations

import re

_COMPARATOR_RE = re.compile(r"^(?:<=|>=|<|>|≤|≥)\s*\d")
_NUMERIC_RE = re.compile(r"(?:^|\s)(?:<=|>=|<|>|≤|≥)?\s*\d[\d.,]*(?:\s|$)")
_UNIT_ONLY_RE = re.compile(r"^(?:%|[a-zA-Z]+/[a-zA-Z0-9/]+|[a-zA-Z]{1,4}\d*)$")
_REF_RANGE_RE = re.compile(r"^[\[(]?\s*(?:<=|>=|<|>)?\s*\d[\d.,]*\s*[-–]\s*(?:<=|>=|<|>)?\s*\d[\d.,]*\s*[\])]?$")


def is_value_bearing_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return False
    if _COMPARATOR_RE.match(text):
        return True
    return _NUMERIC_RE.search(text) is not None


def classify_continuation(line: str) -> str | None:
    text = line.strip()
    if not text:
        return None
    if _UNIT_ONLY_RE.match(text):
        return "unit"
    tokens = text.split()
    compact = re.sub(r"\s+", "", text).lower().replace("^", "")
    if len(tokens) <= 2 and "/" in compact and re.match(r"^[a-z0-9µμ.%/]+$", compact):
        return "unit"
    if _REF_RANGE_RE.match(text):
        return "reference_range"
    if text.lower() in {
        "high", "low", "normal", "abnormal", "h", "l", "trace", "positive", "negative"
    }:
        return "flag"
    if re.match(r"^\d{1,2}$", text):
        return "sample_index"
    return None
