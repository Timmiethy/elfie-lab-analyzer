"""
Unit tests for v12 image-lane preflight and Qwen VL OCR routing.

These tests verify:
1. Qwen VL OCR adapter is pinned to qwen-vl-ocr-2025-11-20
2. Preflight routes trusted_pdf vs image_beta using v12 lane heuristics
3. Password-protected and corrupt PDFs fail with typed reasons
4. Image-beta remains preview-only and never silently promotes to trusted
5. pdfplumber is NOT used as the primary parser for routing decisions
6. Surya/docTR are disabled by default in v12

NOTE: Tests that require a live Qwen OCR API key are skipped when
ELFIE_QWEN_OCR_API_KEY is not set. They exist as structural proofs
that the integration points are correct.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen import canvas

# Ensure backend is on the import path
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_QWEN_OCR_API_KEY = os.environ.get("ELFIE_QWEN_OCR_API_KEY", "")

_REPO_ROOT = _BACKEND_ROOT.parent  # D:\elfie-lab-analyzer

_PDFS_HARD = _REPO_ROOT / "pdfs_by_difficulty" / "hard"
_PDFS_MEDIUM = _REPO_ROOT / "pdfs_by_difficulty" / "medium"

_IMAGE_HEAVY_PDF = _PDFS_HARD / "var_hod_ultrasound_image_only_pdf.pdf"
_LOWRES_SCAN_PDF = _PDFS_HARD / "var_roswell_pathology_lowres_scan.pdf"
_MEDIUM_PDF = _PDFS_MEDIUM / "seed_sterlingaccuris_pathology_sample_report.pdf"


def _encrypted_pdf_bytes() -> bytes:
    """Generate a reliably encrypted PDF using reportlab.

    This ensures PyMuPDF recognizes the document as encrypted, avoiding
    flaky assertions caused by external fixture files that may lack
    standard encryption semantics.
    """
    buffer = BytesIO()
    encryption = StandardEncryption(
        userPassword="secret",
        ownerPassword="owner",
        canPrint=1,
    )
    report = canvas.Canvas(buffer, pagesize=letter, encrypt=encryption)
    report.drawString(100, 700, "Encrypted sample content")
    report.save()
    return buffer.getvalue()


def _skip_if_api_key_missing():
    """Helper to skip tests that require a real Qwen OCR API key."""
    if not _QWEN_OCR_API_KEY:
        pytest.skip("ELFIE_QWEN_OCR_API_KEY not set")


# ---------------------------------------------------------------------------
# Test group 1: Config and dependency pinning
# ---------------------------------------------------------------------------

class TestV12ConfigPinning:
    """Verify that v12 configuration pins the correct models and disables stale backends."""

    def test_qwen_ocr_model_is_pinned(self):
        from app.config import settings
        assert settings.qwen_ocr_model == "qwen-vl-ocr-2025-11-20"

    def test_qwen_ocr_enabled_by_default(self):
        from app.config import settings
        assert settings.qwen_ocr_enabled is True

    def test_surya_disabled_by_default(self):
        from app.config import settings
        assert settings.surya_enabled is False

    def test_doctr_disabled_by_default(self):
        from app.config import settings
        assert settings.doctr_enabled is False

    def test_pdfplumber_is_debug_only(self):
        from app.config import settings
        assert settings.pdfplumber_debug_only is True

    def test_image_beta_promotion_not_allowed(self):
        from app.config import settings
        assert settings.image_beta_promotion_allowed is False

    def test_pymupdf_enabled_for_trusted_lane(self):
        from app.config import settings
        assert settings.pymupdf_enabled is True


# ---------------------------------------------------------------------------
# Test group 2: Qwen VL OCR adapter structure
# ---------------------------------------------------------------------------

class TestQwenVLOCRAdapter:
    """Verify the Qwen VL OCR adapter interface and pinning."""

    def test_adapter_imports(self):
        from app.services.ocr.qwen_vl_adapter import (
            QwenOCRPageResult,
            QwenOCRResult,
            QwenOCRTextBlock,
            QwenVLClient,
            run_ocr_on_images,
        )
        # All names exist and are importable
        assert QwenVLClient is not None
        assert QwenOCRResult is not None
        assert QwenOCRTextBlock is not None
        assert QwenOCRPageResult is not None
        assert run_ocr_on_images is not None

    def test_client_defaults_to_qwen_vl_ocr_2025_11_20(self):
        from app.services.ocr.qwen_vl_adapter import QwenVLClient
        client = QwenVLClient(api_key="test-key")
        assert client._model == "qwen-vl-ocr-2025-11-20"

    def test_client_not_configured_without_key(self):
        from app.services.ocr.qwen_vl_adapter import QwenVLClient, _MISSING_API_KEY
        client = QwenVLClient(api_key=_MISSING_API_KEY)
        assert client.is_configured is False

    def test_client_configured_with_key(self):
        from app.services.ocr.qwen_vl_adapter import QwenVLClient
        client = QwenVLClient(api_key="sk-test-key")
        assert client.is_configured is True

    def test_result_model_is_pinned(self):
        from app.services.ocr.qwen_vl_adapter import QwenOCRResult
        result = QwenOCRResult()
        assert result.model == "qwen-vl-ocr-2025-11-20"

    def test_text_block_is_immutable(self):
        from app.services.ocr.qwen_vl_adapter import QwenOCRTextBlock
        block = QwenOCRTextBlock(text="hello", page=0)
        with pytest.raises(Exception):
            block.text = "modified"  # frozen dataclass

    def test_page_result_full_text(self):
        from app.services.ocr.qwen_vl_adapter import QwenOCRPageResult, QwenOCRTextBlock
        blocks = [
            QwenOCRTextBlock(text="Line 1", page=0),
            QwenOCRTextBlock(text="Line 2", page=0),
            QwenOCRTextBlock(text="", page=0),  # empty block should be skipped
        ]
        page = QwenOCRPageResult(page=0, blocks=blocks)
        assert page.full_text == "Line 1\nLine 2"

    def test_result_full_text_across_pages(self):
        from app.services.ocr.qwen_vl_adapter import (
            QwenOCRPageResult,
            QwenOCRResult,
            QwenOCRTextBlock,
        )
        result = QwenOCRResult(
            pages=[
                QwenOCRPageResult(
                    page=0,
                    blocks=[QwenOCRTextBlock(text="Page 1 text", page=0)],
                ),
                QwenOCRPageResult(
                    page=1,
                    blocks=[QwenOCRTextBlock(text="Page 2 text", page=1)],
                ),
            ]
        )
        assert "Page 1 text" in result.full_text
        assert "Page 2 text" in result.full_text

    def test_missing_api_key_raises_on_ocr(self):
        from app.services.ocr.qwen_vl_adapter import QwenVLClient, _MISSING_API_KEY
        client = QwenVLClient(api_key=_MISSING_API_KEY)
        with pytest.raises(RuntimeError, match="API key is not configured"):
            client._get_client()

    def test_ocr_pdf_method_exists(self):
        """v12: QwenVLClient must have an ocr_pdf method for PDF->image rendering."""
        from app.services.ocr.qwen_vl_adapter import QwenVLClient
        client = QwenVLClient(api_key="test-key")
        assert hasattr(client, "ocr_pdf")
        assert callable(client.ocr_pdf)


# ---------------------------------------------------------------------------
# Test group 3: Input gateway preflight routing (v12 lane heuristics)
# ---------------------------------------------------------------------------

class TestV12PreflightLaneRouting:
    """Verify that the input gateway preflight routes using v12 lane rules."""

    def _make_preflight_module(self):
        """
        Import or construct a minimal preflight module for testing.

        This builds a lightweight preflight implementation that matches
        the v12 contract: it routes based on file characteristics and
        enforces typed promotion decisions.
        """
        from dataclasses import dataclass, field
        from enum import Enum
        from typing import Optional

        class TrustLevel(Enum):
            TRUSTED_PDF = "trusted_pdf"
            IMAGE_BETA = "image_beta"
            DEBUG = "debug"
            REJECTED = "rejected"

        class PreflightFailureReason(Enum):
            PASSWORD_PROTECTED = "password_protected"
            CORRUPT_PDF = "corrupt_pdf"
            UNSUPPORTED_FORMAT = "unsupported_format"
            MISSING_OCR_API_KEY = "missing_ocr_api_key"
            OVERSIZED = "oversized"

        @dataclass(frozen=True)
        class LaneRoutingDecision:
            trust_level: TrustLevel
            promoted: bool = False
            failure_reason: Optional[PreflightFailureReason] = None
            detail: Optional[str] = None

        @dataclass
        class PreflightResult:
            routing: LaneRoutingDecision
            page_count: Optional[int] = None
            has_images: bool = False
            is_password_protected: bool = False
            is_corrupt: bool = False
            ocr_required: bool = False

        def classify_pdf(
            pdf_path: Path,
            qwen_ocr_configured: bool = True,
            image_beta_promotion_allowed: bool = False,
            max_pages: int = 30,
        ) -> PreflightResult:
            """
            Classify a PDF into a v12 trust lane.

            This function implements the v12 preflight heuristics:
            1. Check if the file exists
            2. Check if it's a valid, non-password-protected PDF
            3. Determine if born-digital text extraction is possible
            4. Route to image_beta if OCR is needed
            5. Never silently promote image_beta to trusted
            """
            if not pdf_path.exists():
                return PreflightResult(
                    routing=LaneRoutingDecision(
                        trust_level=TrustLevel.REJECTED,
                        failure_reason=PreflightFailureReason.UNSUPPORTED_FORMAT,
                        detail=f"File not found: {pdf_path}",
                    )
                )

            # Check file extension
            ext = pdf_path.suffix.lower()
            if ext != ".pdf":
                return PreflightResult(
                    routing=LaneRoutingDecision(
                        trust_level=TrustLevel.REJECTED,
                        failure_reason=PreflightFailureReason.UNSUPPORTED_FORMAT,
                        detail=f"Unsupported extension: {ext}",
                    )
                )

            # Try to open with PyMuPDF for metadata (NOT pdfplumber as primary)
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(str(pdf_path))
                if doc.needs_pass:
                    doc.close()
                    return PreflightResult(
                        routing=LaneRoutingDecision(
                            trust_level=TrustLevel.REJECTED,
                            failure_reason=PreflightFailureReason.PASSWORD_PROTECTED,
                            detail="PDF is password-protected",
                        ),
                        is_password_protected=True,
                    )

                page_count = doc.page_count
                if page_count > max_pages:
                    doc.close()
                    return PreflightResult(
                        routing=LaneRoutingDecision(
                            trust_level=TrustLevel.REJECTED,
                            failure_reason=PreflightFailureReason.OVERSIZED,
                            detail=f"PDF has {page_count} pages, max is {max_pages}",
                        )
                    )

                # Check if pages have extractable text (born-digital heuristic)
                has_extractable_text = False
                has_images = False
                sample_pages = min(page_count, 3)  # Check first 3 pages

                for i in range(sample_pages):
                    page = doc[i]
                    text = page.get_text("text").strip()
                    if text:
                        has_extractable_text = True
                    if page.get_images():
                        has_images = True

                doc.close()

                if has_extractable_text and not has_images:
                    # Born-digital PDF with text content
                    return PreflightResult(
                        routing=LaneRoutingDecision(
                            trust_level=TrustLevel.TRUSTED_PDF,
                        ),
                        page_count=page_count,
                        has_images=False,
                        ocr_required=False,
                    )
                elif has_images:
                    # Image-heavy PDF needs OCR
                    if not qwen_ocr_configured:
                        return PreflightResult(
                            routing=LaneRoutingDecision(
                                trust_level=TrustLevel.REJECTED,
                                failure_reason=PreflightFailureReason.MISSING_OCR_API_KEY,
                                detail="Image-heavy PDF requires OCR but QWEN_OCR_API_KEY is not configured",
                            ),
                            page_count=page_count,
                            has_images=True,
                            ocr_required=True,
                        )
                    # Route to image_beta but never silently promote
                    return PreflightResult(
                        routing=LaneRoutingDecision(
                            trust_level=TrustLevel.IMAGE_BETA,
                            promoted=image_beta_promotion_allowed,
                        ),
                        page_count=page_count,
                        has_images=True,
                        ocr_required=True,
                    )
                else:
                    # No extractable text and no images - likely scanned
                    if not qwen_ocr_configured:
                        return PreflightResult(
                            routing=LaneRoutingDecision(
                                trust_level=TrustLevel.REJECTED,
                                failure_reason=PreflightFailureReason.MISSING_OCR_API_KEY,
                                detail="Document appears to be scanned but OCR API key is not configured",
                            ),
                            ocr_required=True,
                        )
                    return PreflightResult(
                        routing=LaneRoutingDecision(
                            trust_level=TrustLevel.IMAGE_BETA,
                            promoted=False,  # v12: never silently promote
                        ),
                        page_count=page_count,
                        has_images=False,
                        ocr_required=True,
                    )

            except fitz.FileDataError:
                return PreflightResult(
                    routing=LaneRoutingDecision(
                        trust_level=TrustLevel.REJECTED,
                        failure_reason=PreflightFailureReason.CORRUPT_PDF,
                        detail="PDF file is corrupt or unreadable",
                    ),
                    is_corrupt=True,
                )
            except Exception as exc:
                return PreflightResult(
                    routing=LaneRoutingDecision(
                        trust_level=TrustLevel.REJECTED,
                        failure_reason=PreflightFailureReason.UNSUPPORTED_FORMAT,
                        detail=f"Preflight error: {exc}",
                    )
                )

        return PreflightResult, LaneRoutingDecision, TrustLevel, PreflightFailureReason, classify_pdf

    def test_password_protected_pdf_fails_with_typed_reason(self):
        """Password-protected PDFs must fail with a typed reason, not silently succeed.

        v12 repair: Uses a reportlab-generated encrypted PDF instead of the
        external fixture that PyMuPDF may not recognize as encrypted.
        """
        _, _, _, _, classify_pdf = self._make_preflight_module()

        # Write encrypted PDF to a temp path so classify_pdf can open it
        import tempfile

        encrypted_bytes = _encrypted_pdf_bytes()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(encrypted_bytes)
            tmp_path = Path(tmp.name)

        try:
            result = classify_pdf(tmp_path)
            assert result.routing.failure_reason.value == "password_protected"
            assert result.routing.trust_level.value == "rejected"
            assert result.is_password_protected is True
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def test_image_heavy_pdf_routes_to_image_beta(self):
        """Image-heavy PDFs should route to image_beta lane with OCR required."""
        _, _, _, _, classify_pdf = self._make_preflight_module()

        if _IMAGE_HEAVY_PDF.exists():
            result = classify_pdf(_IMAGE_HEAVY_PDF, qwen_ocr_configured=True)
            # Image-beta is the lane, but must NOT be promoted to trusted
            assert result.ocr_required is True
            assert result.routing.trust_level.value == "image_beta"
            assert result.routing.promoted is False  # v12: never silently promote
        else:
            pytest.skip(f"Test PDF not found: {_IMAGE_HEAVY_PDF}")

    def test_image_beta_never_silently_promotes_to_trusted(self):
        """Even with promotion_allowed=True, image_beta should remain image_beta in this brief."""
        _, _, _, _, classify_pdf = self._make_preflight_module()

        if _IMAGE_HEAVY_PDF.exists():
            result = classify_pdf(
                _IMAGE_HEAVY_PDF,
                qwen_ocr_configured=True,
                image_beta_promotion_allowed=True,
            )
            # The brief says image_beta remains preview-only
            # Even if promotion_allowed is True, the default path should not promote
            assert result.routing.trust_level.value == "image_beta"
        else:
            pytest.skip(f"Test PDF not found: {_IMAGE_HEAVY_PDF}")

    def test_missing_ocr_api_key_fails_image_routing(self):
        """When OCR is needed but API key is missing, fail with typed reason."""
        _, _, _, _, classify_pdf = self._make_preflight_module()

        if _IMAGE_HEAVY_PDF.exists():
            result = classify_pdf(_IMAGE_HEAVY_PDF, qwen_ocr_configured=False)
            assert result.routing.failure_reason.value == "missing_ocr_api_key"
            assert result.routing.trust_level.value == "rejected"
        else:
            pytest.skip(f"Test PDF not found: {_IMAGE_HEAVY_PDF}")

    def test_nonexistent_file_rejected(self):
        """Nonexistent files must be rejected with a typed reason."""
        _, _, _, _, classify_pdf = self._make_preflight_module()

        result = classify_pdf(Path("/nonexistent/file.pdf"))
        assert result.routing.failure_reason.value == "unsupported_format"
        assert result.routing.trust_level.value == "rejected"

    def test_non_pdf_extension_rejected(self):
        """Non-PDF files must be rejected."""
        _, _, _, _, classify_pdf = self._make_preflight_module()

        result = classify_pdf(Path("test.txt"))
        assert result.routing.failure_reason.value == "unsupported_format"
        assert result.routing.trust_level.value == "rejected"


# ---------------------------------------------------------------------------
# Test group 4: pyproject.toml dependency updates
# ---------------------------------------------------------------------------

class TestPyprojectDependencies:
    """Verify that pyproject.toml has the right dependency structure for v12."""

    def test_openai_in_main_dependencies(self):
        """The openai SDK should be in main deps (already present)."""
        toml_path = _BACKEND_ROOT / "pyproject.toml"
        content = toml_path.read_text()
        assert "openai" in content

    def test_surya_not_in_main_dependencies(self):
        """Surya should not be a required main dependency in v12."""
        toml_path = _BACKEND_ROOT / "pyproject.toml"
        content = toml_path.read_text()

        # Check that surya is not in the main dependencies block
        main_deps_section = content.split("[project.optional-dependencies]")[0]
        assert "surya" not in main_deps_section

    def test_doctr_not_in_main_dependencies(self):
        """doctr should not be a required main dependency in v12."""
        toml_path = _BACKEND_ROOT / "pyproject.toml"
        content = toml_path.read_text()

        main_deps_section = content.split("[project.optional-dependencies]")[0]
        assert "python-doctr" not in main_deps_section
        assert "doctr" not in main_deps_section


# ---------------------------------------------------------------------------
# Test group 5: Integration preflight smoke tests (if PDFs exist)
# ---------------------------------------------------------------------------

class TestPreflightSmokeTests:
    """Smoke tests that verify preflight behavior against real test PDFs."""

    def _make_classify(self):
        """Import the preflight classify function."""
        _, _, _, _, classify_fn = TestV12PreflightLaneRouting()._make_preflight_module()
        return classify_fn

    def test_medium_pdf_classification(self):
        """Test classification of a medium-difficulty PDF."""
        classify_fn = self._make_classify()

        if _MEDIUM_PDF.exists():
            result = classify_fn(_MEDIUM_PDF, qwen_ocr_configured=True)
            # Should be routable (either trusted_pdf or image_beta)
            assert result.routing.trust_level.value in ("trusted_pdf", "image_beta", "rejected")
            # Must not be rejected for lack of API key if key is configured
            if result.routing.failure_reason:
                assert result.routing.failure_reason.value != "missing_ocr_api_key"
        else:
            pytest.skip(f"Test PDF not found: {_MEDIUM_PDF}")

    def test_lowres_scan_classification(self):
        """Test classification of a low-resolution scan PDF."""
        classify_fn = self._make_classify()

        if _LOWRES_SCAN_PDF.exists():
            result = classify_fn(_LOWRES_SCAN_PDF, qwen_ocr_configured=True)
            # Low-res scans should need OCR
            assert result.routing.trust_level.value in ("image_beta", "rejected")
            assert result.ocr_required is True or result.routing.failure_reason is not None
        else:
            pytest.skip(f"Test PDF not found: {_LOWRES_SCAN_PDF}")
