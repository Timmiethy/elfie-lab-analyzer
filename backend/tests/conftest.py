"""Shared test fixtures."""

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_db, get_session_factory
from app.config import settings
from app.main import create_app


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Placeholder for test PDF bytes."""
    return b""


@pytest.fixture
def sample_extracted_rows() -> list[dict]:
    """Placeholder for test extracted rows."""
    return []


@pytest_asyncio.fixture
async def db_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def api_client(
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> AsyncClient:
    original_loinc_path = settings.loinc_path
    loinc_path = tmp_path / "loinc"
    loinc_path.mkdir(parents=True, exist_ok=True)
    (loinc_path / "metadata.json").write_text(
        json.dumps(
            {
                "release": "loinc-test-fixture",
                "checksum": "sha256:test-fixture",
            }
        ),
        encoding="utf-8",
    )
    settings.loinc_path = loinc_path

    app = create_app()

    async def override_get_db():
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = lambda: db_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
    settings.loinc_path = original_loinc_path
