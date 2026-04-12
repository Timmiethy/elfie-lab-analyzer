"""Image beta lane OCR adapter.

This module intentionally stays conservative:
- it never pretends OCR succeeded when the optional stack is unavailable
- it can normalize injected OCR text/rows into downstream QA-compatible rows
- it discovers a real OCR backend with surya primary and doctr fallback
- it derives stable identifiers when callers do not provide them
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
from importlib import import_module
from importlib.util import find_spec
from io import BytesIO
from typing import Any, TypedDict
from uuid import NAMESPACE_URL, UUID, uuid5


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):  # pragma: no cover - defensive import guard
        return False


_SURYA_STACK_AVAILABLE = _module_available("surya")
_DOCTR_STACK_AVAILABLE = _module_available("doctr")

_LINE_VALUE_PATTERN = re.compile(

        r"^\s*(?P<label>.*?)(?:\s+|[:=\-\u2013\u2014|])"
        r"(?P<value>[+-]?\d+(?:\.\d+)?)\b(?P<unit>.*\S)?\s*$"

)
_DEFAULT_OCR_ENGINE = "beta_adapter"


class OcrPromotionDecision(TypedDict):
    promotion_status: str
    backend_available: bool
    backend_candidates: list[str]
    positioned_output: bool


class OcrAdapter:
    """Safe adapter for image-beta OCR.

    The adapter accepts an injected OCR backend or pre-extracted OCR text/rows.
    When neither is available, it raises a clear runtime error instead of
    silently fabricating OCR output. When optional OCR stacks are present, it
    prefers surya and falls back to doctr.
    """

    def __init__(
        self,
        *,
        ocr_backend: Callable[[bytes], Any] | None = None,
        image_beta_enabled: bool = True,
    ) -> None:
        self._ocr_backend = ocr_backend
        self._image_beta_enabled = image_beta_enabled
        self._auto_backend_candidates = self._build_auto_backend_candidates()

    def is_available(self) -> bool:
        """Return whether this adapter can run with a real OCR backend."""

        return bool(self._candidate_backends())

    def promotion_decision(self) -> OcrPromotionDecision:
        """Report whether image-beta OCR is eligible for promotion."""

        backend_candidates = [name for name, _ in self._candidate_backends()]
        backend_available = bool(backend_candidates)
        if not self._image_beta_enabled:
            promotion_status = "blocked_image_beta_disabled"
        elif backend_available:
            promotion_status = "beta_ready"
        else:
            promotion_status = "blocked_no_ocr_backend"
        return {
            "promotion_status": promotion_status,
            "backend_available": backend_available,
            "backend_candidates": backend_candidates,
            "positioned_output": backend_available,
        }

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
                ocr_engine=_DEFAULT_OCR_ENGINE,
            )

        if normalized_lines:
            return self._rows_from_lines(
                normalized_lines,
                document_uuid=document_uuid,
                source_page=source_page,
                language_id=language_id,
                ocr_engine=_DEFAULT_OCR_ENGINE,
            )

        if not self._image_beta_enabled:
            raise RuntimeError(
                "image_beta_disabled: enable the image-beta lane before invoking OCR"
            )

        backend_candidates = self._candidate_backends()
        if not backend_candidates:
            raise RuntimeError(
                "image_beta_ocr_unavailable: install the optional OCR extras with "
                '`pip install -e ".[dev,image-beta]"` or inject pre-extracted OCR '
                "rows/text into OcrAdapter.extract()"
            )

        last_error: Exception | None = None
        for backend_name, backend in backend_candidates:
            try:
                backend_output = backend(bytes(image_bytes))
                if inspect.isawaitable(backend_output):
                    backend_output = await self._await_backend_output(backend_output)
                return self._normalize_backend_output(
                    backend_output,
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                    ocr_engine=backend_name,
                )
            except Exception as exc:  # pragma: no cover - exercised via fallback tests
                last_error = exc

        raise RuntimeError("image_beta_ocr_backend_failed") from last_error

    async def _await_backend_output(self, backend_output: Awaitable[Any]) -> Any:
        return await backend_output

    def _candidate_backends(self) -> list[tuple[str, Callable[[bytes], Any]]]:
        candidates: list[tuple[str, Callable[[bytes], Any]]] = []
        if self._ocr_backend is not None:
            candidates.append(("injected", self._ocr_backend))
        candidates.extend(self._auto_backend_candidates)
        return candidates

    def _build_auto_backend_candidates(self) -> list[tuple[str, Callable[[bytes], Any]]]:
        candidates: list[tuple[str, Callable[[bytes], Any]]] = []

        surya_backend = self._build_surya_backend()
        if surya_backend is not None:
            candidates.append(("surya", surya_backend))

        doctr_backend = self._build_doctr_backend()
        if doctr_backend is not None:
            candidates.append(("doctr", doctr_backend))

        return candidates

    def _build_surya_backend(self) -> Callable[[bytes], Any] | None:
        if not _SURYA_STACK_AVAILABLE:
            return None

        for module_name in ("surya", "surya.ocr"):
            try:
                module = import_module(module_name)
            except Exception:
                continue

            runner = self._locate_callable(
                module,
                ("run_ocr", "ocr", "extract", "predict"),
            )
            if runner is None:
                continue

            return lambda image_bytes, runner=runner: self._invoke_backend_callable(
                runner,
                image_bytes,
            )

        return None

    def _build_doctr_backend(self) -> Callable[[bytes], Any] | None:
        if not _DOCTR_STACK_AVAILABLE:
            return None

        for module_name in ("doctr", "doctr.models", "doctr.io"):
            try:
                module = import_module(module_name)
            except Exception:
                continue

            factory = self._locate_callable(
                module,
                ("ocr_predictor", "predictor", "run_ocr", "ocr", "extract"),
            )
            if factory is None:
                continue

            backend_callable = self._instantiate_backend_factory(factory)
            def backend(image_bytes: bytes, backend_callable=backend_callable) -> Any:
                return self._invoke_backend_callable(backend_callable, image_bytes)

            return backend

        return None

    @staticmethod
    def _locate_callable(module: Any, candidate_names: Sequence[str]) -> Callable[..., Any] | None:
        for candidate_name in candidate_names:
            candidate = getattr(module, candidate_name, None)
            if callable(candidate):
                return candidate
        return None

    @staticmethod
    def _instantiate_backend_factory(factory: Callable[..., Any]) -> Callable[..., Any]:
        for kwargs in (
            {},
            {"pretrained": True},
            {"assume_straight_pages": True},
            {"pretrained": True, "assume_straight_pages": True},
        ):
            try:
                backend = factory(**kwargs)
            except TypeError:
                continue
            except Exception:
                continue
            if callable(backend):
                return backend

        return factory

    def _invoke_backend_callable(
        self,
        backend: Callable[..., Any],
        image_bytes: bytes,
    ) -> Any:
        attempts = (
            lambda: backend(image_bytes),
            lambda: backend(BytesIO(image_bytes)),
            lambda: backend([BytesIO(image_bytes)]),
            lambda: backend([image_bytes]),
        )
        last_error: Exception | None = None
        for attempt in attempts:
            try:
                return attempt()
            except TypeError as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise RuntimeError("ocr_backend_invocation_failed")

    def _normalize_backend_output(
        self,
        backend_output: Any,
        *,
        document_uuid: UUID,
        source_page: int,
        language_id: str | None,
        ocr_engine: str,
    ) -> list[dict[str, Any]]:
        if hasattr(backend_output, "__dict__") and not isinstance(
            backend_output,
            (str, bytes, bytearray, Mapping, Sequence),
        ):
            public_payload = {
                key: getattr(backend_output, key)
                for key in ("rows", "lines", "text", "pages", "blocks", "predictions", "result")
                if hasattr(backend_output, key)
            }
            if public_payload:
                return self._normalize_backend_output(
                    public_payload,
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                    ocr_engine=ocr_engine,
                )

        if isinstance(backend_output, Mapping):
            for key in ("rows", "lines", "text", "pages", "blocks", "predictions", "result"):
                if key not in backend_output:
                    continue
                value = backend_output[key]
                if key == "rows":
                    return self._normalize_rows(
                        value,
                        document_uuid=document_uuid,
                        source_page=source_page,
                        language_id=language_id,
                        ocr_engine=ocr_engine,
                    )
                if key == "lines":
                    return self._rows_from_lines(
                        value,
                        document_uuid=document_uuid,
                        source_page=source_page,
                        language_id=language_id,
                        ocr_engine=ocr_engine,
                    )
                if key == "text":
                    return self._rows_from_lines(
                        self._collect_lines(ocr_text=str(value)),
                        document_uuid=document_uuid,
                        source_page=source_page,
                        language_id=language_id,
                        ocr_engine=ocr_engine,
                    )
                return self._normalize_backend_output(
                    value,
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                    ocr_engine=ocr_engine,
                )

        if isinstance(backend_output, str):
            return self._rows_from_lines(
                self._collect_lines(ocr_text=backend_output),
                document_uuid=document_uuid,
                source_page=source_page,
                language_id=language_id,
                ocr_engine=ocr_engine,
            )

        if isinstance(backend_output, Sequence) and not isinstance(
            backend_output,
            (bytes, bytearray, str),
        ):
            if all(isinstance(item, str) for item in backend_output):
                return self._rows_from_lines(
                    list(backend_output),
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                    ocr_engine=ocr_engine,
                )
            if all(isinstance(item, Mapping) for item in backend_output):
                return self._normalize_rows(
                    list(backend_output),
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                    ocr_engine=ocr_engine,
                )

            rows: list[dict[str, Any]] = []
            for item in backend_output:
                rows.extend(
                    self._normalize_backend_output(
                        item,
                        document_uuid=document_uuid,
                        source_page=source_page,
                        language_id=language_id,
                        ocr_engine=ocr_engine,
                    )
                )
            if rows:
                return rows

        raise RuntimeError("ocr_backend_returned_unsupported_payload")

    def _normalize_rows(
        self,
        ocr_rows: Sequence[Mapping[str, Any]],
        *,
        document_uuid: UUID,
        source_page: int,
        language_id: str | None,
        ocr_engine: str,
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
                    ocr_engine=ocr_engine,
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
        ocr_engine: str,
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
                "ocr_engine": ocr_engine,
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
        ocr_engine: str,
    ) -> dict[str, Any]:
        normalized_row = deepcopy(dict(row))

        row_document_id = normalized_row.get("document_id") or document_uuid
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
        normalized_row.setdefault("ocr_engine", ocr_engine)
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


__all__ = ["OcrAdapter", "OcrPromotionDecision"]
