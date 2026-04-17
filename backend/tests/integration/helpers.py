from __future__ import annotations

import asyncio
import logging
import random

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_LOGGER = logging.getLogger(__name__)

_RESET_BASE_DELAY_SECONDS = 0.05
_RESET_MAX_DELAY_SECONDS = 0.8
_RESET_DELAY_JITTER_RATIO = 0.2

_RESET_STATEMENTS = (
    "DELETE FROM share_events",
    "DELETE FROM benchmark_runs",
    "DELETE FROM lineage_runs",
    "DELETE FROM clinician_artifacts",
    "DELETE FROM patient_artifacts",
    "DELETE FROM policy_events",
    "DELETE FROM rule_events",
    "DELETE FROM mapping_candidates",
    "DELETE FROM observations",
    "DELETE FROM extracted_rows",
    "DELETE FROM jobs",
    "DELETE FROM documents",
)


def _retry_delay_seconds(attempt: int) -> float:
    base_delay = min(_RESET_BASE_DELAY_SECONDS * (2**attempt), _RESET_MAX_DELAY_SECONDS)
    jitter = base_delay * _RESET_DELAY_JITTER_RATIO
    return max(0.0, base_delay + random.uniform(-jitter, jitter))


async def reset_integration_db(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retries: int = 5,
) -> None:
    if retries < 1:
        raise ValueError("retries must be >= 1")

    for attempt in range(retries):
        try:
            async with session_factory() as session:
                for statement in _RESET_STATEMENTS:
                    await session.execute(text(statement))
                await session.commit()
            return
        except DBAPIError as exc:
            if attempt + 1 >= retries:
                raise
            delay_seconds = _retry_delay_seconds(attempt)
            _LOGGER.warning(
                "reset_integration_db retry %s/%s in %.3fs due to %s",
                attempt + 1,
                retries,
                delay_seconds,
                exc.__class__.__name__,
            )
            await asyncio.sleep(delay_seconds)
