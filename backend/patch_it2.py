with open("tests/unit/test_phase_28_pipeline_refactor_guards.py") as f:
    content = f.read()

content = content.replace(
    'monkeypatch.setattr(pipeline_module, "process_image_with_qwen"',
    'monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen"',
)

with open("tests/unit/test_phase_28_pipeline_refactor_guards.py", "w") as f:
    f.write(content)
