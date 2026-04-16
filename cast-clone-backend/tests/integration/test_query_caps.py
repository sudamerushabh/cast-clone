"""Integration tests for Task 8 (CHAN-62): pagination & graph depth caps.

Every list / search / graph-traversal endpoint in ``app/api/`` should reject
unbounded query parameters with HTTP 422 (FastAPI's validation error code for
a violated ``Query(..., le=...)`` constraint). These tests exercise the
boundary behaviour end-to-end via the ASGI transport so a regression in any
affected router surfaces here before reaching production.

Pattern cribbed from ``tests/integration/test_idor_protection.py`` — auth
enabled, DB stubbed, ``get_current_user`` / ``get_accessible_project``
overridden so the validation layer is the only thing standing between the
request and a 200.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.models.db import User

pytestmark = pytest.mark.asyncio


def _is_validation_error_response(resp: object) -> bool:
    """True iff the response body is a FastAPI/Pydantic validation error.

    FastAPI's 422 body has shape ``{"detail": [{"loc": [...], "msg": ...,
    "type": ...}, ...]}``. A handler-level error (500 with plaintext
    ``Internal Server Error`` from the ASGI transport) or a real 2xx
    payload does NOT match this shape, so this lets us distinguish
    "cap rejected the request" from "cap let it through and the stubbed
    handler crashed".
    """
    import json as _json

    try:
        body = _json.loads(resp.content)  # type: ignore[attr-defined]
    except (ValueError, TypeError):
        return False
    if not isinstance(body, dict):
        return False
    detail = body.get("detail")
    if not isinstance(detail, list) or not detail:
        return False
    first = detail[0]
    return (
        isinstance(first, dict)
        and "loc" in first
        and "msg" in first
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
    monkeypatch.setenv("SECRET_KEY", "integration-test-secret-key-for-query-caps")
    monkeypatch.setenv("LICENSE_DISABLED", "true")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")

    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def async_client(auth_enabled_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    # ``raise_app_exceptions=False`` lets the ASGI transport convert any
    # unhandled server-side exception into a 500 response instead of
    # propagating it into the test. We want to assert on HTTP status
    # codes, not on the specific shape of DB/Neo4j mocks.
    transport = ASGITransport(app=auth_enabled_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def admin_token() -> tuple[str, str]:
    """Mint an access token whose user will be overridden to admin."""
    from app.services.auth import create_access_token

    secret = "integration-test-secret-key-for-query-caps"
    uid = str(uuid4())
    token = create_access_token(uid, secret)
    return token, uid


def _override_admin(app: FastAPI, user: User) -> None:
    """Short-circuit auth + DB so validation runs before any handler body."""
    from app.api.analysis_views import get_graph_store as analysis_get_graph_store
    from app.api.dependencies import (
        get_accessible_project,
        get_current_user,
        require_admin,
    )
    from app.api.graph import get_graph_store as graph_get_graph_store
    from app.services.postgres import get_session

    async def _fake_current_user() -> User:
        return user

    async def _fake_require_admin() -> User:
        return user

    async def _fake_accessible_project() -> MagicMock:
        # Returned only if validation lets the request through; the shape
        # doesn't matter for these tests because we only assert on 422.
        proj = MagicMock()
        proj.id = "test-project"
        return proj

    def _fake_graph_store() -> MagicMock:
        # Any handler that reaches this point was past validation; return a
        # MagicMock so awaiting its coroutine methods won't blow up before
        # the test has a chance to compare status codes.
        return MagicMock()

    stub_session = MagicMock()

    async def _fake_get_session():
        yield stub_session

    app.dependency_overrides[get_current_user] = _fake_current_user
    app.dependency_overrides[require_admin] = _fake_require_admin
    app.dependency_overrides[get_accessible_project] = _fake_accessible_project
    app.dependency_overrides[get_session] = _fake_get_session
    app.dependency_overrides[analysis_get_graph_store] = _fake_graph_store
    app.dependency_overrides[graph_get_graph_store] = _fake_graph_store


# ── Pagination: `limit` upper bound ──────────────────────────────────────


async def test_projects_limit_above_cap_rejected(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    admin_token: tuple[str, str],
) -> None:
    """GET /api/v1/projects?limit=1000 must be rejected (cap = 200)."""
    token, uid = admin_token
    _override_admin(auth_enabled_app, _admin(uid, "root"))

    resp = await async_client.get(
        "/api/v1/projects?limit=1000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


async def test_projects_limit_at_cap_accepted(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    admin_token: tuple[str, str],
) -> None:
    """GET /api/v1/projects?limit=200 must pass validation (== cap)."""
    token, uid = admin_token
    _override_admin(auth_enabled_app, _admin(uid, "root"))

    resp = await async_client.get(
        "/api/v1/projects?limit=200",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 500 acceptable — handler body uses stubbed DB that may fail; we
    # only assert the cap did NOT reject the request at the Query layer.
    # Strengthened assertion: also confirm the response body is NOT a
    # Pydantic validation error payload (``raise_app_exceptions=False``
    # converts handler crashes to 500, so a naive ``!= 422`` check would
    # pass even if the cap silently mutated to reject ``limit=200``).
    assert resp.status_code in (200, 500), resp.text
    assert not _is_validation_error_response(resp), resp.text


# ── Pagination: `offset` lower bound ─────────────────────────────────────


async def test_projects_negative_offset_rejected(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    admin_token: tuple[str, str],
) -> None:
    """GET /api/v1/projects?offset=-1 must be rejected (ge=0)."""
    token, uid = admin_token
    _override_admin(auth_enabled_app, _admin(uid, "root"))

    resp = await async_client.get(
        "/api/v1/projects?offset=-1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


async def test_projects_offset_above_cap_rejected(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    admin_token: tuple[str, str],
) -> None:
    """Deep pagination is forbidden — offset > 10000 must 422."""
    token, uid = admin_token
    _override_admin(auth_enabled_app, _admin(uid, "root"))

    resp = await async_client.get(
        "/api/v1/projects?offset=999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


# ── Graph traversal: `depth` cap ─────────────────────────────────────────


async def test_graph_neighbors_depth_above_cap_rejected(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    admin_token: tuple[str, str],
) -> None:
    """GET /api/v1/graphs/{pid}/neighbors/{fqn}?depth=100 must be rejected.

    Variable-length Cypher traversal is O(n^depth); this is the DoS vector
    CHAN-62 is closing. Cap is ``le=5``.
    """
    token, uid = admin_token
    _override_admin(auth_enabled_app, _admin(uid, "root"))

    resp = await async_client.get(
        "/api/v1/graphs/test-project/neighbors/some.node.fqn?depth=100",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


async def test_graph_neighbors_depth_at_cap_accepted(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    admin_token: tuple[str, str],
) -> None:
    """depth=5 is exactly the cap — validation must pass."""
    token, uid = admin_token
    _override_admin(auth_enabled_app, _admin(uid, "root"))

    resp = await async_client.get(
        "/api/v1/graphs/test-project/neighbors/some.node.fqn?depth=5",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 500 acceptable — handler body uses stubbed DB that may fail; we
    # only assert the cap did NOT reject. Strengthened assertion: also
    # confirm the response body is NOT a Pydantic validation error.
    assert resp.status_code in (200, 500), resp.text
    assert not _is_validation_error_response(resp), resp.text


# ── Impact analysis: `max_depth` cap ─────────────────────────────────────


async def test_impact_analysis_max_depth_above_cap_rejected(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    admin_token: tuple[str, str],
) -> None:
    """max_depth=50 on impact must be rejected (cap = 5)."""
    token, uid = admin_token
    _override_admin(auth_enabled_app, _admin(uid, "root"))

    resp = await async_client.get(
        "/api/v1/analysis/test-project/impact/some.fqn?max_depth=50",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


# ── Graph list: `limit` cap ──────────────────────────────────────────────


async def test_graph_nodes_limit_above_cap_rejected(
    async_client: AsyncClient,
    auth_enabled_app: FastAPI,
    admin_token: tuple[str, str],
) -> None:
    """GET /api/v1/graphs/{pid}/nodes?limit=5000 must be rejected."""
    token, uid = admin_token
    _override_admin(auth_enabled_app, _admin(uid, "root"))

    resp = await async_client.get(
        "/api/v1/graphs/test-project/nodes?limit=5000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text
