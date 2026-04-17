"""Input gateway: lane classification, file sanitization, and support scoring."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


class InputGateway:
    """Classify input into trusted PDF or image beta lanes.

    Phase 1 keeps the intake logic intentionally small and deterministic:
    - allow only supported extensions
    - require MIME/extension agreement
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


__all__ = ["InputGateway"]
