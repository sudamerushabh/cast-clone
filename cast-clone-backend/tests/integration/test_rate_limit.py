"""Integration tests for the Redis sliding-window rate limiter.

Covers:
    * ``POST /api/v1/auth/login`` returns 429 after 5 attempts from the same IP.
    * The 429 response carries a ``Retry-After`` header.
    * ``POST /api/v1/projects/{id}/chat`` returns 429 on the 11th call within
      the window.
    * A second concurrent chat call returns 429 due to the per-user lock.

No real Redis is required — the suite swaps :func:`app.services.redis.get_redis`
for a minimal in-memory async fake that supports just the commands the rate
limiter touches (sorted-set ops, ``SET NX EX``, ``DELETE``, ``EXPIRE``).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.models.db import User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# In-memory async Redis fake (only the surface the rate limiter needs).
# ---------------------------------------------------------------------------


class _FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def zremrangebyscore(self, key: str, low: float, high: float) -> _FakePipeline:
        self._ops.append(("zremrangebyscore", (key, low, high)))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> _FakePipeline:
        self._ops.append(("zadd", (key, dict(mapping))))
        return self

    def zcard(self, key: str) -> _FakePipeline:
        self._ops.append(("zcard", (key,)))
        return self

    def expire(self, key: str, seconds: int) -> _FakePipeline:
        self._ops.append(("expire", (key, seconds)))
        return self

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for name, args in self._ops:
            method = getattr(self._redis, f"_pipe_{name}")
            results.append(method(*args))
        return results


class FakeRedis:
    """Tiny in-memory async Redis stand-in for unit/integration tests."""

    def __init__(self) -> None:
        self._zsets: dict[str, dict[str, float]] = {}
        self._strings: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    # Pipeline-underlying sync helpers (called while holding a logical pipeline)
    def _pipe_zremrangebyscore(self, key: str, low: float, high: float) -> int:
        zset = self._zsets.get(key, {})
        removed = [m for m, score in zset.items() if low <= score <= high]
        for m in removed:
            zset.pop(m, None)
        self._zsets[key] = zset
        return len(removed)

    def _pipe_zadd(self, key: str, mapping: dict[str, float]) -> int:
        zset = self._zsets.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            if member not in zset:
                added += 1
            zset[member] = score
        return added

    def _pipe_zcard(self, key: str) -> int:
        return len(self._zsets.get(key, {}))

    def _pipe_expire(self, key: str, seconds: int) -> int:
        # No-op for the fake; real expiry is irrelevant in tests.
        return 1 if key in self._zsets or key in self._strings else 0

    async def set(
        self,
        key: str,
        value: str,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        async with self._lock:
            if nx and key in self._strings:
                return None
            self._strings[key] = value
            return True

    async def exists(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._strings or key in self._zsets:
                count += 1
        return count

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._strings:
                del self._strings[key]
                deleted += 1
            if key in self._zsets:
                del self._zsets[key]
                deleted += 1
        return deleted

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def rate_limit_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Build a FastAPI app with auth enabled and Redis swapped for the fake."""
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("SECRET_KEY", "integration-test-secret-key-for-rate-limit")
    monkeypatch.setenv("LICENSE_DISABLED", "true")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    fake = FakeRedis()
    # Override the FastAPI dependency so any endpoint wired via
    # `Depends(get_redis)` receives the fake. Also patch the source
    # module so direct `get_redis()` callers (e.g. module-level helpers,
    # tests that reach in) see the same fake.
    from app.services.redis import get_redis as _get_redis

    app.dependency_overrides[_get_redis] = lambda: fake
    monkeypatch.setattr("app.api.auth.get_redis", lambda: fake)
    monkeypatch.setattr("app.api.chat.get_redis", lambda: fake)
    monkeypatch.setattr("app.services.redis.get_redis", lambda: fake)
    return app


