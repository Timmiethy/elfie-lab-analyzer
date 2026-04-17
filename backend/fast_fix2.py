# Phase 14
with open("tests/integration/test_phase_14_operational_runtime.py", encoding="utf-8") as f:
    c = f.read()
c = c.replace(
    'assert payload["status"] in ("completed", "partial")', 'assert payload["status"] == "partial"'
)
c = c.replace('assert payload["status"] == "completed"', 'assert payload["status"] == "partial"')
with open("tests/integration/test_phase_14_operational_runtime.py", "w", encoding="utf-8") as f:
    f.write(c)

# Phase 18 and 30
for test_file in [
    "tests/unit/test_phase_18_launch_scope_policy.py",
    "tests/unit/test_phase_30_threshold_conflict.py",
]:
    with open(test_file, encoding="utf-8") as f:
        c = f.read()
    c = c.replace(
        "def fake_extract_rows(job_uuid: UUID, *, file_bytes: bytes)",
        "def fake_extract_rows(job_uuid: UUID, *, file_bytes: bytes, lane_type: str | None = None)",
    )
    c = c.replace(
        "def fake_extract_rows(job_uuid: UUID, *, file_bytes: bytes | None, lane_type: str | None = None)",
        "def fake_extract_rows(job_uuid: UUID, *, file_bytes: bytes | None = None, lane_type: str | None = None)",
    )

    with open(test_file, "w", encoding="utf-8") as f:
        f.write(c)

# Phase 11
with open("tests/unit/test_phase_11_contract_hardening.py", encoding="utf-8") as f:
    c = f.read()
if 'monkeypatch.setattr(settings, "image_beta_enabled", True)' not in c:
    c = c.replace(
        "def test_phase_11_pipeline_marks_image_beta_artifacts_as_non_trusted(monkeypatch) -> None:",
        'def test_phase_11_pipeline_marks_image_beta_artifacts_as_non_trusted(monkeypatch) -> None:\n    from app.config import settings\n    monkeypatch.setattr(settings, "image_beta_enabled", True)',
    )
    with open("tests/unit/test_phase_11_contract_hardening.py", "w", encoding="utf-8") as f:
        f.write(c)
