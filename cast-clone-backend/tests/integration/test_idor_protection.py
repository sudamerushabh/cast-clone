"""Integration-style tests for IDOR (Insecure Direct Object Reference)
protection on resource routers.

These tests boot the FastAPI app with auth enabled and verify that:

1. Unauthenticated requests are rejected (401).
2. Non-admin members cannot hit admin-only endpoints (403).
3. The deny-by-default auth enforcer (Task 2) and per-endpoint dependencies
   (this task) combine to protect every resource router.

Database-backed ownership tests (e.g. "user B cannot DELETE user A's
project") are exercised at the unit level in the per-router fixtures,
because setting up a real PostgreSQL here would require docker/testcontainers
and is out of scope for Task 3. The corresponding xfail test below
documents the gap so a future sprint can fill it in.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.models.db import User

pytestmark = pytest.mark.asyncio


def _member(user_id: str, username: str) -> User:
    return User(
        id=user_id,
        username=username,
        email=f"{username}@test.local",
        password_hash="",
        role="member",
        is_active=True,
    )


def _admin(user_id: str, username: str) -> User:
    return User(
        id=user_id,
        username=username,
        email=f"{username}@test.local",
        password_hash="",
        role="admin",
        is_active=True,
    )


@pytest_asyncio.fixture
async def auth_enabled_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Build a FastAPI app instance with auth enabled (but DB-free)."""
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("SECRET_KEY", "integration-test-secret-key-for-idor")
    monkeypatch.setenv("LICENSE_DISABLED", "true")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def async_client(auth_enabled_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=auth_enabled_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def two_users_with_tokens():
    """Return (token_a, uid_a, token_b, uid_b) without touching a real DB.

    Signs two tokens against the same SECRET_KEY used by the app so they
    round-trip through decode_access_token. The ``get_current_user``
    dependency looks up the users in the DB, so callers override that
    dependency with ``_override_current_user`` in each test to supply the
    synthesised ``User`` objects.
    """
    from app.services.auth import create_access_token

    secret = "integration-test-secret-key-for-idor"
    uid_a, uid_b = str(uuid4()), str(uuid4())
    token_a = create_access_token(uid_a, secret)
    token_b = create_access_token(uid_b, secret)
    return token_a, uid_a, token_b, uid_b


def _override_current_user(app: FastAPI, user: User) -> None:
    """Override ``get_current_user`` / ``require_admin`` to return ``user``.

    Also stubs ``get_session`` so FastAPI's dependency resolver doesn't blow
    up on the uninitialised ``_session_factory`` for endpoints that take a
    session param purely for data access after auth has already settled.
    """
    from app.api.dependencies import get_current_user, require_admin
    from app.services.postgres import get_session
    from fastapi import HTTPException, status

    async def _fake_current_user() -> User:
        return user

    async def _fake_require_admin() -> User:
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        return user

    stub_session = MagicMock()

    async def _fake_get_session():
        yield stub_session

    app.dependency_overrides[get_current_user] = _fake_current_user
    app.dependency_overrides[require_admin] = _fake_require_admin
    app.dependency_overrides[get_session] = _fake_get_session


async def test_requests_without_token_are_rejected(
    async_client: AsyncClient,
) -> None:
    """The Task 2 middleware must reject every sensitive path when no token
    is present — this is the outer ring of defence."""
    sensitive = [
        "/api/v1/projects",
        "/api/v1/repositories",
        "/api/v1/connectors",
        "/api/v1/users",
        "/api/v1/activity",
        "/api/v1/analysis/foo/impact/bar.baz",
        "/api/v1/graphs/foo/nodes",
    ]
    for path in sensitive:
        resp = await async_client.get(path)
        assert resp.status_code == 401, (
            f"{path} should require auth; got {resp.status_code}"
        )


async def test_requests_with_invalid_token_are_rejected(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
) -> None:
    """Middleware lets a Bearer header through; the per-endpoint dependency
    must then validate the JWT and reject garbage. We stub ``get_session``
    so the dependency resolver reaches ``get_current_user`` rather than
    tripping on an uninitialised PG factory."""
    from app.services.postgres import get_session

    auth_enabled_app.dependency_overrides.clear()

    stub_session = MagicMock()

    async def _fake_get_session():
        yield stub_session

    auth_enabled_app.dependency_overrides[get_session] = _fake_get_session

    resp = await async_client.get(
        "/api/v1/projects",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    # The JWT is invalid, so ``get_current_user`` raises 401.
    assert resp.status_code == 401, resp.text


async def test_non_admin_cannot_list_users(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    two_users_with_tokens,
) -> None:
    """Users endpoint is admin-only — a member token must get 403."""
    token_a, uid_a, _tb, _ub = two_users_with_tokens
    _override_current_user(auth_enabled_app, _member(uid_a, "alice"))

    resp = await async_client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, resp.text


async def test_non_admin_cannot_create_user(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    two_users_with_tokens,
) -> None:
    """Creating a user is admin-only."""
    token_a, uid_a, _tb, _ub = two_users_with_tokens
    _override_current_user(auth_enabled_app, _member(uid_a, "alice"))

    resp = await async_client.post(
        "/api/v1/users",
        json={
            "username": "eve",
            "email": "eve@test.local",
            "password": "eve-pass-1234",
            "role": "member",
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, resp.text


async def test_non_admin_cannot_create_connector(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    two_users_with_tokens,
) -> None:
    """Connectors are admin-only; a member must get 403 even with a valid token."""
    token_a, uid_a, _tb, _ub = two_users_with_tokens
    _override_current_user(auth_enabled_app, _member(uid_a, "alice"))

    resp = await async_client.post(
        "/api/v1/connectors",
        json={
            "name": "A Connector",
            "provider": "github",
            "base_url": "https://api.github.com",
            "token": "fake-token",
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, resp.text


async def test_non_admin_cannot_list_activity(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    two_users_with_tokens,
) -> None:
    """Activity log is admin-only."""
    token_a, uid_a, _tb, _ub = two_users_with_tokens
    _override_current_user(auth_enabled_app, _member(uid_a, "alice"))

    resp = await async_client.get(
        "/api/v1/activity",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, resp.text


async def test_user_cannot_read_another_users_repo(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    two_users_with_tokens,
) -> None:
    """If user B hits the repository detail endpoint for a repo user A
    created, they should get 403 (not 200 with the data).

    We mock the session so the repo lookup returns a Repository created_by
    user A, and override get_current_user to return user B.
    """
    from app.models.db import Repository
    from app.services.postgres import get_session

    token_a, uid_a, token_b, uid_b = two_users_with_tokens
    _override_current_user(auth_enabled_app, _member(uid_b, "bob"))

    repo = MagicMock(spec=Repository)
    repo.id = str(uuid4())
    repo.created_by = uid_a  # owned by Alice
    repo.projects = []

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = repo

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override_get_session():
        yield mock_session

    auth_enabled_app.dependency_overrides[get_session] = override_get_session

    resp = await async_client.get(
        f"/api/v1/repositories/{repo.id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403, resp.text


async def test_user_cannot_delete_another_users_repo(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    two_users_with_tokens,
) -> None:
    """Same shape as the read test but for DELETE."""
    from app.models.db import Repository
    from app.services.postgres import get_session

    token_a, uid_a, token_b, uid_b = two_users_with_tokens
    _override_current_user(auth_enabled_app, _member(uid_b, "bob"))

    repo = MagicMock(spec=Repository)
    repo.id = str(uuid4())
    repo.created_by = uid_a

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = repo

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    async def override_get_session():
        yield mock_session

    auth_enabled_app.dependency_overrides[get_session] = override_get_session

    resp = await async_client.delete(
        f"/api/v1/repositories/{repo.id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403, resp.text


async def test_admin_can_read_any_repo(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    two_users_with_tokens,
) -> None:
    """Negative control: an admin must bypass the ownership check even if
    they are not the repo creator."""
    from app.models.db import Repository
    from app.services.postgres import get_session

    token_a, uid_a, token_b, uid_b = two_users_with_tokens
    admin = _admin(str(uuid4()), "root")
    _override_current_user(auth_enabled_app, admin)

    repo = MagicMock(spec=Repository)
    repo.id = str(uuid4())
    repo.connector_id = str(uuid4())
    repo.repo_full_name = "owner/repo"
    repo.default_branch = "main"
    repo.description = None
    repo.language = "Python"
    repo.is_private = False
    repo.clone_status = "cloned"
    repo.clone_error = None
    repo.local_path = "/tmp/x"
    repo.last_synced_at = None
    from datetime import datetime, timezone

    repo.created_at = datetime.now(timezone.utc)
    repo.created_by = uid_a  # owned by Alice
    repo.projects = []

    repo_result = MagicMock()
    repo_result.scalar_one_or_none.return_value = repo
    tracking_result = MagicMock()
    tracking_result.scalar_one_or_none.return_value = None

    mock_session = MagicMock()
    # First execute() returns the Repository; subsequent calls (tracking fetch
    # post-licensing merge) return None so billable_loc stays null.
    mock_session.execute = AsyncMock(side_effect=[repo_result, tracking_result])

    async def override_get_session():
        yield mock_session

    auth_enabled_app.dependency_overrides[get_session] = override_get_session

    resp = await async_client.get(
        f"/api/v1/repositories/{repo.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200, resp.text


async def test_user_cannot_delete_another_users_standalone_project(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    two_users_with_tokens,
) -> None:
    from app.models.db import Project
    from app.services.postgres import get_session

    token_a, uid_a, token_b, uid_b = two_users_with_tokens
    _override_current_user(auth_enabled_app, _member(uid_b, "bob"))

    project = MagicMock(spec=Project)
    project.id = str(uuid4())
    project.repository = None  # standalone — no ownership chain available

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = project

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    async def override_get_session():
        yield mock_session

    auth_enabled_app.dependency_overrides[get_session] = override_get_session

    resp = await async_client.delete(
        f"/api/v1/projects/{project.id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403
