from __future__ import annotations

import json
from pathlib import Path
import asyncio

import pytest

from app.config import settings
from app.main import create_app
from app.terminology import TerminologyLoader
from app.workers.pipeline import PipelineOrchestrator


def _write_snapshot(path: Path, *, release: str = "loinc-2026.04") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "metadata.json").write_text(
        json.dumps(
            {
                "release": release,
                "checksum": "sha256:test-terminology-snapshot",
            }
        ),
        encoding="utf-8",
    )


def test_phase_26_terminology_loader_reads_snapshot_metadata(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "loinc"
    _write_snapshot(snapshot_path)

    loaded = TerminologyLoader().load_loinc(str(snapshot_path))

    assert loaded["release"] == "loinc-2026.04"
    assert loaded["checksum"] == "sha256:test-terminology-snapshot"


def test_phase_26_create_app_fails_fast_when_snapshot_is_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "loinc_path", tmp_path / "missing-loinc")

    with pytest.raises(RuntimeError, match="terminology"):
        create_app()


def test_phase_26_create_app_accepts_valid_snapshot(monkeypatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "loinc"
    _write_snapshot(snapshot_path, release="loinc-2026.05")
    monkeypatch.setattr(settings, "loinc_path", snapshot_path)

    app = create_app()

    assert app.title == "Elfie Labs Analyzer"


def test_phase_26_pipeline_lineage_uses_loaded_terminology_release(
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "loinc"
    _write_snapshot(snapshot_path, release="loinc-2026.05")
    monkeypatch.setattr(settings, "loinc_path", snapshot_path)
    TerminologyLoader().load_loinc(str(snapshot_path))

    result = asyncio.run(
        PipelineOrchestrator().run(
            "phase-26-lineage-terminology",
            file_bytes=None,
            lane_type="trusted_pdf",
            source_checksum="sha256:phase-26-terminology",
        )
    )

    assert result["lineage"]["terminology_release"] == "loinc-2026.05"
