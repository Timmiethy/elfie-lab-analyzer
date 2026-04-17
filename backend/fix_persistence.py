import re

with open("tests/unit/test_phase_28_pipeline_refactor_guards.py", encoding="utf-8") as f:
    content = f.read()

# Replace TrustedPdfParser with process_image_with_qwen
content = re.sub(
    r"async def fake_parse\(self, file_bytes: bytes, \*, max_pages: int \| None = None\) -> list\[dict\]:\s+return \[_supported_row\(document_id=uuid4\(\)\)\]",
    "async def fake_parse(file_bytes: bytes) -> list[VLMRow]:\n        return [_qwen_row()]",
    content,
    flags=re.MULTILINE,
)

content = re.sub(
    r'monkeypatch\.setattr\("app\.workers\.pipeline\.TrustedPdfParser\.parse", fake_parse\)',
    'monkeypatch.setattr(pipeline_module, "process_image_with_qwen", fake_parse)',
    content,
)

with open("tests/unit/test_phase_28_pipeline_refactor_guards.py", "w", encoding="utf-8") as f:
    f.write(content)
