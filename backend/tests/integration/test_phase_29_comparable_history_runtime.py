from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.schemas.artifact import PatientArtifactSchema
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
async def runtime_isolation(
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


async def test_phase_29_first_supported_run_surfaces_unavailable_comparable_history(
    api_client: AsyncClient,
) -> None:
    upload_response = await api_client.post(
        "/api/upload",
        files={
            "file": (
                "glucose-first.pdf",
                _build_text_pdf(["Glucose 96 mg/dL 70-99"]),
                "application/pdf",
            )
        },
    )

    assert upload_response.status_code == 200, upload_response.text
    job_id = upload_response.json()["job_id"]

    patient_response = await api_client.get(f"/api/artifacts/{job_id}/patient")

    assert patient_response.status_code == 200, patient_response.text
    patient = PatientArtifactSchema.model_validate(patient_response.json())

    assert patient.comparable_history is not None
    assert patient.comparable_history.comparability_status == "unavailable"
    assert patient.comparable_history.direction == "trend_unavailable"
    assert all(
        forbidden not in patient.comparable_history.direction
        for forbidden in ["improving", "worsening", "better", "worse"]
    )
    assert {item.reason.value for item in patient.not_assessed} >= {
        "comparable_history_unavailable"
    }


async def test_phase_29_second_supported_run_surfaces_available_comparable_history(
    api_client: AsyncClient,
) -> None:
    first_upload = await api_client.post(
        "/api/upload",
        files={
            "file": (
                "glucose-earlier.pdf",
                _build_text_pdf(["Glucose 96 mg/dL 70-99"]),
                "application/pdf",
            )
        },
    )
    assert first_upload.status_code == 200, first_upload.text

    second_upload = await api_client.post(
        "/api/upload",
        files={
            "file": (
                "glucose-later.pdf",
                _build_text_pdf(["Glucose 110 mg/dL 70-99"]),
                "application/pdf",
            )
        },
    )
    assert second_upload.status_code == 200, second_upload.text
    job_id = second_upload.json()["job_id"]

    patient_response = await api_client.get(f"/api/artifacts/{job_id}/patient")

    assert patient_response.status_code == 200, patient_response.text
    patient = PatientArtifactSchema.model_validate(patient_response.json())

    assert patient.comparable_history is not None
    assert patient.comparable_history.comparability_status == "available"
    assert patient.comparable_history.direction == "increased"
    assert patient.comparable_history.previous_value == "96"
    assert patient.comparable_history.current_value == "110"
    assert patient.comparable_history.previous_date is not None
    assert patient.comparable_history.current_date is not None
