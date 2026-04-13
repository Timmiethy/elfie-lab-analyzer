"""Image beta lane OCR adapter.

This module intentionally stays conservative:
- it never pretends OCR succeeded when the optional stack is unavailable
- it can normalize injected OCR text/rows into downstream QA-compatible rows
- it uses qwen-vl-ocr-2025-11-20 as the primary production OCR backend
- surya and docTR are NOT auto-discovered or used in v12
- it derives stable identifiers when callers do not provide them
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
from importlib.util import find_spec
from io import BytesIO
from pathlib import Path
from typing import Any, TypedDict
from uuid import NAMESPACE_URL, UUID, uuid5

from app.config import settings

logger = logging.getLogger(__name__)

_LINE_VALUE_PATTERN = re.compile(
    r"^\s*(?P<label>.*?)(?:\s+|[:=\-\u2013\u2014|])"
    r"(?P<value>[+-]?\d+(?:\.\d+)?)\b(?P<unit>.*\S)?\s*$"
)
_DEFAULT_OCR_ENGINE = "qwen_ocr"
_IMAGE_BETA_PARSER_BACKEND = "qwen_ocr"
_IMAGE_BETA_PARSER_VERSION = "qwen-vl-ocr-2025-11-20"
_IMAGE_BETA_ROW_ASSEMBLY_VERSION = "row-assembly-v2"

# v12 wave-18: row-shape ceilings to prevent pathological OCR narrative rows
# from reaching persistence and causing StringDataRightTruncationError.
_MAX_RAW_VALUE_STRING = 64
_MAX_RAW_UNIT_STRING = 64
_MAX_RAW_REFERENCE_RANGE = 128
_MAX_SOURCE_BLOCK_ID = 128
_MAX_NORMALIZABLE_TEXT_TOKENS = 32


def _enforce_row_shape_ceilings(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter out image-beta rows that exceed v12 persistence field-length ceilings.

    Rows violating the ceilings are logged and silently dropped rather than
    allowing them to reach persistence and cause asyncpg
    ``StringDataRightTruncationError``.

    Enforced ceilings (from the v12 proof gates):
    - ``raw_value_string`` <= 64
    - ``raw_unit_string`` <= 64
    - ``raw_reference_range`` <= 128
    - ``source_block_id`` <= 128
    - normalizable ``raw_text`` token count <= 32
    """
    kept: list[dict[str, Any]] = []
    for row in rows:
        reason = _check_row_shape_violation(row)
        if reason is not None:
            logger.warning(
                "ocr_row_shape_ceiling_exceeded: %s | raw_text=%r | raw_unit_string=%r",
                reason,
                (row.get("raw_text") or "")[:80],
                (row.get("raw_unit_string") or "")[:40],
            )
            continue
        kept.append(row)
    return kept


def _check_row_shape_violation(row: dict[str, Any]) -> str | None:
    """Return a human-readable violation reason, or None if the row is within ceilings."""
    raw_value = row.get("raw_value_string") or ""
    if len(str(raw_value)) > _MAX_RAW_VALUE_STRING:
        return "raw_value_string_too_long"

    raw_unit = row.get("raw_unit_string") or ""
    if len(str(raw_unit)) > _MAX_RAW_UNIT_STRING:
        return "raw_unit_string_too_long"

    raw_ref = row.get("raw_reference_range") or ""
    if len(str(raw_ref)) > _MAX_RAW_REFERENCE_RANGE:
        return "raw_reference_range_too_long"

    block_id = row.get("source_block_id") or row.get("block_id") or ""
    if len(str(block_id)) > _MAX_SOURCE_BLOCK_ID:
        return "source_block_id_too_long"

    raw_text = row.get("raw_text") or ""
    if raw_text:
        token_count = len(raw_text.split())
        if token_count > _MAX_NORMALIZABLE_TEXT_TOKENS:
            return f"raw_text_token_count_exceeded({token_count}>{_MAX_NORMALIZABLE_TEXT_TOKENS})"

    return None


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):  # pragma: no cover - defensive import guard
        return False


