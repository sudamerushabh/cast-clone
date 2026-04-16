from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

PUBLIC_PATHS = {
    "/",
    "/health",
    "/api/v1/auth/login",
    "/api/v1/auth/setup-status",
    "/api/v1/auth/setup",
    "/docs",
    "/openapi.json",
    "/redoc",
}


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> TestClient:
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("SECRET_KEY", "test-secret-for-enforcement")
    # LICENSE_DISABLED=true keeps the licensing subsystem out of the test
    # path so a missing license database doesn't interfere with middleware
    # behaviour assertions.
    monkeypatch.setenv("LICENSE_DISABLED", "true")
    from app.config import get_settings

    # conftest.py defaults AUTH_DISABLED=true before any test runs so app.main
    # imports successfully. Clear the lru_cache so this test's
    # AUTH_DISABLED=false propagates to every get_settings() caller.
    get_settings.cache_clear()
    # Register a teardown so the cached Settings reflecting AUTH_DISABLED=false
    # doesn't leak into subsequent tests (which expect the conftest default).
    # Finalisers run after monkeypatch has already restored env, so
    # cache_clear() forces the next get_settings() to reload from the
    # restored env.
    request.addfinalizer(get_settings.cache_clear)
    from app.main import create_app

    fresh_app = create_app()
    # raise_server_exceptions=False so downstream handler errors (e.g. DB not
    # initialised because TestClient skips lifespan) surface as 500 rather than
    # re-raising. The middleware's job here is strictly to gate 401s; the rest
    # of the stack's health is not its concern.
    # NOTE: intentionally NOT using `with TestClient(...)` — the `with` triggers
    # app lifespan which initialises Postgres/Neo4j/Redis and mutates module-level
    # singletons. If those fail (as they will in a pure unit test without
    # docker-compose services up), global state leaks into later tests.
    return TestClient(fresh_app, raise_server_exceptions=False)


def test_public_paths_return_200_or_404_not_401(client: TestClient) -> None:
    for path in ["/api/v1/auth/setup-status"]:
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


def test_auth_disabled_allows_unauthenticated_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("LICENSE_DISABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    try:
        resp = client.get("/api/v1/projects")
        assert resp.status_code != 401
    finally:
        get_settings.cache_clear()


def test_bearer_token_bypasses_middleware_401(client: TestClient) -> None:
    # Middleware only checks Authorization scheme, not token validity.
    # A bearer-shaped header MUST reach the downstream handler — whether
    # that handler then returns 200, 401 (invalid token), or 500 (DB
    # unavailable because TestClient skips lifespan) is not the middleware's
    # concern. What we verify here is that the response did NOT come from
    # the middleware's deny branch, identified by its exact JSON body.
    resp_no_auth = client.get("/api/v1/projects")
    assert resp_no_auth.status_code == 401
    assert resp_no_auth.json() == {"detail": "Not authenticated"}

    resp_bearer = client.get(
        "/api/v1/projects",
        headers={"Authorization": "Bearer anything-shaped-like-a-token"},
    )
    # Either the handler rejected the token (401 from get_current_user) or
    # it produced some other status. In either case, the response should
    # NOT be the middleware's exact 401 body — that proves it passed through.
    if resp_bearer.status_code == 401:
        assert resp_bearer.json() != {"detail": "Not authenticated"}, (
            "Bearer-shaped header should reach handler, not middleware deny"
        )


def test_basic_auth_scheme_rejected(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/projects",
        headers={"Authorization": "Basic Zm9vOmJhcg=="},
    )
    assert resp.status_code == 401
    # The middleware itself produced this — confirm by body shape.
    assert resp.json() == {"detail": "Not authenticated"}


def test_case_variation_fails_closed(client: TestClient) -> None:
    resp = client.get("/HEALTH")
    assert resp.status_code == 401


def test_trailing_slash_on_sensitive_path_still_401(client: TestClient) -> None:
    resp = client.get("/api/v1/projects/")
    assert resp.status_code == 401
