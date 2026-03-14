"""API key authentication for the MCP server.

SHA-256 hashing, in-memory cache (5min TTL), batched last_used_at updates.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update

from app.models.db import ApiKey

logger = structlog.get_logger(__name__)


def hash_api_key(raw_key: str) -> str:
    """Hash an API key using SHA-256."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a cryptographically random API key with clk_ prefix."""
    return f"clk_{secrets.token_hex(24)}"


class ApiKeyAuthenticator:
    """Validates API keys with caching and batched usage tracking."""

    def __init__(
        self,
        session_factory: Callable,
        cache_ttl_seconds: int = 300,
        batch_update_seconds: int = 60,
    ) -> None:
        self._session_factory = session_factory
        self._cache_ttl = cache_ttl_seconds
        self._batch_interval = batch_update_seconds
        self._cache: dict[str, tuple[dict[str, Any], float]] = {}
        self._pending_last_used: dict[str, float] = {}

    async def verify_key(self, raw_key: str) -> dict[str, Any] | None:
        """Verify an API key. Returns {"key_id", "user_id"} or None."""
        key_hash = hash_api_key(raw_key)
        now = time.monotonic()

        cached = self._cache.get(key_hash)
        if cached is not None:
            result, cached_at = cached
            if now - cached_at < self._cache_ttl:
                self._record_usage(result["key_id"], now)
                return result

        result = await self._lookup_key(key_hash)
        if result is None:
            return None

        self._cache[key_hash] = (result, now)
        self._record_usage(result["key_id"], now)
        return result

    async def _lookup_key(self, key_hash: str) -> dict[str, Any] | None:
        """Look up a key hash in PostgreSQL."""
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(ApiKey).where(ApiKey.key_hash == key_hash)
                )
                key = result.scalar_one_or_none()
                if key is None or not key.is_active:
                    return None
                return {"key_id": key.id, "user_id": key.user_id}
        except Exception as exc:
            logger.error("api_key_lookup_failed", error=str(exc))
            return None

    def _record_usage(self, key_id: str, now: float) -> None:
        """Record key usage for batched last_used_at update."""
        last_update = self._pending_last_used.get(key_id)
        if last_update is None or now - last_update >= self._batch_interval:
            self._pending_last_used[key_id] = now

    async def flush_last_used(self) -> None:
        """Flush pending last_used_at updates to PostgreSQL."""
        if not self._pending_last_used:
            return

        key_ids = list(self._pending_last_used.keys())
        self._pending_last_used.clear()

        try:
            async with self._session_factory() as session:
                await session.execute(
                    update(ApiKey)
                    .where(ApiKey.id.in_(key_ids))
                    .values(last_used_at=datetime.now(UTC))
                )
                await session.commit()
                logger.info("api_key_last_used_flushed", count=len(key_ids))
        except Exception as exc:
            logger.error("api_key_flush_failed", error=str(exc))

    def invalidate_cache(self, key_hash: str | None = None) -> None:
        """Invalidate cached key(s). Pass None to clear all."""
        if key_hash is None:
            self._cache.clear()
        else:
            self._cache.pop(key_hash, None)
