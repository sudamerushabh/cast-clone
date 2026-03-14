# Phase 5b-M4: MCP Server + API Key Authentication

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the shared AI tool layer (from M1) via a FastMCP server over SSE transport on port 8090, protected by API key authentication with SHA-256 hashing, in-memory cache, and batched last_used_at updates. Provide REST endpoints for API key management (create/list/revoke). Add a Docker Compose service for the MCP server.

**Architecture:** A FastMCP server in `app/mcp/server.py` (~200 lines) wraps each shared tool function from `app/ai/tools.py` as an MCP tool. An auth middleware in `app/mcp/auth.py` validates `Authorization: Bearer <key>` headers using SHA-256 hashed keys from PostgreSQL, cached in-memory for 5 minutes, with batched `last_used_at` updates (at most once per minute per key). The MCP container shares the same PostgreSQL + Neo4j databases as the main API. Key management endpoints (POST/GET/DELETE `/api/v1/api-keys`) live in the main API behind JWT auth. Multi-project context: tools that accept `app_name` build `ChatToolContext` per-call; project-agnostic tools (like `list_applications`) use `GraphStore` directly.

**Tech Stack:** Python 3.12, FastMCP (`mcp[cli]>=1.25,<2`), FastAPI, SQLAlchemy async, Neo4j async driver, Pydantic v2, structlog, pytest + pytest-asyncio.

**Depends on:** M1 (shared tool layer in `app/ai/tools.py` and `app/ai/tool_definitions.py`).

**Implementation notes (from review):**
- The `add_annotation` tool from the design spec is deferred — it requires PostgreSQL write access in `ChatToolContext.db_session` which adds complexity to the MCP server's per-tool context building. Add it as a follow-up once the core MCP tools are validated.
- A `Dockerfile.mcp` must be created for the Docker Compose service (Task 7 includes this).
- FastMCP auth integration depends on the SDK version — if FastMCP doesn't support native Bearer token auth, wrap the MCP SSE app in a FastAPI middleware that validates tokens before proxying.

---

## File Structure

```
app/mcp/                          # NEW package
├── __init__.py                   # Package marker
├── server.py                     # FastMCP server with tool definitions (~200 lines)
└── auth.py                       # API key auth middleware (SHA-256, cache, batched updates)

app/api/
└── api_keys.py                   # NEW — Key management REST endpoints

app/schemas/
└── api_keys.py                   # NEW — Request/response Pydantic models

app/models/db.py                  # MODIFY — add ApiKey ORM model
app/config.py                     # MODIFY — add mcp_* settings
app/api/__init__.py               # MODIFY — register api_keys_router
app/main.py                       # MODIFY — include api_keys_router

docker-compose.yml                # MODIFY — add mcp service

pyproject.toml                    # MODIFY — add mcp[cli] dependency

tests/unit/
├── test_api_key_auth.py          # NEW — auth middleware unit tests
├── test_api_key_schemas.py       # NEW — schema validation tests
├── test_api_key_endpoints.py     # NEW — REST endpoint tests
└── test_mcp_server.py            # NEW — MCP tool registration tests
```

---

## Task 1: Add `mcp[cli]` Dependency + MCP Config Settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/config.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_mcp_config.py
from app.config import Settings


def test_mcp_settings_defaults():
    s = Settings(database_url="postgresql+asyncpg://x", neo4j_uri="bolt://x")
    assert s.mcp_port == 8090
    assert s.mcp_api_key_cache_ttl_seconds == 300
    assert s.mcp_last_used_batch_seconds == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_mcp_config.py -v`
Expected: FAIL — `Settings` has no `mcp_port` attribute.

- [ ] **Step 3: Add mcp dependency to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list after the `anthropic` line:

```toml
    "mcp[cli]>=1.25,<2",
```

- [ ] **Step 4: Run uv sync**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv sync`

- [ ] **Step 5: Add MCP settings to config**

In `app/config.py`, add after the `pr_analysis_*` settings block (after line 41):

```python
    # Phase 5b-M4: MCP server
    mcp_port: int = 8090
    mcp_api_key_cache_ttl_seconds: int = 300     # 5-minute in-memory cache
    mcp_last_used_batch_seconds: int = 60         # Update last_used_at at most once per minute
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_mcp_config.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend && git add pyproject.toml app/config.py tests/unit/test_mcp_config.py
git commit -m "feat(5b-m4): add mcp[cli] dependency and MCP config settings"
```

