from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.store import TopLevelLifecycleStore


@pytest.mark.asyncio
async def test_phase_28_persist_bundle_reuses_existing_lineage_for_benchmark() -> None:
    session = AsyncMock()
    store = TopLevelLifecycleStore(session)
    job = SimpleNamespace(id=uuid4())
    lineage = SimpleNamespace(id=uuid4())
    benchmark = SimpleNamespace(id=uuid4())

    store.get_job = AsyncMock(return_value=job)  # type: ignore[method-assign]
    store.get_latest_lineage_run = AsyncMock(return_value=lineage)  # type: ignore[method-assign]
    store.create_benchmark_run = AsyncMock(return_value=benchmark)  # type: ignore[method-assign]

    result = await store.persist_top_level_bundle(
        job_id=job.id,
        benchmark_run={
            "report_type": "truth_engine_pipeline",
            "metrics": {"processing_ms": 42},
        },
    )

    assert result.job is job
    assert result.lineage_run is lineage
    assert result.benchmark_run is benchmark
    store.create_benchmark_run.assert_awaited_once_with(
        lineage_id=lineage.id,
        report_type="truth_engine_pipeline",
        metrics={"processing_ms": 42},
    )


@pytest.mark.asyncio
async def test_phase_28_persist_bundle_prefers_newly_created_lineage_for_benchmark() -> None:
    session = AsyncMock()
    store = TopLevelLifecycleStore(session)
    job = SimpleNamespace(id=uuid4())
    lineage = SimpleNamespace(id=uuid4())
    benchmark = SimpleNamespace(id=uuid4())

    store.get_job = AsyncMock(return_value=job)  # type: ignore[method-assign]
    store.create_lineage_run = AsyncMock(return_value=lineage)  # type: ignore[method-assign]
    store.get_latest_lineage_run = AsyncMock(return_value=None)  # type: ignore[method-assign]
    store.create_benchmark_run = AsyncMock(return_value=benchmark)  # type: ignore[method-assign]

    result = await store.persist_top_level_bundle(
        job_id=job.id,
        lineage_run={
            "source_checksum": "sha256:phase-28",
            "parser_version": "trusted-pdf-v1",
            "terminology_release": "loinc-phase-28",
            "mapping_threshold_config": {"default": 0.9},
            "unit_engine_version": "ucum-v1",
            "rule_pack_version": "rules-v1",
            "severity_policy_version": "severity-v1",
            "nextstep_policy_version": "nextstep-v1",
            "template_version": "templates-v1",
        },
        benchmark_run={
            "report_type": "truth_engine_pipeline",
            "metrics": {"processing_ms": 42},
        },
    )

    assert result.lineage_run is lineage
    assert result.benchmark_run is benchmark
    store.get_latest_lineage_run.assert_not_awaited()
    store.create_benchmark_run.assert_awaited_once_with(
        lineage_id=lineage.id,
        report_type="truth_engine_pipeline",
        metrics={"processing_ms": 42},
    )


@pytest.mark.asyncio
async def test_phase_28_persist_bundle_requires_lineage_before_benchmark() -> None:
    session = AsyncMock()
    store = TopLevelLifecycleStore(session)
    job = SimpleNamespace(id=uuid4())

    store.get_job = AsyncMock(return_value=job)  # type: ignore[method-assign]
    store.get_latest_lineage_run = AsyncMock(return_value=None)  # type: ignore[method-assign]
    store.create_benchmark_run = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(LookupError, match="lineage_run_required_for_benchmark"):
        await store.persist_top_level_bundle(
            job_id=job.id,
            benchmark_run={
                "report_type": "truth_engine_pipeline",
                "metrics": {"processing_ms": 42},
            },
        )

    store.create_benchmark_run.assert_not_awaited()
