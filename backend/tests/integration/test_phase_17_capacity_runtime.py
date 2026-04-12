from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.tables import BenchmarkRun, Job
from app.schemas.artifact import PatientArtifactSchema
from app.workers.pipeline import _JOB_RUNS
from tests.integration.helpers import reset_integration_db

pytestmark = pytest.mark.asyncio


def _build_text_pdf(lines: list[str], *, pages: int = 1) -> bytes:
    objects: list[bytes] = []
    page_object_numbers: list[int] = []
    next_object_number = 3

    for page_index in range(pages):
        content_lines = ["BT", "/F1 12 Tf", "72 720 Td"]
        for index, line in enumerate(lines):
            escaped_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if index:
                content_lines.append("0 -18 Td")
            content_lines.append(f"({escaped_line}) Tj")
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode("utf-8")

        page_object_number = next_object_number
        content_object_number = next_object_number + 1
        next_object_number += 2
        page_object_numbers.append(page_object_number)

        objects.append(
            f"{page_object_number} 0 obj\n"
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {next_object_number} 0 R >> >> "
            f"/Contents {content_object_number} 0 R >>\n"
            "endobj\n".encode("utf-8")
        )
        objects.append(
            f"{content_object_number} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("utf-8")
            + stream
            + b"\nendstream\nendobj\n"
        )

    font_object_number = next_object_number
    kids = " ".join(f"{number} 0 R" for number in page_object_numbers)

    header_objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        f"2 0 obj\n<< /Type /Pages /Count {pages} /Kids [{kids}] >>\nendobj\n".encode("utf-8"),
    ]

    objects = header_objects + objects
    objects.append(
        f"{font_object_number} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n".encode(
            "utf-8"
        )
    )

    buffer = BytesIO()
    buffer.write(f"%PDF-1.4\n%fixture:{uuid4()}\n".encode("utf-8"))
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


@pytest_asyncio.fixture(autouse=True)
async def integration_runtime_isolation(
    tmp_path: Path,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await reset_integration_db(db_session_factory)

    _JOB_RUNS.clear()
    original_artifact_store_path = settings.artifact_store_path
    original_max_upload_size_mb = settings.max_upload_size_mb
    original_max_pdf_pages = settings.max_pdf_pages
    settings.artifact_store_path = tmp_path / "artifacts"
    settings.image_beta_enabled = False
    try:
        yield
    finally:
        _JOB_RUNS.clear()
        settings.artifact_store_path = original_artifact_store_path
        settings.max_upload_size_mb = original_max_upload_size_mb
        settings.max_pdf_pages = original_max_pdf_pages


async def _job_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        result = await session.execute(select(Job))
        return len(list(result.scalars()))


async def _latest_job(session_factory: async_sessionmaker[AsyncSession]) -> Job:
    async with session_factory() as session:
        result = await session.execute(select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
        job = result.scalar_one_or_none()
        if job is None:
            raise AssertionError("expected persisted job")
        return job


async def _latest_benchmark(session_factory: async_sessionmaker[AsyncSession]) -> BenchmarkRun:
    async with session_factory() as session:
        result = await session.execute(
            select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc(), BenchmarkRun.id.desc()).limit(1)
        )
        benchmark = result.scalar_one_or_none()
        if benchmark is None:
            raise AssertionError("expected benchmark run")
        return benchmark


async def test_phase_17_upload_size_limit_rejects_before_persistence(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings.max_upload_size_mb = 0

    upload_response = await api_client.post(
        "/api/upload",
        files={"file": ("too-large.pdf", _build_text_pdf(["Glucose 180 mg/dL"]), "application/pdf")},
    )

    assert upload_response.status_code == 400
    assert upload_response.json()["detail"] == "file_too_large"
    assert await _job_count(db_session_factory) == 0


async def test_phase_17_pdf_page_limit_fails_safely_with_persisted_job(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings.max_pdf_pages = 1

    upload_response = await api_client.post(
        "/api/upload",
        files={"file": ("too-many-pages.pdf", _build_text_pdf(["Glucose 180 mg/dL"], pages=2), "application/pdf")},
    )

    assert upload_response.status_code == 422
    assert upload_response.json()["detail"] == "processing_failed"
    job = await _latest_job(db_session_factory)
    assert job.status == "failed"
    assert job.operator_note is not None
    assert "page_count_limit_exceeded" in job.operator_note


async def test_phase_17_benchmark_records_timing_signals(
    api_client: AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_response = await api_client.post(
        "/api/upload",
        files={"file": ("timed.pdf", _build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"]), "application/pdf")},
    )

    assert upload_response.status_code == 200, upload_response.text

    benchmark = await _latest_benchmark(db_session_factory)
    assert "processing_ms" in benchmark.metrics
    assert "extraction_ms" in benchmark.metrics
    assert benchmark.metrics["processing_ms"] >= benchmark.metrics["extraction_ms"] >= 0


async def test_phase_17_repeated_seeded_uploads_keep_artifacts_and_timing_stable(
    api_client: AsyncClient,
) -> None:
    seeded_uploads = [
        (
            "seeded-supported-a.pdf",
            ["Glucose 180 mg/dL", "HbA1c 6.8 %"],
            "completed",
        ),
        (
            "seeded-partial-a.pdf",
            ["Glucose 180 mg/dL", "MysteryMarker 7.2 zz"],
            "partial",
        ),
        (
            "seeded-supported-b.pdf",
            ["LDL-C 170 mg/dL", "HDL-C 35 mg/dL"],
            "completed",
        ),
    ]

    for filename, lines, expected_status in seeded_uploads:
        upload_response = await api_client.post(
            "/api/upload",
            files={"file": (filename, _build_text_pdf(lines), "application/pdf")},
        )

        assert upload_response.status_code == 200, upload_response.text
        upload_payload = upload_response.json()
        assert upload_payload["status"] == expected_status

        job_id = upload_payload["job_id"]

        status_response = await api_client.get(f"/api/jobs/{job_id}/status")
        assert status_response.status_code == 200, status_response.text
        status_payload = status_response.json()
        assert status_payload["status"] == expected_status
        assert status_payload["step"] == "lineage_persist"
        assert status_payload["status"] != "dead_lettered"

        proof_pack_response = await api_client.get(f"/api/jobs/{job_id}/proof-pack")
        assert proof_pack_response.status_code == 200, proof_pack_response.text
        proof_pack = proof_pack_response.json()
        assert proof_pack["artifact_refs"]["patient_artifact"] == f"/api/artifacts/{job_id}/patient"
        assert proof_pack["artifact_refs"]["clinician_artifact"] == (
            f"/api/artifacts/{job_id}/clinician"
        )
        assert proof_pack["artifact_refs"]["clinician_pdf"] == (
            f"/api/artifacts/{job_id}/clinician/pdf"
        )
        assert proof_pack["summary"]["timing"]["processing_ms"] >= (
            proof_pack["summary"]["timing"]["extraction_ms"]
        ) >= 0

        pdf_response = await api_client.get(f"/api/artifacts/{job_id}/clinician/pdf")
        assert pdf_response.status_code == 200, pdf_response.text
        assert pdf_response.headers["content-type"].startswith("application/pdf")
        assert pdf_response.content.startswith(b"%PDF-")

        patient_response = await api_client.get(f"/api/artifacts/{job_id}/patient")
        assert patient_response.status_code == 200, patient_response.text
        patient = PatientArtifactSchema.model_validate(patient_response.json())

        if expected_status == "partial":
            assert patient.support_banner.value == "partially_supported"
            assert patient.not_assessed
        else:
            assert patient.support_banner.value == "fully_supported"