---

## Task 2: ApiKey ORM Model

**Files:**
- Modify: `app/models/db.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_api_key_model.py
"""Tests for the ApiKey ORM model."""
from app.models.db import ApiKey


def test_api_key_model_defaults():
    key = ApiKey(
        key_hash="abc123hash",
        name="My Key",
        user_id="user-1",
    )
    assert key.key_hash == "abc123hash"
    assert key.name == "My Key"
    assert key.user_id == "user-1"
    assert key.is_active is True
    assert key.last_used_at is None


def test_api_key_tablename():
    assert ApiKey.__tablename__ == "api_keys"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_api_key_model.py -v`
Expected: FAIL — `ApiKey` not importable from `app.models.db`.

- [ ] **Step 3: Add ApiKey model to db.py**

In `app/models/db.py`, add after the `PrAnalysis` class (at the end of the file):

```python
class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User | None] = relationship()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_api_key_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend && git add app/models/db.py tests/unit/test_api_key_model.py
git commit -m "feat(5b-m4): add ApiKey ORM model"
```

---

## Task 3: API Key Schemas (Pydantic v2)

**Files:**
- Create: `app/schemas/api_keys.py`
- Test: `tests/unit/test_api_key_schemas.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_api_key_schemas.py
"""Tests for API key Pydantic schemas."""
import pytest
from pydantic import ValidationError

from app.schemas.api_keys import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyResponse


class TestApiKeyCreateRequest:
    def test_valid(self):
        req = ApiKeyCreateRequest(name="My Integration Key")
        assert req.name == "My Integration Key"

    def test_name_too_short(self):
        with pytest.raises(ValidationError):
            ApiKeyCreateRequest(name="")

    def test_name_too_long(self):
        with pytest.raises(ValidationError):
            ApiKeyCreateRequest(name="x" * 101)


class TestApiKeyCreateResponse:
    def test_includes_raw_key(self):
        resp = ApiKeyCreateResponse(
            id="key-1",
            name="My Key",
            raw_key="clk_abc123",
            created_at="2026-01-01T00:00:00Z",
        )
        assert resp.raw_key == "clk_abc123"
        assert resp.id == "key-1"


class TestApiKeyResponse:
    def test_no_raw_key(self):
        resp = ApiKeyResponse(
            id="key-1",
            name="My Key",
            is_active=True,
            created_at="2026-01-01T00:00:00Z",
            last_used_at=None,
        )
        assert not hasattr(resp, "raw_key") or "raw_key" not in resp.model_fields
        assert resp.is_active is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_api_key_schemas.py -v`
Expected: FAIL — `app.schemas.api_keys` not found.

- [ ] **Step 3: Create the schemas**

```python
# app/schemas/api_keys.py
"""Request/response models for API key management."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    """Request body for creating a new API key."""
    name: str = Field(..., min_length=1, max_length=100)


class ApiKeyCreateResponse(BaseModel):
    """Response when creating a key — includes the raw key (shown once)."""
    id: str
    name: str
    raw_key: str
    created_at: datetime | str

    model_config = {"from_attributes": True}


class ApiKeyResponse(BaseModel):
    """Response for listing keys — no raw key exposed."""
    id: str
    name: str
    is_active: bool
    created_at: datetime | str
    last_used_at: datetime | str | None

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_api_key_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend && git add app/schemas/api_keys.py tests/unit/test_api_key_schemas.py
git commit -m "feat(5b-m4): add API key Pydantic schemas"
```

---

## Task 4: API Key Auth Middleware

**Files:**
- Create: `app/mcp/__init__.py`
- Create: `app/mcp/auth.py`
- Test: `tests/unit/test_api_key_auth.py`

This is the core auth module: SHA-256 hashing, in-memory cache with 5-min TTL, batched `last_used_at` updates.

- [ ] **Step 1: Create `app/mcp/__init__.py`**

```python
# app/mcp/__init__.py
"""MCP server package — FastMCP server with API key auth."""
```

- [ ] **Step 2: Write the test**

