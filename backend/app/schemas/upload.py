"""Upload request/response schemas."""

from uuid import UUID

from pydantic import BaseModel


class UploadResponse(BaseModel):
    job_id: UUID
    status: str
    lane_type: str
    message: str
