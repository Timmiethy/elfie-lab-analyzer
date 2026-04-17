from __future__ import annotations

import pytest

from app.services.mineru_adapter import MineruAdapter
from app.services.vlm_gateway import VLMRow


def test_mineru_adapter_initializes_with_auto_mode_by_default() -> None:
    adapter = MineruAdapter()
    assert adapter.mode == "auto"


@pytest.mark.asyncio
async def test_mineru_adapter_executes_txt_mode_correctly(monkeypatch) -> None:
    async def fake_qwen(*args, **kwargs):
        return [
            VLMRow(analyte_name="Glucose", value="90", unit="mg/dL", reference_range_raw="70-99")
        ]

    monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen", fake_qwen)

    adapter = MineruAdapter(mode="txt")
    result = await adapter.execute(b"%PDF-1.4 dummy contents")

    assert result["mode"] == "txt"
    assert result["status"] == "success"
    assert "content" in result


@pytest.mark.asyncio
async def test_mineru_adapter_executes_ocr_mode_correctly(monkeypatch) -> None:
    async def fake_qwen(*args, **kwargs):
        return [
            VLMRow(analyte_name="Glucose", value="90", unit="mg/dL", reference_range_raw="70-99")
        ]

    monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen", fake_qwen)

    adapter = MineruAdapter(mode="ocr")
    result = await adapter.execute(b"%PDF-1.4 dummy contents")

    assert result["mode"] == "ocr"
    assert result["status"] == "success"
    assert "content" in result
