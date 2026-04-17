with open("tests/unit/test_phase_27_structured_import.py", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'artifact.support_banner.value == "partially_supported"',
    'artifact.support_banner.value == "fully_supported"',
)

with open("tests/unit/test_phase_27_structured_import.py", "w", encoding="utf-8") as f:
    f.write(content)
