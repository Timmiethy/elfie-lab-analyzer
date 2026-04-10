from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import InterfaceError, OperationalError

from app.config import settings
from app.db import TopLevelLifecycleStore
from app.db.session import async_session_factory
from app.services.observability import observability_metrics
from app.workers.pipeline import PipelineOrchestrator, get_job_run

router = APIRouter()
_PROCESSING_FAILED_DETAIL = "processing_failed"
_JOB_DEAD_LETTER_DETAIL = "job_dead_lettered"


@router.get("/{job_id}")
async def get_job(job_id: UUID) -> dict:
    """Get job details including current processing status."""
    persisted = await _get_persisted_job(str(job_id))
    if persisted is not None:
        return persisted

    job = get_job_run(str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")

    return _runtime_job_payload(job_id=str(job_id), job=job)


@router.post("/{job_id}/retry")
async def retry_job(job_id: UUID) -> dict:
    """Retry a persisted job using the stored document bytes."""

    try:
        async with async_session_factory() as session:
            store = TopLevelLifecycleStore(session)
            job = await store.get_job(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="job_not_found")
            if job.dead_letter:
                raise HTTPException(status_code=409, detail=_JOB_DEAD_LETTER_DETAIL)

            document = await store.get_document(job.document_id)
            if document is None:
                raise HTTPException(status_code=404, detail="document_not_found")

            job_uuid = str(job.id)
            document_uuid = document.id
            document_checksum = document.checksum
            document_storage_path = document.storage_path
            lane_type = job.lane_type
            retry_count = int(job.retry_count or 0) + 1

            try:
                file_bytes = Path(document_storage_path).read_bytes()
            except OSError as exc:
                await session.rollback()
                dead_letter = retry_count >= settings.max_job_retries
                await store.update_job_status(
                    job_uuid,
                    status="dead_lettered" if dead_letter else "failed",
                    retry_count=retry_count,
                    dead_letter=dead_letter,
                    operator_note=str(exc),
                )
                await session.commit()
                raise HTTPException(status_code=422, detail=_PROCESSING_FAILED_DETAIL) from exc

            pipeline = PipelineOrchestrator()
            try:
                result = await pipeline.run(
                    job_uuid,
                    file_bytes=file_bytes,
                    lane_type=lane_type,
                    db_session=session,
                    document_id=document_uuid,
                    source_checksum=document_checksum,
                )
            except Exception as exc:
                await session.rollback()
                dead_letter = retry_count >= settings.max_job_retries
                await store.update_job_status(
                    job_uuid,
                    status="dead_lettered" if dead_letter else "failed",
                    retry_count=retry_count,
                    dead_letter=dead_letter,
                    operator_note=str(exc),
                )
                await session.commit()
                raise HTTPException(status_code=422, detail=_PROCESSING_FAILED_DETAIL) from exc

            await store.update_job_status(
                job_uuid,
                status=result["status"],
                retry_count=retry_count,
                dead_letter=False,
            )
            await session.commit()
            return await _get_persisted_job(job_uuid)
    except (InterfaceError, OperationalError):
        raise HTTPException(status_code=503, detail="database_unavailable") from None


@router.get("/{job_id}/status")
async def get_job_status(job_id: UUID) -> dict:
    """Get lightweight job status for polling."""
    persisted = await _get_persisted_job_status(str(job_id))
    if persisted is not None:
        return persisted

    job = get_job_run(str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")

    return {
        "job_id": str(job_id),
        "status": job["status"],
        "lane_type": job.get("lane_type"),
    }


async def _get_persisted_job(job_id: str) -> dict | None:
    try:
        async with async_session_factory() as session:
            store = TopLevelLifecycleStore(session)
            job = await store.get_job(job_id)
            if job is None:
                return None
            lineage = await store.get_latest_lineage_run(job_id)
            lineage_count = (
                await store.count_lineage_runs(job_id)
                if hasattr(store, "count_lineage_runs")
                else (1 if lineage is not None else 0)
            )
            return _job_payload_from_model(
                job_id=str(job.id),
                job=job,
                lineage_count=lineage_count,
                lineage=lineage,
            )
    except (InterfaceError, OperationalError):
        observability_metrics.record_persistence_fallback()
        return None


async def _get_persisted_job_status(job_id: str) -> dict | None:
    try:
        async with async_session_factory() as session:
            store = TopLevelLifecycleStore(session)
            job = await store.get_job(job_id)
            if job is None:
                return None
            return {
                "job_id": str(job.id),
                "status": job.status,
                "lane_type": job.lane_type,
            }
    except (InterfaceError, OperationalError):
        observability_metrics.record_persistence_fallback()
        return None


def _job_payload_from_model(*, job_id: str, job, lineage_count: int, lineage) -> dict:
    retry_count = int(getattr(job, "retry_count", 0) or 0)
    return {
        "job_id": job_id,
        "status": job.status,
        "lane_type": job.lane_type,
        "qa": None,
        "findings": [],
        "lineage": None if lineage is None else {"id": str(lineage.id)},
        "retry_count": retry_count,
        "dead_letter": bool(getattr(job, "dead_letter", False)),
        "retried": retry_count > 0,
        "operator_note": getattr(job, "operator_note", None),
        "lineage_runs_count": lineage_count,
    }


def _runtime_job_payload(*, job_id: str, job: dict) -> dict:
    lineage = job.get("lineage")
    retry_count = int(job.get("retry_count", 0) or 0)
    return {
        "job_id": job_id,
        "status": job["status"],
        "lane_type": job.get("lane_type"),
        "qa": job.get("qa"),
        "findings": job.get("findings", []),
        "lineage": lineage,
        "retry_count": retry_count,
        "dead_letter": bool(job.get("dead_letter", False)),
        "retried": retry_count > 0,
        "operator_note": job.get("operator_note"),
        "lineage_runs_count": int(job.get("lineage_runs_count", 1 if lineage else 0)),
    }
