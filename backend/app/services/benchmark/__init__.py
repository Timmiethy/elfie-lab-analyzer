"""Benchmark recorder: validation metrics and report generation."""


class BenchmarkRecorder:
    def record(self, lineage_id: str, report_type: str, metrics: dict) -> dict:
        raise NotImplementedError