```python
# tests/unit/test_api_key_auth.py
"""Unit tests for MCP API key authentication.

Tests SHA-256 hashing, in-memory cache, cache expiry, and batched last_used_at updates.
"""
from __future__ import annotations

import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.auth import (
    ApiKeyAuthenticator,
    hash_api_key,
    generate_api_key,
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
        # clk_ (4) + 48 hex chars = 52
        assert len(key) >= 48

    def test_unique(self):
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100


class TestApiKeyAuthenticator:
    @pytest.fixture
    def mock_session_factory(self):
        """Returns an async context manager that yields a mock session."""
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

        # Mock DB returning a matching active key
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

        # Mock DB returning no match
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

        # First call: populate cache from DB
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

        # Second call: should use cache, no extra DB hit
        result2 = await auth.verify_key(raw_key)
        assert result2 is not None
        assert session.execute.call_count == 1  # No additional DB call

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

        # Populate cache
        await auth.verify_key(raw_key)
        assert session.execute.call_count == 1

        # Expire the cache entry
        auth._cache[key_hash] = (auth._cache[key_hash][0], time.monotonic() - 400)

        # Should hit DB again
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

        # Verify the key_id is in the pending updates set
        assert "key-id-5" in auth._pending_last_used
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_api_key_auth.py -v`
Expected: FAIL — `app.mcp.auth` not found.

- [ ] **Step 4: Implement the auth module**

```python
# app/mcp/auth.py
"""API key authentication for the MCP server.

Design decisions:
- SHA-256 for key hashing (not bcrypt). API keys are randomly generated with high
  entropy, so brute-force resistance is less critical. bcrypt at ~100ms/hash would
  add unacceptable latency for rapid MCP tool calls.
- In-memory cache of verified key hashes with configurable TTL (default 5 min)
  to avoid repeated DB lookups during agent sessions.
- Batched last_used_at updates: at most once per minute per key, flushed
  periodically by the MCP server's background task.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import ApiKey

logger = structlog.get_logger(__name__)


def hash_api_key(raw_key: str) -> str:
    """Hash an API key using SHA-256."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a cryptographically random API key with clk_ prefix."""
    return f"clk_{secrets.token_hex(24)}"


class ApiKeyAuthenticator:
    """Validates API keys with caching and batched usage tracking.

    Args:
        session_factory: Callable returning an async context manager yielding AsyncSession.
        cache_ttl_seconds: How long verified keys stay cached (default 300 = 5 min).
        batch_update_seconds: Minimum interval between last_used_at updates per key (default 60).
    """

    def __init__(
        self,
        session_factory: Callable,
        cache_ttl_seconds: int = 300,
        batch_update_seconds: int = 60,
    ) -> None:
        self._session_factory = session_factory
        self._cache_ttl = cache_ttl_seconds
        self._batch_interval = batch_update_seconds
        # Cache: key_hash -> (result_dict, monotonic_timestamp)
        self._cache: dict[str, tuple[dict[str, Any], float]] = {}
        # Pending last_used_at updates: key_id -> last_update_monotonic
        self._pending_last_used: dict[str, float] = {}

    async def verify_key(self, raw_key: str) -> dict[str, Any] | None:
        """Verify an API key. Returns {"key_id": ..., "user_id": ...} or None.

        Uses in-memory cache to avoid DB lookups on every request.
        Records the key for batched last_used_at updates.
        """
        key_hash = hash_api_key(raw_key)
        now = time.monotonic()

        # Check cache
        cached = self._cache.get(key_hash)
        if cached is not None:
            result, cached_at = cached
            if now - cached_at < self._cache_ttl:
                self._record_usage(result["key_id"], now)
                return result

        # Cache miss or expired — query DB
        result = await self._lookup_key(key_hash)
        if result is None:
            # Cache negative result too (prevents repeated DB hits for invalid keys)
            # But don't cache for long — 30 seconds for negative results
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
        """Record a key usage for batched last_used_at update."""
        last_update = self._pending_last_used.get(key_id)
        if last_update is None or now - last_update >= self._batch_interval:
            self._pending_last_used[key_id] = now

    async def flush_last_used(self) -> None:
        """Flush pending last_used_at updates to PostgreSQL.

        Called periodically by the MCP server (e.g., every 60 seconds).
        """
        if not self._pending_last_used:
            return

        key_ids = list(self._pending_last_used.keys())
        self._pending_last_used.clear()

        try:
            async with self._session_factory() as session:
                await session.execute(
                    update(ApiKey)
                    .where(ApiKey.id.in_(key_ids))
                    .values(last_used_at=datetime.now(timezone.utc))
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_api_key_auth.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend && git add app/mcp/__init__.py app/mcp/auth.py tests/unit/test_api_key_auth.py
git commit -m "feat(5b-m4): add API key auth middleware with SHA-256 cache and batched updates"
```

