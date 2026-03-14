"""Unit tests for MCP API key authentication."""

from __future__ import annotations

import hashlib
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mcp.auth import (
    ApiKeyAuthenticator,
    generate_api_key,
    hash_api_key,
)


class TestHashApiKey:
    def test_sha256_hash(self):
        raw = "clk_test_key_abc123"
        hashed = hash_api_key(raw)
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert hashed == expected
        assert len(hashed) == 64

    def test_deterministic(self):
        raw = "clk_deterministic_test"
        assert hash_api_key(raw) == hash_api_key(raw)

    def test_different_keys_different_hashes(self):
        assert hash_api_key("key_a") != hash_api_key("key_b")


class TestGenerateApiKey:
    def test_prefix(self):
        key = generate_api_key()
        assert key.startswith("clk_")

    def test_length(self):
        key = generate_api_key()
        assert len(key) >= 48

    def test_unique(self):
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100


class TestApiKeyAuthenticator:
    @pytest.fixture
    def mock_session_factory(self):
        session = AsyncMock()
        factory = AsyncMock()
        factory.__aenter__ = AsyncMock(return_value=session)
        factory.__aexit__ = AsyncMock(return_value=False)
        return factory, session

    @pytest.fixture
    def authenticator(self, mock_session_factory):
        factory, session = mock_session_factory
        auth = ApiKeyAuthenticator(
            session_factory=lambda: factory,
            cache_ttl_seconds=300,
            batch_update_seconds=60,
        )
        return auth, session

    @pytest.mark.asyncio
    async def test_valid_key(self, authenticator):
        auth, session = authenticator
        raw_key = "clk_valid_key_123"
        key_hash = hash_api_key(raw_key)

        mock_result = MagicMock()
        mock_key = MagicMock()
        mock_key.id = "key-id-1"
        mock_key.key_hash = key_hash
        mock_key.is_active = True
        mock_key.user_id = "user-1"
        mock_result.scalar_one_or_none.return_value = mock_key
        session.execute.return_value = mock_result

        result = await auth.verify_key(raw_key)
        assert result is not None
        assert result["key_id"] == "key-id-1"
        assert result["user_id"] == "user-1"

    @pytest.mark.asyncio
    async def test_invalid_key(self, authenticator):
        auth, session = authenticator
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        result = await auth.verify_key("clk_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_inactive_key_rejected(self, authenticator):
        auth, session = authenticator
        raw_key = "clk_inactive_key"
        key_hash = hash_api_key(raw_key)

        mock_result = MagicMock()
        mock_key = MagicMock()
        mock_key.id = "key-id-2"
        mock_key.key_hash = key_hash
        mock_key.is_active = False
        mock_result.scalar_one_or_none.return_value = mock_key
        session.execute.return_value = mock_result

        result = await auth.verify_key(raw_key)
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_skips_db(self, authenticator):
        auth, session = authenticator
        raw_key = "clk_cached_key"
        key_hash = hash_api_key(raw_key)

        mock_result = MagicMock()
        mock_key = MagicMock()
        mock_key.id = "key-id-3"
        mock_key.key_hash = key_hash
        mock_key.is_active = True
        mock_key.user_id = "user-3"
        mock_result.scalar_one_or_none.return_value = mock_key
        session.execute.return_value = mock_result

        result1 = await auth.verify_key(raw_key)
        assert result1 is not None
        assert session.execute.call_count == 1

        result2 = await auth.verify_key(raw_key)
        assert result2 is not None
        assert session.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_expiry(self, authenticator):
        auth, session = authenticator
        raw_key = "clk_expiry_test"
        key_hash = hash_api_key(raw_key)

        mock_result = MagicMock()
        mock_key = MagicMock()
        mock_key.id = "key-id-4"
        mock_key.key_hash = key_hash
        mock_key.is_active = True
        mock_key.user_id = "user-4"
        mock_result.scalar_one_or_none.return_value = mock_key
        session.execute.return_value = mock_result

        await auth.verify_key(raw_key)
        assert session.execute.call_count == 1

        auth._cache[key_hash] = (auth._cache[key_hash][0], time.monotonic() - 400)

        await auth.verify_key(raw_key)
        assert session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_batched_last_used_at(self, authenticator):
        auth, session = authenticator
        raw_key = "clk_batch_test"
        key_hash = hash_api_key(raw_key)

        mock_result = MagicMock()
        mock_key = MagicMock()
        mock_key.id = "key-id-5"
        mock_key.key_hash = key_hash
        mock_key.is_active = True
        mock_key.user_id = "user-5"
        mock_result.scalar_one_or_none.return_value = mock_key
        session.execute.return_value = mock_result

        await auth.verify_key(raw_key)
        assert "key-id-5" in auth._pending_last_used
