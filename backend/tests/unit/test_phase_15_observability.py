"""Phase 15 acceptance tests for pipeline observability."""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.workers.pipeline import PipelineOrchestrator
from tests.support.pdf_builder import build_text_pdf


def test_pipeline_logs_job_start_and_completion_with_context(caplog) -> None:
    with caplog.at_level(logging.INFO):
        result = asyncio.run(
            PipelineOrchestrator().run(
                "phase-15-observe",
                file_bytes=build_text_pdf([
                    "Glucose 180 mg/dL 70-99",
                ]),
                lane_type="trusted_pdf",
            )
        )

    assert result["status"] in {"completed", "partial"}
    assert any(
        "pipeline_start" in record.getMessage()
        and "phase-15-observe" in record.getMessage()
        and "trusted_pdf" in record.getMessage()
        for record in caplog.records
    )
    assert any(
        "pipeline_complete" in record.getMessage()
        and "phase-15-observe" in record.getMessage()
        and result["status"] in record.getMessage()
        for record in caplog.records
    )


def test_pipeline_logs_failure_context_for_unsupported_lane(caplog) -> None:
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ValueError):
            asyncio.run(
                PipelineOrchestrator().run(
                    "phase-15-failure",
                    lane_type="legacy_csv",
                )
            )

    assert any(
        "pipeline_failed" in record.getMessage()
        and "phase-15-failure" in record.getMessage()
        and "unsupported_lane:legacy_csv" in record.getMessage()
        for record in caplog.records
    )
