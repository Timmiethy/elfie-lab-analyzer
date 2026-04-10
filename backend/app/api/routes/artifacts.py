from uuid import UUID

from fastapi import APIRouter

router = APIRouter()


@router.get("/{job_id}/patient")
async def get_patient_artifact(job_id: UUID) -> dict:
    """Get the patient-facing lab understanding artifact."""
    raise NotImplementedError


@router.get("/{job_id}/clinician")
async def get_clinician_artifact(job_id: UUID) -> dict:
    """Get the clinician-share artifact."""
    raise NotImplementedError
