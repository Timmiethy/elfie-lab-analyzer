import glob

patch_count = 0
for path in glob.glob("tests/unit/test_*.py"):
    with open(path, encoding="utf-8") as f:
        content = f.read()

    old_str = 'monkeypatch.setattr(pipeline_module, "process_image_with_qwen"'
    new_str = 'monkeypatch.setattr("app.services.mineru_adapter.process_image_with_qwen"'

    if old_str in content:
        content = content.replace(old_str, new_str)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Patched {path}")
        patch_count += 1
print(f"Total patched: {patch_count}")
