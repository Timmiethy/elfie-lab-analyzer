from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


async def reset_integration_db(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retries: int = 4,
) -> None:
    for attempt in range(retries):
        try:
            async with session_factory() as session:
                for statement in _RESET_STATEMENTS:
                    await session.execute(text(statement))
                await session.commit()
            return
        except DBAPIError:
            if attempt + 1 >= retries:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))
