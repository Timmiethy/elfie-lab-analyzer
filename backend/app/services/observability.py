"""Backend observability helpers for correlation IDs and counters."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

CORRELATION_ID_HEADER = "x-correlation-id"

_current_correlation_id: ContextVar[str | None] = ContextVar(
    "current_correlation_id",
    default=None,
)


def generate_correlation_id() -> str:
    return uuid4().hex


def set_current_correlation_id(correlation_id: str) -> None:
    _current_correlation_id.set(correlation_id)


def get_current_correlation_id() -> str | None:
    return _current_correlation_id.get()


@contextmanager
def span(name: str):
    """Measure elapsed wall-clock time for a named pipeline stage."""

    start = perf_counter()
    timing: dict[str, int | str] = {"name": name, "elapsed_ms": 0}
    try:
        yield timing
    finally:
        timing["elapsed_ms"] = int((perf_counter() - start) * 1000)


@dataclass(slots=True)
class ObservabilityMetrics:
    # Counter operations in CPython are GIL-protected; no explicit lock needed.
    # Using threading.Lock here would block the asyncio event loop when contended.
    _counters: Counter[str] = field(default_factory=Counter)

    _KNOWN_COUNTERS = (
        "upload_requests",
        "jobs_completed",
        "jobs_partial",
        "jobs_failed",
        "unsupported_inputs",
        "persistence_fallbacks",
    )

    def reset(self) -> None:
        self._counters.clear()

    def record_upload_request(self) -> None:
        self._increment("upload_requests")

    def record_job_outcome(self, status: str) -> None:
        if status == "completed":
            self._increment("jobs_completed")
        elif status == "partial":
            self._increment("jobs_partial")
        elif status == "failed":
            self._increment("jobs_failed")

    def record_unsupported_input(self) -> None:
        self._increment("unsupported_inputs")

    def record_persistence_fallback(self) -> None:
        self._increment("persistence_fallbacks")

    def snapshot(self) -> dict[str, int]:
        return {
            counter_name: int(self._counters.get(counter_name, 0))
            for counter_name in self._KNOWN_COUNTERS
        }

    def _increment(self, counter_name: str) -> None:
        self._counters[counter_name] += 1


observability_metrics = ObservabilityMetrics()
