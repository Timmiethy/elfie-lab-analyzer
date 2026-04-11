"""Trusted PDF parser using pdfplumber for machine-generated PDFs."""

from __future__ import annotations

import re
from hashlib import sha256
from io import BytesIO
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pdfplumber

_PAGE_MARKER_RE = re.compile(r"^page\s*\d+(?:\s*(?:of|/)\s*\d+)?$", re.IGNORECASE)
_REFERENCE_TOKEN_RE = re.compile(
    r"^(?:[<>]=?|≤|≥)\s*\d|\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?$"
)
_VALUE_TOKEN_RE = re.compile(
    r"^(?P<comparison>[<>]=?|≤|≥)?(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)(?P<suffix>[^\d\s].*)?$"
)
_NOISE_WORDS = {
    "analyte",
    "comment",
    "comments",
    "date",
    "flag",
    "method",
    "patient",
    "range",
    "reference",
    "report",
    "result",
    "results",
    "specimen",
    "test",
    "unit",
    "units",
    "value",
}


class TrustedPdfParser:
    """Extract structured rows from supported PDF layout families.

    Uses pdfplumber only. No OCR in the trusted lane.
    """

    async def parse(self, file_bytes: bytes, *, max_pages: int | None = None) -> list[dict[str, Any]]:
        return _parse_trusted_pdf(file_bytes, max_pages=max_pages)


def _parse_trusted_pdf(file_bytes: bytes, *, max_pages: int | None = None) -> list[dict[str, Any]]:
    if not file_bytes:
        raise ValueError("unsupported_pdf: empty input")

    checksum = sha256(file_bytes).hexdigest()
    document_id = uuid5(NAMESPACE_URL, f"trusted-pdf:{checksum}")
    rows: list[dict[str, Any]] = []
    seen_rows: set[str] = set()
    saw_any_embedded_text = False

    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                raise ValueError("unsupported_pdf: empty PDF")

            if max_pages is not None and len(pdf.pages) > max_pages:
                raise ValueError(
                    f"page_count_limit_exceeded:{len(pdf.pages)}>{max_pages}"
                )

            for page_number, page in enumerate(pdf.pages, start=1):
                page_rows, page_has_text = _extract_page_rows(
                    page=page,
                    page_number=page_number,
                    document_id=document_id,
                    checksum=checksum,
                )
                saw_any_embedded_text = saw_any_embedded_text or page_has_text

                for row in page_rows:
                    row_hash = str(row["row_hash"])
                    if row_hash in seen_rows:
                        continue
                    seen_rows.add(row_hash)
                    rows.append(row)
    except ValueError:
        raise
    except Exception as exc:  # pragma: no cover - library-specific failure mapping
        raise ValueError("unsupported_pdf: unable to open or read PDF") from exc

    if rows:
        return rows

    if not saw_any_embedded_text:
        raise ValueError("unsupported_pdf: no embedded text found")

    raise ValueError("unsupported_pdf: no parsable rows found")


