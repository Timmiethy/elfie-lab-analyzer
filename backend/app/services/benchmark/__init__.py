"""Benchmark recorder: validation metrics and report generation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from numbers import Real
from uuid import NAMESPACE_URL, uuid5

CONTRACT_VERSION = "benchmark-contract-v1"
PROOF_PACK_CONTRACT_VERSION = "benchmark-proof-pack-v1"
PROOF_PACK_REPORT_NAMES = (
    "parser_report.json",
    "mapping_report.json",
    "policy_report.json",
    "coverage_report.json",
    "explanation_report.json",
    "patient_comprehension_report.json",
    "partial_support_report.json",
    "clinician_scan_report.json",
    "ablation_report.json",
)
_TRACE_REF_FIELDS = (
    "parser_trace",
    "normalization_trace",
    "suppression_report",
)
_LINEAGE_VERSION_FIELDS = (
    "parser_version",
    "ocr_version",
    "family_adapter_version",
    "row_assembly_version",
    "terminology_release",
    "unit_engine_version",
    "rule_pack_version",
    "severity_policy_version",
    "nextstep_policy_version",
    "template_version",
    "model_version",
)


def _stable_payload(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _is_timing_metric(metric_name: str) -> bool:
    return metric_name.endswith("_ms")


def _compare_metric(observed: object, baseline: object) -> dict:
    if (
        isinstance(observed, Real)
        and not isinstance(observed, bool)
        and isinstance(baseline, Real)
        and not isinstance(baseline, bool)
    ):
        status = "pass" if float(observed) >= float(baseline) else "regressed"
        delta = float(observed) - float(baseline)
        return {
            "observed": observed,
            "baseline": baseline,
            "delta": delta,
            "status": status,
        }

    status = "pass" if observed == baseline else "regressed"
    return {
        "observed": observed,
        "baseline": baseline,
        "delta": None,
        "status": status,
    }


def _lineage_version_ids(lineage: Mapping[str, object]) -> dict[str, object]:
    return {field_name: lineage.get(field_name) for field_name in _LINEAGE_VERSION_FIELDS}


def _compact_trace_refs(trace_refs: Mapping[str, object] | None) -> dict[str, object]:
    if not trace_refs:
        return {}

    return {
        str(ref_name): ref_value
        for ref_name, ref_value in trace_refs.items()
        if ref_value not in (None, "", [], {}, ())
    }


def _trace_refs_from_artifact_refs(artifact_refs: Mapping[str, object]) -> dict[str, object]:
    return {
        ref_name: artifact_refs[ref_name]
        for ref_name in _TRACE_REF_FIELDS
        if artifact_refs.get(ref_name) not in (None, "", [], {}, ())
    }


def _proof_report_base(
    report_name: str,
    *,
    benchmark: Mapping[str, object],
    lineage: Mapping[str, object],
    artifact_refs: Mapping[str, object],
    report_metadata: Mapping[str, object],
) -> dict[str, object]:
    return {
        "report_name": report_name,
        "build_commit": report_metadata.get("build_commit") or lineage.get("build_commit"),
        "benchmark_id": str(benchmark.get("id")),
        "lineage_id": str(lineage.get("id") or benchmark.get("lineage_id") or ""),
        "corpus_id": report_metadata.get("corpus_id"),
        "lane_id": report_metadata.get("lane_id"),
        "language_id": report_metadata.get("language_id"),
        "timestamp": report_metadata.get("timestamp"),
        "lineage_version_ids": _lineage_version_ids(lineage),
        "artifact_refs": dict(artifact_refs),
    }


def _build_proof_reports(
    *,
    benchmark: Mapping[str, object],
    lineage: Mapping[str, object],
    artifact_refs: Mapping[str, object],
    report_metadata: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    summary = dict(benchmark.get("summary") or {})
    metrics = dict(benchmark.get("metrics") or {})
    regression_tags = list(benchmark.get("regression_tags") or [])

    def report(report_name: str, payload: Mapping[str, object]) -> dict[str, object]:
        base = _proof_report_base(
            report_name,
            benchmark=benchmark,
            lineage=lineage,
            artifact_refs=artifact_refs,
            report_metadata=report_metadata,
        )
        base["payload"] = dict(payload)
        return base

    return {
        "parser_report.json": report(
            "parser_report.json",
            {
                "timing": dict(summary.get("timing") or {}),
                "regression_tags": regression_tags,
            },
        ),
        "mapping_report.json": report(
            "mapping_report.json",
            {
                "mapping_threshold_config": dict(lineage.get("mapping_threshold_config") or {}),
                "metrics": metrics,
            },
        ),
        "policy_report.json": report(
            "policy_report.json",
            {
                "rule_pack_version": lineage.get("rule_pack_version"),
                "severity_policy_version": lineage.get("severity_policy_version"),
                "nextstep_policy_version": lineage.get("nextstep_policy_version"),
                "baseline_checks": dict(summary.get("baseline_checks") or {}),
            },
        ),
        "coverage_report.json": report(
            "coverage_report.json",
            {
                "metrics": dict(summary.get("metrics") or {}),
                "regressed_metrics": list(summary.get("regressed_metrics") or []),
            },
        ),
        "explanation_report.json": report(
            "explanation_report.json",
            {
                "template_version": lineage.get("template_version"),
                "model_version": lineage.get("model_version"),
            },
        ),
        "patient_comprehension_report.json": report(
            "patient_comprehension_report.json",
            {
                "evaluation_status": "pending_person_b_validation",
            },
        ),
        "partial_support_report.json": report(
            "partial_support_report.json",
            {
                "summary": {
                    "regression_tags": regression_tags,
                    "regressed_metrics": list(summary.get("regressed_metrics") or []),
                }
            },
        ),
        "clinician_scan_report.json": report(
            "clinician_scan_report.json",
            {
                "evaluation_status": "pending_person_b_validation",
            },
        ),
        "ablation_report.json": report(
            "ablation_report.json",
            {
                "regression_tags": regression_tags,
                "report_type": benchmark.get("report_type"),
            },
        ),
    }


class BenchmarkRecorder:
    def record(
        self,
        lineage_id: str,
        report_type: str,
        metrics: dict,
        baselines: Mapping[str, object] | None = None,
        regression_tags: Sequence[str] | None = None,
        *,
        family_benchmarks: Mapping[str, object] | None = None,
        trace_refs: Mapping[str, object] | None = None,
    ) -> dict:
        lineage_id_str = str(lineage_id)
        metrics_payload = dict(metrics)
        baselines_payload = dict(baselines or {})
        regression_tags_payload = list(regression_tags or [])
        family_benchmarks_payload = dict(family_benchmarks or {})
        trace_refs_payload = _compact_trace_refs(trace_refs)
        benchmark_key = _stable_payload(
            {
                "baselines": baselines_payload,
                "family_benchmarks": family_benchmarks_payload,
                "metrics": metrics_payload,
                "regression_tags": regression_tags_payload,
                "trace_refs": trace_refs_payload,
            }
        )
        benchmark_id = uuid5(
            NAMESPACE_URL,
            f"benchmark:{lineage_id_str}:{report_type}:{benchmark_key}",
        )

        timing_summary = {
            metric_name: metric_value
            for metric_name, metric_value in metrics_payload.items()
            if _is_timing_metric(metric_name)
        }
        non_timing_summary = {
            metric_name: metric_value
            for metric_name, metric_value in metrics_payload.items()
            if not _is_timing_metric(metric_name)
        }

        baseline_checks: dict[str, dict] = {}
        regressed_metrics: list[str] = []
        for metric_name, baseline_value in baselines_payload.items():
            if metric_name not in metrics_payload:
                baseline_checks[metric_name] = {
                    "observed": None,
                    "baseline": baseline_value,
                    "delta": None,
                    "status": "missing",
                }
                continue

            comparison = _compare_metric(metrics_payload[metric_name], baseline_value)
            baseline_checks[metric_name] = comparison
            if comparison["status"] == "regressed":
                regressed_metrics.append(metric_name)

        return {
            "contract_version": CONTRACT_VERSION,
            "id": benchmark_id,
            "lineage_id": lineage_id_str,
            "report_type": report_type,
            "metrics": metrics_payload,
            "baselines": baselines_payload,
            "regression_tags": regression_tags_payload,
            "family_benchmarks": family_benchmarks_payload,
            "trace_refs": trace_refs_payload,
            "summary": {
                "timing": timing_summary,
                "metrics": non_timing_summary,
                "baseline_checks": baseline_checks,
                "regressed_metrics": regressed_metrics,
                "regression_tags": regression_tags_payload,
                "family_benchmarks": family_benchmarks_payload,
                "trace_refs": trace_refs_payload,
            },
        }

    def build_proof_pack(
        self,
        benchmark: Mapping[str, object],
        lineage: Mapping[str, object],
        artifact_refs: Mapping[str, object],
        report_metadata: Mapping[str, object] | None = None,
    ) -> dict:
        benchmark_payload = dict(benchmark)
        lineage_payload = dict(lineage)
        artifact_refs_payload = dict(artifact_refs)
        report_metadata_payload = dict(report_metadata or {})
        summary_payload = dict(benchmark_payload.get("summary") or {})
        summary_payload.setdefault(
            "regression_tags", list(benchmark_payload.get("regression_tags") or [])
        )
        benchmark_trace_refs = _compact_trace_refs(benchmark_payload.get("trace_refs"))
        artifact_trace_refs = _trace_refs_from_artifact_refs(artifact_refs_payload)
        trace_refs_payload = {**benchmark_trace_refs, **artifact_trace_refs}
        family_benchmarks_payload = dict(
            benchmark_payload.get("family_benchmarks")
            or summary_payload.get("family_benchmarks")
            or {}
        )

        return {
            "contract_version": PROOF_PACK_CONTRACT_VERSION,
            "benchmark_id": str(benchmark_payload.get("id")),
            "benchmark_contract_version": benchmark_payload.get("contract_version"),
            "lineage_id": benchmark_payload.get("lineage_id"),
            "report_type": benchmark_payload.get("report_type"),
            "summary": summary_payload,
            "metrics": dict(benchmark_payload.get("metrics") or {}),
            "regression_tags": list(benchmark_payload.get("regression_tags") or []),
            "lineage": lineage_payload,
            "artifact_refs": artifact_refs_payload,
            "trace_refs": trace_refs_payload,
            "family_benchmarks": family_benchmarks_payload,
            "reports": _build_proof_reports(
                benchmark=benchmark_payload,
                lineage=lineage_payload,
                artifact_refs=artifact_refs_payload,
                report_metadata=report_metadata_payload,
            ),
        }
