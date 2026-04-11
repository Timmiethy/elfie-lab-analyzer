from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import settings
from app.services.observability import (
    CORRELATION_ID_HEADER,
    generate_correlation_id,
    observability_metrics,
    set_current_correlation_id,
)
from app.terminology import TerminologyLoader


def _verify_terminology_snapshot() -> None:
    snapshot_dir = settings.loinc_path
    metadata = snapshot_dir / "metadata.json"
    if not metadata.exists():
        raise RuntimeError(
            f"terminology snapshot not found at {snapshot_dir}: metadata.json is missing"
        )


def create_app() -> FastAPI:
    _verify_terminology_snapshot()
    TerminologyLoader().load_loinc(str(settings.loinc_path))
    observability_metrics.reset()
    app = FastAPI(
        title="Elfie Labs Analyzer",
        version="0.1.0",
        description="Patient-facing lab understanding feature for Elfie Health Report",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[CORRELATION_ID_HEADER],
    )

    @app.middleware("http")
    async def add_correlation_id(request: Request, call_next) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or generate_correlation_id()
        set_current_correlation_id(correlation_id)
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response

    app.include_router(api_router, prefix="/api")

    return app


try:
    app = create_app()
except RuntimeError:
    app = None  # deferred; tests call create_app() directly with patched settings

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
