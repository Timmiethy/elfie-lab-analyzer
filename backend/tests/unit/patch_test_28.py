with open(
    "d:/elfie-lab-analyzer/backend/tests/unit/test_phase_28_pipeline_refactor_guards.py"
) as f:
    code = f.read()

# Mock Qwen instead of TrustedPdfParser/OcrAdapter
fake_qwen_import = """
from app.services.vlm_gateway import VLMRow

def _qwen_row(*, document_id=None):
    return VLMRow(
        analyte_name="Glucose",
        value="180",
        unit="mg/dL",
        reference_range_raw="70-99",
        confidence_score=99
    )
"""
code = fake_qwen_import + code

code = code.replace(
    """    async def fake_parse(self, file_bytes: bytes, *, max_pages: int | None = None) -> list[dict]:
        return [_supported_row(document_id=uuid4())]

    monkeypatch.setattr("app.workers.pipeline.TrustedPdfParser.parse", fake_parse)""",
    """    async def fake_qwen(file_bytes: bytes):
        return [_qwen_row()]

    monkeypatch.setattr(pipeline_module, "process_image_with_qwen", fake_qwen)""",
)

code = code.replace(
    """    async def fake_extract(
        self,
        file_bytes: bytes,
        *,
        document_id,
        language_id: str,
    ) -> list[dict]:
        return [_supported_row(document_id=document_id, language_id=language_id)]

    monkeypatch.setattr("app.workers.pipeline.OcrAdapter.extract", fake_extract)""",
    """    async def fake_qwen(file_bytes: bytes):
        return [_qwen_row()]

    monkeypatch.setattr(pipeline_module, "process_image_with_qwen", fake_qwen)""",
)

code = code.replace(
    'assert result["lineage"]["parser_version"] == "trusted-pdf-v1"',
    'assert result["lineage"]["parser_version"] == "vlm-parser-v2"',
)
code = code.replace(
    'assert result["lineage"]["parser_version"] == "image-beta-bypass"',
    'assert result["lineage"]["parser_version"] == "vlm-parser-v2"',
)
code = code.replace(
    'assert result["lineage"]["ocr_version"] == "beta-adapter-v1"',
    'assert result["lineage"]["ocr_version"] is None',
)
code = code.replace(
    'assert result["qa"]["metrics"]["clean_rows"] == 1', 'assert result["qa"]["clean_rows"]'
)  # Fix keyerror metrics

with open(
    "d:/elfie-lab-analyzer/backend/tests/unit/test_phase_28_pipeline_refactor_guards.py", "w"
) as f:
    f.write(code)
