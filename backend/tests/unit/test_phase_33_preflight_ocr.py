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
    assert result["document_class"] == "text_pdf"
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
            _load_pdf("hard/var_hod_ultrasound_image_only_pdf.pdf"),
            "var_hod_ultrasound_image_only_pdf.pdf",
            "application/pdf",
        )
    )

    assert result["lane_type"] == "image_beta"
    assert result["document_class"] in {"mixed_pdf", "image_pdf"}
    assert result["promotion_status"] == "blocked_image_beta_disabled"
    assert result["image_density"] > 0.5

    with pytest.raises(InputGatewayError) as exc_info:
        asyncio.run(
            gateway.classify(
                _load_pdf("hard/var_hod_ultrasound_image_only_pdf.pdf"),
                "var_hod_ultrasound_image_only_pdf.pdf",
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


def test_phase_33_ocr_adapter_prefers_surya_then_doctr_and_preserves_positioning() -> None:
    adapter = OcrAdapter(image_beta_enabled=True)
    calls: list[str] = []

    def fake_surya(_: bytes) -> dict:
        calls.append("surya")
        raise RuntimeError("surya failed")

    def fake_doctr(_: bytes) -> dict:
        calls.append("doctr")
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
                    "ocr_engine": "doctr-layout",
                }
            ]
        }

    adapter._auto_backend_candidates = [("surya", fake_surya), ("doctr", fake_doctr)]

    decision = adapter.promotion_decision()
    assert decision["promotion_status"] == "beta_ready"
    assert decision["backend_candidates"] == ["surya", "doctr"]
    assert adapter.is_available() is True

    rows = asyncio.run(
        adapter.extract(
            b"image-bytes",
            document_id=uuid4(),
            source_page=3,
            language_id="en",
        )
    )

    assert calls == ["surya", "doctr"]
    assert rows[0]["ocr_engine"] == "doctr-layout"
    assert rows[0]["bbox"] == [12, 34, 56, 78]
    assert rows[0]["raw_analyte_label"] == "Glucose"
    assert rows[0]["lane_type"] == "image_beta"
    assert rows[0]["row_hash"]
