"""Timestamp hygiene tests for persistence helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.store import TopLevelLifecycleStore
from app.models.tables import utc_now


def test_utc_now_returns_timezone_aware_datetime() -> None:
    timestamp = utc_now()

    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() is not None


@pytest.mark.asyncio
async def test_update_job_status_sets_timezone_aware_updated_at() -> None:
    session = AsyncMock()
    store = TopLevelLifecycleStore(session)
    job = SimpleNamespace(
        id=uuid4(),
        status="pending",
        updated_at=None,
        retry_count=0,
        dead_letter=False,
        operator_note=None,
    )
    store.get_job = AsyncMock(return_value=job)  # type: ignore[method-assign]

    updated = await store.update_job_status(job.id, status="completed")

    assert updated is job
    assert job.status == "completed"
    assert job.updated_at.tzinfo is not None
    session.flush.assert_awaited_once()