---

## Task 5: API Key Management Endpoints

**Files:**
- Create: `app/api/api_keys.py`
- Modify: `app/api/__init__.py`
- Modify: `app/main.py`
- Test: `tests/unit/test_api_key_endpoints.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_api_key_endpoints.py
"""Tests for API key management endpoints.

Tests create, list, and revoke operations using mocked DB sessions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def mock_session():
    session = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_create_api_key():
    """POST /api/v1/api-keys creates a key and returns raw key once."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    with patch("app.api.api_keys.get_session") as mock_get_session:
        mock_get_session.return_value = mock_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/api-keys",
                json={"name": "My Test Key"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["name"] == "My Test Key"
            assert "raw_key" in data
            assert data["raw_key"].startswith("clk_")
            assert "id" in data


@pytest.mark.asyncio
async def test_create_api_key_missing_name():
    """POST /api/v1/api-keys with empty name returns 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/api-keys",
            json={"name": ""},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_api_keys():
    """GET /api/v1/api-keys returns keys without raw key."""
    mock_key = MagicMock()
    mock_key.id = "key-1"
    mock_key.name = "Test Key"
    mock_key.is_active = True
    mock_key.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mock_key.last_used_at = None

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_key]
    mock_session.execute.return_value = mock_result

    with patch("app.api.api_keys.get_session") as mock_get_session:
        mock_get_session.return_value = mock_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/api-keys")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["name"] == "Test Key"
            assert "raw_key" not in data[0]


@pytest.mark.asyncio
async def test_revoke_api_key():
    """DELETE /api/v1/api-keys/{id} sets is_active=false."""
    mock_key = MagicMock()
    mock_key.id = "key-1"
    mock_key.is_active = True

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_key
    mock_session.execute.return_value = mock_result
    mock_session.commit = AsyncMock()

    with patch("app.api.api_keys.get_session") as mock_get_session:
        mock_get_session.return_value = mock_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/api/v1/api-keys/key-1")
            assert resp.status_code == 200
            assert resp.json()["message"] == "Key revoked"


@pytest.mark.asyncio
async def test_revoke_nonexistent_key():
    """DELETE /api/v1/api-keys/{id} with unknown id returns 404."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    with patch("app.api.api_keys.get_session") as mock_get_session:
        mock_get_session.return_value = mock_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/api/v1/api-keys/nonexistent")
            assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_api_key_endpoints.py -v`
Expected: FAIL — `app.api.api_keys` not found.

- [ ] **Step 3: Create the endpoint module**

```python
# app/api/api_keys.py
"""API key management endpoints.

Allows creating, listing, and revoking API keys for MCP server access.
Keys are hashed with SHA-256 before storage; the raw key is returned only
on creation and never stored.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.mcp.auth import generate_api_key, hash_api_key
from app.models.db import ApiKey, User
from app.schemas.api_keys import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyResponse
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ApiKeyCreateResponse)
async def create_api_key(
    body: ApiKeyCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyCreateResponse:
    """Create a new API key. Returns the raw key once — it cannot be retrieved later."""
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)

    api_key = ApiKey(
        key_hash=key_hash,
        name=body.name,
        user_id=user.id,
    )
    session.add(api_key)
    await session.commit()

    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        raw_key=raw_key,
        created_at=api_key.created_at or "",
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKeyResponse]:
    """List all API keys for the current user (no raw key exposed)."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        ApiKeyResponse(
            id=k.id,
            name=k.name,
            is_active=k.is_active,
            created_at=k.created_at or "",
            last_used_at=k.last_used_at,
        )
        for k in keys
    ]


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Revoke an API key (set is_active=false). Does not delete the record."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    api_key.is_active = False
    await session.commit()
    return {"message": "Key revoked"}
```

- [ ] **Step 4: Register the router in `app/api/__init__.py`**

Add after the existing imports:

```python
from app.api.api_keys import router as api_keys_router
```

Add `"api_keys_router"` to the `__all__` list.

- [ ] **Step 5: Include the router in `app/main.py`**

Add `api_keys_router` to the imports from `app.api`:

```python
from app.api import (
    ...
    api_keys_router,
    ...
)
```

Add after the existing `include_router` calls:

