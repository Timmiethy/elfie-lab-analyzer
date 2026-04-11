"""Phase 9 acceptance tests for the top-level persistence bridge."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str) -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def include_router(self, *_args, **_kwargs) -> None:
            return None

        def get(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

    def File(*_args, **_kwargs):
        return None

    class UploadFile:
        pass

    fastapi_stub.APIRouter = APIRouter
    fastapi_stub.File = File
    fastapi_stub.HTTPException = HTTPException
    fastapi_stub.UploadFile = UploadFile
    sys.modules["fastapi"] = fastapi_stub

if "app.db.session" not in sys.modules:
    db_session_stub = types.ModuleType("app.db.session")

    def _unpatched_async_session_factory():
        raise RuntimeError("async_session_factory must be monkeypatched in tests")

    db_session_stub.async_session_factory = _unpatched_async_session_factory
    sys.modules["app.db.session"] = db_session_stub

from app.api.routes import artifacts as artifacts_route
from app.api.routes import jobs as jobs_route
from app.api.routes import upload as upload_route
from app.workers import pipeline as pipeline_module


class _DummyUploadFile:
    def __init__(self, *, filename: str, content_type: str, payload: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self._payload = payload

    async def read(self) -> bytes:
        return self._payload


class _DummySession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


class _DummySessionContext:
    def __init__(self, session: _DummySession) -> None:
        self._session = session

    async def __aenter__(self) -> _DummySession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def test_upload_route_uses_persisted_job_path_when_db_session_is_available(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session = _DummySession()
    calls: dict[str, object] = {}
    document_id = uuid4()
    job_id = uuid4()

    class FakeStore:
        def __init__(self, incoming_session: _DummySession) -> None:
            assert incoming_session is session

        async def get_job_by_idempotency_key(self, _idempotency_key: str):
            return None

        async def get_job_by_input_checksum(self, _input_checksum: str):
            return None

        async def create_document(self, **kwargs):
            calls["document"] = kwargs
            return SimpleNamespace(id=document_id)

        async def create_job(self, **kwargs):
            calls["job"] = kwargs
            return SimpleNamespace(id=job_id)

        async def update_job_status(self, *args, **kwargs):
            calls["failed_status"] = kwargs
            return SimpleNamespace(id=job_id)

    class FakePipeline:
        async def run(self, job_id: str, **kwargs):
            calls["pipeline"] = {"job_id": job_id, **kwargs}
            return {"status": "completed"}

    monkeypatch.setattr(upload_route, "TopLevelLifecycleStore", FakeStore)
    monkeypatch.setattr(upload_route, "PipelineOrchestrator", lambda: FakePipeline())
    monkeypatch.setattr(
        upload_route,
        "_write_upload_file",
        lambda **kwargs: tmp_path / "persisted-upload.pdf",
    )

    response = asyncio.run(
        upload_route.upload_lab_report(
            _DummyUploadFile(
                filename="report.pdf",
                content_type="application/pdf",
                payload=b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n",
            ),
            session_factory=lambda: _DummySessionContext(session),
        )
    )

    assert response.job_id == job_id
    assert response.status == "completed"
    assert response.lane_type == "trusted_pdf"
    assert response.message == "Upload persisted and processed."
    assert calls["document"]["lane_type"] == "trusted_pdf"
    assert calls["job"]["document_id"] == document_id
    assert calls["pipeline"]["job_id"] == str(job_id)
    assert calls["pipeline"]["db_session"] is session
    assert session.commit_calls >= 2
    assert session.rollback_calls == 0


def test_jobs_route_prefers_persisted_job_records_over_in_memory_fallback(monkeypatch) -> None:
    job_id = uuid4()

    class FakeStore:
        def __init__(self, session: _DummySession) -> None:
            pass

        async def get_job(self, incoming_job_id: str):
            assert incoming_job_id == str(job_id)
            return SimpleNamespace(id=job_id, status="completed", lane_type="trusted_pdf")

        async def get_latest_lineage_run(self, incoming_job_id: str):
            assert incoming_job_id == str(job_id)
            return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(jobs_route, "TopLevelLifecycleStore", FakeStore)
    monkeypatch.setattr(
        jobs_route,
        "get_job_run",
        lambda _job_id: {"status": "memory-only", "lane_type": "image_beta"},
    )

    payload = asyncio.run(
        jobs_route.get_job(
            job_id,
            session_factory=lambda: _DummySessionContext(_DummySession()),
        )
    )

    assert payload["job_id"] == str(job_id)
    assert payload["status"] == "completed"
    assert payload["lane_type"] == "trusted_pdf"
    assert payload["lineage"] is not None


def test_artifacts_route_prefers_persisted_artifacts_over_in_memory_fallback(monkeypatch) -> None:
    job_id = uuid4()
    patient_artifact = {"job_id": str(job_id), "support_banner": "fully_supported"}
    clinician_artifact = {"job_id": str(job_id), "support_coverage": "fully_supported"}

    class FakeStore:
        def __init__(self, session: _DummySession) -> None:
            pass

        async def get_patient_artifact(self, incoming_job_id: str):
            assert incoming_job_id == str(job_id)
            return SimpleNamespace(content=patient_artifact)

        async def get_clinician_artifact(self, incoming_job_id: str):
            assert incoming_job_id == str(job_id)
            return SimpleNamespace(content=clinician_artifact)

    monkeypatch.setattr(artifacts_route, "TopLevelLifecycleStore", FakeStore)
    monkeypatch.setattr(
        artifacts_route,
        "get_job_run",
        lambda _job_id: {
            "patient_artifact": {"source": "memory"},
            "clinician_artifact": {"source": "memory"},
        },
    )

    patient_payload = asyncio.run(
        artifacts_route.get_patient_artifact(
            job_id,
            session_factory=lambda: _DummySessionContext(_DummySession()),
        )
    )
    clinician_payload = asyncio.run(
        artifacts_route.get_clinician_artifact(
            job_id,
            session_factory=lambda: _DummySessionContext(_DummySession()),
        )
    )

    assert patient_payload == patient_artifact
    assert clinician_payload == clinician_artifact


def test_pipeline_persists_top_level_bundle_when_db_session_is_provided(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeStore:
        def __init__(self, session: object) -> None:
            calls["session"] = session

        async def create_extracted_row(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_observation(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_mapping_candidate(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_rule_event(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_policy_event(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def persist_top_level_bundle(self, **kwargs):
            calls["bundle"] = kwargs

    monkeypatch.setattr(pipeline_module, "TopLevelLifecycleStore", FakeStore)

    result = asyncio.run(
        pipeline_module.PipelineOrchestrator().run(
            "phase-9-job",
            db_session=object(),
        )
    )

    assert result["status"] in {"completed", "partial"}
    assert "bundle" in calls
    assert calls["bundle"]["status"] == result["status"]
    assert "patient_artifact" in calls["bundle"]
    assert "clinician_artifact" in calls["bundle"]
    assert "lineage_run" in calls["bundle"]
    assert "benchmark_run" in calls["bundle"]
