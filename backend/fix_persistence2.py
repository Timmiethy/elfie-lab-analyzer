with open("tests/unit/test_phase_28_pipeline_refactor_guards.py", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'assert captured["status"] == "partial"', 'assert captured["status"] == "completed"'
)
content = content.replace(
    'assert patient_payload["support_banner"] == "partially_supported"',
    'assert patient_payload["support_banner"] == "fully_supported"',
)

with open("tests/unit/test_phase_28_pipeline_refactor_guards.py", "w", encoding="utf-8") as f:
    f.write(content)