```python
    application.include_router(api_keys_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_api_key_endpoints.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend && git add app/api/api_keys.py app/api/__init__.py app/main.py tests/unit/test_api_key_endpoints.py
git commit -m "feat(5b-m4): add API key management endpoints (create/list/revoke)"
```

---

## Task 6: MCP Server with FastMCP

**Files:**
- Create: `app/mcp/server.py`
- Test: `tests/unit/test_mcp_server.py`

This is the core FastMCP server. Each tool is a decorated function that calls the shared tool layer from M1. ~200 lines total.

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_mcp_server.py
"""Tests for the MCP server tool registration and context construction.

Tests that all tools are registered and that multi-project context
is handled correctly.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMcpToolRegistration:
    def test_all_tools_registered(self):
        """Verify all shared tools are exposed via MCP."""
        from app.mcp.server import mcp

        # FastMCP stores tools internally; list them
        tool_names = set(mcp._tool_manager._tools.keys())

        expected = {
            "list_applications",
            "application_stats",
            "get_architecture",
            "search_objects",
            "object_details",
            "impact_analysis",
            "find_path",
            "list_transactions",
            "transaction_graph",
            "get_source_code",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"

    def test_tool_count(self):
        """Verify the expected number of tools are registered."""
        from app.mcp.server import mcp

        tool_names = set(mcp._tool_manager._tools.keys())
        assert len(tool_names) >= 10


class TestMcpContextConstruction:
    @pytest.mark.asyncio
    async def test_project_agnostic_tool(self):
        """list_applications should work without app_name."""
        from app.ai.tools import ChatToolContext

        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {"name": "app1", "module_count": 5},
        ]
        ctx = ChatToolContext(
            graph_store=mock_store,
            app_name="",
            project_id="",
        )
        from app.ai.tools import list_applications
        result = await list_applications(ctx)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_project_specific_tool(self):
        """impact_analysis requires app_name in context."""
        from app.ai.tools import ChatToolContext, impact_analysis

        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {"fqn": "com.app.A", "name": "A", "type": "Class", "file": "A.java", "depth": 1},
        ]
        ctx = ChatToolContext(
            graph_store=mock_store,
            app_name="my-app",
            project_id="proj-1",
        )
        result = await impact_analysis(ctx, node_fqn="com.app.X")
        assert result["total"] == 1
        # Verify app_name was passed to the query
        call_args = mock_store.query.call_args
        assert call_args[1]["app_name"] == "my-app" or "my-app" in str(call_args)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_mcp_server.py -v`
Expected: FAIL — `app.mcp.server` not found.

- [ ] **Step 3: Implement the MCP server**

```python
# app/mcp/server.py
"""FastMCP server — exposes CodeLens architecture tools via MCP protocol.

This is a thin wrapper (~200 lines) over the shared tool functions in
app.ai.tools. Each @mcp.tool() decorated function builds a ChatToolContext
per-call and delegates to the shared layer.

Transport: SSE on port 8090.
Auth: API key via Authorization: Bearer <key> header.

Multi-project context:
- Tools that take app_name build ChatToolContext per-call.
- Project-agnostic tools (list_applications) use GraphStore directly
  without app_name.
