"""Unit test fixtures — no external services required."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.models.db import Base, Project


# ---------------------------------------------------------------------------
# SQLite compatibility shim: map JSONB -> JSON for in-memory test sessions
# ---------------------------------------------------------------------------


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return compiler.visit_JSON(element, **kw)


# ---------------------------------------------------------------------------
# Async SQLite session fixture for unit tests that need real ORM operations
# ---------------------------------------------------------------------------


_LOC_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS git_connectors (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    base_url VARCHAR(1024) NOT NULL,
    auth_method VARCHAR(50) NOT NULL DEFAULT 'pat',
    encrypted_token TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'connected',
    remote_username VARCHAR(255),
    created_by VARCHAR(36),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS repositories (
    id VARCHAR(36) PRIMARY KEY,
    connector_id VARCHAR(36) NOT NULL,
    repo_full_name VARCHAR(512) NOT NULL,
    repo_clone_url VARCHAR(1024) NOT NULL,
    default_branch VARCHAR(255) NOT NULL DEFAULT 'main',
    description TEXT,
    language VARCHAR(100),
    is_private BOOLEAN DEFAULT 0,
    local_path VARCHAR(1024),
    clone_status VARCHAR(50) DEFAULT 'pending',
    clone_error TEXT,
    last_synced_at DATETIME,
    created_by VARCHAR(36),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    source_path VARCHAR(1024) NOT NULL,
    status VARCHAR(50) DEFAULT 'created',
    repository_id VARCHAR(36),
    branch VARCHAR(255),
    last_analyzed_commit VARCHAR(40),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    stage VARCHAR(50),
    stage_progress INTEGER,
    started_at DATETIME,
    completed_at DATETIME,
    error_message TEXT,
    node_count INTEGER,
    edge_count INTEGER,
    report JSON,
    snapshot JSON,
    commit_sha VARCHAR(40),
    total_loc INTEGER
);

CREATE TABLE IF NOT EXISTS repository_loc_tracking (
    id VARCHAR(36) PRIMARY KEY,
    repository_id VARCHAR(36) NOT NULL UNIQUE,
    billable_loc INTEGER NOT NULL DEFAULT 0,
    max_loc_project_id VARCHAR(36),
    max_loc_branch_name VARCHAR(255),
    breakdown JSON NOT NULL DEFAULT '{}',
    last_recalculated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest_asyncio.fixture
async def async_session() -> AsyncSession:  # type: ignore[misc]
    """In-memory SQLite async session for unit tests that need real ORM ops.

    Creates only the tables needed for loc_tracking tests.  Foreign key
    enforcement is left off (SQLite default) so Repository rows can be
    inserted without a real GitConnector row.  Each test gets a fresh DB.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        for stmt in _LOC_TRACKING_DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def mock_session():
    """Mock AsyncSession for DB-dependent tests."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.add = MagicMock()  # add() is sync in SQLAlchemy
    return session


@pytest_asyncio.fixture
async def app_client(mock_session):
    """Async test client with mocked database session.

    Patches get_session to yield the mock session, so API endpoint tests
    don't need a real PostgreSQL connection. Also bypasses the license
    gate so pre-existing API tests don't need to know about licensing.
    """
    from app.api.dependencies import require_license_writable
    from app.main import create_app
    from app.services.postgres import get_session

    app = create_app()

    async def override_get_session():
        yield mock_session

    async def override_require_license_writable() -> None:
        return None

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_license_writable] = (
        override_require_license_writable
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


def make_project(
    id: str | None = None,
    name: str = "test-project",
    source_path: str = "/opt/code/test",
    status: str = "created",
) -> MagicMock:
    """Factory for mock Project ORM objects."""
    project = MagicMock(spec=Project)
    project.id = id or str(uuid4())
    project.name = name
    project.source_path = source_path
    project.status = status
    project.created_at = datetime.now(timezone.utc)
    project.updated_at = datetime.now(timezone.utc)
    return project
