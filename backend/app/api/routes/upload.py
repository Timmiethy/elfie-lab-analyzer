from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


@router.post("")
async def upload_lab_report(
    file: UploadFile = File(...),
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
        file_bytes = await file.read()
        if len(file_bytes) > settings.max_upload_size_mb * 1024 * 1024:
            raise HTTPException(status_code=400, detail="file_too_large")
        classification = await gateway.classify(
            file_bytes=file_bytes,
            filename=file.filename or "",
            mime_type=file.content_type or "",
        )
    except ValueError as exc:
        observability_metrics.record_unsupported_input()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return await _persisted_upload_response(
            classification=classification,
            file_bytes=file_bytes,
            pipeline=pipeline,
            session_factory=session_factory,
        )
    except (InterfaceError, OperationalError):
        observability_metrics.record_persistence_fallback()
        return await _in_memory_upload_response(
            classification=classification,
            file_bytes=file_bytes,
            pipeline=pipeline,
        )


async def _persisted_upload_response(
    *,
    classification: dict,
    file_bytes: bytes,
    pipeline: PipelineOrchestrator,
    session_factory: async_sessionmaker[AsyncSession],
) -> UploadResponse:
    idempotency_key = f"upload:{classification['checksum']}"

    async with session_factory() as session:
        store = TopLevelLifecycleStore(session)
        existing_job = await store.get_job_by_idempotency_key(idempotency_key)
        if existing_job is None:
            get_by_checksum = getattr(store, "get_job_by_input_checksum", None)
            if get_by_checksum is not None:
                existing_job = await get_by_checksum(classification["checksum"])

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
            page_count=classification.get("page_count"),
            lane_type=classification["lane_type"],
            document_class=classification.get("document_class"),
            preflight_failure_code=classification.get("failure_code"),
            duplicate_state=classification.get("duplicate_state"),
            promotion_status=classification.get("promotion_status"),
            text_extractability=str(classification.get("text_extractability"))
            if classification.get("text_extractability") is not None
            else None,
            image_density=str(classification.get("image_density"))
            if classification.get("image_density") is not None
            else None,
            storage_path=str(storage_path),
        )
        job = await store.create_job(
            document_id=document.id,
            idempotency_key=idempotency_key,
            input_checksum=classification["checksum"],
            lane_type=classification["lane_type"],
            status="pending",
        )
        job_id = job.id
        document_id = document.id
        await session.commit()

    try:
        async with session_factory() as session:
            result = await pipeline.run(
                str(job_id),
                file_bytes=file_bytes,
                lane_type=classification["lane_type"],
                db_session=session,
                document_id=document_id,
                source_checksum=classification["checksum"],
            )
            await session.commit()
    except Exception as exc:
        await _update_job_status_in_fresh_session(
            str(job_id),
            status="failed",
            operator_note=str(exc),
            session_factory=session_factory,
        )
        observability_metrics.record_job_outcome("failed")
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
) -> UploadResponse:
    job_id = uuid5(NAMESPACE_URL, f"upload:{classification['checksum']}")
    try:
        result = await pipeline.run(
            str(job_id),
            file_bytes=file_bytes,
            lane_type=classification["lane_type"],
            source_checksum=classification["checksum"],
        )
    except Exception:
        observability_metrics.record_job_outcome("failed")
        raise

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