@pytest_asyncio.fixture
async def client(rate_limit_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=rate_limit_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _member(user_id: str, username: str) -> User:
    return User(
        id=user_id,
        username=username,
        email=f"{username}@test.local",
        password_hash="",
        role="member",
        is_active=True,
    )


def _override_auth_session(app: FastAPI) -> None:
    """Make the login endpoint hit the rate limiter without real DB."""
    from app.services.postgres import get_session

    # No-user result so each login fails after the rate-limit check runs.
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    async def _fake_get_session():
        yield session

    app.dependency_overrides[get_session] = _fake_get_session


def _override_chat_deps(app: FastAPI, user: User) -> None:
    from app.api.dependencies import get_current_user
    from app.services.postgres import get_session

    async def _fake_current_user() -> User:
        return user

    session = MagicMock()
    # Project lookup returns None -> fast path through _resolve_project_context
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)

    async def _fake_get_session():
        yield session

    app.dependency_overrides[get_current_user] = _fake_current_user
    app.dependency_overrides[get_session] = _fake_get_session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_login_rate_limit_returns_429_after_threshold(
    client: AsyncClient,
    rate_limit_app: FastAPI,
) -> None:
    _override_auth_session(rate_limit_app)

    # First 5 requests should be rejected as 401 (bad creds), not 429.
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "nope", "password": "nope"},
        )
        assert resp.status_code == 401, resp.text

    # 6th attempt within the window must be throttled.
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "nope", "password": "nope"},
    )
    assert resp.status_code == 429, resp.text
    assert "retry-after" in {h.lower() for h in resp.headers.keys()}
    assert int(resp.headers["retry-after"]) == 60


async def test_chat_rate_limit_returns_429_after_threshold(
    client: AsyncClient,
    rate_limit_app: FastAPI,
) -> None:
    from app.services.auth import create_access_token

    user = _member(str(uuid4()), "alice")
    _override_chat_deps(rate_limit_app, user)
    token = create_access_token(
        user.id, "integration-test-secret-key-for-rate-limit"
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Patch chat_stream + get_ai_config + graph-store deps so the endpoint
    # reaches the rate-limit/lock logic and returns a stream that terminates
    # quickly when iterated.
    import app.api.chat as chat_mod

    async def _fake_chat_stream(**_kwargs: Any):
        if False:  # pragma: no cover - satisfies async-generator protocol
            yield b""
        return

    async def _fake_get_ai_config(_session: Any):
        return MagicMock()

    chat_mod.chat_stream = _fake_chat_stream  # type: ignore[assignment]
    chat_mod.get_ai_config = _fake_get_ai_config  # type: ignore[assignment]
    chat_mod.get_driver = lambda: MagicMock()  # type: ignore[assignment]
    chat_mod.Neo4jGraphStore = lambda _driver: MagicMock()  # type: ignore[assignment]

    project_id = str(uuid4())
    # Drain the body on each call so the event_generator's finally runs,
    # releasing the per-user lock before the next request.
    for _i in range(10):
        async with client.stream(
            "POST",
            f"/api/v1/projects/{project_id}/chat",
            headers=headers,
            json={"message": "hi", "history": []},
        ) as resp:
            assert resp.status_code == 200, await resp.aread()
            async for _chunk in resp.aiter_bytes():
                pass

    # 11th call -> rate-limit 429 (happens before the lock check).
    resp = await client.post(
        f"/api/v1/projects/{project_id}/chat",
        headers=headers,
        json={"message": "hi", "history": []},
    )
    assert resp.status_code == 429, resp.text
    assert int(resp.headers["retry-after"]) == 60


async def test_chat_lock_blocks_concurrent_streams(
    rate_limit_app: FastAPI,
) -> None:
    """Hold the lock manually, then verify a second request is rejected."""
    import app.api.chat as chat_mod
    from app.services.auth import create_access_token
    from app.services.rate_limit import chat_lock

    user = _member(str(uuid4()), "bob")
    _override_chat_deps(rate_limit_app, user)
    token = create_access_token(
        user.id, "integration-test-secret-key-for-rate-limit"
    )
    headers = {"Authorization": f"Bearer {token}"}

    fake = chat_mod.get_redis()

    # Acquire the lock out-of-band and hold it for the duration of the test.
    lock_ctx = chat_lock(fake, str(user.id), ttl_seconds=300)
    await lock_ctx.__aenter__()

    try:
        transport = ASGITransport(app=rate_limit_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/projects/{uuid4()}/chat",
                headers=headers,
                json={"message": "hi", "history": []},
            )
        assert resp.status_code == 429, resp.text
        assert "active chat stream" in resp.text.lower()
    finally:
        await lock_ctx.__aexit__(None, None, None)


async def test_rate_limiter_sliding_window_unit(
    rate_limit_app: FastAPI,
) -> None:
    """Directly exercise ``check_rate_limit`` against the fake."""
    import app.api.chat as chat_mod
    from app.services.rate_limit import RateLimitExceeded, check_rate_limit

    fake = chat_mod.get_redis()
    key = f"rl:unit:{time.time_ns()}"
    for _ in range(3):
        await check_rate_limit(fake, key, window_seconds=60, max_requests=3)
    with pytest.raises(RateLimitExceeded) as err:
        await check_rate_limit(fake, key, window_seconds=60, max_requests=3)
    assert err.value.retry_after == 60
