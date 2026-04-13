from __future__ import annotations

import json
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[3]
CORPUS_ROOT = ROOT / "pdfs_by_difficulty"
MANIFEST_PATH = ROOT / "backend" / "tests" / "fixtures" / "pdf_corpus_manifest.json"

# Ensure backend is on sys.path so we can import corpus_runner support modules
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def _actual_pdf_paths() -> list[str]:
    return sorted(
        path.relative_to(CORPUS_ROOT).as_posix()
        for path in CORPUS_ROOT.rglob("*.pdf")
    )


def test_phase_33_manifest_covers_every_pdf_once() -> None:
    manifest = _load_manifest()
    files = manifest["files"]
    pdf_entries = [entry for entry in files if entry["kind"] == "pdf"]
    metadata_entries = [entry for entry in files if entry["kind"] == "metadata"]
    manifest_pdf_paths = sorted(entry["path"] for entry in pdf_entries)

    assert len(pdf_entries) == 39
    assert len(metadata_entries) == 3
    assert manifest_pdf_paths == _actual_pdf_paths()
    assert len({entry["path"] for entry in pdf_entries}) == len(pdf_entries)
    assert {entry["path"] for entry in metadata_entries} == {
        "download_results.json",
        "download_summary.txt",
        "failed_downloads.csv",
    }

    required_keys = {"path", "difficulty", "kind", "family", "expected_lane", "expected_outcome"}
    for entry in pdf_entries:
        assert required_keys.issubset(entry)
        assert entry["difficulty"] in {"easy", "medium", "hard"}
        assert entry["expected_lane"] in {"trusted_pdf", "image_beta", "unsupported"}
        assert entry["expected_outcome"] in {"supported", "partial", "beta_supported", "unsupported"}


def test_phase_33_manifest_encodes_key_family_and_lane_expectations() -> None:
    manifest = _load_manifest()
    by_path = {entry["path"]: entry for entry in manifest["files"]}

    assert by_path["easy/seed_innoquest_dbticbm.pdf"]["family"] == "innoquest_bilingual_general"
    assert by_path["easy/seed_innoquest_dbticbm.pdf"]["expected_lane"] == "trusted_pdf"
    assert by_path["easy/seed_innoquest_dbticbm.pdf"]["expected_outcome"] == "supported"

    assert by_path["medium/seed_innoquest_dbticrp.pdf"]["family"] == "innoquest_bilingual_general"
    assert by_path["medium/seed_innoquest_dbticrp.pdf"]["expected_lane"] == "trusted_pdf"
    assert by_path["medium/seed_innoquest_dbticrp.pdf"]["expected_outcome"] == "supported"

    assert by_path["hard/var_hod_ultrasound_image_only_pdf.pdf"]["family"] == "hod_ultrasound"
    assert by_path["hard/var_hod_ultrasound_image_only_pdf.pdf"]["expected_lane"] == "image_beta"
    assert by_path["hard/var_hod_ultrasound_image_only_pdf.pdf"]["expected_outcome"] == "beta_supported"

    assert by_path["hard/var_singapore_mr_password_protected.pdf"]["family"] == "singapore_medical_report"
    assert by_path["hard/var_singapore_mr_password_protected.pdf"]["expected_lane"] == "unsupported"
    assert by_path["hard/var_singapore_mr_password_protected.pdf"]["expected_outcome"] == "unsupported"


# ---------------------------------------------------------------------------
# v12: corpus harness parser metadata tests
# ---------------------------------------------------------------------------


def test_phase_33_v12_runresult_carries_parser_metadata_fields() -> None:
    """v12: RunResult dataclass should carry parser_backend, parser_backend_version,
    and row_assembly_version fields."""
    from tests.support.corpus_runner import RunResult

    result = RunResult(
        path="test.pdf",
        difficulty="easy",
        family="test_family",
        expected_lane="trusted_pdf",
        expected_outcome="supported",
    )
    # Default values should be None
    assert result.parser_backend is None
    assert result.parser_backend_version is None
    assert result.row_assembly_version is None

    # Values should be settable
    result.parser_backend = "pymupdf"
    result.parser_backend_version = "pymupdf-1.27.x"
    result.row_assembly_version = "row-assembly-v2"
    assert result.parser_backend == "pymupdf"
    assert result.parser_backend_version == "pymupdf-1.27.x"
    assert result.row_assembly_version == "row-assembly-v2"


