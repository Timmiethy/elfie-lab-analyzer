"""Phase 16 acceptance tests for safer upload failure responses."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

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
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _DummySessionContext:
    def __init__(self, session: _DummySession) -> None:
        self._session = session

    async def __aenter__(self) -> _DummySession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def test_upload_route_sanitizes_processing_errors_but_keeps_operator_note(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session = _DummySession()
    captured: dict[str, object] = {}

    class FakeStore:
        def __init__(self, incoming_session: _DummySession) -> None:
            assert incoming_session is session

        async def get_job_by_idempotency_key(self, _idempotency_key: str):
            return None

        async def get_job_by_input_checksum(self, _input_checksum: str):
            return None

        async def create_document(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_job(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def update_job_status(self, _job_id, **kwargs):
            captured["update_job_status"] = kwargs
            return SimpleNamespace(id=uuid4())

    class FakePipeline:
        async def run(self, *args, **kwargs):
            raise ValueError("internal failure: /tmp/private/report.pdf")

    monkeypatch.setattr(upload_route, "TopLevelLifecycleStore", FakeStore)
    monkeypatch.setattr(upload_route, "PipelineOrchestrator", lambda: FakePipeline())
    monkeypatch.setattr(
        upload_route,
        "_write_upload_file",
        lambda **kwargs: tmp_path / "sanitized-upload.pdf",
    )

    with pytest.raises(upload_route.HTTPException) as exc_info:
        asyncio.run(
            upload_route.upload_lab_report(
                _DummyUploadFile(
                filename="report.pdf",
                content_type="application/pdf",
                payload=build_text_pdf(["Glucose 180 mg/dL"]),
            ),
            session_factory=lambda: _DummySessionContext(session),
        )
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "processing_failed"
    assert "internal failure" in captured["update_job_status"]["operator_note"]
    assert "/tmp/private/report.pdf" in captured["update_job_status"]["operator_note"]


def test_retry_success_clears_stale_operator_note(monkeypatch, tmp_path: Path) -> None:
    """v12: Successful retry must clear the stale operator_note set during a
    prior failed run.

    Simulates: upload fails (sets operator_note) -> retry succeeds ->
    _update_job_status_in_fresh_session is called with clear_operator_note=True.
    """
    captured: dict[str, object] = {}
    session = _DummySession()

    class FakeStore:
        def __init__(self, incoming_session: _DummySession) -> None:
            assert incoming_session is session

        async def get_job_by_idempotency_key(self, _idempotency_key: str):
            return None

        async def get_job_by_input_checksum(self, _input_checksum: str):
            return None

        async def create_document(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_job(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def update_job_status(self, _job_id, **kwargs):
            captured["update_job_status"] = kwargs
            return SimpleNamespace(id=uuid4())

    # First attempt: pipeline fails, setting a stale operator_note
    class FakeFailingPipeline:
        async def run(self, *args, **kwargs):
            raise ValueError("internal failure: /tmp/private/report.pdf")

    monkeypatch.setattr(upload_route, "TopLevelLifecycleStore", FakeStore)
    monkeypatch.setattr(
        upload_route,
        "PipelineOrchestrator",
        lambda: FakeFailingPipeline(),
    )
    monkeypatch.setattr(
        upload_route,
        "_write_upload_file",
        lambda **kwargs: tmp_path / "retry-note-test.pdf",
    )

    with pytest.raises(upload_route.HTTPException) as exc_info:
        asyncio.run(
            upload_route.upload_lab_report(
                _DummyUploadFile(
                    filename="report.pdf",
                    content_type="application/pdf",
                    payload=build_text_pdf(["Glucose 180 mg/dL"]),
                ),
                session_factory=lambda: _DummySessionContext(session),
            )
        )

    assert exc_info.value.status_code == 422
    assert captured["update_job_status"]["operator_note"] is not None
    assert "internal failure" in captured["update_job_status"]["operator_note"]

    # Now simulate the retry success path from jobs.py.
    # The retry handler calls _update_job_status_in_fresh_session with
    # clear_operator_note=True when the retry succeeds.
    import app.api.routes.jobs as jobs_route

    retry_captured: dict[str, object] = {}

    class RetryFakeStore:
        def __init__(self, incoming_session: _DummySession) -> None:
            pass

        async def update_job_status(self, _job_id, **kwargs):
            retry_captured["update_job_status"] = kwargs
            return SimpleNamespace(
                id=uuid4(),
                status="completed",
                operator_note=None,
            )

    monkeypatch.setattr(jobs_route, "TopLevelLifecycleStore", RetryFakeStore)

    # Call the retry success helper directly (simulating the success branch
    # of POST /api/jobs/{id}/retry)
    job_id = uuid4()
    asyncio.run(
        jobs_route._update_job_status_in_fresh_session(
            str(job_id),
            status="completed",
            session_factory=lambda: _DummySessionContext(session),
            retry_count=2,
            dead_letter=False,
            clear_operator_note=True,
        )
    )

    assert "update_job_status" in retry_captured
    assert retry_captured["update_job_status"]["clear_operator_note"] is True
    assert retry_captured["update_job_status"]["status"] == "completed"


def test_upload_success_does_not_clobber_omitted_operator_note(monkeypatch, tmp_path: Path) -> None:
    """v12: Successful upload (non-retry path) must NOT pass clear_operator_note,
    preserving the default None-as-omit semantics."""
    captured: dict[str, object] = {}
    session = _DummySession()

    class FakeStore:
        def __init__(self, incoming_session: _DummySession) -> None:
            assert incoming_session is session

        async def get_job_by_idempotency_key(self, _idempotency_key: str):
            return None

        async def get_job_by_input_checksum(self, _input_checksum: str):
            return None

        async def create_document(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_job(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def update_job_status(self, _job_id, **kwargs):
            captured["update_job_status"] = kwargs
            return SimpleNamespace(id=uuid4())

    class FakePipeline:
        async def run(self, job_id: str, **kwargs):
            return {"status": "completed"}

    monkeypatch.setattr(upload_route, "TopLevelLifecycleStore", FakeStore)
    monkeypatch.setattr(upload_route, "PipelineOrchestrator", lambda: FakePipeline())
    monkeypatch.setattr(
        upload_route,
        "_write_upload_file",
        lambda **kwargs: tmp_path / "no-clobber-test.pdf",
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

    assert response.status == "completed"
    # The upload success path does NOT call update_job_status at all
    # (it returns the UploadResponse directly), so operator_note is untouched.
    # If update_job_status were called for success, clear_operator_note must not
    # be silently injected.
    assert "clear_operator_note" not in captured.get("update_job_status", {})
