from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.routes import artifacts as artifacts_routes
from app.api.routes import jobs as jobs_routes
from app.api.routes import upload as upload_routes
from app.config import settings
from app.main import create_app
from app.models.tables import Document, Job, LineageRun
from app.workers.pipeline import _JOB_RUNS

pytestmark = pytest.mark.asyncio


def _build_text_pdf(lines: list[str]) -> bytes:
    escaped_lines = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
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
        + f"<< /Length {len(stream)} >>\n".encode("utf-8")
        + b"stream\n"
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    buffer = BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(buffer.tell())
        buffer.write(obj)

    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("utf-8"))
    buffer.write(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode("utf-8")
    )
    return buffer.getvalue()


@pytest_asyncio.fixture
async def db_session_factory(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(upload_routes, "async_session_factory", session_factory)
    monkeypatch.setattr(jobs_routes, "async_session_factory", session_factory)
    monkeypatch.setattr(artifacts_routes, "async_session_factory", session_factory)
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def integration_runtime_isolation(
    tmp_path: Path,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE "
                "share_events, benchmark_runs, lineage_runs, clinician_artifacts, "
                "patient_artifacts, policy_events, rule_events, mapping_candidates, "
                "observations, extracted_rows, jobs, documents "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()

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


@pytest_asyncio.fixture
async def api_client() -> AsyncClient:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def _latest_job(session_factory: async_sessionmaker[AsyncSession]) -> Job:
    async with session_factory() as session:
        result = await session.execute(select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
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


async def _lineage_count_for_job(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
) -> int:
    async with session_factory() as session:
        result = await session.execute(select(LineageRun).where(LineageRun.job_id == job_id))
        return len(list(result.scalars()))


@pytest.mark.anyio
async def test_phase_14_retry_reprocesses_persisted_document_and_records_history(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    failed_upload = await api_client.post(
        "/api/upload",
        files={"file": ("needs-retry.pdf", _build_text_pdf([]), "application/pdf")},
    )
    assert failed_upload.status_code == 422

    failed_job = await _latest_job(db_session_factory)
    assert failed_job.status == "failed"
    original_lineage_count = await _lineage_count_for_job(db_session_factory, str(failed_job.id))

    document = await _document_for_job(db_session_factory, str(failed_job.id))
    Path(document.storage_path).write_bytes(_build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"]))

    retry_response = await api_client.post(f"/api/jobs/{failed_job.id}/retry")

    assert retry_response.status_code == 200, retry_response.text
    retry_payload = retry_response.json()
    assert retry_payload["job_id"] == str(failed_job.id)
    assert retry_payload["status"] == "completed"
    assert retry_payload["retry_count"] == 1
    assert retry_payload["dead_letter"] is False
    assert retry_payload["retried"] is True

    job_response = await api_client.get(f"/api/jobs/{failed_job.id}")
    assert job_response.status_code == 200, job_response.text
    job_payload = job_response.json()
    assert job_payload["status"] == "completed"
    assert job_payload["retry_count"] == 1
    assert job_payload["dead_letter"] is False
    assert job_payload["retried"] is True
    assert job_payload["lineage_runs_count"] >= original_lineage_count + 1

    artifact_response = await api_client.get(f"/api/artifacts/{failed_job.id}/patient")
    assert artifact_response.status_code == 200, artifact_response.text


@pytest.mark.anyio
async def test_phase_14_retry_dead_letters_job_after_max_attempts(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings.max_job_retries = 1

    failed_upload = await api_client.post(
        "/api/upload",
        files={"file": ("always-bad.pdf", _build_text_pdf([]), "application/pdf")},
    )
    assert failed_upload.status_code == 422

    failed_job = await _latest_job(db_session_factory)
    assert failed_job.status == "failed"
    assert failed_job.dead_letter is False

    retry_response = await api_client.post(f"/api/jobs/{failed_job.id}/retry")

    assert retry_response.status_code == 422
    assert retry_response.json()["detail"] == "processing_failed"

    job_response = await api_client.get(f"/api/jobs/{failed_job.id}")
    assert job_response.status_code == 200, job_response.text
    job_payload = job_response.json()
    assert job_payload["status"] == "dead_lettered"
    assert job_payload["retry_count"] == 1
    assert job_payload["dead_letter"] is True
    assert job_payload["retried"] is True
    assert job_payload["operator_note"] is not None
