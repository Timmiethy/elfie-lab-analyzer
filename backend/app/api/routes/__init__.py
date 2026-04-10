from fastapi import APIRouter

from app.api.routes.artifacts import router as artifacts_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.upload import router as upload_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(upload_router, prefix="/upload", tags=["upload"])
router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
router.include_router(artifacts_router, prefix="/artifacts", tags=["artifacts"])
