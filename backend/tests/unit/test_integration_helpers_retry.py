from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from tests.integration import helpers as integration_helpers


class _RecordingSession:
    def __init__(self) -> None:
        self.executed: list[object] = []
        self.committed = False

    async def execute(self, statement: object) -> None:
        self.executed.append(statement)

    async def commit(self) -> None:
        self.committed = True


class _FlakySessionFactory:
    def __init__(self, *, fail_attempts: int) -> None:
        self.fail_attempts = fail_attempts
        self.attempts = 0
        self.session = _RecordingSession()

    def __call__(self) -> _FlakySessionFactory:
        return self

    async def __aenter__(self) -> _RecordingSession:
        self.attempts += 1
        if self.attempts <= self.fail_attempts:
            raise OperationalError("DELETE FROM jobs", {}, Exception("transient db failure"))
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_reset_integration_db_retries_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _FlakySessionFactory(fail_attempts=2)
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(
        integration_helpers,
        "_retry_delay_seconds",
        lambda attempt: 0.1 * (attempt + 1),
    )
    monkeypatch.setattr(integration_helpers.asyncio, "sleep", fake_sleep)

    await integration_helpers.reset_integration_db(factory, retries=5)

    assert factory.attempts == 3
    assert sleep_calls == [0.1, 0.2]
    assert factory.session.committed is True
    assert len(factory.session.executed) == len(integration_helpers._RESET_STATEMENTS)


@pytest.mark.asyncio
async def test_reset_integration_db_raises_after_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _FlakySessionFactory(fail_attempts=10)
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(integration_helpers, "_retry_delay_seconds", lambda _attempt: 0.05)
    monkeypatch.setattr(integration_helpers.asyncio, "sleep", fake_sleep)

    with pytest.raises(OperationalError):
        await integration_helpers.reset_integration_db(factory, retries=3)

    assert factory.attempts == 3
    assert sleep_calls == [0.05, 0.05]


@pytest.mark.asyncio
async def test_reset_integration_db_rejects_invalid_retry_budget() -> None:
    factory = _FlakySessionFactory(fail_attempts=0)

    with pytest.raises(ValueError, match="retries must be >= 1"):
        await integration_helpers.reset_integration_db(factory, retries=0)
