"""Input gateway: lane classification, file sanitization, and typed preflight."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, TypedDict

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from app.config import settings
from app.services.ocr import OcrAdapter


class InputGatewayError(ValueError):
    """Typed input-gateway failure with a stable error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class InputGatewayPreflight(TypedDict, total=False):
    lane_type: str
    document_class: str
    failure_code: str | None
    duplicate_state: str
    promotion_status: str
    text_extractability: float
    image_density: float
    password_protected: bool
    corrupt: bool
    page_count: int
    total_text_chars: int
    total_text_words: int
    total_image_area_ratio: float
    has_text_layer: bool
    has_image_layer: bool
    filename: str
    sanitized_filename: str
    extension: str
    mime_type: str
    file_size_bytes: int
    checksum: str


class InputGateway:
    """Classify input into trusted PDF, image beta, or structured lanes."""

    _SUPPORTED_MIME_BY_EXTENSION = {
        ".pdf": {"application/pdf"},
        ".png": {"image/png"},
        ".jpg": {"image/jpeg"},
        ".jpeg": {"image/jpeg"},
        ".webp": {"image/webp"},
        ".gif": {"image/gif"},
        ".bmp": {"image/bmp"},
        ".tif": {"image/tiff"},
        ".tiff": {"image/tiff"},
        ".json": {"application/json", "application/fhir+json"},
    }

    _MIME_ALIASES = {
        "application/x-pdf": "application/pdf",
        "image/jpg": "image/jpeg",
        "image/pjpeg": "image/jpeg",
        "image/x-png": "image/png",
        "image/x-bmp": "image/bmp",
        "image/x-tiff": "image/tiff",
    }

    _IMAGE_BETA_IMAGE_DENSITY_THRESHOLD = 0.35
    _IMAGE_BETA_TEXT_EXTRACTABILITY_THRESHOLD = 0.65

    async def preflight(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
    ) -> InputGatewayPreflight:
        sanitized_filename = self._sanitize_filename(filename)
        extension = Path(sanitized_filename).suffix.lower()
        normalized_mime_type = self._normalize_mime_type(mime_type)
        checksum = sha256(file_bytes).hexdigest()
        base_result: InputGatewayPreflight = {
            "filename": sanitized_filename,
            "sanitized_filename": sanitized_filename,
            "extension": extension,
            "mime_type": normalized_mime_type,
            "file_size_bytes": len(file_bytes),
            "checksum": checksum,
            "duplicate_state": "not_checked",
            "failure_code": None,
        }

        if extension not in self._SUPPORTED_MIME_BY_EXTENSION:
            raise InputGatewayError(f"unsupported_extension:{extension or 'missing'}")

        expected_mime_types = self._SUPPORTED_MIME_BY_EXTENSION[extension]
        if normalized_mime_type not in expected_mime_types:
            raise InputGatewayError(
                "mime_type_mismatch:"
                f"{extension}:{normalized_mime_type or 'missing'}"
            )

        if extension == ".json":
            return {
                **base_result,
                "lane_type": "structured",
                "document_class": "structured_record",
                "promotion_status": "ready",
                "text_extractability": 1.0,
                "image_density": 0.0,
                "password_protected": False,
                "corrupt": False,
                "page_count": 0,
                "total_text_chars": 0,
                "total_text_words": 0,
                "total_image_area_ratio": 0.0,
                "has_text_layer": False,
                "has_image_layer": False,
            }

        if extension == ".pdf":
            return {**base_result, **self._preflight_pdf(file_bytes)}

        return {
            **base_result,
            "lane_type": "image_beta",
            "document_class": "image_file",
            "promotion_status": self._resolve_image_beta_promotion_status(),
            "text_extractability": 0.0,
            "image_density": 1.0,
            "password_protected": False,
            "corrupt": False,
            "page_count": 1,
            "total_text_chars": 0,
            "total_text_words": 0,
            "total_image_area_ratio": 1.0,
            "has_text_layer": False,
            "has_image_layer": True,
        }

    async def classify(self, file_bytes: bytes, filename: str, mime_type: str) -> dict:
        """Return a lane classification for upload routing.

        This keeps the public upload path safe: anything that is not ready to
        run is surfaced as a typed ValueError instead of slipping into runtime
        pipeline failure.
        """

        result = await self.preflight(file_bytes, filename, mime_type)
        failure_code = result.get("failure_code")
        promotion_status = result.get("promotion_status")
        if failure_code:
            raise InputGatewayError(str(failure_code))
        if promotion_status not in {"ready", "beta_ready"}:
            raise InputGatewayError(str(promotion_status))
        return dict(result)

    def _preflight_pdf(self, file_bytes: bytes) -> InputGatewayPreflight:
        try:
            with pdfplumber.open(BytesIO(file_bytes)) as pdf:
                page_count = len(pdf.pages)
                if page_count == 0:
                    return self._unsupported_pdf_preflight(
                        file_bytes=file_bytes,
                        failure_code="pdf_corrupt",
                        promotion_status="blocked_corrupt",
                    )
                return self._measure_pdf_preflight(
                    pdf,
                    page_count=page_count,
                    file_bytes=file_bytes,
                )
        except PdfminerException as exc:
            return self._unsupported_pdf_preflight(
                file_bytes=file_bytes,
                failure_code=self._pdf_failure_code_from_exception(exc),
                promotion_status=self._pdf_promotion_status_from_exception(exc),
            )
        except (PDFPasswordIncorrect, PDFSyntaxError) as exc:
            return self._unsupported_pdf_preflight(
                file_bytes=file_bytes,
                failure_code=self._pdf_failure_code_from_exception(exc),
                promotion_status=self._pdf_promotion_status_from_exception(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            return self._unsupported_pdf_preflight(
                file_bytes=file_bytes,
                failure_code=self._pdf_failure_code_from_exception(exc),
                promotion_status=self._pdf_promotion_status_from_exception(exc),
            )

    def _measure_pdf_preflight(
        self,
        pdf: Any,
        *,
        page_count: int,
        file_bytes: bytes,
    ) -> InputGatewayPreflight:
        total_page_area = 0.0
        total_image_area = 0.0
        total_text_chars = 0
        total_text_words = 0
        has_text_layer = False
        has_image_layer = False

        for page in pdf.pages:
            page_area = float(getattr(page, "width", 0.0) or 0.0) * float(
                getattr(page, "height", 0.0) or 0.0
            )
            total_page_area += page_area

            page_image_area = 0.0
            for image in getattr(page, "images", []):
                has_image_layer = True
                image_width = float(image.get("width", 0.0) or 0.0)
                image_height = float(image.get("height", 0.0) or 0.0)
                page_image_area += max(0.0, image_width * image_height)

            total_image_area += min(page_area, page_image_area) if page_area else 0.0

            text = page.extract_text() or ""
            cleaned_text = text.strip()
            if cleaned_text:
                has_text_layer = True
                total_text_chars += len(cleaned_text)

            total_text_words += len(page.extract_words() or [])

        image_density = round(
            min(1.0, total_image_area / total_page_area) if total_page_area else 0.0,
            3,
        )
        text_extractability = round(max(0.0, 1.0 - image_density), 3)
        document_class = self._classify_document_class(image_density=image_density)
        lane_type = self._classify_lane_type(
            image_density=image_density,
            text_extractability=text_extractability,
        )

        if lane_type == "trusted_pdf":
            promotion_status = "ready"
        else:
            promotion_status = self._resolve_image_beta_promotion_status()

        return {
            "lane_type": lane_type,
            "document_class": document_class,
            "failure_code": None,
            "promotion_status": promotion_status,
            "text_extractability": text_extractability,
            "image_density": image_density,
            "password_protected": False,
            "corrupt": False,
            "page_count": page_count,
            "total_text_chars": total_text_chars,
            "total_text_words": total_text_words,
            "total_image_area_ratio": image_density,
            "has_text_layer": has_text_layer,
            "has_image_layer": has_image_layer,
        }

    def _unsupported_pdf_preflight(
        self,
        *,
        file_bytes: bytes,
        failure_code: str,
        promotion_status: str,
    ) -> InputGatewayPreflight:
        return {
            "lane_type": "unsupported",
            "document_class": "unsupported_pdf",
            "failure_code": failure_code,
            "promotion_status": promotion_status,
            "text_extractability": 0.0,
            "image_density": 0.0,
            "password_protected": failure_code == "pdf_password_protected",
            "corrupt": failure_code == "pdf_corrupt",
            "page_count": 0,
            "total_text_chars": 0,
            "total_text_words": 0,
            "total_image_area_ratio": 0.0,
            "has_text_layer": False,
            "has_image_layer": False,
        }

    @classmethod
    def _classify_document_class(cls, *, image_density: float) -> str:
        if image_density >= 0.75:
            return "image_pdf"
        if image_density >= 0.15:
            return "mixed_pdf"
        return "text_pdf"

    @classmethod
    def _classify_lane_type(
        cls,
        *,
        image_density: float,
        text_extractability: float,
    ) -> str:
        if (
            image_density >= cls._IMAGE_BETA_IMAGE_DENSITY_THRESHOLD
            or text_extractability < cls._IMAGE_BETA_TEXT_EXTRACTABILITY_THRESHOLD
        ):
            return "image_beta"
        return "trusted_pdf"

    def _resolve_image_beta_promotion_status(self) -> str:
        ocr_adapter = OcrAdapter(image_beta_enabled=settings.image_beta_enabled)
        if not settings.image_beta_enabled:
            return "blocked_image_beta_disabled"
        if ocr_adapter.is_available():
            return "beta_ready"
        return "blocked_no_ocr_backend"

    @staticmethod
    def _pdf_failure_code_from_exception(exc: Exception) -> str:
        for candidate in InputGateway._iter_pdf_exceptions(exc):
            if isinstance(candidate, PDFPasswordIncorrect):
                return "pdf_password_protected"
            if isinstance(candidate, PDFSyntaxError):
                return "pdf_corrupt"
            message = str(candidate).strip().lower()
            if "password" in message:
                return "pdf_password_protected"
        return "pdf_corrupt"

    @staticmethod
    def _pdf_promotion_status_from_exception(exc: Exception) -> str:
        failure_code = InputGateway._pdf_failure_code_from_exception(exc)
        if failure_code == "pdf_password_protected":
            return "blocked_password_protected"
        return "blocked_corrupt"

    @staticmethod
    def _iter_pdf_exceptions(exc: Exception) -> list[Exception]:
        candidates: list[Exception] = [exc]
        for nested in exc.args:
            if isinstance(nested, Exception):
                candidates.append(nested)
        if exc.__cause__ is not None and isinstance(exc.__cause__, Exception):
            candidates.append(exc.__cause__)
        if exc.__context__ is not None and isinstance(exc.__context__, Exception):
            candidates.append(exc.__context__)
        return candidates

    @classmethod
    def _sanitize_filename(cls, filename: str) -> str:
        sanitized = Path(filename).name.strip()
        if not sanitized:
            raise InputGatewayError("filename_missing")

        return sanitized.replace("\x00", "")

    @classmethod
    def _normalize_mime_type(cls, mime_type: str | None) -> str:
        normalized = (mime_type or "").strip().lower()
        return cls._MIME_ALIASES.get(normalized, normalized)


__all__ = ["InputGateway", "InputGatewayError", "InputGatewayPreflight"]