def _extract_page_rows(
    *,
    page: Any,
    page_number: int,
    document_id: UUID,
    checksum: str,
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    page_has_text = False

    tables = _safe_extract_tables(page)
    if tables:
        page_has_text = True
        for table in tables:
            for raw_text in _candidate_texts_from_table(table):
                parsed_row = _parse_candidate_text(raw_text)
                if parsed_row is None:
                    continue
                rows.append(
                    _materialize_row(
                        parsed_row,
                        document_id=document_id,
                        checksum=checksum,
                        page_number=page_number,
                    )
                )

    page_text = _safe_extract_text(page)
    if page_text:
        page_has_text = True
        pending_label: str | None = None

        for raw_line in page_text.splitlines():
            line = _normalize_text(raw_line)
            if not line:
                continue
            if _is_noise_line(line):
                pending_label = None
                continue

            parsed_row = _parse_candidate_text(line)
            if parsed_row is None and pending_label is not None:
                parsed_row = _parse_candidate_text(f"{pending_label} {line}")

            if parsed_row is not None:
                rows.append(
                    _materialize_row(
                        parsed_row,
                        document_id=document_id,
                        checksum=checksum,
                        page_number=page_number,
                    )
                )
                pending_label = None
                continue

            if _contains_value_token(line):
                pending_label = None
            else:
                pending_label = _join_texts(pending_label, line)

    return rows, page_has_text


def _safe_extract_tables(page: Any) -> list[list[list[str | None]]]:
    try:
        tables = page.extract_tables() or []
    except Exception:
        return []

    normalized_tables: list[list[list[str | None]]] = []
    for table in tables:
        if not table:
            continue
        normalized_table: list[list[str | None]] = []
        for row in table:
            if not row:
                continue
            normalized_row = [None if cell is None else _normalize_text(str(cell)) for cell in row]
            if any(cell for cell in normalized_row):
                normalized_table.append(normalized_row)
        if normalized_table:
            normalized_tables.append(normalized_table)
    return normalized_tables


def _safe_extract_text(page: Any) -> str:
    try:
        text = page.extract_text()
    except Exception:
        return ""
    return (text or "").strip()


def _candidate_texts_from_table(table: list[list[str | None]]) -> list[str]:
    candidates: list[str] = []
    for row in table:
        candidate = _join_texts(*[cell for cell in row if cell])
        if candidate:
            candidates.append(candidate)
    return candidates


def _parse_candidate_text(raw_text: str) -> dict[str, Any] | None:
    text = _normalize_text(raw_text)
    if not text or _is_noise_line(text):
        return None

    tokens = text.split()
    value_index, raw_value_string, parsed_numeric_value, suffix = _locate_value_token(tokens)
    if value_index is None or raw_value_string is None:
        return None

    label = _normalize_text(" ".join(tokens[:value_index]))
    if not label:
        return None

    raw_unit_string = suffix
    raw_reference_range: str | None = None

    trailing_tokens = tokens[value_index + 1 :]
    if trailing_tokens:
        reference_index = _first_reference_index(trailing_tokens)
        if reference_index is None:
            unit_tokens = trailing_tokens
            reference_tokens: list[str] = []
        else:
            unit_tokens = trailing_tokens[:reference_index]
            reference_tokens = trailing_tokens[reference_index:]

        unit_text = _normalize_text(" ".join(unit_tokens))
        if unit_text:
            raw_unit_string = _join_texts(raw_unit_string, unit_text)

        reference_text = _normalize_text(" ".join(reference_tokens))
        if reference_text:
            raw_reference_range = reference_text

    return {
        "raw_text": text,
        "raw_analyte_label": label,
        "raw_value_string": raw_value_string,
        "raw_unit_string": raw_unit_string,
        "raw_reference_range": raw_reference_range,
        "parsed_numeric_value": parsed_numeric_value,
    }


def _materialize_row(
    parsed_row: dict[str, Any],
    *,
    document_id: UUID,
    checksum: str,
    page_number: int,
) -> dict[str, Any]:
    row_hash = sha256(
        f"{checksum}:{page_number}:{parsed_row['raw_text']}".encode("utf-8")
    ).hexdigest()
    row: dict[str, Any] = {
        "document_id": document_id,
        "source_page": page_number,
        "row_hash": row_hash,
        "raw_text": parsed_row["raw_text"],
        "raw_analyte_label": parsed_row["raw_analyte_label"],
        "raw_value_string": parsed_row["raw_value_string"],
        "raw_unit_string": parsed_row["raw_unit_string"],
        "raw_reference_range": parsed_row["raw_reference_range"],
        "parsed_numeric_value": parsed_row["parsed_numeric_value"],
    }
    return row


def _locate_value_token(
    tokens: list[str],
) -> tuple[int | None, str | None, float | None, str | None]:
    for index, token in enumerate(tokens):
        raw_value_string, parsed_numeric_value, suffix = _split_value_token(token)
        if raw_value_string is not None:
            return index, raw_value_string, parsed_numeric_value, suffix
    return None, None, None, None


def _split_value_token(token: str) -> tuple[str | None, float | None, str | None]:
    cleaned = token.strip().strip(",;:")
    if not cleaned or _is_reference_token(cleaned):
        return None, None, None

    match = _VALUE_TOKEN_RE.match(cleaned)
    if match is None:
        return None, None, None

    raw_value_string = cleaned
    numeric_value = float(match.group("number").replace(",", ""))
    suffix = match.group("suffix")
    if suffix is not None:
        suffix = suffix.strip() or None
    return raw_value_string, numeric_value, suffix


def _is_reference_token(token: str) -> bool:
    return bool(_REFERENCE_TOKEN_RE.match(token))


def _first_reference_index(tokens: list[str]) -> int | None:
    for index, token in enumerate(tokens):
        cleaned = token.strip().strip(",;:")
        if not cleaned:
            continue
        if _is_reference_token(cleaned):
            return index
        if cleaned in {"<", ">", "<=", ">=", "≤", "≥"} and index + 1 < len(tokens):
            if _split_value_token(tokens[index + 1])[0] is not None:
                return index
    return None


def _contains_value_token(text: str) -> bool:
    tokens = _normalize_text(text).split()
    return any(_split_value_token(token)[0] is not None for token in tokens)


def _is_noise_line(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return True
    if _PAGE_MARKER_RE.match(lowered):
        return True

    tokens = [re.sub(r"[^\w%/.-]", "", token.lower()) for token in lowered.split()]
    meaningful_tokens = {token for token in tokens if token}

    if meaningful_tokens and meaningful_tokens <= _NOISE_WORDS:
        return True

    if lowered in {"reference range", "test result", "result units"}:
        return True

    return False


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _join_texts(*values: str | None) -> str | None:
    parts = [_normalize_text(value) for value in values if _normalize_text(value)]
    if not parts:
        return None
    return " ".join(parts)
