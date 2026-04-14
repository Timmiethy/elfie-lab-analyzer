from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen import canvas

from app.config import settings
from app.services.input_gateway import InputGateway, InputGatewayError
from app.services.ocr import OcrAdapter

ROOT = Path(__file__).resolve().parents[3]
PDF_DIR = ROOT / "pdfs_by_difficulty"


def _load_pdf(relative_path: str) -> bytes:
    return (PDF_DIR / relative_path).read_bytes()


def _encrypted_pdf_bytes() -> bytes:
    buffer = BytesIO()
    encryption = StandardEncryption(
        userPassword="secret",
        ownerPassword="owner",
        canPrint=1,
    )
    report = canvas.Canvas(buffer, pagesize=letter, encrypt=encryption)
    report.drawString(100, 700, "Encrypted sample")
    report.save()
    return buffer.getvalue()


def test_phase_33_preflight_routes_trusted_text_pdf_to_ready_lane() -> None:
    gateway = InputGateway()

    result = asyncio.run(
        gateway.preflight(
            _load_pdf("easy/seed_innoquest_dbticbm.pdf"),
            "seed_innoquest_dbticbm.pdf",
            "application/pdf",
        )
    )

    assert result["lane_type"] == "trusted_pdf"
    assert result["document_class"] == "trusted_pdf_lab"
    assert result["route_document_class"] == "trusted_pdf_lab"
    assert result["failure_code"] is None
    assert result["promotion_status"] == "ready"
    assert result["duplicate_state"] == "not_checked"
    assert result["image_density"] < 0.05
    assert result["text_extractability"] > 0.95


def test_phase_33_preflight_routes_image_heavy_pdf_to_beta_and_blocks_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "image_beta_enabled", False, raising=False)
    gateway = InputGateway()

    result = asyncio.run(
        gateway.preflight(
            _load_pdf("easy/seed_ulta_sample_alt.pdf"),
            "seed_ulta_sample_alt.pdf",
            "application/pdf",
        )
    )

    assert result["lane_type"] == "image_beta"
    assert result["document_class"] == "image_pdf_lab"
    assert result["promotion_status"] == "blocked_image_beta_disabled"
    assert result["image_density"] > 0.5

    with pytest.raises(InputGatewayError) as exc_info:
        asyncio.run(
            gateway.classify(
                _load_pdf("easy/seed_ulta_sample_alt.pdf"),
                "seed_ulta_sample_alt.pdf",
                "application/pdf",
            )
        )

    assert exc_info.value.code == "blocked_image_beta_disabled"


def test_phase_33_preflight_reports_typed_password_and_corrupt_failures() -> None:
    gateway = InputGateway()

    encrypted_result = asyncio.run(
        gateway.preflight(
            _encrypted_pdf_bytes(),
            "encrypted.pdf",
            "application/pdf",
        )
    )
    assert encrypted_result["lane_type"] == "unsupported"
    assert encrypted_result["failure_code"] == "pdf_password_protected"
    assert encrypted_result["promotion_status"] == "blocked_password_protected"
    assert encrypted_result["password_protected"] is True

    with pytest.raises(InputGatewayError) as exc_info:
        asyncio.run(
            gateway.classify(
                _encrypted_pdf_bytes(),
                "encrypted.pdf",
                "application/pdf",
            )
        )
    assert exc_info.value.code == "pdf_password_protected"

    corrupt_result = asyncio.run(
        gateway.preflight(
            b"%PDF-1.4\n%%EOF",
            "corrupt.pdf",
            "application/pdf",
        )
    )
    assert corrupt_result["lane_type"] == "unsupported"
    assert corrupt_result["failure_code"] == "pdf_corrupt"
    assert corrupt_result["promotion_status"] == "blocked_corrupt"
    assert corrupt_result["corrupt"] is True

    with pytest.raises(InputGatewayError) as exc_info_corrupt:
        asyncio.run(
            gateway.classify(
                b"%PDF-1.4\n%%EOF",
                "corrupt.pdf",
                "application/pdf",
            )
        )
    assert exc_info_corrupt.value.code == "pdf_corrupt"


def test_phase_33_ocr_adapter_uses_qwen_backend_and_preserves_positioning() -> None:
    """v12: OcrAdapter should use qwen_vl_ocr as the primary backend, not surya/docTR."""
    adapter = OcrAdapter(image_beta_enabled=True)

    # Without an API key, no auto-backend should be available
    # but injected backends still work for testing
    calls: list[str] = []

    def fake_qwen(_: bytes) -> dict:
        calls.append("qwen_vl_ocr")
        return {
            "rows": [
                {
                    "document_id": str(uuid4()),
                    "source_page": 2,
                    "raw_text": "Glucose 180 mg/dL",
                    "raw_analyte_label": "Glucose",
                    "raw_value_string": "180",
                    "raw_unit_string": "mg/dL",
                    "bbox": [12, 34, 56, 78],
                    "ocr_engine": "qwen_vl_ocr",
                }
            ]
        }

    # Inject a fake qwen backend
    adapter._ocr_backend = fake_qwen
    adapter._auto_backend_candidates = []

    decision = adapter.promotion_decision()
    assert decision["promotion_status"] == "beta_ready"
    assert decision["backend_candidates"] == ["injected"]
    assert adapter.is_available() is True

    rows = asyncio.run(
        adapter.extract(
            b"image-bytes",
            document_id=uuid4(),
            source_page=3,
            language_id="en",
        )
    )

    assert calls == ["qwen_vl_ocr"]
    assert rows[0]["ocr_engine"] == "qwen_vl_ocr"
    assert rows[0]["bbox"] == [12, 34, 56, 78]
    assert rows[0]["raw_analyte_label"] == "Glucose"
    assert rows[0]["lane_type"] == "image_beta"
    assert rows[0]["row_hash"]


