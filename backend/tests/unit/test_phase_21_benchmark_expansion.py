"""Phase 21 benchmark expansion tests."""

from __future__ import annotations

from uuid import uuid4

from app.services.benchmark import BenchmarkRecorder


def test_phase_21_benchmark_record_includes_summary_and_baseline_comparison() -> None:
    recorder = BenchmarkRecorder()

    benchmark = recorder.record(
        lineage_id=str(uuid4()),
        report_type="launch_scope_eval",
        metrics={
            "processing_ms": 1820,
            "extraction_ms": 640,
            "parser_precision": 0.985,
            "rule_agreement": 0.962,
        },
        baselines={
            "parser_precision": 0.980,
            "rule_agreement": 0.970,
        },
        regression_tags=["parser", "policy"],
    )

    assert benchmark["regression_tags"] == ["parser", "policy"]
    assert benchmark["summary"]["timing"]["processing_ms"] == 1820
    assert benchmark["summary"]["timing"]["extraction_ms"] == 640
    assert benchmark["summary"]["baseline_checks"]["parser_precision"]["status"] == "pass"
    assert benchmark["summary"]["baseline_checks"]["rule_agreement"]["status"] == "regressed"
    assert benchmark["summary"]["regressed_metrics"] == ["rule_agreement"]


def test_phase_21_benchmark_proof_pack_collects_future_review_evidence() -> None:
    recorder = BenchmarkRecorder()
    benchmark = recorder.record(
        lineage_id=str(uuid4()),
        report_type="launch_scope_eval",
        metrics={"processing_ms": 1200, "supported_documents": 14},
        baselines={"supported_documents": 10},
        regression_tags=["parser", "lineage"],
    )

    proof_pack = recorder.build_proof_pack(
        benchmark=benchmark,
        lineage={
            "id": str(uuid4()),
            "rule_pack_version": "launch-scope-rules-v1",
            "severity_policy_version": "severity-v1",
            "nextstep_policy_version": "nextstep-v1",
            "build_commit": "abc123",
        },
        artifact_refs={
            "patient_artifact": "artifacts/patient.json",
            "clinician_artifact": "artifacts/clinician.json",
        },
        report_metadata={
            "corpus_id": "seeded-launch-corpus-v1",
            "lane_id": "trusted_pdf",
            "language_id": "en",
            "timestamp": "2026-04-11T00:00:00Z",
        },
    )

    assert proof_pack["contract_version"] == "benchmark-proof-pack-v1"
    assert proof_pack["benchmark_id"] == str(benchmark["id"])
    assert proof_pack["report_type"] == "launch_scope_eval"
    assert proof_pack["lineage"]["rule_pack_version"] == "launch-scope-rules-v1"
    assert proof_pack["artifact_refs"]["patient_artifact"] == "artifacts/patient.json"
    assert proof_pack["summary"]["regression_tags"] == ["parser", "lineage"]
    assert set(proof_pack["reports"]) == {
        "parser_report.json",
        "mapping_report.json",
        "policy_report.json",
        "coverage_report.json",
        "explanation_report.json",
        "patient_comprehension_report.json",
        "partial_support_report.json",
        "clinician_scan_report.json",
        "ablation_report.json",
    }

    parser_report = proof_pack["reports"]["parser_report.json"]
    assert parser_report["build_commit"] == "abc123"
    assert parser_report["corpus_id"] == "seeded-launch-corpus-v1"
    assert parser_report["lane_id"] == "trusted_pdf"
    assert parser_report["language_id"] == "en"
    assert parser_report["timestamp"] == "2026-04-11T00:00:00Z"
    assert parser_report["lineage_version_ids"]["rule_pack_version"] == "launch-scope-rules-v1"