def test_phase_33_v12_runresult_to_report_includes_parser_metadata() -> None:
    """v12: RunResult.to_report() should include parser substrate metadata."""
    from tests.support.corpus_runner import RunResult

    result = RunResult(
        path="test.pdf",
        difficulty="easy",
        family="test_family",
        expected_lane="trusted_pdf",
        expected_outcome="supported",
        parser_backend="pymupdf",
        parser_backend_version="pymupdf-1.27.x",
        row_assembly_version="row-assembly-v2",
    )
    report = result.to_report()
    assert report["parser_backend"] == "pymupdf"
    assert report["parser_backend_version"] == "pymupdf-1.27.x"
    assert report["row_assembly_version"] == "row-assembly-v2"


def test_phase_33_v12_runresult_to_report_image_beta_parser_metadata() -> None:
    """v12: image_beta entries should also carry parser substrate metadata."""
    from tests.support.corpus_runner import RunResult

    result = RunResult(
        path="scan.pdf",
        difficulty="hard",
        family="hod_ultrasound",
        expected_lane="image_beta",
        expected_outcome="beta_supported",
        parser_backend="qwen_ocr",
        parser_backend_version="qwen-vl-ocr-2025-11-20",
        row_assembly_version="row-assembly-v2",
    )
    report = result.to_report()
    assert report["parser_backend"] == "qwen_ocr"
    assert report["parser_backend_version"] == "qwen-vl-ocr-2025-11-20"
    assert report["row_assembly_version"] == "row-assembly-v2"


def test_phase_33_v12_extract_parser_metadata_from_lineage() -> None:
    """v12: extract_v12_parser_metadata should read from lineage dict."""
    from tests.support.corpus_runner import extract_v12_parser_metadata

    pipeline_result = {
        "lineage": {
            "parser_backend": "pymupdf",
            "parser_backend_version": "pymupdf-1.27.x",
            "row_assembly_version": "row-assembly-v2",
        },
        "benchmark": {"metrics": {}},
    }
    meta = extract_v12_parser_metadata(pipeline_result, "trusted_pdf")
    assert meta["parser_backend"] == "pymupdf"
    assert meta["parser_backend_version"] == "pymupdf-1.27.x"
    assert meta["row_assembly_version"] == "row-assembly-v2"


def test_phase_33_v12_extract_parser_metadata_from_benchmark_metrics() -> None:
    """v12: extract_v12_parser_metadata should fall back to benchmark metrics."""
    from tests.support.corpus_runner import extract_v12_parser_metadata

    pipeline_result = {
        "lineage": {},
        "benchmark": {
            "metrics": {
                "parser_backend": "qwen_ocr",
                "parser_backend_version": "qwen-vl-ocr-2025-11-20",
                "row_assembly_version": "row-assembly-v2",
            }
        },
    }
    meta = extract_v12_parser_metadata(pipeline_result, "image_beta")
    assert meta["parser_backend"] == "qwen_ocr"
    assert meta["parser_backend_version"] == "qwen-vl-ocr-2025-11-20"
    assert meta["row_assembly_version"] == "row-assembly-v2"


def test_phase_33_v12_extract_parser_metadata_defaults_by_lane() -> None:
    """v12: extract_v12_parser_metadata should default to lane-level constants."""
    from tests.support.corpus_runner import extract_v12_parser_metadata

    pipeline_result = {"lineage": {}, "benchmark": {"metrics": {}}}

    trusted_meta = extract_v12_parser_metadata(pipeline_result, "trusted_pdf")
    assert trusted_meta["parser_backend"] == "pymupdf"
    assert trusted_meta["parser_backend_version"] == "pymupdf-1.27.x"
    assert trusted_meta["row_assembly_version"] == "row-assembly-v2"

    image_meta = extract_v12_parser_metadata(pipeline_result, "image_beta")
    assert image_meta["parser_backend"] == "qwen_ocr"
    assert image_meta["parser_backend_version"] == "qwen-vl-ocr-2025-11-20"
    assert image_meta["row_assembly_version"] == "row-assembly-v2"
