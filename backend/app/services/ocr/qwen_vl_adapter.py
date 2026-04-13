"""
Qwen VL OCR adapter for v12 image-lane parsing.

This module provides a bounded adapter for the qwen-vl-ocr-2025-11-20 model,
pinned as the primary OCR backend for image/scanned PDFs in the v12 stack.

Key properties:
- Model is pinned to qwen-vl-ocr-2025-11-20 and must NOT be silently swapped.
- Returns raw OCR text blocks with page-level coordinates where available.
- Does NOT emit CanonicalObservationV2 or any downstream artifact directly.
- Image-beta trust level is never silently promoted to trusted.

The caller (input_gateway preflight) is responsible for:
- Ensuring QWEN_OCR_API_KEY is configured before invoking this adapter.
- Wrapping results in PageParseArtifactV3 via the parser substrate contract.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Sentinel for missing API key so callers can fail loudly.
_MISSING_API_KEY = "__QWEN_OCR_API_KEY_NOT_CONFIGURED__"


@dataclass(frozen=True)
class QwenOCRTextBlock:
    """A single text block returned by the Qwen VL OCR API."""

    text: str
    page: int
    confidence: Optional[float] = None
    bbox: Optional[tuple[float, float, float, float]] = None  # (x0, y0, x1, y1)


@dataclass(frozen=True)
class QwenOCRPageResult:
    """OCR result for a single page."""

    page: int
    blocks: list[QwenOCRTextBlock]
    image_width: Optional[int] = None
    image_height: Optional[int] = None

    @property
    def full_text(self) -> str:
        """Concatenate all block text for this page."""
        return "\n".join(b.text for b in self.blocks if b.text.strip())


@dataclass
class QwenOCRResult:
    """Aggregate OCR result for an entire document."""

    pages: list[QwenOCRPageResult] = field(default_factory=list)
    model: str = "qwen-vl-ocr-2025-11-20"
    error: Optional[str] = None

    @property
    def full_text(self) -> str:
        """Concatenate full text across all pages."""
        return "\n\n".join(p.full_text for p in self.pages if p.full_text)

    @property
    def page_count(self) -> int:
        return len(self.pages)


class QwenVLClient:
    """
    HTTP client for the Qwen VL OCR API (DashScope compatible).

    The client wraps the OpenAI-compatible interface provided by DashScope
    so that qwen-vl-ocr-2025-11-20 can be called via the standard
    ``openai`` Python SDK.
    """

    def __init__(
        self,
        api_key: str = _MISSING_API_KEY,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen-vl-ocr-2025-11-20",
        timeout: int = 120,
    ) -> None:
        self._model = model
        self._timeout = timeout
        self._api_key = api_key
        self._base_url = base_url
        self._client: Optional[object] = None

    @property
    def is_configured(self) -> bool:
        """Return True if an API key has been provided."""
        return bool(self._api_key) and self._api_key != _MISSING_API_KEY

    def _get_client(self):
        """Lazily create the OpenAI client instance."""
        if self._client is not None:
            return self._client

        if not self.is_configured:
            raise RuntimeError(
                "Qwen OCR API key is not configured. "
                "Set QWEN_OCR_API_KEY or pass api_key to QwenVLClient."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for the Qwen VL OCR adapter. "
                "Install it with: pip install openai"
            ) from exc

        self._client = OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
        )
        return self._client

    @staticmethod
    def _encode_image(image_path: Path) -> str:
        """Encode a local image file as base64 data URL."""
        data = image_path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        ext = image_path.suffix.lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(ext, "image/png")
        return f"data:{mime};base64,{b64}"

    def ocr_image(self, image_path: Path) -> QwenOCRPageResult:
        """
        Run OCR on a single image file.

        The image should already be extracted from the PDF (e.g., by PyMuPDF
        or pdfplumber in debug mode).

        Returns a QwenOCRPageResult with page=0 (single-page context).
        """
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        client = self._get_client()
        data_url = self._encode_image(image_path)

        system_prompt = (
            "You are a precise OCR engine. Extract all visible text from the "
            "provided image. Preserve layout structure where possible. "
            "Return only the extracted text with no commentary."
        )

        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                            {
                                "type": "text",
                                "text": "Extract all text from this medical document image.",
                            },
                        ],
                    },
                ],
                temperature=0.0,  # OCR should be deterministic
                max_tokens=4096,
            )

            text = ""
            if response.choices and response.choices[0].message:
                text = response.choices[0].message.content or ""

            # Parse response into blocks. For now, treat the entire response
            # as a single block. A future enhancement could parse structured
            # output with bounding boxes if the model supports it.
            block = QwenOCRTextBlock(
                text=text,
                page=0,
                confidence=None,
                bbox=None,
            )
            return QwenOCRPageResult(
                page=0,
                blocks=[block],
            )

        except Exception as exc:
            logger.error("Qwen OCR API call failed for %s: %s", image_path, exc)
            raise

    def ocr_pdf(self, pdf_bytes: bytes, *, max_pages: int | None = None) -> QwenOCRResult:
        """
        Run OCR on a PDF by rendering pages to images via PyMuPDF.

        This is the primary path for image-heavy / scanned PDFs in the v12
        image lane.  Each page is rendered at 2x scale (144 DPI) to preserve
        text detail for the OCR engine, then sent to qwen-vl-ocr-2025-11-20
        individually.

        Returns a QwenOCRResult with one QwenOCRPageResult per successfully
        processed page.
        """
        import tempfile

        try:
            import fitz  # PyMuPDF
        except ImportError as exc:
            raise ImportError(
                "PyMuPDF is required for PDF rendering in the OCR lane. "
                "Install it with: pip install PyMuPDF"
            ) from exc

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"Failed to open PDF for OCR rendering: {exc}") from exc

        try:
            if doc.is_encrypted:
                raise ValueError(
                    "PDF is password-protected and cannot be rendered for OCR."
                )

            total_pages = doc.page_count
            pages_to_process = (
                range(total_pages) if max_pages is None else range(min(total_pages, max_pages))
            )

            result = QwenOCRResult(model=self._model)

            for page_idx in pages_to_process:
                page = doc[page_idx]
                try:
                    # Render page to image at 2x scale for better OCR quality
                    mat = fitz.Matrix(2, 2)
                    pix = page.get_pixmap(matrix=mat)

                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        tmp.write(pix.tobytes("png"))
                        tmp_path = Path(tmp.name)

                    try:
                        page_result = self.ocr_image(tmp_path)
                        # Re-number pages sequentially
                        page_result = QwenOCRPageResult(
                            page=page_idx,
                            blocks=[
                                QwenOCRTextBlock(
                                    text=b.text,
                                    page=page_idx,
                                    confidence=b.confidence,
                                    bbox=b.bbox,
                                )
                                for b in page_result.blocks
                            ],
                            image_width=pix.width,
                            image_height=pix.height,
                        )
                        result.pages.append(page_result)
                    finally:
                        try:
                            tmp_path.unlink()
                        except OSError:
                            pass

                except Exception as exc:  # pragma: no cover - per-page error handling
                    logger.warning("OCR failed on page %d: %s", page_idx, exc)
                    result.error = f"OCR failed on page {page_idx}: {exc}"
                    break

            return result

        finally:
            try:
                doc.close()
            except Exception:  # noqa: BLE001 - defensive
                pass


def run_ocr_on_images(
    image_paths: list[Path],
    api_key: str = _MISSING_API_KEY,
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: str = "qwen-vl-ocr-2025-11-20",
    timeout: int = 120,
) -> QwenOCRResult:
    """
    Convenience function to run OCR on a list of extracted images.

    Callers should prefer injecting a QwenVLClient instance in production
    code; this function exists for simple / test flows.
    """
    client = QwenVLClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
    )

    result = QwenOCRResult(model=model)
    for idx, img_path in enumerate(image_paths):
        try:
            page_result = client.ocr_image(img_path)
            # Renumber pages sequentially
            page_result = QwenOCRPageResult(
                page=idx,
                blocks=[
                    QwenOCRTextBlock(
                        text=b.text,
                        page=idx,
                        confidence=b.confidence,
                        bbox=b.bbox,
                    )
                    for b in page_result.blocks
                ],
                image_width=page_result.image_width,
                image_height=page_result.image_height,
            )
            result.pages.append(page_result)
        except Exception as exc:
            result.error = f"OCR failed on image {img_path}: {exc}"
            logger.error(result.error)
            break

    return result
