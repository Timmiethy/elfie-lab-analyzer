import glob

for path in glob.glob("tests/unit/test_*.py"):
    with open(path, encoding="utf-8") as f:
        content = f.read()

    new_content = content.replace(
        '"app.workers.pipeline.process_image_with_qwen"',
        '"app.services.mineru_adapter.process_image_with_qwen"',
    )
    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Patched {path}")