class OcrPromotionDecision(TypedDict):
    promotion_status: str
    backend_available: bool
    backend_candidates: list[str]
    positioned_output: bool


class OcrAdapter:
    """Safe adapter for image-beta OCR.

    v12: Uses qwen-vl-ocr-2025-11-20 as the primary production OCR backend.
    The adapter accepts an injected OCR backend or pre-extracted OCR text/rows.
    When neither is available, it raises a clear runtime error instead of
    silently fabricating OCR output.

    surya and docTR are no longer auto-discovered as primary backends.
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
                "image_beta_ocr_unavailable: the Qwen OCR backend is not configured. "
                "Set ELFIE_QWEN_OCR_API_KEY or inject pre-extracted OCR "
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
        """Build the list of auto-discovered OCR backends.

        v12: Only qwen-vl-ocr is a production backend.
        surya and docTR are no longer auto-discovered here.
        """
        candidates: list[tuple[str, Callable[[bytes], Any]]] = []

        qwen_backend = self._build_qwen_vl_ocr_backend()
        if qwen_backend is not None:
            candidates.append(("qwen_vl_ocr", qwen_backend))

        return candidates

    def _build_qwen_vl_ocr_backend(self) -> Callable[[bytes], Any] | None:
        """Build a Qwen VL OCR backend if the API key is configured.

        Returns a callable that accepts image bytes and returns OCR results,
        or None if the API key is not configured.
        """
        api_key = settings.qwen_ocr_api_key
        if not api_key:
            return None

        try:
            from app.services.ocr.qwen_vl_adapter import QwenVLClient
        except ImportError:
            logger.warning("Qwen VL OCR adapter module not available")
            return None

        try:
            client = QwenVLClient(
                api_key=api_key,
                base_url=settings.qwen_ocr_api_base,
                model=settings.qwen_ocr_model,
                timeout=settings.qwen_ocr_timeout_seconds,
            )
            if not client.is_configured:
                return None
        except Exception:  # pragma: no cover - defensive
            return None

        def backend(image_bytes: bytes, client=client) -> Any:
            """Run Qwen OCR on image bytes, detecting PDF vs image input.

            v12: If the input is a PDF (magic bytes %PDF), render pages to
            images via PyMuPDF and OCR each page through ocr_pdf.  Otherwise
            treat the bytes as a single image and call ocr_image.

            Multi-page PDF results are returned as a list of per-page dicts,
            each with ``text``, ``blocks``, and ``source_page``.  Single-image
            results are returned as a list with one entry so the caller can
            always iterate uniformly.
            """
            import tempfile

            if image_bytes.startswith(b"%PDF"):
                # PDF input: render pages to images and OCR each page
                page_results = client.ocr_pdf(image_bytes)
                pages: list[dict[str, Any]] = []

                # v12 wave-17: accept both QwenOCRResult (with .pages) and
                # plain list mocks from existing unit tests.
                if hasattr(page_results, "pages"):
                    page_iter = page_results.pages
                elif isinstance(page_results, list):
                    page_iter = page_results
                else:
                    page_iter = [page_results]

                for page_result in page_iter:
                    pages.append({
                        "text": page_result.full_text,
                        "blocks": page_result.blocks,
                        "source_page": page_result.page + 1,  # 1-based
                    })
                return pages

            # Image input: write to temp file and OCR as a single image
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = Path(tmp.name)

            try:
                page_result = client.ocr_image(tmp_path)
                return [{
                    "text": page_result.full_text,
                    "blocks": page_result.blocks,
                    "source_page": 1,
                }]
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        return backend

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
                # v12: Multi-page PDF OCR results are a list of per-page dicts
                # with keys like "text", "blocks", "source_page".  Detect this
                # shape so we preserve per-page source_page instead of collapsing
                # everything to page 1.  Route through PageParseArtifactV3 ->
                # RowAssemblerV2 so the image lane uses the same parser-output
                # contract as the trusted PDF lane.
                has_page_shape = all(
                    "text" in item and "source_page" in item
                    for item in backend_output
                )
                if has_page_shape:
                    rows: list[dict[str, Any]] = []
                    for page_item in backend_output:
                        page_num = int(page_item.get("source_page", source_page))
                        page_text = str(page_item.get("text", ""))
                        if page_text:
                            page_rows = self._rows_from_page_text(
                                page_text,
                                document_uuid=document_uuid,
                                source_page=page_num,
                                language_id=language_id,
                                ocr_engine=ocr_engine,
                            )
                            rows.extend(page_rows)
                    if rows:
                        return _enforce_row_shape_ceilings(rows)
                    # If text is empty, fall through to normalize as rows
                return self._normalize_rows(
                    list(backend_output),
                    document_uuid=document_uuid,
                    source_page=source_page,
                    language_id=language_id,
                    ocr_engine=ocr_engine,
                )

            rows = []
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
                return _enforce_row_shape_ceilings(rows)

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
        return _enforce_row_shape_ceilings(normalized_rows)

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

        return _enforce_row_shape_ceilings(rows)

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

    def _rows_from_page_text(
        self,
        page_text: str,
        *,
        document_uuid: UUID,
        source_page: int,
        language_id: str | None,
        ocr_engine: str,
    ) -> list[dict[str, Any]]:
        """v13: Convert raw OCR page text into candidate rows via
        PageParseArtifactV4 -> BlockGraphV1 -> RowAssemblerV3.

        This is the contract bridge for the image-lane OCR path so it produces
        the same downstream row shape as the trusted PDF path.
        """
        from app.services.document_system.block_graph_builder import BlockGraphBuilder
        from app.services.document_system.ocr_substrate import OcrSubstrate
        from app.services.document_system.row_assembler import (
            RowAssemblerV3,
            candidate_row_to_legacy,
        )

        substrate = OcrSubstrate()
        artifact_v4 = substrate.artifact_from_text(
            page_text=page_text,
            page_number=source_page,
            document_id=str(document_uuid),
            backend_id=_IMAGE_BETA_PARSER_BACKEND,
            backend_version=_IMAGE_BETA_PARSER_VERSION,
        )

        block_graph = BlockGraphBuilder().build(artifact_v4)
        assembler = RowAssemblerV3()
        page_class = {
            "lab_results": "analyte_table_page",
            "threshold_reference": "threshold_page",
            "admin_metadata": "admin_page",
            "narrative_guidance": "narrative_page",
            "interpreted_summary": "narrative_page",
            "non_lab_medical": "narrative_page",
            "footer_header": "header_footer_page",
        }.get(getattr(artifact_v4.page_kind, "value", "unknown"), "mixed_page")

        candidate_rows, suppression_report = assembler.assemble(
            block_graph=block_graph,
            artifact=artifact_v4,
            family_adapter_id="generic_layout",
            page_class=page_class,
        )
        raw_rows = []
        for candidate_row in candidate_rows:
            legacy_row = candidate_row_to_legacy(candidate_row, trust_level=artifact_v4.lane_type)
            legacy_row["source_page"] = source_page
            legacy_row["candidate_trace"] = {
                **(legacy_row.get("candidate_trace") or {}),
                "suppression_record_count": len(suppression_report.suppression_records),
            }
            raw_rows.append(legacy_row)

        return self._enrich_ocr_rows(raw_rows, document_uuid=document_uuid, ocr_engine=ocr_engine)

    def _enrich_ocr_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        document_uuid: UUID,
        ocr_engine: str,
    ) -> list[dict[str, Any]]:
        """Enrich assembled rows with image-lane metadata."""
        enriched: list[dict[str, Any]] = []
        for row in rows:
            row["document_id"] = document_uuid
            row.setdefault("lane_type", "image_beta")
            row.setdefault("ocr_engine", ocr_engine)
            row.setdefault("parser_backend", _IMAGE_BETA_PARSER_BACKEND)
            row.setdefault("parser_backend_version", _IMAGE_BETA_PARSER_VERSION)
            row.setdefault("row_assembly_version", _IMAGE_BETA_ROW_ASSEMBLY_VERSION)
            enriched.append(row)
        return _enforce_row_shape_ceilings(enriched)

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
