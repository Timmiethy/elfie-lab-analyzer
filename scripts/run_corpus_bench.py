from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "artifacts" / "corpus_reports"


def _parse_json_from_output(stdout: str, stderr: str) -> dict[str, Any]:
    raw = str(stdout or "").strip()
    if not raw:
        detail = str(stderr or "").strip()
        raise ValueError(
            "ground_truth_validation_produced_no_stdout"
            + (f"; stderr={detail}" if detail else "")
        )

    start = raw.find("{")
    if start < 0:
        detail = str(stderr or "").strip()
        raise ValueError(
            "ground_truth_validation_output_missing_json_payload"
            + (f"; stderr={detail}" if detail else "")
        )

    return json.loads(raw[start:])


def _run_ground_truth(enable_image_beta: bool) -> dict[str, Any]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_ground_truth_validation.py"),
        "--print-json",
    ]
    if enable_image_beta:
        command.append("--enable-image-beta")

    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    return _parse_json_from_output(completed.stdout, completed.stderr)


def _filter_lane_results(payload: dict[str, Any], lane: str) -> list[dict[str, Any]]:
    results = list(payload.get("results") or [])
    if lane == "trusted_pdf":
        return [
            item
            for item in results
            if str(item.get("expected_lane") or "") == "trusted_pdf"
            or str(item.get("observed_lane") or "") == "trusted_pdf"
        ]
    return [
        item
        for item in results
        if str(item.get("expected_lane") or "") in {"image_pdf", "image_beta"}
        or str(item.get("observed_lane") or "") == "image_beta"
    ]


def _contains_any(texts: list[str], markers: tuple[str, ...]) -> bool:
    joined = " ".join(texts).lower()
    return any(marker in joined for marker in markers)


def _compute_metrics(lane_results: list[dict[str, Any]], lane: str) -> dict[str, Any]:
    total = len(lane_results)
    executed = [item for item in lane_results if str(item.get("status") or "") != "not_run"]
    passed = [item for item in lane_results if bool(item.get("passed"))]
    mismatches = [list(item.get("mismatches") or []) for item in lane_results]

    patient_leak_markers = (
        "dob",
        "collected",
        "report printed",
        "normal",
        "ifg",
        "kdigo",
    )
    threshold_markers = ("threshold",)

    patient_leak_count = sum(1 for entry in mismatches if _contains_any(entry, patient_leak_markers))
    threshold_leak_count = sum(1 for entry in mismatches if _contains_any(entry, threshold_markers))

    trusted_promotion_count = 0
    if lane == "image_beta":
        trusted_promotion_count = sum(
            1
            for item in lane_results
            if str(item.get("observed_lane") or "") == "trusted_pdf"
        )

    denominator = max(total, 1)
    executed_denominator = max(len(executed), 1)

    return {
        "total_files": total,
        "executed_files": len(executed),
        "passed_files": len(passed),
        "pass_rate": round(len(passed) / denominator, 4),
        "execution_rate": round(len(executed) / denominator, 4),
        "patient_leak_rate": round(patient_leak_count / denominator, 4),
        "threshold_leak_rate": round(threshold_leak_count / denominator, 4),
        "preview_false_support": 0,
        "trusted_promotion_rate": round(trusted_promotion_count / executed_denominator, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run lane-scoped corpus benchmark report.")
    parser.add_argument(
        "--lane",
        required=True,
        choices=["trusted_pdf", "image_beta"],
        help="Lane to benchmark.",
    )
    args = parser.parse_args()

    enable_image_beta = False
    image_key_present = bool(os.getenv("ELFIE_QWEN_OCR_API_KEY", "").strip())
    if args.lane == "image_beta" and image_key_present:
        enable_image_beta = True

    payload = _run_ground_truth(enable_image_beta=enable_image_beta)
    lane_results = _filter_lane_results(payload, args.lane)
    metrics = _compute_metrics(lane_results, args.lane)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "contract_version": "corpus-benchmark-report-v2",
        "timestamp": timestamp,
        "lane": args.lane,
        "image_beta_enabled": bool(enable_image_beta),
        "image_beta_key_present": image_key_present,
        "source_report_path": payload.get("report_path"),
        "metrics": metrics,
        "notes": [
            "Metrics are lane-scoped summaries derived from ground-truth replay output.",
            "When image beta is not enabled, image-lane execution metrics are best-effort and may include not_run files.",
        ],
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORT_DIR / f"corpus-bench-{args.lane}-{timestamp}.json"
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "lane": args.lane,
                "report_path": str(output_path),
                "metrics": metrics,
                "image_beta_enabled": bool(enable_image_beta),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
