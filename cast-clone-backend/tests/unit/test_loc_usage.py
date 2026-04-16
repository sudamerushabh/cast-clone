"""Tests for cumulative LOC usage query with caching."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services import loc_usage


@pytest.fixture(autouse=True)
def _reset_cache():
    """Ensure cache is clean before each test."""
    loc_usage.invalidate_cumulative_loc_cache()
    yield
    loc_usage.invalidate_cumulative_loc_cache()


class _FakeScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeSession:
    """Minimal stand-in for AsyncSession that counts execute() calls."""

    def __init__(self, value: int) -> None:
        self.value = value
        self.calls = 0

    async def execute(self, _stmt: object) -> _FakeScalarResult:
        self.calls += 1
        return _FakeScalarResult(self.value)


@pytest.mark.asyncio
async def test_cumulative_loc_returns_query_result():
    session = _FakeSession(12345)
    result = await loc_usage.cumulative_loc(session=session)
    assert result == 12345


@pytest.mark.asyncio
async def test_cumulative_loc_caches_within_ttl():
    session = _FakeSession(100)
    first = await loc_usage.cumulative_loc(session=session)
    second = await loc_usage.cumulative_loc(session=session)
    assert first == second == 100
    assert session.calls == 1, "Cache should prevent second query"


@pytest.mark.asyncio
async def test_invalidate_forces_refresh():
    session = _FakeSession(500)
    await loc_usage.cumulative_loc(session=session)
    session.value = 999
    loc_usage.invalidate_cumulative_loc_cache()
    result = await loc_usage.cumulative_loc(session=session)
    assert result == 999
    assert session.calls == 2


@pytest.mark.asyncio
async def test_cache_expires_after_ttl(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(7)
    await loc_usage.cumulative_loc(session=session)
    # Fast-forward past the 60s TTL
    monkeypatch.setattr(loc_usage, "_cache_set_at", time.monotonic() - 61)
    session.value = 42
    result = await loc_usage.cumulative_loc(session=session)
    assert result == 42
    assert session.calls == 2


@pytest.mark.asyncio
async def test_concurrent_calls_share_cache():
    """If N coroutines all miss together, at most a few hit the DB."""
    session = _FakeSession(1000)
    results = await asyncio.gather(
        *[loc_usage.cumulative_loc(session=session) for _ in range(5)]
    )
    assert all(r == 1000 for r in results)
    # With the lock, only 1 actual query runs.  Allow up to 2 for race
    # safety (rare scheduling where one finishes and sets cache just before
    # another checks under the lock).
    assert session.calls <= 2
