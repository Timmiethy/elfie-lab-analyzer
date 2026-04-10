from fastapi import APIRouter, UploadFile

router = APIRouter()


@router.post("")
async def upload_lab_report(file: UploadFile) -> dict:
    """Accept a lab report file (PDF or image) and create a processing job."""
    raise NotImplementedError
