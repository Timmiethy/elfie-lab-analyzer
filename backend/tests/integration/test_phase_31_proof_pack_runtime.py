from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
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


async def test_phase_31_persisted_runtime_exposes_machine_readable_proof_pack(
    api_client: AsyncClient,
) -> None:
    upload_response = await api_client.post(
        "/api/upload",
        files={
            "file": (
                "proof-pack.pdf",
                _build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"]),
                "application/pdf",
            )
        },
    )

    assert upload_response.status_code == 200, upload_response.text
    job_id = upload_response.json()["job_id"]

    audit_response = await api_client.get(f"/api/jobs/{job_id}/audit")
    assert audit_response.status_code == 200, audit_response.text
    audit_payload = audit_response.json()
    assert audit_payload["proof_pack_available"] is True
    assert audit_payload["proof_pack_ref"]
    assert audit_payload["clinician_pdf_ref"] == f"/api/artifacts/{job_id}/clinician/pdf"
    assert audit_payload["clinician_pdf_available"] is True

    proof_pack_response = await api_client.get(f"/api/jobs/{job_id}/proof-pack")

    assert proof_pack_response.status_code == 200, proof_pack_response.text
    proof_pack = proof_pack_response.json()
    assert proof_pack["contract_version"] == "benchmark-proof-pack-v1"
    assert proof_pack["benchmark_contract_version"] == "benchmark-contract-v1"
    assert proof_pack["lineage"]["terminology_release"]
    assert proof_pack["artifact_refs"]["patient_artifact"] == f"/api/artifacts/{job_id}/patient"
    assert proof_pack["artifact_refs"]["clinician_artifact"] == f"/api/artifacts/{job_id}/clinician"
    assert proof_pack["artifact_refs"]["clinician_pdf"] == f"/api/artifacts/{job_id}/clinician/pdf"
    assert set(proof_pack["reports"]) == {
        "parser_report.json",
        "mapping_report.json",
        "policy_report.json",
        "coverage_report.json",
        "explanation_report.json",
        "patient_comprehension_report.json",
        "partial_support_report.json",
        "clinician_scan_report.json",
        "ablation_report.json",
    }

    parser_report = proof_pack["reports"]["parser_report.json"]
    assert parser_report["build_commit"]
    assert parser_report["corpus_id"] == "seeded-launch-corpus-v1"
    assert parser_report["lane_id"] == "trusted_pdf"
    assert parser_report["language_id"] == "en"
    assert parser_report["timestamp"]
    assert (
        parser_report["lineage_version_ids"]["terminology_release"]
        == proof_pack["lineage"]["terminology_release"]
    )

    pdf_response = await api_client.get(f"/api/artifacts/{job_id}/clinician/pdf")
    assert pdf_response.status_code == 200, pdf_response.text
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert pdf_response.content.startswith(b"%PDF-")
    assert b"Clinician Smoke Report" in pdf_response.content
