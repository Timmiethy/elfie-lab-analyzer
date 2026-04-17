"""Input gateway: lane classification, file sanitization, and support scoring."""

from __future__ import annotations

import logging
from hashlib import sha256
from pathlib import Path

_PDF_MAGIC = b"%PDF"
_PNG_MAGIC = b"\x89PNG"
_JPEG_MAGIC = b"\xff\xd8\xff"
_LOGGER = logging.getLogger(__name__)
_MAGIC_WARNING_EMITTED = False

try:
    import magic as _python_magic
except Exception:  # pragma: no cover - optional dependency
    _python_magic = None


class InputGateway:
    """Classify input into trusted PDF or image beta lanes.

    Phase 1 keeps the intake logic intentionally small and deterministic:
    - allow only supported extensions
    - require MIME/extension agreement
    - validate magic bytes to prevent polyglot bypass
    - sanitize filenames locally
    - compute checksum and file size
    """

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

    async def classify(self, file_bytes: bytes, filename: str, mime_type: str) -> dict:
        sanitized_filename = self._sanitize_filename(filename)
        extension = Path(sanitized_filename).suffix.lower()
        normalized_mime_type = self._normalize_mime_type(mime_type)

        if extension not in self._SUPPORTED_MIME_BY_EXTENSION:
            raise ValueError(f"unsupported_extension:{extension or 'missing'}")

        expected_mime_types = self._SUPPORTED_MIME_BY_EXTENSION[extension]
        if normalized_mime_type not in expected_mime_types:
            raise ValueError(f"mime_type_mismatch:{extension}:{normalized_mime_type or 'missing'}")

        self._validate_detected_mime(
            file_bytes=file_bytes,
            extension=extension,
            expected_mime_types=expected_mime_types,
        )

        # Magic-byte validation — prevents polyglot files bypassing extension+MIME checks.
        if normalized_mime_type == "application/pdf" and not file_bytes.startswith(_PDF_MAGIC):
            raise ValueError("magic_byte_mismatch:pdf")
        if normalized_mime_type == "image/png" and not file_bytes.startswith(_PNG_MAGIC):
            raise ValueError("magic_byte_mismatch:png")
        if normalized_mime_type == "image/jpeg" and not file_bytes.startswith(_JPEG_MAGIC):
            raise ValueError("magic_byte_mismatch:jpeg")

        if extension == ".json":
            lane_type = "structured"
        elif extension == ".pdf":
            try:
                import pdf_inspector

                result = pdf_inspector.process_pdf_bytes(file_bytes)
                if result.pdf_type == "text_based":
                    lane_type = "trusted_pdf"
                else:
                    lane_type = "image_beta"  # Send scanned/mixed to minerU/VLM
            except Exception:
                lane_type = "trusted_pdf"
        else:
            lane_type = "image_beta"

        checksum = sha256(file_bytes).hexdigest()

        return {
            "lane_type": lane_type,
            "filename": sanitized_filename,
            "sanitized_filename": sanitized_filename,
            "extension": extension,
            "mime_type": normalized_mime_type,
            "file_size_bytes": len(file_bytes),
            "checksum": checksum,
        }

    @classmethod
    def _sanitize_filename(cls, filename: str) -> str:
        sanitized = Path(filename).name.strip()
        if not sanitized:
            raise ValueError("filename_missing")

        return sanitized.replace("\x00", "")

    @classmethod
    def _normalize_mime_type(cls, mime_type: str | None) -> str:
        normalized = (mime_type or "").strip().lower()
        return cls._MIME_ALIASES.get(normalized, normalized)

    @classmethod
    def _validate_detected_mime(
        cls,
        *,
        file_bytes: bytes,
        extension: str,
        expected_mime_types: set[str],
    ) -> None:
        global _MAGIC_WARNING_EMITTED

        if _python_magic is None:
            if not _MAGIC_WARNING_EMITTED:
                _LOGGER.warning(
                    "python-magic unavailable; using static magic-byte validation fallback"
                )
                _MAGIC_WARNING_EMITTED = True
            return

        try:
            detected = _python_magic.from_buffer(file_bytes, mime=True)
            detected_mime_type = cls._normalize_mime_type(detected)
        except Exception:
            return

        if detected_mime_type and detected_mime_type not in expected_mime_types:
            raise ValueError(f"mime_detect_mismatch:{extension}:{detected_mime_type}")


__all__ = ["InputGateway"]
