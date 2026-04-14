from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _resolve_loinc_path(cli_value: str | None, configured_loinc_path: Path) -> Path:
    if cli_value:
        return Path(cli_value).resolve()
    if (configured_loinc_path / "metadata.json").exists():
        return configured_loinc_path
    fallback = REPO_ROOT / "artifacts" / "dev-terminology"
    return fallback.resolve()


def _load_runtime_modules() -> dict[str, object]:
    from app.config import settings
    from app.services.input_gateway import InputGateway
    from app.terminology import TerminologyLoader
    from app.workers.pipeline import PipelineOrchestrator
    from tests.support.ground_truth_runner import (
        GroundTruthReport,
        build_checksum_expectation_index,
        load_ground_truth,
        load_pdf,
        validate_entry,
        write_ground_truth_report,
    )

    return {
        "settings": settings,
        "InputGateway": InputGateway,
        "TerminologyLoader": TerminologyLoader,
        "PipelineOrchestrator": PipelineOrchestrator,
        "GroundTruthReport": GroundTruthReport,
        "build_checksum_expectation_index": build_checksum_expectation_index,
        "load_ground_truth": load_ground_truth,
        "load_pdf": load_pdf,
        "validate_entry": validate_entry,
        "write_ground_truth_report": write_ground_truth_report,
    }


async def _run_ground_truth(*, enable_image_beta: bool, runtime: dict[str, object]) -> tuple[Path, dict]:
    gateway = runtime["InputGateway"]()
    pipeline = runtime["PipelineOrchestrator"]()
    report = runtime["GroundTruthReport"]()
    dataset = runtime["load_ground_truth"]()
    checksum_index = runtime["build_checksum_expectation_index"](dataset)
    load_pdf = runtime["load_pdf"]
    validate_entry = runtime["validate_entry"]
    write_report = runtime["write_ground_truth_report"]

    results = []

    for entry in dataset.entries:
        file_bytes = load_pdf(entry)
        filename = Path(entry.relative_pdf_path).name
        preflight = await gateway.preflight(file_bytes, filename, "application/pdf")

        lane_type = str(preflight.get("lane_type") or "unsupported")
        promotion_status = str(preflight.get("promotion_status") or "")
        pipeline_result = None

        run_pipeline = False
        if lane_type == "trusted_pdf":
            run_pipeline = True
        elif lane_type == "image_beta":
            run_pipeline = enable_image_beta and promotion_status == "beta_ready"
        elif lane_type == "unsupported":
            run_pipeline = promotion_status == "ready_unsupported"

        if run_pipeline:
            try:
                pipeline_result = await pipeline.run(
                    entry.relative_pdf_path,
                    file_bytes=file_bytes,
                    lane_type=lane_type,
                    source_checksum=preflight.get("checksum"),
                    source_filename=filename,
                    source_mime_type="application/pdf",
                    runtime_preflight=preflight,
                )
            except Exception as exc:  # noqa: BLE001
                pipeline_result = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "patient_artifact": {},
                }

        result = validate_entry(
            dataset=dataset,
            entry=entry,
            preflight=preflight,
            pipeline_result=pipeline_result,
            checksum_expectation=checksum_index.get(str(preflight.get("checksum") or "")),
        )

        if not run_pipeline and lane_type == "image_beta" and enable_image_beta:
            result.mismatches.append(
                "image_beta_not_executed: rerun with --enable-image-beta and configured Qwen OCR key"
            )

        if pipeline_result is not None and str(pipeline_result.get("status") or "") == "error":
            result.mismatches.append(f"pipeline_error: {pipeline_result.get('error')}")

        results.append(result)

    report.finalize(results)
    report_path = write_report(report)
    payload = report.to_dict()
    payload["report_path"] = str(report_path)
    payload["dataset"] = dataset.dataset
    payload["dataset_version"] = dataset.version
    payload["image_beta_enabled"] = bool(enable_image_beta)
    payload["failed_files"] = [
        item["file"]
        for item in payload["results"]
        if item.get("passed") is False
    ]
    return report_path, payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run hard ground-truth validation for pdfs_by_difficulty and emit "
            "a production-safety report with explicit mismatches."
        )
    )
    parser.add_argument(
        "--loinc-path",
        help=(
            "Override terminology snapshot path. Defaults to configured path, "
            "then artifacts/dev-terminology."
        ),
    )
    parser.add_argument(
        "--enable-image-beta",
        action="store_true",
        help=(
            "Execute image_beta files through OCR lane. Requires "
            "ELFIE_QWEN_OCR_API_KEY."
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print full report JSON to stdout.",
    )
    args = parser.parse_args()

    runtime = _load_runtime_modules()
    settings = runtime["settings"]

    loinc_path = _resolve_loinc_path(args.loinc_path, Path(settings.loinc_path))
    metadata_path = loinc_path / "metadata.json"
    if not metadata_path.exists():
        raise SystemExit(f"terminology metadata not found at {metadata_path}")

    settings.loinc_path = loinc_path
    settings.image_beta_enabled = bool(args.enable_image_beta)
    runtime["TerminologyLoader"]().load_loinc(str(loinc_path))

    _, payload = asyncio.run(
        _run_ground_truth(enable_image_beta=args.enable_image_beta, runtime=runtime)
    )

    if args.print_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        summary = {
            "report_path": payload["report_path"],
            "dataset": payload["dataset"],
            "dataset_version": payload["dataset_version"],
            "total_files": payload["total_files"],
            "passed": payload["passed"],
            "failed": payload["failed"],
            "failed_files": payload["failed_files"],
            "image_beta_enabled": payload["image_beta_enabled"],
        }
        print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
