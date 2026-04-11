from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text

from app.api.deps import get_session_factory
from app.config import settings
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


class _FailingSessionFactory:
    def __call__(self) -> "_FailingSessionFactory":
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


async def test_phase_15_readiness_and_metrics_cover_success_failure_and_partial(
    api_client: AsyncClient,
) -> None:
    readiness_response = await api_client.get("/api/health/ready")
    assert readiness_response.status_code == 200, readiness_response.text
    readiness_payload = readiness_response.json()
    assert readiness_payload["status"] == "ok"
    assert readiness_payload["checks"]["db_reachable"] is True
    assert readiness_payload["checks"]["artifact_store_writable"] is True

    success_response = await api_client.post(
        "/api/upload",
        files={"file": ("success.pdf", _build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"]), "application/pdf")},
        headers={"x-correlation-id": "obs-success"},
    )
    assert success_response.status_code == 200, success_response.text
    assert success_response.headers["x-correlation-id"] == "obs-success"

    partial_response = await api_client.post(
        "/api/upload",
        files={"file": ("partial.pdf", _build_text_pdf(["Glucose 180 mg/dL", "MysteryMarker 7.2 zz"]), "application/pdf")},
        headers={"x-correlation-id": "obs-partial"},
    )
    assert partial_response.status_code == 200, partial_response.text
    assert partial_response.headers["x-correlation-id"] == "obs-partial"

    failed_response = await api_client.post(
        "/api/upload",
        files={"file": ("failed.pdf", _build_text_pdf([]), "application/pdf")},
        headers={"x-correlation-id": "obs-failed"},
    )
    assert failed_response.status_code == 422
    assert failed_response.headers["x-correlation-id"] == "obs-failed"

    metrics_response = await api_client.get("/api/health/metrics")
    assert metrics_response.status_code == 200, metrics_response.text
    metrics_payload = metrics_response.json()
    assert metrics_payload["counters"]["upload_requests"] == 3
    assert metrics_payload["counters"]["jobs_completed"] == 1
    assert metrics_payload["counters"]["jobs_partial"] == 1
    assert metrics_payload["counters"]["jobs_failed"] == 1
    assert metrics_payload["counters"]["unsupported_inputs"] == 0
    assert metrics_payload["counters"]["persistence_fallbacks"] == 0


async def test_phase_15_correlation_id_and_metrics_cover_persistence_fallback(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing_factory = _FailingSessionFactory()
    app = api_client._transport.app
    monkeypatch.setitem(app.dependency_overrides, get_session_factory, lambda: failing_factory)

    upload_response = await api_client.post(
        "/api/upload",
        files={"file": ("fallback.pdf", _build_text_pdf(["Glucose 180 mg/dL", "HbA1c 6.8 %"]), "application/pdf")},
        headers={"x-correlation-id": "fallback-123"},
    )
    assert upload_response.status_code == 200, upload_response.text
    assert upload_response.headers["x-correlation-id"] == "fallback-123"

    metrics_response = await api_client.get("/api/health/metrics", headers={"x-correlation-id": "metrics-123"})
    assert metrics_response.status_code == 200, metrics_response.text
    assert metrics_response.headers["x-correlation-id"] == "metrics-123"
    metrics_payload = metrics_response.json()
    assert metrics_payload["counters"]["persistence_fallbacks"] == 1

    readiness_response = await api_client.get("/api/health/ready")
    assert readiness_response.status_code == 503, readiness_response.text
    readiness_payload = readiness_response.json()
    assert readiness_payload["status"] == "degraded"
    assert readiness_payload["checks"]["db_reachable"] is False
