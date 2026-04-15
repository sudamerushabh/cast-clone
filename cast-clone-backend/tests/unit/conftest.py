"""Unit test fixtures — no external services required."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.db import Project


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
