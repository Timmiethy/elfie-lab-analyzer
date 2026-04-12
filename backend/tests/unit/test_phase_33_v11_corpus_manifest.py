from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORPUS_ROOT = ROOT / "pdfs_by_difficulty"
MANIFEST_PATH = ROOT / "backend" / "tests" / "fixtures" / "pdf_corpus_manifest.json"


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
