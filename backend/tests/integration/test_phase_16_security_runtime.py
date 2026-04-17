from __future__ import annotations

from io import BytesIO
from pathlib import Path
from stat import S_IMODE
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.tables import Document, Job, ShareEvent
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
    original_upload_retention_days = getattr(settings, "upload_retention_days", 30)
    original_artifact_retention_days = getattr(settings, "artifact_retention_days", 30)
    settings.artifact_store_path = tmp_path / "artifacts"
    settings.image_beta_enabled = False
    try:
        yield
    finally:
        _JOB_RUNS.clear()
        settings.artifact_store_path = original_artifact_store_path
        if hasattr(settings, "upload_retention_days"):
            settings.upload_retention_days = original_upload_retention_days
        if hasattr(settings, "artifact_retention_days"):
            settings.artifact_retention_days = original_artifact_retention_days


async def _latest_job_and_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Job, Document]:
    async with session_factory() as session:
        result = await session.execute(
            select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(1)
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise AssertionError("expected persisted job")
        document = await session.get(Document, job.document_id)
        if document is None:
            raise AssertionError("expected persisted document")
        return job, document


async def _share_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[ShareEvent]:
    async with session_factory() as session:
        result = await session.execute(
            select(ShareEvent).order_by(ShareEvent.created_at.asc(), ShareEvent.id.asc())
        )
        return list(result.scalars())


async def test_phase_16_upload_storage_is_private_and_artifact_access_is_audited(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_response = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={
            "file": (
                "security.pdf",
                _build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"]),
                "application/pdf",
            )
        },
    )
    assert upload_response.status_code == 200, upload_response.text
    job_id = upload_response.json()["job_id"]

    job, document = await _latest_job_and_document(db_session_factory)
    assert str(job.id) == job_id

    stored_file = Path(document.storage_path)
    assert stored_file.exists()
    import os

    if os.name != "nt":
        assert S_IMODE(stored_file.stat().st_mode) == 0o600
        assert S_IMODE(stored_file.parent.stat().st_mode) == 0o700

    patient_response = await api_client.get(f"/api/artifacts/{job_id}/patient")
    clinician_response = await api_client.get(f"/api/artifacts/{job_id}/clinician")
    assert patient_response.status_code == 200, patient_response.text
    assert clinician_response.status_code == 200, clinician_response.text

    events = await _share_events(db_session_factory)
    assert len(events) == 2
    assert {event.artifact_type for event in events} == {"patient", "clinician"}
    assert all(event.share_method == "view" for event in events)


async def test_phase_16_privacy_policy_endpoint_exposes_retention_and_sanitization(
    api_client: AsyncClient,
) -> None:
    privacy_response = await api_client.get("/api/health/privacy")
    assert privacy_response.status_code == 200, privacy_response.text
    privacy_payload = privacy_response.json()
    assert privacy_payload["status"] == "ok"
    assert privacy_payload["retention"]["upload_retention_days"] > 0
    assert privacy_payload["retention"]["artifact_retention_days"] > 0
    assert privacy_payload["controls"]["artifact_access_audited"] is True
    assert privacy_payload["controls"]["api_failure_detail"] == "sanitized"
