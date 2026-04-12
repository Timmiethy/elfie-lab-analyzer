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


def _load_runtime_modules():
    from app.config import settings
    from app.services.input_gateway import InputGateway
    from app.terminology import TerminologyLoader
    from app.workers.pipeline import PipelineOrchestrator
    from tests.support.corpus_runner import (
        CorpusReport,
        RunResult,
        load_manifest,
        load_pdf,
        write_corpus_report,
    )

    return {
        "settings": settings,
        "InputGateway": InputGateway,
        "TerminologyLoader": TerminologyLoader,
        "PipelineOrchestrator": PipelineOrchestrator,
        "CorpusReport": CorpusReport,
        "RunResult": RunResult,
        "load_manifest": load_manifest,
        "load_pdf": load_pdf,
        "write_corpus_report": write_corpus_report,
    }


async def _run_manifest(*, enable_image_beta: bool, runtime: dict[str, object]) -> tuple[Path, dict]:
    gateway = runtime["InputGateway"]()
    pipeline = runtime["PipelineOrchestrator"]()
    report_cls = runtime["CorpusReport"]
    run_result_cls = runtime["RunResult"]
    load_manifest = runtime["load_manifest"]
    load_pdf = runtime["load_pdf"]
    write_corpus_report = runtime["write_corpus_report"]
    results = []

    for entry in load_manifest():
        file_bytes = load_pdf(entry)
        preflight = await gateway.preflight(file_bytes, Path(entry.path).name, "application/pdf")
        result = run_result_cls(
            path=entry.path,
            difficulty=entry.difficulty,
            family=entry.family,
            expected_lane=entry.expected_lane,
            expected_outcome=entry.expected_outcome,
            actual_lane=preflight.get("lane_type"),
            promotion_status=preflight.get("promotion_status"),
            failure_code=preflight.get("failure_code"),
            document_class=preflight.get("document_class"),
        )

        if preflight.get("lane_type") == "trusted_pdf":
            try:
                pipeline_result = await pipeline.run(
                    entry.path,
                    file_bytes=file_bytes,
                    lane_type="trusted_pdf",
                    source_checksum=preflight.get("checksum"),
                )
            except Exception as exc:  # noqa: BLE001
                result.actual_status = "error"
                result.actual_outcome = "error"
                result.error = f"{type(exc).__name__}: {exc}"
            else:
                qa_metrics = pipeline_result.get("qa", {}).get("metrics", {})
                patient_artifact = pipeline_result.get("patient_artifact", {})
                result.actual_status = str(pipeline_result.get("status") or "")
                result.actual_outcome = result.actual_status
                result.observations_count = len(pipeline_result.get("observations", []))
                result.clean_rows_count = int(qa_metrics.get("clean_rows") or 0)
                result.findings_count = len(pipeline_result.get("findings", []))
                result.not_assessed_count = len(patient_artifact.get("not_assessed", []))
                result.support_banner = patient_artifact.get("support_banner")
                benchmark_metrics = pipeline_result.get("benchmark", {}).get("metrics", {})
                result.processing_ms = int(benchmark_metrics.get("processing_ms") or 0)
                result.job_id = str(pipeline_result.get("job_id") or entry.path)
        elif preflight.get("lane_type") == "unsupported":
            result.actual_status = "unsupported"
            result.actual_outcome = "unsupported"
            if preflight.get("failure_code"):
                result.error = str(preflight["failure_code"])
        else:
            result.actual_status = "preflight_only"
            result.actual_outcome = str(preflight.get("promotion_status") or "image_beta")
            if enable_image_beta and str(preflight.get("promotion_status")) == "beta_ready":
                result.error = "image_beta_runtime_not_implemented_for_pdf_inputs"

        results.append(result)

    report = report_cls()
    report.finalize(results)
    report_path = write_corpus_report(report)
    return report_path, report.to_dict()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the v11 manifest-driven corpus validation over pdfs_by_difficulty."
    )
    parser.add_argument(
        "--loinc-path",
        help=(
            "Override the terminology snapshot directory. Defaults to the configured path, "
            "then artifacts/dev-terminology."
        ),
    )
    parser.add_argument(
        "--enable-image-beta",
        action="store_true",
        help="Temporarily enable image-beta promotion checks during the run.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the full report JSON to stdout after the run.",
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

    report_path, payload = asyncio.run(
        _run_manifest(enable_image_beta=args.enable_image_beta, runtime=runtime)
    )
    payload["report_path"] = str(report_path)
    payload["loinc_path"] = str(loinc_path)
    payload["image_beta_enabled"] = bool(args.enable_image_beta)

    if args.print_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        summary = {
            "report_path": str(report_path),
            "total_entries": payload["total_entries"],
            "completed": payload["completed"],
            "partial": payload["partial"],
            "blocked": payload["blocked"],
            "unsupported": payload["unsupported"],
            "errors": payload["errors"],
            "lane_matches": payload["lane_matches"],
            "outcome_matches": payload["outcome_matches"],
        }
        print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
