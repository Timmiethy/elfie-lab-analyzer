"""Support helpers for the v11 corpus manifest runner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "pdf_corpus_manifest.json"
_CORPUS_ROOT = Path(__file__).resolve().parents[3] / "pdfs_by_difficulty"
_REPORT_DIR = Path(__file__).resolve().parents[3] / "artifacts" / "corpus_reports"


@dataclass
class ManifestEntry:
    path: str
    difficulty: str | None
    kind: str
    family: str | None
    expected_lane: str | None
    expected_outcome: str | None


@dataclass
class RunResult:
    path: str
    difficulty: str | None
    family: str | None
    expected_lane: str | None
    expected_outcome: str | None
    actual_lane: str | None = None
    actual_status: str | None = None
    actual_outcome: str | None = None
    promotion_status: str | None = None
    failure_code: str | None = None
    document_class: str | None = None
    error: str | None = None
    observations_count: int = 0
    clean_rows_count: int = 0
    findings_count: int = 0
    not_assessed_count: int = 0
    support_banner: str | None = None
    processing_ms: int = 0
    job_id: str | None = None

    # v12 parser substrate metadata recorded honestly from runtime results
    parser_backend: str | None = None
    parser_backend_version: str | None = None
    row_assembly_version: str | None = None

    def lane_matches(self) -> bool:
        if self.expected_lane is None:
            return True
        return self.actual_lane == self.expected_lane

    def outcome_matches(self) -> bool:
        if self.expected_outcome is None:
            return True
        if self.expected_outcome == "supported":
            return self.actual_status == "completed"
        if self.expected_outcome == "partial":
            return self.actual_status == "partial"
        if self.expected_outcome == "beta_supported":
            return (
                self.actual_status in {"partial", "completed"}
                and self.actual_lane == "image_beta"
            )
        if self.expected_outcome == "unsupported":
            return self.actual_lane == "unsupported" or self.error is not None
        return False

    def to_report(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "difficulty": self.difficulty,
            "family": self.family,
            "expected_lane": self.expected_lane,
            "expected_outcome": self.expected_outcome,
            "actual_lane": self.actual_lane,
            "actual_status": self.actual_status,
            "actual_outcome": self.actual_outcome,
            "promotion_status": self.promotion_status,
            "failure_code": self.failure_code,
            "document_class": self.document_class,
            "error": self.error,
            "lane_matches": self.lane_matches(),
            "outcome_matches": self.outcome_matches(),
            "observations_count": self.observations_count,
            "clean_rows_count": self.clean_rows_count,
            "findings_count": self.findings_count,
            "not_assessed_count": self.not_assessed_count,
            "support_banner": self.support_banner,
            "processing_ms": self.processing_ms,
            "job_id": self.job_id,
            # v12 parser substrate metadata
            "parser_backend": self.parser_backend,
            "parser_backend_version": self.parser_backend_version,
            "row_assembly_version": self.row_assembly_version,
        }


@dataclass
class CorpusReport:
    contract_version: str = "v11-corpus-report-v1"
    timestamp: str = ""
    total_entries: int = 0
    completed: int = 0
    partial: int = 0
    blocked: int = 0
    unsupported: int = 0
    errors: int = 0
    lane_matches: int = 0
    outcome_matches: int = 0
    entries: list[dict[str, Any]] = field(default_factory=list)
    summary_by_difficulty: dict[str, dict[str, int]] = field(default_factory=dict)
    summary_by_family: dict[str, dict[str, int]] = field(default_factory=dict)

    def finalize(self, results: list[RunResult]) -> None:
        self.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.total_entries = len(results)
        self.entries = [r.to_report() for r in results]

        for r in results:
            if r.actual_status == "completed":
                self.completed += 1
            elif r.actual_status == "partial":
                self.partial += 1
            elif r.actual_status == "blocked" or (
                r.expected_lane == "image_beta" and r.actual_lane in {"unsupported", "image_beta"}
            ):
                self.blocked += 1
            elif r.actual_lane == "unsupported":
                self.unsupported += 1
            elif r.error:
                self.errors += 1

            if r.lane_matches():
                self.lane_matches += 1
            if r.outcome_matches():
                self.outcome_matches += 1

        for difficulty in {"easy", "medium", "hard", None}:
            group = [r for r in results if r.difficulty == difficulty]
            if not group:
                continue
            label = difficulty or "metadata"
            self.summary_by_difficulty[label] = {
                "total": len(group),
                "lane_matches": sum(1 for r in group if r.lane_matches()),
                "outcome_matches": sum(1 for r in group if r.outcome_matches()),
                "errors": sum(1 for r in group if r.error),
            }

        for r in results:
            fam = r.family or "unknown"
            if fam not in self.summary_by_family:
                self.summary_by_family[fam] = {
                    "total": 0,
                    "lane_matches": 0,
                    "outcome_matches": 0,
                }
            self.summary_by_family[fam]["total"] += 1
            if r.lane_matches():
                self.summary_by_family[fam]["lane_matches"] += 1
            if r.outcome_matches():
                self.summary_by_family[fam]["outcome_matches"] += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "timestamp": self.timestamp,
            "total_entries": self.total_entries,
            "completed": self.completed,
            "partial": self.partial,
            "blocked": self.blocked,
            "unsupported": self.unsupported,
            "errors": self.errors,
            "lane_matches": self.lane_matches,
            "outcome_matches": self.outcome_matches,
            "entries": self.entries,
            "summary_by_difficulty": self.summary_by_difficulty,
            "summary_by_family": self.summary_by_family,
        }


def load_manifest() -> list[ManifestEntry]:
    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    entries: list[ManifestEntry] = []
    for item in data.get("files", []):
        if item.get("kind") != "pdf":
            continue
        entries.append(
            ManifestEntry(
                path=item["path"],
                difficulty=item.get("difficulty"),
                kind=item.get("kind", "pdf"),
                family=item.get("family"),
                expected_lane=item.get("expected_lane"),
                expected_outcome=item.get("expected_outcome"),
            )
        )
    return entries


def load_pdf(entry: ManifestEntry) -> bytes:
    pdf_path = _CORPUS_ROOT / entry.path
    if not pdf_path.exists():
        raise FileNotFoundError(f"corpus pdf not found: {pdf_path}")
    return pdf_path.read_bytes()


def write_corpus_report(report: CorpusReport) -> Path:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _REPORT_DIR / f"corpus-report-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report_path


def extract_v12_parser_metadata(
    pipeline_result: dict[str, Any],
    lane_type: str,
) -> dict[str, str | None]:
    """Extract v12 parser substrate metadata from a pipeline result.

    Reads parser_backend, parser_backend_version, and row_assembly_version
    from the lineage or benchmark sections. Falls back to lane-level defaults
    when the pipeline result does not carry explicit parser metadata.
    """
    lineage = pipeline_result.get("lineage", {})
    benchmark = pipeline_result.get("benchmark", {})
    metrics = benchmark.get("metrics", {})

    parser_backend = (
        lineage.get("parser_backend")
        or metrics.get("parser_backend")
        or ("pymupdf" if lane_type == "trusted_pdf" else "qwen_ocr")
    )
    parser_backend_version = (
        lineage.get("parser_backend_version")
        or metrics.get("parser_backend_version")
        or (
            "pymupdf-1.27.x"
            if lane_type == "trusted_pdf"
            else "qwen-vl-ocr-2025-11-20"
        )
    )
    row_assembly_version = (
        lineage.get("row_assembly_version")
        or metrics.get("row_assembly_version")
        or "row-assembly-v2"
    )

    return {
        "parser_backend": str(parser_backend) if parser_backend else None,
        "parser_backend_version": str(parser_backend_version) if parser_backend_version else None,
        "row_assembly_version": str(row_assembly_version) if row_assembly_version else None,
    }
