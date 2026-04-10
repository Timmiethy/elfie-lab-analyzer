from uuid import UUID

from fastapi import APIRouter

router = APIRouter()


@router.get("/{job_id}")
async def get_job(job_id: UUID) -> dict:
    """Get job details including current processing status."""
    raise NotImplementedError


@router.get("/{job_id}/status")
async def get_job_status(job_id: UUID) -> dict:
    """Get lightweight job status for polling."""
    raise NotImplementedError
