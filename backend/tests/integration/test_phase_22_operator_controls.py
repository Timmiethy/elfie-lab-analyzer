from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.tables import Document, Job
from app.workers.pipeline import _JOB_RUNS
from tests.integration.helpers import reset_integration_db

pytestmark = pytest.mark.asyncio


def _build_text_pdf(lines: list[str]) -> bytes:
    escaped_lines = [
        line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines
    ]
    content_lines = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(escaped_lines):
        if index:
            content_lines.append("0 -18 Td")
        content_lines.append(f"({line}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("utf-8")

    objects: list[bytes] = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n")
    objects.append(
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\n"
        b"endobj\n"
    )
    objects.append(
        b"4 0 obj\n"
        + f"<< /Length {len(stream)} >>\n".encode()
        + b"stream\n"
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    buffer = BytesIO()
    buffer.write(f"%PDF-1.4\n%fixture:{uuid4()}\n".encode())
    offsets = [0]
    for obj in objects:
        offsets.append(buffer.tell())
        buffer.write(obj)

    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode())
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode())
    buffer.write(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode()
    )
    return buffer.getvalue()


@pytest_asyncio.fixture(autouse=True)
async def integration_runtime_isolation(
    tmp_path: Path,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await reset_integration_db(db_session_factory)

    _JOB_RUNS.clear()
    original_artifact_store_path = settings.artifact_store_path
    original_max_job_retries = getattr(settings, "max_job_retries", 2)
    settings.artifact_store_path = tmp_path / "artifacts"
    settings.image_beta_enabled = False
    settings.max_job_retries = 2
    try:
        yield
    finally:
        _JOB_RUNS.clear()
        settings.artifact_store_path = original_artifact_store_path
        settings.max_job_retries = original_max_job_retries


async def _latest_job(session_factory: async_sessionmaker[AsyncSession]) -> Job:
    async with session_factory() as session:
        result = await session.execute(
            select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(1)
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise AssertionError("expected persisted job")
        return job


async def _document_for_job(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
) -> Document:
    async with session_factory() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise AssertionError("expected job row")
        document = await session.get(Document, job.document_id)
        if document is None:
            raise AssertionError("expected document row")
        return document


async def test_phase_22_recent_jobs_endpoint_lists_operator_view(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    completed_upload = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={
            "file": ("recent-good.pdf", _build_text_pdf(["Glucose 180 mg/dL"]), "application/pdf")
        },
    )
    assert completed_upload.status_code == 200, completed_upload.text

    failed_upload = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={"file": ("recent-bad.pdf", _build_text_pdf([]), "application/pdf")},
    )
    assert failed_upload.status_code == 422

    recent_response = await api_client.get("/api/jobs/ops/recent", params={"limit": 5})

    assert recent_response.status_code == 200, recent_response.text
    payload = recent_response.json()
    assert len(payload["jobs"]) >= 2
    assert payload["jobs"][0]["updated_at"] >= payload["jobs"][1]["updated_at"]
    assert {job["status"] for job in payload["jobs"]} >= {"completed", "failed"}
    assert all("retry_count" in job for job in payload["jobs"])
    assert all("has_patient_artifact" in job for job in payload["jobs"])


async def test_phase_22_job_audit_endpoint_reports_share_and_benchmark_activity(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_response = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={
            "file": (
                "audit.pdf",
                _build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"]),
                "application/pdf",
            )
        },
    )
    assert upload_response.status_code == 200, upload_response.text
    job_id = upload_response.json()["job_id"]

    patient_artifact_response = await api_client.get(f"/api/artifacts/{job_id}/patient")
    clinician_artifact_response = await api_client.get(f"/api/artifacts/{job_id}/clinician")
    assert patient_artifact_response.status_code == 200
    assert clinician_artifact_response.status_code == 200

    audit_response = await api_client.get(f"/api/jobs/{job_id}/audit")

    assert audit_response.status_code == 200, audit_response.text
    payload = audit_response.json()
    assert payload["job_id"] == job_id
    assert payload["lineage_runs_count"] >= 1
    assert payload["latest_benchmark"] is not None
    assert payload["latest_benchmark"]["report_type"]
    assert len(payload["share_events"]) >= 2
    assert {event["artifact_type"] for event in payload["share_events"]} >= {"patient", "clinician"}


async def test_phase_22_retry_preview_explains_reprocessing_readiness(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    failed_upload = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={"file": ("preview-bad.pdf", _build_text_pdf([]), "application/pdf")},
    )
    assert failed_upload.status_code == 422

    failed_job = await _latest_job(db_session_factory)
    preview_before_fix = await api_client.get(f"/api/jobs/{failed_job.id}/retry-preview")

    assert preview_before_fix.status_code == 200, preview_before_fix.text
    before_payload = preview_before_fix.json()
    assert before_payload["job_id"] == str(failed_job.id)
    assert before_payload["retry_allowed"] is True
    assert before_payload["document_present"] is True
    assert before_payload["dead_letter"] is False

    document = await _document_for_job(db_session_factory, str(failed_job.id))
    Path(document.storage_path).unlink()

    preview_after_removal = await api_client.get(f"/api/jobs/{failed_job.id}/retry-preview")

    assert preview_after_removal.status_code == 200, preview_after_removal.text
    after_payload = preview_after_removal.json()
    assert after_payload["retry_allowed"] is False
    assert after_payload["document_present"] is False
    assert after_payload["retry_block_reason"] == "document_missing"
