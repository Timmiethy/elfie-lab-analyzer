from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth import CurrentUserId
from app.api.deps import get_db, get_session_factory
from app.config import settings
from app.db import TopLevelLifecycleStore
from app.services.clinician_pdf import clinician_pdf_path, clinician_pdf_route
from app.services.observability import observability_metrics
from app.services.proof_pack import proof_pack_route, read_proof_pack
from app.workers.pipeline import PipelineOrchestrator, PipelineStep, get_job_run

router = APIRouter()
_PROCESSING_FAILED_DETAIL = "processing_failed"
_JOB_DEAD_LETTER_DETAIL = "job_dead_lettered"


@router.get("/ops/recent")
async def get_recent_jobs(
    user_id: CurrentUserId,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the most recently updated operator-visible jobs."""

    limit = max(1, min(limit, 100))
    try:
        store = TopLevelLifecycleStore(db)
        return {"jobs": await store.list_recent_jobs(limit, user_id=user_id)}
    except (InterfaceError, OperationalError):
        raise HTTPException(status_code=503, detail="database_unavailable") from None


@router.get("/{job_id}/audit")
async def get_job_audit(
    job_id: UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return operator audit details for a persisted job."""

    try:
        store = TopLevelLifecycleStore(db)
        try:
            payload = await store.get_job_audit_data(job_id)
            proof_pack = read_proof_pack(job_id)
            payload["proof_pack_available"] = proof_pack is not None
            payload["proof_pack_ref"] = proof_pack_route(job_id) if proof_pack is not None else None
            payload["clinician_pdf_ref"] = clinician_pdf_route(job_id)
            payload["clinician_pdf_available"] = clinician_pdf_path(job_id).exists()
            return payload
        except LookupError:
            raise HTTPException(status_code=404, detail="job_not_found")
    except (InterfaceError, OperationalError):
        raise HTTPException(status_code=503, detail="database_unavailable") from None


@router.get("/{job_id}/proof-pack")
async def get_proof_pack(job_id: UUID, user_id: CurrentUserId) -> dict:
    proof_pack = read_proof_pack(job_id)
    if proof_pack is None:
        raise HTTPException(status_code=404, detail="proof_pack_not_found")
    return proof_pack


@router.get("/{job_id}/retry-preview")
async def get_retry_preview(
    job_id: UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Explain whether a persisted job can be retried right now."""

    try:
        store = TopLevelLifecycleStore(db)
        try:
            return await store.get_retry_preview_data(
                job_id,
                max_retry_count=settings.max_job_retries,
            )
        except LookupError:
            raise HTTPException(status_code=404, detail="job_not_found")
    except (InterfaceError, OperationalError):
        raise HTTPException(status_code=503, detail="database_unavailable") from None


@router.get("/{job_id}")
async def get_job(
    job_id: UUID,
    user_id: CurrentUserId,
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> dict:
    """Get job details including current processing status."""
    persisted = await _get_persisted_job(str(job_id), session_factory)
    if persisted is not None:
        return persisted

    job = get_job_run(str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")

    return _runtime_job_payload(job_id=str(job_id), job=job)


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> dict:
    """Retry a persisted job using the stored document bytes."""

    try:
        store = TopLevelLifecycleStore(db)
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
            dead_letter = retry_count >= settings.max_job_retries
            await _update_job_status_in_fresh_session(
                job_uuid,
                status="dead_lettered" if dead_letter else "failed",
                session_factory=session_factory,
                retry_count=retry_count,
                dead_letter=dead_letter,
                operator_note=str(exc),
            )
            raise HTTPException(status_code=422, detail=_PROCESSING_FAILED_DETAIL) from exc

        pipeline = PipelineOrchestrator()
        try:
            async with session_factory() as session:
                result = await pipeline.run(
                    job_uuid,
                    file_bytes=file_bytes,
                    lane_type=lane_type,
                    db_session=session,
                    document_id=document_uuid,
                    source_checksum=document_checksum,
                    source_filename=document.filename,
                    source_mime_type=document.mime_type,
                )
                await session.commit()
        except Exception as exc:
            dead_letter = retry_count >= settings.max_job_retries
            await _update_job_status_in_fresh_session(
                job_uuid,
                status="dead_lettered" if dead_letter else "failed",
                session_factory=session_factory,
                retry_count=retry_count,
                dead_letter=dead_letter,
                operator_note=str(exc),
            )
            raise HTTPException(status_code=422, detail=_PROCESSING_FAILED_DETAIL) from exc

        # v12: Clear stale operator_note on successful retry
        await _update_job_status_in_fresh_session(
            job_uuid,
            status=result["status"],
            session_factory=session_factory,
            retry_count=retry_count,
            dead_letter=False,
            clear_operator_note=True,
        )
        return await _get_persisted_job(job_uuid, session_factory)
    except (InterfaceError, OperationalError):
        raise HTTPException(status_code=503, detail="database_unavailable") from None


@router.get("/{job_id}/status")
async def get_job_status(
    job_id: UUID,
    user_id: CurrentUserId,
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> dict:
    """Get lightweight job status for polling."""
    persisted = await _get_persisted_job_status(str(job_id), session_factory)
    if persisted is not None:
        return persisted

    job = get_job_run(str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")

    return {
        "job_id": str(job_id),
        "status": job["status"],
        "step": job.get("step") or _status_step_from_status(job["status"]),
        "lane_type": job.get("lane_type"),
    }


async def _get_persisted_job(
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict | None:
    try:
        async with session_factory() as session:
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


async def _get_persisted_job_status(
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict | None:
    try:
        async with session_factory() as session:
            store = TopLevelLifecycleStore(session)
            job = await store.get_job(job_id)
            if job is None:
                return None
            return {
                "job_id": str(job.id),
                "status": job.status,
                "step": _status_step_from_status(job.status),
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
        "step": _status_step_from_status(job.status),
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
        "step": job.get("step") or _status_step_from_status(job["status"]),
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


def _status_step_from_status(status: str) -> str:
    if status in {"completed", "partial"}:
        return PipelineStep.LINEAGE_PERSIST.value
    if status == "pending":
        return PipelineStep.PREFLIGHT.value
    if status in {"failed", "dead_lettered"}:
        return status
    return str(status)


async def _update_job_status_in_fresh_session(
    job_id: str,
    *,
    status: str,
    session_factory: async_sessionmaker[AsyncSession],
    retry_count: int | None = None,
    dead_letter: bool | None = None,
    operator_note: str | None = None,
    clear_operator_note: bool = False,
) -> None:
    async with session_factory() as session:
        store = TopLevelLifecycleStore(session)
        await store.update_job_status(
            job_id,
            status=status,
            retry_count=retry_count,
            dead_letter=dead_letter,
            operator_note=operator_note,
            clear_operator_note=clear_operator_note,
        )
        await session.commit()