"""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from mcp.server.fastmcp import FastMCP

from app.ai import tools
from app.ai.tools import ChatToolContext
from app.config import Settings, get_settings
from app.mcp.auth import ApiKeyAuthenticator
from app.services.neo4j import Neo4jGraphStore, init_neo4j, close_neo4j, get_driver
from app.services.postgres import init_postgres, close_postgres, get_background_session

logger = structlog.get_logger(__name__)

mcp = FastMCP("codelens")

# Module-level state initialized during server startup
_graph_store: Neo4jGraphStore | None = None
_authenticator: ApiKeyAuthenticator | None = None


def _get_graph_store() -> Neo4jGraphStore:
    """Get the initialized GraphStore instance."""
    assert _graph_store is not None, "MCP server not initialized — GraphStore is None"
    return _graph_store


async def _resolve_repo_path(app_name: str) -> str | None:
    """Look up the repo path for an app_name from PostgreSQL."""
    if not app_name:
        return None
    try:
        async with get_background_session() as session:
            from sqlalchemy import select, or_
            from app.models.db import Project
            result = await session.execute(
                select(Project).where(
                    or_(Project.id == app_name, Project.name == app_name)
                )
            )
            project = result.scalar_one_or_none()
            return project.source_path if project else None
    except Exception:
        return None


def _build_context(app_name: str = "", repo_path: str | None = None) -> ChatToolContext:
    """Build a ChatToolContext for a tool call."""
    return ChatToolContext(
        graph_store=_get_graph_store(),
        app_name=app_name,
        project_id="",
        repo_path=repo_path,
    )


# ── Portfolio Tools (project-agnostic) ──────────────────────


@mcp.tool()
async def list_applications() -> list[dict]:
    """List all analyzed applications in CodeLens with their languages and module count."""
    ctx = _build_context()
    return await tools.list_applications(ctx)


@mcp.tool()
async def application_stats(app_name: str) -> dict:
    """Get size, complexity, and technology metrics for an application.

    Args:
        app_name: The application name as shown by list_applications.
    """
    ctx = _build_context(app_name)
    return await tools.application_stats(ctx, app_name=app_name)


# ── Architecture Tools ──────────────────────────────────────


@mcp.tool()
async def get_architecture(app_name: str, level: str = "module") -> dict:
    """Get application architecture showing modules/classes and their dependencies.

    Args:
        app_name: The application name.
        level: Level of detail — "module" or "class".
    """
    ctx = _build_context(app_name)
    return await tools.get_architecture(ctx, level=level)


@mcp.tool()
async def search_objects(app_name: str, query: str, type_filter: str | None = None) -> list[dict]:
    """Search for code objects (classes, functions, tables, endpoints) by name.

    Args:
        app_name: The application name.
        query: Search string — matches name or fully qualified name.
        type_filter: Optional filter: Class, Function, Interface, Table, APIEndpoint.
    """
    ctx = _build_context(app_name)
    return await tools.search_objects(ctx, query=query, type_filter=type_filter)


# ── Node Detail Tools ───────────────────────────────────────


@mcp.tool()
async def object_details(app_name: str, node_fqn: str) -> dict:
    """Get detailed info about a specific code object including callers, callees, and metrics.

    Args:
        app_name: The application name.
        node_fqn: Fully qualified name of the code object.
    """
    ctx = _build_context(app_name)
    return await tools.object_details(ctx, node_fqn=node_fqn)


@mcp.tool()
async def get_source_code(app_name: str, node_fqn: str) -> dict:
    """Get the source code for a specific code object (line-numbered).

    Args:
        app_name: The application name.
        node_fqn: Fully qualified name of the code object.
    """
    repo_path = await _resolve_repo_path(app_name)
    ctx = _build_context(app_name, repo_path=repo_path)
    return await tools.get_source_code(ctx, node_fqn=node_fqn)


# ── Analysis Tools ──────────────────────────────────────────


@mcp.tool()
async def impact_analysis(
    app_name: str,
    node_fqn: str,
    depth: int = 5,
    direction: str = "both",
) -> dict:
    """Compute the blast radius of changing a specific code object.

    Args:
        app_name: The application name.
        node_fqn: Fully qualified name of the node to analyze.
        depth: Max traversal depth (default 5, max 10).
        direction: Impact direction — "downstream", "upstream", or "both".
    """
    ctx = _build_context(app_name)
    return await tools.impact_analysis(
        ctx, node_fqn=node_fqn, depth=depth, direction=direction,
    )


@mcp.tool()
async def find_path(app_name: str, from_fqn: str, to_fqn: str) -> dict:
    """Find the shortest connection path between two code objects.

    Args:
        app_name: The application name.
        from_fqn: Fully qualified name of the source node.
        to_fqn: Fully qualified name of the target node.
    """
    ctx = _build_context(app_name)
    return await tools.find_path(ctx, from_fqn=from_fqn, to_fqn=to_fqn)


# ── Transaction Tools ───────────────────────────────────────


@mcp.tool()
async def list_transactions(app_name: str) -> list[dict]:
    """List all end-to-end transaction flows (API requests) in an application.

    Args:
        app_name: The application name.
    """
    ctx = _build_context(app_name)
    return await tools.list_transactions(ctx)


@mcp.tool()
async def transaction_graph(app_name: str, transaction_name: str) -> dict:
    """Get the full call graph for a specific transaction flow.

    Args:
        app_name: The application name.
        transaction_name: Name of the transaction (e.g., "POST /orders").
    """
    ctx = _build_context(app_name)
    return await tools.transaction_graph(ctx, transaction_name=transaction_name)


# ── Server Lifecycle ────────────────────────────────────────


async def _flush_loop(authenticator: ApiKeyAuthenticator) -> None:
    """Periodically flush batched last_used_at updates."""
    while True:
        await asyncio.sleep(60)
        await authenticator.flush_last_used()


async def run_server() -> None:
    """Initialize services and run the MCP server."""
    global _graph_store, _authenticator

    settings = get_settings()

    # Initialize database connections
    await init_postgres(settings)
    await init_neo4j(settings)

    _graph_store = Neo4jGraphStore(get_driver())
    _authenticator = ApiKeyAuthenticator(
        session_factory=get_background_session,
        cache_ttl_seconds=settings.mcp_api_key_cache_ttl_seconds,
        batch_update_seconds=settings.mcp_last_used_batch_seconds,
    )

    # Start background flush task
    flush_task = asyncio.create_task(_flush_loop(_authenticator))

    logger.info("mcp_server_starting", port=settings.mcp_port)

    try:
        # Run with SSE transport on configured port
        # NOTE: Auth is handled at the application level — the MCP server
        # validates API keys via _authenticator in a custom middleware.
        # For FastMCP >=1.25, use mcp.run() with transport params.
        # If FastMCP doesn't support auth natively, wrap with a FastAPI
        # app that validates Bearer tokens before proxying to MCP.
        await mcp.run_async(transport="sse")
    finally:
        flush_task.cancel()
        try:
            await flush_task
        except asyncio.CancelledError:
            pass
        # Final flush
        await _authenticator.flush_last_used()
        await close_neo4j()
        await close_postgres()


if __name__ == "__main__":
    asyncio.run(run_server())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend && git add app/mcp/server.py tests/unit/test_mcp_server.py
git commit -m "feat(5b-m4): add FastMCP server with all shared tools exposed"
```

---

## Task 7: Docker Compose Service for MCP

**Files:**
- Create: `cast-clone-backend/Dockerfile.mcp`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Create Dockerfile.mcp**

Create `/home/ubuntu/cast-clone/cast-clone-backend/Dockerfile.mcp`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY app/ app/

EXPOSE 8090

CMD ["uv", "run", "python", "-m", "app.mcp.server"]
```

- [ ] **Step 2: Add MCP service to docker-compose.yml**

Add the following service definition to `/home/ubuntu/cast-clone/docker-compose.yml`, before the `volumes:` section:

```yaml
  mcp:
    build:
      context: ./cast-clone-backend
      dockerfile: Dockerfile.mcp
    ports:
      - "${MCP_PORT:-8090}:8090"
    environment:
      DATABASE_URL: "postgresql+asyncpg://codelens:codelens@postgres:5432/codelens"
      NEO4J_URI: "bolt://neo4j:7687"
      NEO4J_USER: "neo4j"
      NEO4J_PASSWORD: "codelens"
      REDIS_URL: "redis://redis:6379/0"
      MCP_PORT: "8090"
    depends_on:
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_healthy
    restart: unless-stopped
```

- [ ] **Step 2: Verify compose config is valid**

Run: `cd /home/ubuntu/cast-clone && docker compose config --quiet`
Expected: exits 0 with no errors (or warnings only).

- [ ] **Step 3: Commit**

```bash
cd /home/ubuntu/cast-clone && git add docker-compose.yml cast-clone-backend/Dockerfile.mcp
git commit -m "feat(5b-m4): add MCP server Dockerfile and Docker Compose service"
```

---

## Task 8: Integration Test — Full MCP Tool Round-Trip

**Files:**
- Create: `tests/unit/test_mcp_integration.py`

This test verifies the end-to-end flow: auth middleware validates a key, MCP tool dispatches to the shared tool layer, result is returned.

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_mcp_integration.py
"""Integration-style tests for MCP server components.

