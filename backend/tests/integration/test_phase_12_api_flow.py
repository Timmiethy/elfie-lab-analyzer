from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_session_factory
from app.config import settings
from app.models.tables import (
    BenchmarkRun,
    ClinicianArtifact,
    Document,
    ExtractedRow,
    Job,
    LineageRun,
    MappingCandidate,
    Observation,
    PatientArtifact,
    PolicyEvent,
    RuleEvent,
)
from app.schemas.artifact import ClinicianArtifactSchema, PatientArtifactSchema
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


class _FailingSessionFactory:
    def __call__(self) -> _FailingSessionFactory:
        return self

    async def __aenter__(self):
        raise OperationalError("db_unavailable", {}, Exception("database unavailable"))

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest_asyncio.fixture(autouse=True)
async def integration_runtime_isolation(
    tmp_path: Path,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await reset_integration_db(db_session_factory)

    _JOB_RUNS.clear()
    original_artifact_store_path = settings.artifact_store_path
    settings.artifact_store_path = tmp_path / "artifacts"
    settings.image_beta_enabled = False
    try:
        yield
    finally:
        _JOB_RUNS.clear()
        settings.artifact_store_path = original_artifact_store_path


async def _table_count(
    session_factory: async_sessionmaker[AsyncSession],
    model: type,
) -> int:
    async with session_factory() as session:
        result = await session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())


