from __future__ import annotations

from uuid import uuid4

from app.config import settings
from app.services.clinician_pdf import (
    build_clinician_pdf_bytes,
    clinician_pdf_path,
    write_clinician_pdf,
)


def test_phase_32_clinician_pdf_generation_writes_expected_bytes(tmp_path) -> None:
    original_artifact_store_path = settings.artifact_store_path
    settings.artifact_store_path = tmp_path / "artifacts"
    try:
        job_id = uuid4()
        clinician_artifact = {
            "job_id": job_id,
            "report_date": "2026-04-10",
            "top_findings": [
                {
                    "finding_id": "glucose_high::row-001",
                    "rule_id": "glucose_high_threshold",
                    "threshold_source": "adult_fasting_default_70_99",
                    "severity_class": "S2",
                    "nextstep_class": "A2",
                    "explanatory_scaffold_id": "glucose_high_v1",
                }
            ],
            "severity_classes": ["S2"],
            "nextstep_classes": ["A2"],
            "support_coverage": "fully_supported",
            "trust_status": "trusted",
            "not_assessed": [
                {"raw_label": "mystery marker", "reason": "insufficient_support"},
            ],
            "provenance_link": "/api/jobs/example/proof-pack",
        }

        pdf_bytes = build_clinician_pdf_bytes(clinician_artifact)
        path = write_clinician_pdf(job_id, clinician_artifact)

        assert pdf_bytes.startswith(b"%PDF-")
        assert b"Clinician Smoke Report" in pdf_bytes
        assert b"fully_supported" in pdf_bytes
        assert b"glucose_high_v1" in pdf_bytes
        assert path == clinician_pdf_path(job_id)
        assert path.exists()
        assert path.read_bytes().startswith(b"%PDF-")
    finally:
        settings.artifact_store_path = original_artifact_store_path
