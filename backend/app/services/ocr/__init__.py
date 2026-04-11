"""Image beta lane OCR adapter.

This module intentionally stays conservative:
- it never pretends OCR succeeded when the optional stack is unavailable
- it can normalize injected OCR text/rows into downstream QA-compatible rows
- it derives stable identifiers when callers do not provide them
"""

from __future__ import annotations

import inspect
import re
from copy import deepcopy
from hashlib import sha256
from importlib.util import find_spec
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

_IMAGE_BETA_STACK_AVAILABLE = find_spec("doctr") is not None and find_spec("surya") is not None

_LINE_VALUE_PATTERN = re.compile(
    (
        r"^\s*(?P<label>.*?)(?:\s+|[:=\-\u2013\u2014|])"
        r"(?P<value>[+-]?\d+(?:\.\d+)?)\b(?P<unit>.*\S)?\s*$"
    )
)


class OcrAdapter:
    """Safe adapter for image-beta OCR.

    The adapter accepts an injected OCR backend or pre-extracted OCR text/rows.
    When neither is available, it raises a clear runtime error instead of
    silently fabricating OCR output.
    """

    def __init__(
        self,
        *,
        ocr_backend: Callable[[bytes], Any] | None = None,
        image_beta_enabled: bool = True,
    ) -> None:
        self._ocr_backend = ocr_backend
        self._image_beta_enabled = image_beta_enabled

    def is_available(self) -> bool:
        """Return whether this adapter can run with a real OCR backend."""

        return self._ocr_backend is not None or _IMAGE_BETA_STACK_AVAILABLE

    async def extract(
        self,
        image_bytes: bytes,
        *,
        document_id: UUID | str | None = None,
        source_page: int = 1,
        language_id: str | None = "en",
        ocr_text: str | None = None,
        ocr_lines: Sequence[str] | None = None,
        ocr_rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Extract OCR rows for the image-beta lane.

        If a concrete OCR backend is not available, callers may still use this
        adapter to normalize already-extracted text/rows. Otherwise the method
        fails loudly and keeps the lane visibly beta.
        """

        if not self._image_beta_enabled:
            raise RuntimeError(
                "image_beta_disabled: enable the image-beta lane before invoking OCR"
            )
        if not isinstance(image_bytes, (bytes, bytearray)):
            raise TypeError("image_bytes must be bytes")
        if not image_bytes:
            raise ValueError("image_bytes_empty")

        document_uuid = self._coerce_document_id(document_id, bytes(image_bytes))
        normalized_lines = self._collect_lines(ocr_text=ocr_text, ocr_lines=ocr_lines)

        if ocr_rows is not None:
            return self._normalize_rows(
                ocr_rows,
                document_uuid=document_uuid,
                source_page=source_page,
                language_id=language_id,
            )

        if normalized_lines:
            return self._rows_from_lines(
                normalized_lines,
                document_uuid=document_uuid,
                source_page=source_page,
                language_id=language_id,
            )

        if self._ocr_backend is not None:
            backend_output = self._ocr_backend(bytes(image_bytes))
            if inspect.isawaitable(backend_output):
                backend_output = await self._await_backend_output(backend_output)
            return self._normalize_backend_output(
                backend_output,
                document_uuid=document_uuid,
                source_page=source_page,
                language_id=language_id,
            )

        if not _IMAGE_BETA_STACK_AVAILABLE:
            raise RuntimeError(
                "image_beta_ocr_unavailable: install the optional OCR extras with "
                '`pip install -e ".[dev,image-beta]"` or inject pre-extracted OCR '
                "rows/text into OcrAdapter.extract()"
            )

        raise RuntimeError(
            "image_beta_ocr_backend_not_wired: the optional OCR packages are "
            "available, but no OCR backend callable or pre-extracted text/rows was provided"
        )

    async def _await_backend_output(self, backend_output: Awaitable[Any]) -> Any:
        return await backend_output

    def _normalize_backend_output(
        self,
        backend_output: Any,
        *,
        document_uuid: UUID,
        source_page: int,
        language_id: str | None,
    ) -> list[dict[str, Any]]:
        if isinstance(backend_output, Mapping):
            if "rows" in backend_output:
                return self._normalize_rows(
                    backend_output["rows"],
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                )
            if "lines" in backend_output:
                return self._rows_from_lines(
                    backend_output["lines"],
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                )
            if "text" in backend_output:
                return self._rows_from_lines(
                    self._collect_lines(ocr_text=str(backend_output["text"])),
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                )

        if isinstance(backend_output, str):
            return self._rows_from_lines(
                self._collect_lines(ocr_text=backend_output),
                document_uuid=document_uuid,
                source_page=source_page,
                language_id=language_id,
            )

        if isinstance(backend_output, Sequence) and not isinstance(
            backend_output, (bytes, bytearray, str)
        ):
            if all(isinstance(item, str) for item in backend_output):
                return self._rows_from_lines(
                    list(backend_output),
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                )
            if all(isinstance(item, Mapping) for item in backend_output):
                return self._normalize_rows(
                    list(backend_output),
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                )

        raise RuntimeError("ocr_backend_returned_unsupported_payload")

    def _normalize_rows(
        self,
        ocr_rows: Sequence[Mapping[str, Any]],
        *,
        document_uuid: UUID,
        source_page: int,
        language_id: str | None,
    ) -> list[dict[str, Any]]:
        normalized_rows: list[dict[str, Any]] = []
        for index, row in enumerate(ocr_rows):
            normalized_rows.append(
                self._normalize_row(
                    row,
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                    row_index=index,
                )
            )
        return normalized_rows

    def _rows_from_lines(
        self,
        lines: Sequence[str],
        *,
        document_uuid: UUID,
        source_page: int,
        language_id: str | None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            cleaned_line = self._clean_text(line)
            if not cleaned_line:
                continue

            label, value_string, unit_string = self._parse_line(cleaned_line)
            row = {
                "document_id": document_uuid,
                "source_page": source_page,
                "row_hash": self._stable_row_hash(
                    document_uuid=document_uuid,
                    source_page=source_page,
                    row_index=index,
                    raw_text=cleaned_line,
                ),
                "raw_text": cleaned_line,
                "raw_analyte_label": label,
                "raw_value_string": value_string,
                "raw_unit_string": unit_string,
                "raw_reference_range": None,
                "parsed_numeric_value": self._coerce_float(value_string),
                "specimen_context": None,
                "method_context": None,
                "language_id": language_id,
                "extraction_confidence": 0.55 if value_string or unit_string else 0.35,
                "lane_type": "image_beta",
                "ocr_engine": "beta_adapter",
            }
            rows.append(row)

        return rows

    def _normalize_row(
        self,
        row: Mapping[str, Any],
        *,
        document_uuid: UUID,
        source_page: int,
        language_id: str | None,
        row_index: int,
    ) -> dict[str, Any]:
        normalized_row = deepcopy(dict(row))

        row_document_id = normalized_row.get("document_id", document_uuid)
        row_document_uuid = self._coerce_document_id(row_document_id, b"")
        raw_text = self._clean_text(
            normalized_row.get("raw_text")
            or normalized_row.get("text")
            or normalized_row.get("line_text")
        )
        raw_label = self._clean_text(
            normalized_row.get("raw_analyte_label")
            or normalized_row.get("label")
            or normalized_row.get("analyte_label")
        )
        if not raw_label and raw_text:
            raw_label, inferred_value, inferred_unit = self._parse_line(raw_text)
            normalized_row.setdefault("raw_value_string", inferred_value)
            normalized_row.setdefault("raw_unit_string", inferred_unit)
            normalized_row.setdefault(
                "parsed_numeric_value", self._coerce_float(inferred_value)
            )
            if not raw_label:
                raw_label = raw_text

        if not raw_label:
            raise ValueError("ocr_row_missing_analyte_label")

        normalized_row["document_id"] = row_document_uuid
        normalized_row["source_page"] = int(normalized_row.get("source_page", source_page))
        normalized_row["row_hash"] = self._clean_text(
            normalized_row.get("row_hash")
        ) or self._stable_row_hash(
            document_uuid=row_document_uuid,
            source_page=normalized_row["source_page"],
            row_index=row_index,
            raw_text=raw_text or raw_label,
        )
        normalized_row["raw_analyte_label"] = raw_label
        normalized_row["raw_text"] = raw_text or raw_label
        normalized_row["raw_value_string"] = self._clean_text(
            normalized_row.get("raw_value_string")
        )
        normalized_row["raw_unit_string"] = self._clean_text(
            normalized_row.get("raw_unit_string")
        )
        normalized_row["raw_reference_range"] = self._clean_text(
            normalized_row.get("raw_reference_range")
        )
        normalized_row["parsed_numeric_value"] = self._coerce_float(
            normalized_row.get("parsed_numeric_value")
        )
        normalized_row["specimen_context"] = self._clean_text(
            normalized_row.get("specimen_context")
        )
        normalized_row["method_context"] = self._clean_text(
            normalized_row.get("method_context")
        )
        normalized_row["language_id"] = self._clean_text(
            normalized_row.get("language_id")
        ) or language_id
        normalized_row.setdefault(
            "extraction_confidence",
            (
                0.8
                if normalized_row.get("raw_value_string")
                or normalized_row.get("raw_unit_string")
                else 0.5
            ),
        )
        normalized_row.setdefault("lane_type", "image_beta")
        normalized_row.setdefault("ocr_engine", "beta_adapter")
        return normalized_row

    @staticmethod
    def _collect_lines(
        *,
        ocr_text: str | None,
        ocr_lines: Sequence[str] | None,
    ) -> list[str]:
        lines: list[str] = []

        if ocr_text:
            lines.extend(ocr_text.splitlines())
        if ocr_lines is not None:
            lines.extend(str(line) for line in ocr_lines)

        return lines

    @classmethod
    def _parse_line(cls, line: str) -> tuple[str, str | None, str | None]:
        match = _LINE_VALUE_PATTERN.match(line)
        if match is None:
            return cls._clean_text(line), None, None

        label = cls._clean_text(match.group("label"))
        value_string = cls._clean_text(match.group("value"))
        unit_string = cls._clean_text(match.group("unit"))
        return label or cls._clean_text(line), value_string, unit_string

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).replace("\x00", "").strip()

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_document_id(document_id: UUID | str | None, image_bytes: bytes) -> UUID:
        if isinstance(document_id, UUID):
            return document_id
        if document_id is not None and str(document_id).strip():
            return UUID(str(document_id))

        checksum = sha256(image_bytes).hexdigest()
        return uuid5(NAMESPACE_URL, f"ocr:{checksum}")

    @staticmethod
    def _stable_row_hash(
        *,
        document_uuid: UUID,
        source_page: int,
        row_index: int,
        raw_text: str,
    ) -> str:
        payload = f"{document_uuid}:{source_page}:{row_index}:{raw_text}"
        return sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["OcrAdapter"]