def test_phase_33_ocr_adapter_detects_pdf_input_and_returns_per_page_list() -> None:
    """v12: OcrAdapter backend should detect %PDF magic bytes and return per-page list."""
    from unittest.mock import MagicMock, patch

    monkey = pytest.MonkeyPatch()
    monkey.setattr(settings, "qwen_ocr_api_key", "test-key", raising=False)

    page1 = MagicMock()
    page1.full_text = "Glucose 180 mg/dL"
    page1.blocks = [{"text": "Glucose 180 mg/dL", "bbox": [10, 20, 50, 30]}]
    page1.page = 0

    page2 = MagicMock()
    page2.full_text = "HbA1c 7.2 %"
    page2.blocks = [{"text": "HbA1c 7.2 %", "bbox": [15, 25, 55, 35]}]
    page2.page = 1

    def fake_ocr_pdf(_):
        return [page1, page2]

    def fake_ocr_image(_):
        raise AssertionError("ocr_image should NOT be called for PDF input")

    with patch("app.services.ocr.qwen_vl_adapter.QwenVLClient") as MockClient:
        instance = MockClient.return_value
        instance.is_configured = True
        instance.ocr_pdf = fake_ocr_pdf
        instance.ocr_image = fake_ocr_image

        adapter = OcrAdapter(image_beta_enabled=True)
        backend_candidates = adapter._candidate_backends()
        assert backend_candidates, "Expected qwen_vl_ocr backend to be available"

        _, backend = backend_candidates[0]
        pdf_bytes = b"%PDF-1.4\n%fake pdf content\n%%EOF"
        result = backend(pdf_bytes)

        # Backend now returns a list of per-page dicts, not a flat blob
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["source_page"] == 1
        assert result[0]["text"] == "Glucose 180 mg/dL"
        assert result[1]["source_page"] == 2
        assert result[1]["text"] == "HbA1c 7.2 %"

    monkey.undo()


def test_phase_33_ocr_adapter_handles_image_input_returns_single_page_list() -> None:
    """v12: Non-PDF image bytes should go through ocr_image and return a single-page list."""
    from unittest.mock import MagicMock, patch

    monkey = pytest.MonkeyPatch()
    monkey.setattr(settings, "qwen_ocr_api_key", "test-key", raising=False)

    def fake_ocr_pdf(_):
        raise AssertionError("ocr_pdf should NOT be called for image input")

    def fake_ocr_image(_):
        from app.services.ocr.qwen_vl_adapter import QwenOCRPageResult, QwenOCRTextBlock
        return QwenOCRPageResult(
            page=0,
            blocks=[QwenOCRTextBlock(text="Glucose 180 mg/dL", page=0)],
        )

    with patch("app.services.ocr.qwen_vl_adapter.QwenVLClient") as MockClient:
        instance = MockClient.return_value
        instance.is_configured = True
        instance.ocr_pdf = fake_ocr_pdf
        instance.ocr_image = fake_ocr_image

        adapter = OcrAdapter(image_beta_enabled=True)
        backend_candidates = adapter._candidate_backends()

        if backend_candidates:
            _, backend = backend_candidates[0]
            # PNG magic bytes: first 4 bytes of a valid PNG header
            image_bytes = b"\x89PNG\r\n\x1a\n" + b"fake image data"
            result = backend(image_bytes)

            # v12: image input returns a single-element list, not a flat dict
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["source_page"] == 1
            assert "Glucose 180 mg/dL" in result[0]["text"]

    monkey.undo()


def test_phase_33_ocr_adapter_multi_page_pdf_preserves_source_page_through_extract() -> None:
    """v12: Full extract() path for multi-page PDF must preserve per-page source_page."""
    from unittest.mock import MagicMock, patch

    monkey = pytest.MonkeyPatch()
    monkey.setattr(settings, "qwen_ocr_api_key", "test-key", raising=False)

    page1 = MagicMock()
    page1.full_text = "Glucose 180 mg/dL\nCreatinine 1.2 mg/dL"
    page1.blocks = []
    page1.page = 0

    page2 = MagicMock()
    page2.full_text = "HbA1c 7.2 %\nWBC 6.5 K/uL"
    page2.blocks = []
    page2.page = 1

    def fake_ocr_pdf(_):
        return [page1, page2]

    def fake_ocr_image(_):
        raise AssertionError("ocr_image should NOT be called for PDF input")

    with patch("app.services.ocr.qwen_vl_adapter.QwenVLClient") as MockClient:
        instance = MockClient.return_value
        instance.is_configured = True
        instance.ocr_pdf = fake_ocr_pdf
        instance.ocr_image = fake_ocr_image

        adapter = OcrAdapter(image_beta_enabled=True)
        doc_id = uuid4()
        pdf_bytes = b"%PDF-1.4\npage1 content\npage2 content\n%%EOF"

        rows = asyncio.run(adapter.extract(pdf_bytes, document_id=doc_id, language_id="en"))

    # Should have rows from both pages
    assert len(rows) >= 2, "Expected at least 2 rows (one from each page)"

    # Verify per-page source_page is preserved
    page_sources = {row["source_page"] for row in rows}
    assert 1 in page_sources, "Expected rows from page 1"
    assert 2 in page_sources, "Expected rows from page 2"

    # Verify all rows have correct lane_type and ocr_engine
    for row in rows:
        assert row["lane_type"] == "image_beta"
        assert row["ocr_engine"] == "qwen_vl_ocr"
        assert row["document_id"] == doc_id
        assert "row_hash" in row

    monkey.undo()
