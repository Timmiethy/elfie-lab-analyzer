from __future__ import annotations

from app.services import observability


def test_generate_correlation_id_is_hex_uuid() -> None:
    correlation_id = observability.generate_correlation_id()

    assert len(correlation_id) == 32
    int(correlation_id, 16)


def test_set_and_get_current_correlation_id_round_trip() -> None:
    token = observability._current_correlation_id.set(None)
    try:
        observability.set_current_correlation_id("phase-15-correlation")
        assert observability.get_current_correlation_id() == "phase-15-correlation"
    finally:
        observability._current_correlation_id.reset(token)


def test_observability_metrics_snapshot_starts_with_known_counters() -> None:
    metrics = observability.ObservabilityMetrics()

    assert metrics.snapshot() == {
        "upload_requests": 0,
        "jobs_completed": 0,
        "jobs_partial": 0,
        "jobs_failed": 0,
        "unsupported_inputs": 0,
        "persistence_fallbacks": 0,
    }


def test_observability_metrics_records_outcomes_and_reset() -> None:
    metrics = observability.ObservabilityMetrics()

    metrics.record_upload_request()
    metrics.record_job_outcome("completed")
    metrics.record_job_outcome("partial")
    metrics.record_job_outcome("failed")
    metrics.record_job_outcome("ignored")
    metrics.record_unsupported_input()
    metrics.record_persistence_fallback()

    assert metrics.snapshot() == {
        "upload_requests": 1,
        "jobs_completed": 1,
        "jobs_partial": 1,
        "jobs_failed": 1,
        "unsupported_inputs": 1,
        "persistence_fallbacks": 1,
    }

    metrics.reset()
    assert metrics.snapshot() == {
        "upload_requests": 0,
        "jobs_completed": 0,
        "jobs_partial": 0,
        "jobs_failed": 0,
        "unsupported_inputs": 0,
        "persistence_fallbacks": 0,
    }
