"""Lineage logger: full provenance tracking (blueprint section 11.3)."""


class LineageLogger:
    def record(self, job_id: str, components: dict) -> dict:
        raise NotImplementedError
