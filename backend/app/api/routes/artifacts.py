from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_session_factory
from app.db import TopLevelLifecycleStore
from app.services.observability import observability_metrics
from app.workers.pipeline import get_job_run

router = APIRouter()


@router.get("/{job_id}/patient")
async def get_patient_artifact(
    job_id: UUID,
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> dict:
    """Get the patient-facing lab understanding artifact."""
    persisted = await _get_persisted_patient_artifact(str(job_id), session_factory)
    if persisted is not None:
        return persisted

    job = get_job_run(str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job["patient_artifact"]


@router.get("/{job_id}/clinician")
async def get_clinician_artifact(
    job_id: UUID,
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> dict:
    """Get the clinician-share artifact."""
    persisted = await _get_persisted_clinician_artifact(str(job_id), session_factory)
    if persisted is not None:
        return persisted

    job = get_job_run(str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job["clinician_artifact"]


async def _get_persisted_patient_artifact(
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict | None:
    try:
        async with session_factory() as session:
            store = TopLevelLifecycleStore(session)
            artifact = await store.get_patient_artifact(job_id)
            if artifact is None:
                return None
            create_share_event = getattr(store, "create_share_event", None)
            if callable(create_share_event):
                await create_share_event(
                    job_id=job_id,
                    artifact_type="patient",
                    share_method="view",
                )
            await session.commit()
            return dict(artifact.content)
    except (InterfaceError, OperationalError):
        observability_metrics.record_persistence_fallback()
        return None


async def _get_persisted_clinician_artifact(
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict | None:
    try:
        async with session_factory() as session:
            store = TopLevelLifecycleStore(session)
            artifact = await store.get_clinician_artifact(job_id)
            if artifact is None:
                return None
            create_share_event = getattr(store, "create_share_event", None)
            if callable(create_share_event):
                await create_share_event(
                    job_id=job_id,
                    artifact_type="clinician",
                    share_method="view",
                )
            await session.commit()
            return dict(artifact.content)
    except (InterfaceError, OperationalError):
        observability_metrics.record_persistence_fallback()
        return None
