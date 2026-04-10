"""Benchmark recorder: validation metrics and report generation."""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5


def _stable_metrics(metrics: dict) -> str:
    return json.dumps(metrics, sort_keys=True, separators=(",", ":"), default=str)


class BenchmarkRecorder:
    def record(self, lineage_id: str, report_type: str, metrics: dict) -> dict:
        lineage_id_str = str(lineage_id)
        benchmark_id = uuid5(NAMESPACE_URL, f"benchmark:{lineage_id_str}:{report_type}:{_stable_metrics(metrics)}")

        return {
            "id": benchmark_id,
            "lineage_id": lineage_id_str,
            "report_type": report_type,
            "metrics": dict(metrics),
        }
