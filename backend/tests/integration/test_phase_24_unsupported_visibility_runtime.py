from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.schemas.artifact import ClinicianArtifactSchema, PatientArtifactSchema
from app.workers.pipeline import _JOB_RUNS
from tests.integration.helpers import reset_integration_db

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


async def test_phase_24_partial_support_runtime_keeps_unsupported_rows_visible_in_both_artifacts(
    api_client: AsyncClient,
) -> None:
    pdf_bytes = _build_text_pdf(["Glucose 180 mg/dL", "MysteryMarker 7.2 zz"])

    upload_response = await api_client.post(
        "/api/upload",
        files={"file": ("partial-support.pdf", pdf_bytes, "application/pdf")},
    )

    assert upload_response.status_code == 200, upload_response.text
    upload_payload = upload_response.json()
    assert upload_payload["status"] == "partial"

    job_id = upload_payload["job_id"]
    patient_response = await api_client.get(f"/api/artifacts/{job_id}/patient")
    clinician_response = await api_client.get(f"/api/artifacts/{job_id}/clinician")

    assert patient_response.status_code == 200, patient_response.text
    assert clinician_response.status_code == 200, clinician_response.text

    patient = PatientArtifactSchema.model_validate(patient_response.json())
    clinician = ClinicianArtifactSchema.model_validate(clinician_response.json())

    assert patient.support_banner.value == "partially_supported"
    assert patient.not_assessed, "partial-support patient artifact must not hide unsupported rows"
    assert clinician.not_assessed, "clinician artifact must preserve unsupported row visibility"
    assert {item.raw_label for item in patient.not_assessed} >= {"MysteryMarker"}
    assert {item.raw_label for item in clinician.not_assessed} >= {"MysteryMarker"}
