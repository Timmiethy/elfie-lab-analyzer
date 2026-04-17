"""Shared test fixtures."""

import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_db, get_session_factory
from app.config import settings
from app.main import create_app


@pytest.fixture(autouse=True)
def mock_vlm_for_pipeline(request):
    if "test_vlm_gateway" in request.node.name or "test_vlm_gateway" in str(request.node.fspath):
        yield
        return

    from app.config import settings
    from app.services.vlm_gateway import VLMRow

    async def mock_process_image(file_bytes, instructions=None):
        print(f"MOCK PROCESS RECV BYTES: {len(file_bytes)}")
        import io

        import pdfplumber

        if file_bytes.startswith(b"%PDF"):
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                if len(pdf.pages) > settings.max_pdf_pages:
                    raise ValueError("page_count_limit_exceeded")

        raw = file_bytes.decode("utf-8", errors="ignore")
        rows = []
        if "Glucose" in raw:
            value = "180" if "180" in raw else "110" if "110" in raw else "96"
            rows.append(
                VLMRow(
                    analyte_name="Glucose", value=value, unit="mg/dL", reference_range_raw="70-100"
                )
            )
        if "HbA1c" in raw:
            rows.append(
                VLMRow(analyte_name="HbA1c", value="6.8", unit="%", reference_range_raw="4.0-6.0")
            )
        if "MysteryMarker" in raw:
            rows.append(
                VLMRow(analyte_name="MysteryMarker", value="7.2", unit="zz", reference_range_raw="")
            )

        if not rows:
            raise ValueError("unsupported_pdf / empty pdf mock")
        return rows

    async def mock_generate_text(prompt, response_format=None):
        import json

        try:
            start = prompt.find("[")
            end = prompt.rfind("]") + 1
            rows = json.loads(prompt[start:end])
        except Exception:
            rows = []
        results = []
        for i, row in enumerate(rows):
            name = str(row.get("raw_analyte_label") or row.get("analyte_name") or "")
            if "Glucose" in name:
                norm = "fasting glucose"
            elif "HbA1c" in name:
                norm = "hba1c"
            else:
                norm = name
            results.append({"index": i, "is_valid_result": True, "normalized_analyte_name": norm})
        return json.dumps({"results": results})

    with patch(
        "app.services.mineru_adapter.process_image_with_qwen", new_callable=AsyncMock
    ) as mock_p:
        mock_p.side_effect = mock_process_image
        with patch(
            "app.services.semantic_cleaner.generate_text_with_qwen", new_callable=AsyncMock
        ) as mock_g:
            mock_g.side_effect = mock_generate_text
            yield


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Placeholder for test PDF bytes."""
    return b""


@pytest.fixture
def sample_extracted_rows() -> list[dict]:
    """Placeholder for test extracted rows."""
    return []


@pytest_asyncio.fixture
async def db_session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
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
) -> AsyncGenerator[AsyncClient, None]:
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
