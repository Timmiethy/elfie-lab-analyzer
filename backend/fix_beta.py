import re

with open("tests/unit/test_phase_28_pipeline_refactor_guards.py", encoding="utf-8") as f:
    content = f.read()

# Add image_beta_enabled setting patch to first beta test
if (
    'monkeypatch.setattr(settings, "image_beta_enabled", True)'
    not in content.split("test_phase_28_image_beta_lane_keeps_beta_render_and_lineage_contracts")[
        1
    ].split("test_phase_28_image_beta_lane")[0]
):
    content = re.sub(
        r"def test_phase_28_image_beta_lane_keeps_beta_render_and_lineage_contracts\(monkeypatch\) -> None:",
        'def test_phase_28_image_beta_lane_keeps_beta_render_and_lineage_contracts(monkeypatch) -> None:\n    monkeypatch.setattr(settings, "image_beta_enabled", True)',
        content,
    )

with open("tests/unit/test_phase_28_pipeline_refactor_guards.py", "w", encoding="utf-8") as f:
    f.write(content)
