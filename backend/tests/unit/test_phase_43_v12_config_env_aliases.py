"""Phase 43: v12 config env-alias tests for qwen_ocr_api_base.

Verifies that Settings accepts both ELFIE_QWEN_OCR_API_BASE (canonical)
and ELFIE_QWEN_OCR_BASE_URL (legacy) environment variable names, with
the canonical name taking precedence when both are present.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_BACKEND_PY = Path(__file__).resolve().parents[3]
_BACKEND = _BACKEND_PY
if str(_BACKEND) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_BACKEND))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(*, _env_file: str | None, monkeypatch: pytest.MonkeyPatch) -> "Settings":
    """Build a Settings instance with isolated env and no .env file."""
    monkeypatch.delenv("ELFIE_QWEN_OCR_API_BASE", raising=False)
    monkeypatch.delenv("ELFIE_QWEN_OCR_BASE_URL", raising=False)
    from app.config import Settings
    return Settings(_env_file=_env_file)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_phase_43_default_value() -> None:
    """qwen_ocr_api_base should default to the canonical DashScope URL."""
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.qwen_ocr_api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_phase_43_legacy_env_var_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings should accept ELFIE_QWEN_OCR_BASE_URL without raising."""
    monkeypatch.setenv("ELFIE_QWEN_OCR_BASE_URL", "https://legacy.example.com/v1")
    monkeypatch.delenv("ELFIE_QWEN_OCR_API_BASE", raising=False)
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.qwen_ocr_api_base == "https://legacy.example.com/v1"


def test_phase_43_canonical_env_var_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings should accept ELFIE_QWEN_OCR_API_BASE without raising."""
    monkeypatch.setenv("ELFIE_QWEN_OCR_API_BASE", "https://canonical.example.com/v1")
    monkeypatch.delenv("ELFIE_QWEN_OCR_BASE_URL", raising=False)
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.qwen_ocr_api_base == "https://canonical.example.com/v1"


def test_phase_43_canonical_wins_when_both_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """When both env vars are set, the canonical name takes precedence."""
    monkeypatch.setenv("ELFIE_QWEN_OCR_BASE_URL", "https://legacy.example.com/v1")
    monkeypatch.setenv("ELFIE_QWEN_OCR_API_BASE", "https://canonical.example.com/v1")
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.qwen_ocr_api_base == "https://canonical.example.com/v1"


def test_phase_43_internal_field_name_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The internal Settings attribute must remain qwen_ocr_api_base."""
    from app.config import Settings
    s = Settings(_env_file=None)
    # The field must exist and be accessible by its canonical name
    assert hasattr(s, "qwen_ocr_api_base")
    # Ensure no stale alternative attribute leaked
    assert not hasattr(s, "qwen_ocr_base_url")
