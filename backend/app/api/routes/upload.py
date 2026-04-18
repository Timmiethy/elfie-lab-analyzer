from __future__ import annotations

import logging
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth import CurrentUserId
from app.api.deps import get_session_factory
from app.config import settings
from app.db import TopLevelLifecycleStore
from app.schemas.upload import UploadResponse
from app.services.input_gateway import InputGateway
from app.services.observability import observability_metrics
from app.services.privacy import write_private_file
from app.workers.pipeline import PipelineOrchestrator

router = APIRouter()
_PROCESSING_FAILED_DETAIL = "processing_failed"
_LOGGER = logging.getLogger(__name__)
_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
_PAYLOAD_LIMIT_ERRORS = {
    "page_count_limit_exceeded",
    "pdf_render_bytes_limit_exceeded",
}


@router.post("")
async def upload_lab_report(
    user_id: CurrentUserId,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    age_years: float | None = Form(None),
    sex: str | None = Form(None),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> UploadResponse:
    """Accept a lab report file, create a pending job, schedule processing in background.

    HTTP returns as soon as the job row is committed so the frontend polling
    screen renders immediately. The 14-stage pipeline runs asynchronously via
    FastAPI BackgroundTasks using its own DB session; per-stage progress is
    surfaced through jobs.current_step (polled by the UI).
    """

    gateway = InputGateway()
    pipeline = PipelineOrchestrator()
    observability_metrics.record_upload_request()

    try:
        _max_bytes = settings.max_upload_size_mb * 1024 * 1024
        file_bytes = await _read_upload_bytes_limited(file, max_bytes=_max_bytes)
        classification = await gateway.classify(
            file_bytes=file_bytes,
            filename=file.filename or "",
            mime_type=file.content_type or "",
        )
    except ValueError as exc:
        observability_metrics.record_unsupported_input()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if classification["lane_type"] == "image_beta" and not settings.image_beta_enabled:
        observability_metrics.record_unsupported_input()
        raise HTTPException(status_code=400, detail="image_beta_disabled")

    try:
        return await _persisted_upload_response(
            classification=classification,
            file_bytes=file_bytes,
            pipeline=pipeline,
            session_factory=session_factory,
            user_id=user_id,
            age_years=age_years,
            sex=sex,
            background_tasks=background_tasks,
        )
    except (InterfaceError, OperationalError, OSError):
        observability_metrics.record_persistence_fallback()
        return await _in_memory_upload_response(
            classification=classification,
            file_bytes=file_bytes,
            pipeline=pipeline,
            age_years=age_years,
            sex=sex,
            background_tasks=background_tasks,
        )


async def _persisted_upload_response(
    *,
    classification: dict,
    file_bytes: bytes,
    pipeline: PipelineOrchestrator,
    session_factory: async_sessionmaker[AsyncSession],
    user_id: UUID,
    age_years: float | None = None,
    sex: str | None = None,
    background_tasks: BackgroundTasks,
) -> UploadResponse:
    idempotency_key = f"upload:{classification['checksum']}"

    # Commit the job row up-front so the frontend polling screen can see
    # status=pending + job_id immediately. Pipeline runs asynchronously in a
    # BackgroundTask using its own session; failures mark the job via a fresh
    # session inside the background runner.
    try:
        async with session_factory() as session:
            store = TopLevelLifecycleStore(session)
            existing_job = await store.get_job_by_idempotency_key(
                idempotency_key,
                user_id=user_id,
            )
            if existing_job is None:
                get_by_checksum = getattr(store, "get_job_by_input_checksum", None)
                if get_by_checksum is not None:
                    existing_job = await get_by_checksum(
                        classification["checksum"],
                        user_id=user_id,
                    )

            if existing_job is not None:
                return UploadResponse(
                    job_id=existing_job.id,
                    status=existing_job.status,
                    lane_type=existing_job.lane_type,
                    message="Upload already exists and was not reprocessed.",
                )

            storage_path = _write_upload_file(
                checksum=classification["checksum"],
                filename=classification["sanitized_filename"],
                file_bytes=file_bytes,
            )

            document = await store.create_document(
                checksum=classification["checksum"],
                filename=classification["sanitized_filename"],
                mime_type=classification["mime_type"],
                file_size_bytes=classification["file_size_bytes"],
                lane_type=classification["lane_type"],
                storage_path=storage_path.as_posix(),
                user_id=user_id,
            )
            await session.flush()

            create_job_on_conflict = getattr(store, "create_job_on_conflict_do_nothing", None)
            if callable(create_job_on_conflict):
                job = await create_job_on_conflict(
                    document_id=document.id,
                    idempotency_key=idempotency_key,
                    input_checksum=classification["checksum"],
                    lane_type=classification["lane_type"],
                    status="pending",
                    user_id=user_id,
                )
                if job is None:
                    await session.rollback()
                    existing_job = await store.get_job_by_idempotency_key(
                        idempotency_key,
                        user_id=user_id,
                    )
                    if existing_job is None:
                        raise RuntimeError("idempotency_conflict_without_existing_job")
                    return UploadResponse(
                        job_id=existing_job.id,
                        status=existing_job.status,
                        lane_type=existing_job.lane_type,
                        message="Upload already exists and was not reprocessed.",
                    )
            else:
                try:
                    job = await store.create_job(
                        document_id=document.id,
                        idempotency_key=idempotency_key,
                        input_checksum=classification["checksum"],
                        lane_type=classification["lane_type"],
                        status="pending",
                        user_id=user_id,
                    )
                except IntegrityError:
                    await session.rollback()
                    existing_job = await store.get_job_by_idempotency_key(
                        idempotency_key,
                        user_id=user_id,
                    )
                    if existing_job is None:
                        raise
                    return UploadResponse(
                        job_id=existing_job.id,
                        status=existing_job.status,
                        lane_type=existing_job.lane_type,
                        message="Upload already exists and was not reprocessed.",
                    )

            await session.commit()
            job_id = job.id
            document_id = document.id
    except (InterfaceError, OperationalError, OSError):
        raise

    background_tasks.add_task(
        _run_pipeline_background,
        job_id=str(job_id),
        file_bytes=file_bytes,
        lane_type=classification["lane_type"],
        document_id=str(document_id),
        source_checksum=classification["checksum"],
        age_years=age_years,
        sex=sex,
        session_factory=session_factory,
    )

    return UploadResponse(
        job_id=job_id,
        status="pending",
        lane_type=classification["lane_type"],
        message="Upload accepted — processing in background.",
    )


async def _run_pipeline_background(
    *,
    job_id: str,
    file_bytes: bytes,
    lane_type: str,
    document_id: str,
    source_checksum: str,
    age_years: float | None,
    sex: str | None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run the orchestrator outside the request scope.

    Uses a dedicated session so commits (incl. per-stage progress) are visible
    to polling reads. On exception, marks the job failed via a fresh session.
    """
    pipeline = PipelineOrchestrator()
    try:
        async with session_factory() as session:
            result = await pipeline.run(
                job_id,
                file_bytes=file_bytes,
                lane_type=lane_type,
                db_session=session,
                document_id=document_id,
                source_checksum=source_checksum,
                age_years=age_years,
                sex=sex,
            )
            await session.commit()
        observability_metrics.record_job_outcome(str(result["status"]))
    except Exception as exc:
        _LOGGER.error("background_pipeline_failed job_id=%s err=%s", job_id, exc, exc_info=True)
        try:
            await _update_job_status_in_fresh_session(
                job_id,
                status="failed",
                operator_note=str(exc),
                session_factory=session_factory,
            )
        except Exception:
            pass
        observability_metrics.record_job_outcome("failed")


async def _in_memory_upload_response(
    *,
    classification: dict,
    file_bytes: bytes,
    pipeline: PipelineOrchestrator,
    age_years: float | None = None,
    sex: str | None = None,
    background_tasks: BackgroundTasks,
) -> UploadResponse:
    job_id = uuid5(NAMESPACE_URL, f"upload:{classification['checksum']}")

    # Pre-seed job run so polling gets status=pending immediately.
    from app.workers.pipeline import _JOB_RUNS  # type: ignore
    _JOB_RUNS[str(job_id)] = {
        "status": "pending",
        "lane_type": classification["lane_type"],
    }

    async def _run() -> None:
        try:
            result = await pipeline.run(
                str(job_id),
                file_bytes=file_bytes,
                lane_type=classification["lane_type"],
                source_checksum=classification["checksum"],
                age_years=age_years,
                sex=sex,
            )
            observability_metrics.record_job_outcome(str(result["status"]))
        except Exception as exc:
            _LOGGER.error("in_memory_pipeline_failed job_id=%s err=%s", job_id, exc, exc_info=True)
            observability_metrics.record_job_outcome("failed")
            _JOB_RUNS[str(job_id)] = {
                "status": "failed",
                "lane_type": classification["lane_type"],
                "operator_note": str(exc),
            }

    background_tasks.add_task(_run)

    return UploadResponse(
        job_id=job_id,
        status="pending",
        lane_type=classification["lane_type"],
        message="Upload accepted (in-memory) — processing in background.",
    )


def _write_upload_file(*, checksum: str, filename: str, file_bytes: bytes) -> Path:
    uploads_dir = settings.artifact_store_path / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    try:
        uploads_dir.chmod(0o700)
    except OSError:
        pass
    safe_name = f"{checksum[:12]}_{Path(filename).name}"
    destination = uploads_dir / safe_name
    write_private_file(destination, file_bytes)
    return destination


async def _update_job_status_in_fresh_session(
    job_id: str,
    *,
    status: str,
    session_factory: async_sessionmaker[AsyncSession],
    retry_count: int | None = None,
    dead_letter: bool | None = None,
    operator_note: str | None = None,
) -> None:
    async with session_factory() as session:
        store = TopLevelLifecycleStore(session)
        await store.update_job_status(
            job_id,
            status=status,
            retry_count=retry_count,
            dead_letter=dead_letter,
            operator_note=operator_note,
        )
        await session.commit()


async def _read_upload_bytes_limited(file: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    supports_chunk_size = True

    while True:
        if supports_chunk_size:
            try:
                chunk = await file.read(_UPLOAD_READ_CHUNK_BYTES)
            except TypeError:
                # Unit-test doubles may not accept a chunk-size arg.
                supports_chunk_size = False
                chunk = await file.read()
        else:
            chunk = await file.read()

        if not chunk:
            break

        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise HTTPException(status_code=400, detail="file_too_large")
        chunks.append(chunk)

        if not supports_chunk_size:
            break

        if len(chunk) < _UPLOAD_READ_CHUNK_BYTES:
            break

    return b"".join(chunks)
