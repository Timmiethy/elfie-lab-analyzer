from __future__ import annotations

from pathlib import Path

from tests.support.ground_truth_runner import (
    expected_runtime_lane,
    infer_observed_terminal_state,
    load_ground_truth,
)

ROOT = Path(__file__).resolve().parents[3]
CORPUS_ROOT = ROOT / "pdfs_by_difficulty"


def _actual_pdf_files() -> list[str]:
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in CORPUS_ROOT.rglob("*.pdf")
    )


def test_phase_45_ground_truth_fixture_covers_every_pdf_once() -> None:
    dataset = load_ground_truth()
    files = sorted(entry.file for entry in dataset.entries)

    assert dataset.dataset == "pdfs_by_difficulty"
    assert dataset.version
    assert len(dataset.entries) == 39
    assert files == _actual_pdf_files()
    assert len(set(files)) == len(files)


def test_phase_45_lane_mapping_contract() -> None:
    dataset = load_ground_truth()
    by_file = {entry.file: entry for entry in dataset.entries}

    trusted = by_file["pdfs_by_difficulty/easy/seed_innoquest_dbticbm.pdf"]
    image = by_file["pdfs_by_difficulty/easy/seed_ulta_sample_alt.pdf"]
    unsupported = by_file["pdfs_by_difficulty/hard/var_singapore_mr_password_protected.pdf"]

    assert expected_runtime_lane(trusted) == "trusted_pdf"
    assert expected_runtime_lane(image) == "image_beta"
    assert expected_runtime_lane(unsupported) == "unsupported"


def test_phase_45_terminal_inference_prefers_route_class_for_non_lab() -> None:
    observed = infer_observed_terminal_state(
        preflight={
            "lane_type": "unsupported",
            "route_document_class": "non_lab_medical",
            "failure_code": None,
        },
        pipeline_result={"status": "partial"},
    )
    assert observed == "non_lab_medical_artifact"


def test_phase_45_terminal_inference_encrypted_pdf() -> None:
    observed = infer_observed_terminal_state(
        preflight={
            "lane_type": "unsupported",
            "route_document_class": "unsupported",
            "failure_code": "pdf_password_protected",
        },
        pipeline_result=None,
    )
    assert observed == "unsupported_encrypted_artifact"
