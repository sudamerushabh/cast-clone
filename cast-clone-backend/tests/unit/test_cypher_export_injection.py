from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("LICENSE_DISABLED", "true")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    from app.services.postgres import get_session

    app = create_app()

    # Override the DB session dependency so the auth-disabled branch of
    # get_current_user doesn't blow up on an uninitialized engine. We never
    # actually query Postgres in this test (auth is disabled), but FastAPI
    # still resolves the dependency chain.
    async def _fake_session() -> AsyncMock:
        return AsyncMock()

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app, raise_server_exceptions=False)


def test_export_rejects_unknown_field_name(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/export/proj/nodes.csv",
        params={"fields": "fqn,name,fqn} RETURN 1 AS pwned //"},
    )
    assert resp.status_code == 400
    assert "unknown field" in resp.text.lower()


def test_export_rejects_cypher_keyword_injection(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/export/proj/nodes.csv",
        params={"fields": "fqn,MATCH n RETURN n"},
    )
    assert resp.status_code == 400


def test_export_rejects_semicolon_injection(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/export/proj/nodes.csv",
        params={"fields": "fqn;DROP DATABASE"},
    )
    assert resp.status_code == 400


def test_export_accepts_valid_node_fields(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/export/proj/nodes.csv",
        params={"fields": "fqn,name,kind"},
    )
    # May be 200 with empty body, or 404 if project doesn't exist.
    # Either way, NOT 400.
    assert resp.status_code != 400


def test_export_accepts_valid_edge_fields(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/export/proj/edges.csv",
        params={"fields": "source,target,type"},
    )
    assert resp.status_code != 400
