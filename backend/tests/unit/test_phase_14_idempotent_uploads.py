"""Phase 14 acceptance tests for idempotent upload/job behavior."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

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

from app.api.routes import upload as upload_route
from tests.support.pdf_builder import build_text_pdf


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

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        return None


class _DummySessionContext:
    def __init__(self, session: _DummySession) -> None:
        self._session = session

    async def __aenter__(self) -> _DummySession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def test_upload_route_reuses_existing_job_for_same_idempotency_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session = _DummySession()
    existing_job_id = uuid4()
    calls = {
        "create_document": 0,
        "create_job": 0,
        "pipeline": 0,
        "idempotency_key": None,
    }

    class FakeStore:
        def __init__(self, incoming_session: _DummySession) -> None:
            assert incoming_session is session

        async def get_job_by_idempotency_key(self, idempotency_key: str):
            calls["idempotency_key"] = idempotency_key
            return SimpleNamespace(
                id=existing_job_id,
                status="completed",
                lane_type="trusted_pdf",
            )

        async def create_document(self, **kwargs):
            calls["create_document"] += 1
            return SimpleNamespace(id=uuid4())

        async def create_job(self, **kwargs):
            calls["create_job"] += 1
            return SimpleNamespace(id=uuid4())

    class FakePipeline:
        async def run(self, *args, **kwargs):
            calls["pipeline"] += 1
            return {"status": "completed"}

    monkeypatch.setattr(upload_route, "TopLevelLifecycleStore", FakeStore)
    monkeypatch.setattr(upload_route, "PipelineOrchestrator", lambda: FakePipeline())
    monkeypatch.setattr(
        upload_route,
        "_write_upload_file",
        lambda **kwargs: tmp_path / "dedupe-upload.pdf",
    )

    response = asyncio.run(
        upload_route.upload_lab_report(
            _DummyUploadFile(
                filename="report.pdf",
                content_type="application/pdf",
                payload=build_text_pdf(["Glucose 180 mg/dL"]),
            ),
            session_factory=lambda: _DummySessionContext(session),
        )
    )

    assert response.job_id == existing_job_id
    assert response.status == "completed"
    assert response.lane_type == "trusted_pdf"
    assert response.message == "Upload already exists and was not reprocessed."
    assert calls["idempotency_key"] is not None
    assert calls["create_document"] == 0
    assert calls["create_job"] == 0
    assert calls["pipeline"] == 0