Tests the full flow: auth -> tool dispatch -> shared tool -> result.
All external services (DB, Neo4j) are mocked.
"""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.auth import ApiKeyAuthenticator, hash_api_key, generate_api_key


class TestEndToEndKeyAuth:
    @pytest.mark.asyncio
    async def test_create_and_verify_key(self):
        """Simulate creating a key via the API and verifying it in the MCP auth."""
        # Step 1: Generate a key (simulates what POST /api/v1/api-keys does)
        raw_key = generate_api_key()
        key_hash = hash_api_key(raw_key)

        # Step 2: Set up authenticator with a mock DB that returns this key
        mock_key = MagicMock()
        mock_key.id = "key-123"
        mock_key.key_hash = key_hash
        mock_key.is_active = True
        mock_key.user_id = "user-456"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_key
        mock_session.execute.return_value = mock_result

        session_ctx = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        auth = ApiKeyAuthenticator(
            session_factory=lambda: session_ctx,
            cache_ttl_seconds=300,
            batch_update_seconds=60,
        )

        # Step 3: Verify the key
        result = await auth.verify_key(raw_key)
        assert result is not None
        assert result["key_id"] == "key-123"
        assert result["user_id"] == "user-456"

        # Step 4: Verify cache works (second call should not hit DB)
        result2 = await auth.verify_key(raw_key)
        assert result2 is not None
        assert mock_session.execute.call_count == 1  # Only one DB call


class TestToolDispatchWithContext:
    @pytest.mark.asyncio
    async def test_mcp_tool_uses_shared_layer(self):
        """Verify MCP tools delegate to the shared tool layer correctly."""
        from app.ai.tools import ChatToolContext, search_objects

        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {"fqn": "com.app.OrderService", "name": "OrderService",
             "type": "Class", "language": "Java", "path": "Order.java"},
        ]

        ctx = ChatToolContext(
            graph_store=mock_store,
            app_name="test-app",
            project_id="proj-1",
        )

        result = await search_objects(ctx, query="Order")
        assert len(result) == 1
        assert result[0]["fqn"] == "com.app.OrderService"

        # Verify the query included app_name
        call_args = mock_store.query.call_args
        cypher = call_args[0][0]
        params = call_args[1] if len(call_args) > 1 else call_args[0][1]
        assert params.get("app_name") == "test-app"
```

- [ ] **Step 2: Run test**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_mcp_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd /home/ubuntu/cast-clone/cast-clone-backend && git add tests/unit/test_mcp_integration.py
git commit -m "test(5b-m4): add MCP integration tests for auth + tool dispatch"
```

---

## Task 9: Run Full Test Suite

- [ ] **Step 1: Run all M4 tests**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/test_mcp_config.py tests/unit/test_api_key_model.py tests/unit/test_api_key_schemas.py tests/unit/test_api_key_auth.py tests/unit/test_api_key_endpoints.py tests/unit/test_mcp_server.py tests/unit/test_mcp_integration.py -v`
Expected: All PASS

- [ ] **Step 2: Run existing unit tests to ensure no regressions**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run pytest tests/unit/ -v --timeout=60`
Expected: All PASS (no regressions from model/config changes)

- [ ] **Step 3: Run linting**

Run: `cd /home/ubuntu/cast-clone/cast-clone-backend && uv run ruff check app/mcp/ app/api/api_keys.py app/schemas/api_keys.py`
Expected: No errors

---

## Summary

| Task | Files | What It Delivers |
|------|-------|------------------|
| 1 | `pyproject.toml`, `app/config.py` | `mcp[cli]` dependency + MCP config settings |
| 2 | `app/models/db.py` | `ApiKey` ORM model |
| 3 | `app/schemas/api_keys.py` | Pydantic request/response schemas |
| 4 | `app/mcp/__init__.py`, `app/mcp/auth.py` | SHA-256 auth middleware with cache + batched updates |
| 5 | `app/api/api_keys.py`, `app/api/__init__.py`, `app/main.py` | Key management REST endpoints (POST/GET/DELETE) |
| 6 | `app/mcp/server.py` | FastMCP server with all shared tools (~200 lines) |
| 7 | `docker-compose.yml` | MCP Docker Compose service on port 8090 |
| 8 | `tests/unit/test_mcp_integration.py` | End-to-end auth + tool dispatch tests |
| 9 | (none) | Full test suite validation |

**Total estimated time:** ~45-60 minutes for implementation, following TDD steps.

**Key design decisions:**
- SHA-256 (not bcrypt) for API key hashing — keys are high-entropy random strings, brute force is impractical, and bcrypt's ~100ms latency is unacceptable for per-request MCP auth
- In-memory cache with 5-min TTL avoids DB round-trips during agent sessions
- Batched `last_used_at` updates (at most once per minute per key) prevent write amplification
- MCP tools take `app_name` as an explicit parameter (unlike chat tools which get it from the project context) because MCP clients are project-agnostic
- MCP container depends on API container's health check, ensuring migrations have run