async def _latest_job(session_factory: async_sessionmaker[AsyncSession]) -> Job:
    async with session_factory() as session:
        result = await session.execute(
            select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(1)
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise AssertionError("expected a persisted job row")
        return job


async def _job_by_id(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
) -> Job:
    async with session_factory() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise AssertionError("expected a persisted job row")
        return job


async def test_phase_12_db_backed_upload_happy_path_persists_and_serves_artifacts(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pdf_bytes = _build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"])

    upload_response = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={"file": ("happy-path.pdf", pdf_bytes, "application/pdf")},
    )

    assert upload_response.status_code == 200, upload_response.text
    upload_payload = upload_response.json()
    job_id = upload_payload["job_id"]
    patient_res = await api_client.get(f"/api/artifacts/{job_id}/patient")
    print(patient_res.json())
    assert upload_payload["status"] == "completed"
    assert upload_payload["lane_type"] == "trusted_pdf"

    job_id = upload_payload["job_id"]

    status_response = await api_client.get(f"/api/jobs/{job_id}/status")
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["status"] == "completed"

    job_response = await api_client.get(f"/api/jobs/{job_id}")
    assert job_response.status_code == 200, job_response.text
    job_payload = job_response.json()
    assert job_payload["job_id"] == job_id
    assert job_payload["status"] == "completed"
    assert job_payload["lineage"] is not None

    patient_response = await api_client.get(f"/api/artifacts/{job_id}/patient")
    clinician_response = await api_client.get(f"/api/artifacts/{job_id}/clinician")
    assert patient_response.status_code == 200, patient_response.text
    assert clinician_response.status_code == 200, clinician_response.text

    try:
        patient_artifact = PatientArtifactSchema.model_validate(patient_response.json())
        clinician_artifact = ClinicianArtifactSchema.model_validate(clinician_response.json())
    except ValidationError as exc:  # pragma: no cover - assertion-friendly failure
        raise AssertionError(f"artifact schema validation failed: {exc}") from exc

    assert str(patient_artifact.job_id) == job_id
    assert str(clinician_artifact.job_id) == job_id
    assert patient_artifact.support_banner == "fully_supported"

    persisted_job = await _job_by_id(db_session_factory, job_id)
    async with db_session_factory() as session:
        persisted_document = await session.get(Document, persisted_job.document_id)
        assert persisted_document is not None
        assert (
            await session.execute(
                select(func.count())
                .select_from(PatientArtifact)
                .where(PatientArtifact.job_id == job_id)
            )
        ).scalar_one() == 1
        assert (
            await session.execute(
                select(func.count())
                .select_from(ClinicianArtifact)
                .where(ClinicianArtifact.job_id == job_id)
            )
        ).scalar_one() == 1
        assert (
            await session.execute(
                select(func.count()).select_from(LineageRun).where(LineageRun.job_id == job_id)
            )
        ).scalar_one() == 1
        lineage_result = await session.execute(
            select(LineageRun.id).where(LineageRun.job_id == job_id).limit(1)
        )
        lineage_id = lineage_result.scalar_one()
        assert (
            await session.execute(
                select(func.count())
                .select_from(BenchmarkRun)
                .where(BenchmarkRun.lineage_id == lineage_id)
            )
        ).scalar_one() == 1
        assert (
            await session.execute(
                select(func.count()).select_from(ExtractedRow).where(ExtractedRow.job_id == job_id)
            )
        ).scalar_one() == 2
        assert (
            await session.execute(
                select(func.count()).select_from(Observation).where(Observation.job_id == job_id)
            )
        ).scalar_one() == 2
        assert (
            await session.execute(
                select(func.count())
                .select_from(MappingCandidate)
                .join(Observation, MappingCandidate.observation_id == Observation.id)
                .where(Observation.job_id == job_id)
            )
        ).scalar_one() >= 2
        assert (
            await session.execute(
                select(func.count()).select_from(RuleEvent).where(RuleEvent.job_id == job_id)
            )
        ).scalar_one() >= 1
        assert (
            await session.execute(
                select(func.count()).select_from(PolicyEvent).where(PolicyEvent.job_id == job_id)
            )
        ).scalar_one() >= 1


async def test_phase_12_partial_support_pdf_is_exposed_as_partial_job(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pdf_bytes = _build_text_pdf(["Glucose 180 mg/dL", "MysteryMarker 7.2 zz"])

    upload_response = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={"file": ("partial-support.pdf", pdf_bytes, "application/pdf")},
    )

    assert upload_response.status_code == 200, upload_response.text
    upload_payload = upload_response.json()
    assert upload_payload["status"] == "partial"

    job_id = upload_payload["job_id"]
    patient_response = await api_client.get(f"/api/artifacts/{job_id}/patient")
    assert patient_response.status_code == 200, patient_response.text

    patient_artifact = PatientArtifactSchema.model_validate(patient_response.json())
    assert patient_artifact.support_banner == "partially_supported"

    persisted_job = await _job_by_id(db_session_factory, job_id)
    assert persisted_job.status == "partial"


async def test_phase_12_unsupported_mime_is_rejected_before_persistence(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pdf_bytes = _build_text_pdf(["Glucose 180 mg/dL"])

    upload_response = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={"file": ("wrong-mime.pdf", pdf_bytes, "image/png")},
    )

    assert upload_response.status_code == 400
    assert upload_response.json()["detail"] == "mime_type_mismatch:.pdf:image/png"
    assert await _table_count(db_session_factory, Document) == 0
    assert await _table_count(db_session_factory, Job) == 0


async def test_phase_12_image_beta_failure_is_safe_and_persisted(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_response = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={"file": ("beta-input.png", b"not-a-real-image", "image/png")},
    )

    assert upload_response.status_code == 422
    assert upload_response.json()["detail"] == "processing_failed"

    latest_job = await _latest_job(db_session_factory)
    assert latest_job.lane_type == "image_beta"
    assert latest_job.status == "failed"
    assert latest_job.operator_note is not None
    assert "image_beta_disabled" in latest_job.operator_note
    assert await _table_count(db_session_factory, Document) == 1
    assert await _table_count(db_session_factory, Job) == 1
    assert await _table_count(db_session_factory, PatientArtifact) == 0
    assert await _table_count(db_session_factory, ClinicianArtifact) == 0


async def test_phase_12_no_text_pdf_fails_safely_and_keeps_auditable_job(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    empty_pdf_bytes = _build_text_pdf([])

    upload_response = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={"file": ("no-text.pdf", empty_pdf_bytes, "application/pdf")},
    )

    assert upload_response.status_code == 422
    assert upload_response.json()["detail"] == "processing_failed"

    latest_job = await _latest_job(db_session_factory)
    assert latest_job.lane_type == "image_beta"
    assert latest_job.status == "failed"
    assert latest_job.operator_note is not None
    assert "image_beta_disabled" in latest_job.operator_note


async def test_phase_12_persistence_unavailable_falls_back_to_in_memory_runtime(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing_factory = _FailingSessionFactory()

    app = api_client._transport.app
    monkeypatch.setitem(app.dependency_overrides, get_session_factory, lambda: failing_factory)

    pdf_bytes = _build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"])

    upload_response = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={"file": ("fallback.pdf", pdf_bytes, "application/pdf")},
    )

    assert upload_response.status_code == 200, upload_response.text
    upload_payload = upload_response.json()
    assert upload_payload["status"] == "completed"
    assert (
        upload_payload["message"]
        == "Upload processed in memory because persistence is unavailable."
    )

    job_id = upload_payload["job_id"]
    job_response = await api_client.get(f"/api/jobs/{job_id}")
    patient_response = await api_client.get(f"/api/artifacts/{job_id}/patient")

    assert job_response.status_code == 200, job_response.text
    assert patient_response.status_code == 200, patient_response.text
    assert job_response.json()["status"] == "completed"
    PatientArtifactSchema.model_validate(patient_response.json())

    assert await _table_count(db_session_factory, Document) == 0
    assert await _table_count(db_session_factory, Job) == 0


async def test_phase_12_persistence_unavailable_unparsable_pdf_returns_processing_failed(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing_factory = _FailingSessionFactory()

    app = api_client._transport.app
    monkeypatch.setitem(app.dependency_overrides, get_session_factory, lambda: failing_factory)

    empty_pdf_bytes = _build_text_pdf([])

    upload_response = await api_client.post(
        "/api/upload",
        data={"age_years": 42.0, "sex": "female"},
        files={"file": ("fallback-no-text.pdf", empty_pdf_bytes, "application/pdf")},
    )

    assert upload_response.status_code == 422
    assert upload_response.json()["detail"] == "processing_failed"
    assert await _table_count(db_session_factory, Document) == 0
    assert await _table_count(db_session_factory, Job) == 0
