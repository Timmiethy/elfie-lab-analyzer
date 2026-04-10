from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError

from app.config import settings
from app.db.session import async_session_factory
from app.services.observability import observability_metrics
from app.services.privacy import build_privacy_policy_payload

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready() -> JSONResponse:
    db_reachable = await _check_database_reachable()
    artifact_store_writable = _check_artifact_store_writable()
    status = "ok" if db_reachable and artifact_store_writable else "degraded"
    payload = {
        "status": status,
        "checks": {
            "db_reachable": db_reachable,
            "artifact_store_writable": artifact_store_writable,
        },
    }
    return JSONResponse(status_code=200 if status == "ok" else 503, content=payload)


@router.get("/health/metrics")
async def health_metrics() -> dict:
    return {
        "status": "ok",
        "counters": observability_metrics.snapshot(),
    }


@router.get("/health/privacy")
async def health_privacy() -> dict:
    return build_privacy_policy_payload(
        upload_retention_days=settings.upload_retention_days,
        artifact_retention_days=settings.artifact_retention_days,
    )


async def _check_database_reachable() -> bool:
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
            return True
    except (InterfaceError, OperationalError):
        return False


def _check_artifact_store_writable() -> bool:
    try:
        artifact_store_path = settings.artifact_store_path
        artifact_store_path.mkdir(parents=True, exist_ok=True)
        probe_path = artifact_store_path / ".health-write-probe"
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
        return True
    except OSError:
        return False
