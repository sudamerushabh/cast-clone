from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

PUBLIC_PATHS = {
    "/",
    "/health",
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/setup-status",
    "/api/v1/auth/setup",
    "/api/v1/license/status",
    "/api/v1/system/info",
    "/docs",
    "/openapi.json",
    "/redoc",
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("SECRET_KEY", "test-secret-for-enforcement")
    monkeypatch.setenv("LICENSE_DISABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    fresh_app = create_app()
    # raise_server_exceptions=False so downstream handler errors (e.g. DB not
    # initialised because TestClient skips lifespan) surface as 500 rather than
    # re-raising. The middleware's job here is strictly to gate 401s; the rest
    # of the stack's health is not its concern.
    return TestClient(fresh_app, raise_server_exceptions=False)


def test_public_paths_return_200_or_404_not_401(client: TestClient) -> None:
    for path in ["/api/v1/auth/setup-status", "/api/v1/license/status"]:
        resp = client.get(path)
        assert resp.status_code != 401, f"{path} should be public"


def test_sensitive_paths_return_401_without_token(client: TestClient) -> None:
    sensitive = [
        "/api/v1/projects",
        "/api/v1/repositories",
        "/api/v1/users",
        "/api/v1/connectors",
        "/api/v1/activity",
    ]
    for path in sensitive:
        resp = client.get(path)
        assert resp.status_code == 401, (
            f"{path} should require auth; got {resp.status_code}"
        )
