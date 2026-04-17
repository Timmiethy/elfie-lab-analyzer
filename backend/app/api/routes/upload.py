from __future__ import annotations

import logging
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
    file: UploadFile = File(...),
    age_years: float | None = Form(None),
    sex: str | None = Form(None),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> UploadResponse:
    """Accept a lab report file and create a job.

    When Postgres is reachable, the route persists the document and job first,
    then runs the current orchestration path and stores top-level outputs.
    When Postgres is unavailable, it falls back to the in-memory orchestration
    path so the working local scaffold remains usable.
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
        )
    except (InterfaceError, OperationalError, OSError):
        observability_metrics.record_persistence_fallback()
        return await _in_memory_upload_response(
            classification=classification,
            file_bytes=file_bytes,
            pipeline=pipeline,
            age_years=age_years,
            sex=sex,
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
) -> UploadResponse:
    idempotency_key = f"upload:{classification['checksum']}"

    # Single session spans idempotency check → document/job create → pipeline run.
    # No pre-pipeline commit: if the pipeline raises, the document/job rows are
    # rolled back so we never leave orphan persisted state. Job-failed bookkeeping
    # uses a *fresh* session afterwards so the failure record survives the rollback.
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
            # Flush (not commit) so pipeline can see the row via FK without
            # persisting past a later rollback.
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
                    # Another request won the idempotency race.
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
                    # Compatibility path when store lacks ON CONFLICT helper.
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

            await session.flush()
            job_id = job.id
            document_id = document.id

            result = await pipeline.run(
                str(job_id),
                file_bytes=file_bytes,
                lane_type=classification["lane_type"],
                db_session=session,
                document_id=document_id,
                source_checksum=classification["checksum"],
                age_years=age_years,
                sex=sex,
            )
            await session.commit()
    except (InterfaceError, OperationalError, OSError):
        # Bubble DB connectivity errors to the caller (in-memory fallback path).
        raise
    except Exception as exc:
        _LOGGER.error(
            "upload_processing_failed error=%s", exc, exc_info=True
        )
        # The single-session block above already rolled back on exit. Record the
        # failure in a fresh session so it survives.
        failed_job_id = locals().get("job_id")
        if failed_job_id is not None:
            await _update_job_status_in_fresh_session(
                str(failed_job_id),
                status="failed",
                operator_note=str(exc),
                session_factory=session_factory,
            )
        observability_metrics.record_job_outcome("failed")
        if str(exc) in _PAYLOAD_LIMIT_ERRORS:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        raise HTTPException(
            status_code=422,
            detail=_PROCESSING_FAILED_DETAIL,
        ) from exc

    observability_metrics.record_job_outcome(str(result["status"]))
    return UploadResponse(
        job_id=job_id,
        status=result["status"],
        lane_type=classification["lane_type"],
        message="Upload persisted and processed.",
    )


async def _in_memory_upload_response(
    *,
    classification: dict,
    file_bytes: bytes,
    pipeline: PipelineOrchestrator,
    age_years: float | None = None,
    sex: str | None = None,
) -> UploadResponse:
    job_id = uuid5(NAMESPACE_URL, f"upload:{classification['checksum']}")
    try:
        result = await pipeline.run(
            str(job_id),
            file_bytes=file_bytes,
            lane_type=classification["lane_type"],
            source_checksum=classification["checksum"],
            age_years=age_years,
            sex=sex,
        )
    except Exception as exc:
        observability_metrics.record_job_outcome("failed")
        if str(exc) in _PAYLOAD_LIMIT_ERRORS:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        raise HTTPException(
            status_code=422,
            detail=_PROCESSING_FAILED_DETAIL,
        ) from exc

    observability_metrics.record_job_outcome(str(result["status"]))

    return UploadResponse(
        job_id=job_id,
        status=result["status"],
        lane_type=classification["lane_type"],
        message="Upload processed in memory because persistence is unavailable.",
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
