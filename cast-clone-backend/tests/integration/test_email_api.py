"""Integration tests for email API endpoints (CHAN-42).

Uses an in-memory SQLite database for the email_config table so that
real SQLAlchemy sessions exercise the full API code path without
requiring a running PostgreSQL instance.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# JSONB -> JSON compile rule for SQLite
# ---------------------------------------------------------------------------


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return compiler.visit_JSON(element, **kw)


# ---------------------------------------------------------------------------
# DDL for the tables we need (SQLite-compatible, no ::jsonb casts)
# ---------------------------------------------------------------------------

_EMAIL_CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS email_config (
    id VARCHAR(36) PRIMARY KEY,
    singleton BOOLEAN DEFAULT 1 NOT NULL UNIQUE,
    enabled BOOLEAN DEFAULT 0 NOT NULL,
    smtp_host TEXT DEFAULT '' NOT NULL,
    smtp_port INTEGER DEFAULT 587 NOT NULL,
    smtp_username TEXT DEFAULT '' NOT NULL,
    smtp_password_encrypted BLOB,
    smtp_use_tls BOOLEAN DEFAULT 1 NOT NULL,
    from_address TEXT DEFAULT '' NOT NULL,
    from_name TEXT DEFAULT 'ChangeSafe' NOT NULL,
    recipients JSON DEFAULT '[]' NOT NULL,
    flentas_bcc_enabled BOOLEAN DEFAULT 0 NOT NULL,
    cadence TEXT DEFAULT 'off' NOT NULL,
    cadence_day INTEGER DEFAULT 1 NOT NULL,
    cadence_hour_utc INTEGER DEFAULT 9 NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _sqlite_engine():
    """Create a shared in-memory SQLite engine for integration tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text(_EMAIL_CONFIG_DDL))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def _session_factory(_sqlite_engine):
    """Create an async session factory bound to the in-memory SQLite engine."""
    return async_sessionmaker(_sqlite_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def app_client(_session_factory):
    """Async httpx client with session overridden to use in-memory SQLite.

    Bypasses auth (AUTH_DISABLED=true via default settings) and license gate.
    Also patches get_background_session so service-layer code that fetches
    its own session outside of FastAPI Depends() still hits the test DB.
    """
    from app.api.dependencies import require_license_writable
    from app.main import create_app
    from app.services.postgres import get_session

    app = create_app()

    async def override_get_session():
        async with _session_factory() as session:
            yield session

    async def override_require_license_writable() -> None:
        return None

    @contextlib.asynccontextmanager
    async def override_get_background_session() -> AsyncIterator[AsyncSession]:
        async with _session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_license_writable] = (
        override_require_license_writable
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "app.services.postgres.get_background_session",
            override_get_background_session,
        ):
            yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetEmailConfig:
    @pytest.mark.asyncio
    async def test_returns_default_when_no_config(self, app_client: AsyncClient):
        resp = await app_client.get("/api/v1/email/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["smtp_host"] == ""
        assert data["smtp_password"] == ""
        assert data["cadence"] == "off"


class TestPutEmailConfig:
    @pytest.mark.asyncio
    async def test_create_config(self, app_client: AsyncClient):
        payload = {
            "enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "user",
            "smtp_password": "secret123",
            "smtp_use_tls": True,
            "from_address": "noreply@example.com",
            "from_name": "ChangeSafe",
            "recipients": ["admin@example.com"],
            "flentas_bcc_enabled": False,
            "cadence": "monthly",
            "cadence_day": 1,
            "cadence_hour_utc": 9,
        }
        resp = await app_client.put("/api/v1/email/config", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["smtp_host"] == "smtp.example.com"
        assert data["smtp_password"] == "***"  # Redacted

    @pytest.mark.asyncio
    async def test_mask_preserves_password(self, app_client: AsyncClient):
        # First set a password
        payload = {
            "enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "user",
            "smtp_password": "original-password",
            "smtp_use_tls": True,
            "from_address": "noreply@example.com",
            "from_name": "ChangeSafe",
            "recipients": [],
            "flentas_bcc_enabled": False,
            "cadence": "off",
            "cadence_day": 1,
            "cadence_hour_utc": 9,
        }
        resp1 = await app_client.put("/api/v1/email/config", json=payload)
        assert resp1.status_code == 200
        assert resp1.json()["smtp_password"] == "***"

        # Now update with "***" — should preserve existing password
        payload["smtp_password"] = "***"
        payload["smtp_host"] = "new-smtp.example.com"
        resp2 = await app_client.put("/api/v1/email/config", json=payload)
        assert resp2.status_code == 200
        assert resp2.json()["smtp_password"] == "***"
        assert resp2.json()["smtp_host"] == "new-smtp.example.com"


class TestTestSend:
    @pytest.mark.asyncio
    async def test_test_send_success(self, app_client: AsyncClient):
        # First configure SMTP
        payload = {
            "enabled": True,
            "smtp_host": "localhost",
            "smtp_port": 1025,
            "smtp_username": "",
            "smtp_password": "",
            "smtp_use_tls": False,
            "from_address": "test@example.com",
            "from_name": "ChangeSafe",
            "recipients": [],
            "flentas_bcc_enabled": False,
            "cadence": "off",
            "cadence_day": 1,
            "cadence_hour_utc": 9,
        }
        await app_client.put("/api/v1/email/config", json=payload)

        # Mock aiosmtplib.send to succeed
        with (
            patch("app.services.email.aiosmtplib.send", new_callable=AsyncMock),
            patch(
                "app.services.email.cumulative_loc",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            resp = await app_client.post(
                "/api/v1/email/test-send",
                json={"to": "recipient@example.com"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "sent"
            assert data["error"] is None
