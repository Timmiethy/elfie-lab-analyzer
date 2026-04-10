"""Backend observability helpers for correlation IDs and counters."""

from __future__ import annotations

from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
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


@dataclass(slots=True)
class ObservabilityMetrics:
    _counters: Counter[str] = field(default_factory=Counter)
    _lock: Lock = field(default_factory=Lock)

    _KNOWN_COUNTERS = (
        "upload_requests",
        "jobs_completed",
        "jobs_partial",
        "jobs_failed",
        "unsupported_inputs",
        "persistence_fallbacks",
    )

    def reset(self) -> None:
        with self._lock:
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
        with self._lock:
            return {
                counter_name: int(self._counters.get(counter_name, 0))
                for counter_name in self._KNOWN_COUNTERS
            }

    def _increment(self, counter_name: str) -> None:
        with self._lock:
            self._counters[counter_name] += 1


observability_metrics = ObservabilityMetrics()

