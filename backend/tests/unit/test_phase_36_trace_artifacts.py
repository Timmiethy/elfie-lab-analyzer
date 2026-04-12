from __future__ import annotations

from uuid import uuid4

from app.services.benchmark import BenchmarkRecorder
from app.services.lineage import LineageLogger


def test_phase_36_proof_pack_preserves_trace_refs_family_benchmarks_and_lineage_versions() -> None:
    recorder = BenchmarkRecorder()
    job_id = uuid4()
    lineage = LineageLogger().record(
        str(job_id),
        {
            "source_checksum": "checksum-phase-36",
            "parser_version": "trusted-pdf-v1",
            "ocr_version": None,
            "family_adapter_version": "innoquest-bilingual-adapter-v11",
            "row_assembly_version": "geometry-row-assembler-v11",
            "terminology_release": "loinc-2026-04",
            "mapping_threshold_config": {"default": 0.9},
            "unit_engine_version": "ucum-v1",
            "rule_pack_version": "rules-v1",
            "severity_policy_version": "severity-v1",
            "nextstep_policy_version": "nextstep-v1",
            "template_version": "templates-v1",
            "model_version": None,
            "build_commit": "abc123",
        },
    )

    benchmark = recorder.record(
        lineage_id=str(lineage["id"]),
        report_type="v11_trace_eval",
        metrics={
            "processing_ms": 12,
            "parser_precision": 0.992,
            "family_precision": 0.988,
        },
        family_benchmarks={
            "innoquest_bilingual_general": {
                "result_row_recall": 0.99,
                "row_assembly_f1": 0.98,
                "leak_rate": 0.0,
            }
        },
        trace_refs={
            "parser_trace": f"/api/artifacts/{job_id}/parser-trace",
            "normalization_trace": f"/api/artifacts/{job_id}/normalization-trace",
        },
    )

    proof_pack = recorder.build_proof_pack(
        benchmark=benchmark,
        lineage=lineage,
        artifact_refs={
            "patient_artifact": f"/api/artifacts/{job_id}/patient",
            "clinician_artifact": f"/api/artifacts/{job_id}/clinician",
            "clinician_pdf": f"/api/artifacts/{job_id}/clinician/pdf",
            "suppression_report": f"/api/artifacts/{job_id}/suppression-report",
        },
        report_metadata={
            "corpus_id": "pdfs_by_difficulty",
            "lane_id": "trusted_pdf",
            "language_id": "en",
            "timestamp": "2026-04-12T00:00:00Z",
        },
    )

    assert benchmark["trace_refs"]["parser_trace"] == f"/api/artifacts/{job_id}/parser-trace"
    assert benchmark["trace_refs"]["normalization_trace"] == f"/api/artifacts/{job_id}/normalization-trace"
    assert benchmark["family_benchmarks"]["innoquest_bilingual_general"]["row_assembly_f1"] == 0.98
    assert benchmark["summary"]["trace_refs"]["parser_trace"] == f"/api/artifacts/{job_id}/parser-trace"
    assert benchmark["summary"]["family_benchmarks"]["innoquest_bilingual_general"]["leak_rate"] == 0.0

    assert proof_pack["trace_refs"] == {
        "parser_trace": f"/api/artifacts/{job_id}/parser-trace",
        "normalization_trace": f"/api/artifacts/{job_id}/normalization-trace",
        "suppression_report": f"/api/artifacts/{job_id}/suppression-report",
    }
    assert proof_pack["family_benchmarks"]["innoquest_bilingual_general"]["result_row_recall"] == 0.99
    assert proof_pack["lineage"]["family_adapter_version"] == "innoquest-bilingual-adapter-v11"
    assert proof_pack["lineage"]["row_assembly_version"] == "geometry-row-assembler-v11"
    assert (
        proof_pack["reports"]["parser_report.json"]["lineage_version_ids"]["family_adapter_version"]
        == "innoquest-bilingual-adapter-v11"
    )
    assert (
        proof_pack["reports"]["parser_report.json"]["lineage_version_ids"]["row_assembly_version"]
        == "geometry-row-assembler-v11"
    )
