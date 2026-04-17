import pytest

from app.config import settings
from app.services.semantic_cleaner import SemanticCleaner

pytestmark = pytest.mark.asyncio


async def test_semantic_cleaner_deterministically_filters_admin_noise(monkeypatch) -> None:
    called = False

    async def fake_generate_text(prompt: str, response_format: dict | None = None) -> str:
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr("app.services.semantic_cleaner.generate_text_with_qwen", fake_generate_text)

    cleaner = SemanticCleaner()
    rows = [
        {
            "raw_text": "Creatinine 肌酸酐 88 umol/L (44-110)",
            "raw_analyte_label": "Creatinine 肌酸酐",
            "raw_value_string": "88",
            "raw_unit_string": "umol/L",
        },
        {
            "raw_text": "Ref : 14 JALAN 19/1 2ND FLR",
            "raw_analyte_label": "Ref :",
            "raw_value_string": "14",
            "raw_unit_string": "JALAN 19/1 2ND FLR",
        },
    ]

    cleaned = await cleaner.clean(rows)
    assert called is False
    assert len(cleaned) == 1
    assert cleaned[0]["raw_analyte_label"] == "creatinine"


async def test_semantic_cleaner_filters_noise_and_normalizes(monkeypatch) -> None:
    async def fake_generate_text(prompt: str, response_format: dict | None = None) -> str:
        # Mocking the JSON response from the LLM
        return """{
            "results": [
                {
                    "index": 0,
                    "is_valid_result": true,
                    "normalized_analyte_name": "Hemoglobin"
                },
                {
                    "index": 1,
                    "is_valid_result": false,
                    "normalized_analyte_name": null
                }
            ]
        }"""

    monkeypatch.setattr("app.services.semantic_cleaner.generate_text_with_qwen", fake_generate_text)
    monkeypatch.setattr(settings, "qwen_api_key", "test-key")

    cleaner = SemanticCleaner()
    rows = [
        {
            "raw_text": "Hb 12.0 g/dL",
            "raw_analyte_label": "Hb",
            "raw_value_string": "12.0",
            "raw_unit_string": "g/dL",
        },
        {
            "raw_text": "CITY, ST ZIP 12345",
            "raw_analyte_label": "CITY",
            "raw_value_string": "",
            "raw_unit_string": "",
        },
    ]

    cleaned = await cleaner.clean(rows)
    assert len(cleaned) == 1
    assert cleaned[0]["raw_analyte_label"] == "hemoglobin"
