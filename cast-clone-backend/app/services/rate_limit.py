"""Redis-backed sliding-window rate limiter + per-user chat lock.

Uses a Redis sorted set per key: score = epoch-ms, member = unique request id.
The current request is counted against the limit (add-then-check).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger(__name__)


class RateLimitExceeded(Exception):  # noqa: N818 — public API name required by spec
    """Raised when a key has exceeded the configured request budget."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limit exceeded, retry after {retry_after}s")
        self.retry_after = retry_after


class ChatLockBusy(Exception):  # noqa: N818 — public API name required by spec
    """Raised when a per-user chat lock is already held."""


async def check_rate_limit(
    redis: aioredis.Redis,
    key: str,
    window_seconds: int,
    max_requests: int,
) -> None:
    """Raise :class:`RateLimitExceeded` if ``key`` exceeded the budget.

    Counts requests made in the last ``window_seconds`` and rejects any that
    would push the count past ``max_requests``. Uses
    ZREMRANGEBYSCORE + ZADD + ZCARD + EXPIRE in a single pipeline.
    """
    now_ms = int(time.time() * 1000)
    window_ms = window_seconds * 1000
    member = f"{now_ms}:{uuid4().hex}"

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now_ms - window_ms)
    pipe.zadd(key, {member: now_ms})
    pipe.zcard(key)
    pipe.expire(key, window_seconds)
    results = await pipe.execute()

    count = int(results[2])
    if count > max_requests:
        logger.warning(
            "rate_limit.exceeded",
            key=key,
            count=count,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        raise RateLimitExceeded(retry_after=window_seconds)


@asynccontextmanager
async def chat_lock(
    redis: aioredis.Redis,
    user_id: str,
    ttl_seconds: int = 300,
) -> AsyncIterator[None]:
    """Acquire a per-user chat lock. Raise :class:`ChatLockBusy` if already held."""
    key = f"chat:lock:{user_id}"
    acquired = await redis.set(key, "1", nx=True, ex=ttl_seconds)
    if not acquired:
        raise ChatLockBusy()
    try:
        yield
    finally:
        try:
            await redis.delete(key)
        except Exception as exc:  # noqa: BLE001 — log and swallow on cleanup
            logger.warning("chat_lock.release_failed", user_id=user_id, error=str(exc))
