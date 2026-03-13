# Phase 5a M3 — Webhook Receivers + Git Config API

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose webhook receiver endpoints (unauthenticated, signature-verified) and git integration config CRUD endpoints (authenticated, admin-only).

**Architecture:** Two new routers: `webhooks.py` handles incoming webhook payloads from Git platforms and queues analysis, `git_config.py` handles project-level Git integration setup. Webhook endpoints use the M2 `GitPlatformClient` for parsing/verification. Git config endpoints follow the existing CRUD pattern from `connectors.py`. Both routers are registered in `main.py`.

**Tech Stack:** FastAPI, SQLAlchemy async, existing auth dependencies.

**Depends On:** M1 (models, schemas), M2 (Git platform clients).

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── api/
│   │   ├── __init__.py              # MODIFY — register new routers
│   │   ├── webhooks.py              # CREATE — webhook receiver endpoints
│   │   └── git_config.py            # CREATE — git config CRUD
│   └── main.py                      # MODIFY — include new routers
└── tests/
    └── unit/
        ├── test_webhooks_api.py     # CREATE
        └── test_git_config_api.py   # CREATE
```

---

### Task 1: Webhook Receiver Endpoints

**Files:**
- Create: `app/api/webhooks.py`
- Test: `tests/unit/test_webhooks_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_webhooks_api.py
"""Tests for webhook receiver API endpoints."""
import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.db import RepositoryGitConfig, PrAnalysis, Project
from app.services.postgres import get_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
async def client(mock_session):
    async def _override():
        return mock_session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _make_git_config(repo_id: str = "repo-1") -> RepositoryGitConfig:
    cfg = MagicMock(spec=RepositoryGitConfig)
    cfg.repository_id = repo_id
    cfg.platform = "github"
    cfg.webhook_secret = "test-secret"
    cfg.api_token_encrypted = "encrypted"
    cfg.is_active = True
    cfg.monitored_branches = ["main", "develop"]
    return cfg


class TestWebhookEndpoints:
    @pytest.mark.asyncio
    async def test_github_webhook_returns_accepted(self, client, mock_session):
        """Valid GitHub PR webhook returns 202 accepted."""
        config = _make_git_config()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_session.execute.return_value = mock_result

        payload = {
            "action": "opened",
            "pull_request": {
                "number": 1, "title": "Test", "body": "",
                "user": {"login": "alice"},
                "head": {"ref": "feat", "sha": "abc"},
                "base": {"ref": "main"},
                "html_url": "https://github.com/org/repo/pull/1",
                "created_at": "2026-03-13T10:00:00Z",
            },
            "repository": {"html_url": "https://github.com/org/repo"},
        }
        body = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()

        with patch("app.api.webhooks.BackgroundTasks") as mock_bg:
            resp = await client.post(
                "/api/v1/webhooks/github/repo-1",
                content=body,
                headers={
                    "x-github-event": "pull_request",
                    "x-hub-signature-256": sig,
                    "content-type": "application/json",
                },
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_webhook_invalid_signature_returns_403(self, client, mock_session):
        config = _make_git_config()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_session.execute.return_value = mock_result

        resp = await client.post(
            "/api/v1/webhooks/github/repo-1",
            content=b'{"action":"opened"}',
            headers={
                "x-github-event": "pull_request",
                "x-hub-signature-256": "sha256=invalid",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_webhook_unknown_project_returns_404(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        resp = await client.post(
            "/api/v1/webhooks/github/nonexistent",
            content=b'{}',
            headers={"x-github-event": "pull_request", "x-hub-signature-256": "sha256=x"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_webhook_ignored_event_returns_200(self, client, mock_session):
        """Non-PR events (e.g., push) return 200 with status=ignored."""
        config = _make_git_config()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_session.execute.return_value = mock_result

        body = b'{"ref": "refs/heads/main"}'
        sig = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()

        resp = await client.post(
            "/api/v1/webhooks/github/repo-1",
            content=body,
            headers={
                "x-github-event": "push",
                "x-hub-signature-256": sig,
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhooks_api.py -v`
Expected: FAIL — route not found (404 for all endpoints)

- [ ] **Step 3: Implement webhook receiver**

```python
# app/api/webhooks.py
"""Webhook receiver endpoints for Git platform PR events.

These endpoints are UNAUTHENTICATED — they are called by Git platforms
and protected by webhook signature verification instead of JWT.
"""
from __future__ import annotations

import secrets
from typing import Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.git import create_platform_client
from app.models.db import PrAnalysis, RepositoryGitConfig
from app.schemas.webhooks import WebhookResponse
from app.services.postgres import get_session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

Platform = Literal["github", "gitlab", "bitbucket", "gitea"]


@router.post(
    "/{platform}/{repo_id}",
    response_model=WebhookResponse,
    status_code=202,
)
async def receive_webhook(
    platform: Platform,
    repo_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> WebhookResponse:
    """Receive and process a Git platform webhook."""
    # 1. Look up git config for this project
    result = await session.execute(
        select(RepositoryGitConfig).where(
            RepositoryGitConfig.repository_id == repo_id,
            RepositoryGitConfig.platform == platform,
            RepositoryGitConfig.is_active.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="No active git config for this repository")

    # 2. Read raw body and headers
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    # 3. Verify signature
    client = create_platform_client(platform)
    if not client.verify_webhook_signature(headers, body, config.webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    # 4. Parse webhook
    event = client.parse_webhook(headers, body)
    if event is None:
        return JSONResponse(
            status_code=200,
            content=WebhookResponse(status="ignored", message="Not a relevant PR event").model_dump(),
        )

    # 5. Check if target branch is monitored
    monitored = config.monitored_branches or ["main", "master", "develop"]
    if event.target_branch not in monitored:
        return JSONResponse(
            status_code=200,
            content=WebhookResponse(
                status="ignored",
                message=f"Target branch '{event.target_branch}' not monitored",
            ).model_dump(),
        )

    # 6. Create pr_analyses record
    pr_record = PrAnalysis(
        repository_id=repo_id,
        platform=platform,
        pr_number=event.pr_number,
        pr_title=event.pr_title,
        pr_description=event.pr_description,
        pr_author=event.author,
        source_branch=event.source_branch,
        target_branch=event.target_branch,
        commit_sha=event.commit_sha,
        pr_url=event.raw_payload.get("pull_request", {}).get("html_url")
        or event.raw_payload.get("object_attributes", {}).get("url"),
        status="pending",
    )
    session.add(pr_record)
    await session.commit()
    await session.refresh(pr_record)

    logger.info(
        "webhook_received",
        platform=platform,
        repo_id=repo_id,
        pr_number=event.pr_number,
        analysis_id=pr_record.id,
    )

    # 7. Queue background analysis (M8 will implement the actual analyzer)
    # background_tasks.add_task(run_pr_analysis, pr_record.id)

    return WebhookResponse(status="accepted", pr_analysis_id=pr_record.id)
```

- [ ] **Step 4: Register the router**

Add to `app/api/__init__.py`:
```python
from app.api.webhooks import router as webhooks_router
```
Add `"webhooks_router"` to the `__all__` list.

Add to `app/main.py` in the imports and router registration:
```python
from app.api import webhooks_router
# ...
application.include_router(webhooks_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhooks_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend
git add app/api/webhooks.py app/api/__init__.py app/main.py tests/unit/test_webhooks_api.py
git commit -m "feat(phase5a): add webhook receiver endpoints with signature verification"
```

---

### Task 2: Git Config CRUD Endpoints

**Files:**
- Create: `app/api/git_config.py`
- Test: `tests/unit/test_git_config_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_git_config_api.py
"""Tests for git config CRUD API endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from app.config import Settings, get_settings
from app.main import app
from app.models.db import RepositoryGitConfig, User
from app.api.dependencies import get_current_user
from app.services.postgres import get_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def admin_user():
    return User(
        id="admin-1",
        username="admin",
        email="admin@test.com",
        password_hash="x",
        role="admin",
        is_active=True,
    )


@pytest.fixture
async def client(mock_session, admin_user):
    async def _override_session():
        return mock_session

    async def _override_user():
        return admin_user

    def _override_settings():
        return Settings(auth_disabled=False, secret_key="test-key")

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_settings] = _override_settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


class TestCreateGitConfig:
    @pytest.mark.asyncio
    async def test_create_config(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No existing config
        mock_session.execute.return_value = mock_result

        resp = await client.post(
            "/api/v1/repositories/repo-1/git-config",
            json={
                "platform": "github",
                "repo_url": "https://github.com/org/repo",
                "api_token": "ghp_test123",
                "monitored_branches": ["main"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["platform"] == "github"
        assert "api_token" not in data
        assert data["webhook_url"] is not None
        assert data["webhook_secret"] is not None

    @pytest.mark.asyncio
    async def test_create_rejects_invalid_platform(self, client, mock_session):
        resp = await client.post(
            "/api/v1/repositories/repo-1/git-config",
            json={
                "platform": "svn",
                "repo_url": "https://example.com",
                "api_token": "token",
            },
        )
        assert resp.status_code == 422


class TestGetGitConfig:
    @pytest.mark.asyncio
    async def test_get_config(self, client, mock_session):
        config = MagicMock(spec=RepositoryGitConfig)
        config.id = "cfg-1"
        config.repository_id = "repo-1"
        config.platform = "github"
        config.repo_url = "https://github.com/org/repo"
        config.monitored_branches = ["main"]
        config.is_active = True
        config.webhook_secret = "secret"
        config.created_at = "2026-03-13T00:00:00Z"
        config.updated_at = "2026-03-13T00:00:00Z"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_session.execute.return_value = mock_result

        resp = await client.get("/api/v1/repositories/repo-1/git-config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform"] == "github"

    @pytest.mark.asyncio
    async def test_get_config_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        resp = await client.get("/api/v1/repositories/repo-1/git-config")
        assert resp.status_code == 404


class TestDeleteGitConfig:
    @pytest.mark.asyncio
    async def test_delete_config(self, client, mock_session):
        config = MagicMock(spec=RepositoryGitConfig)
        config.id = "cfg-1"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_session.execute.return_value = mock_result

        resp = await client.delete("/api/v1/repositories/repo-1/git-config")
        assert resp.status_code == 204
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_git_config_api.py -v`
Expected: FAIL

- [ ] **Step 3: Implement git config CRUD**

```python
# app/api/git_config.py
"""Git integration configuration CRUD endpoints (admin only)."""
from __future__ import annotations

import secrets

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.config import Settings, get_settings
from app.models.db import RepositoryGitConfig, User
from app.schemas.git_config import (
    GitConfigCreate,
    GitConfigResponse,
    GitConfigUpdate,
    WebhookUrlResponse,
)
from app.services.crypto import encrypt_token
from app.services.postgres import get_session

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/repositories/{repo_id}/git-config",
    tags=["git-config"],
)


async def _get_config_or_404(
    repo_id: str, session: AsyncSession
) -> RepositoryGitConfig:
    result = await session.execute(
        select(RepositoryGitConfig).where(RepositoryGitConfig.repository_id == repo_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Git config not found")
    return config


@router.post("", status_code=201)
async def create_git_config(
    repo_id: str,
    body: GitConfigCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _user: User = Depends(require_admin),
) -> dict:
    """Configure Git integration for a repository."""
    # Check for existing config
    result = await session.execute(
        select(RepositoryGitConfig).where(RepositoryGitConfig.repository_id == repo_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Git config already exists for this repository")

    webhook_secret = secrets.token_urlsafe(32)
    config = RepositoryGitConfig(
        repository_id=repo_id,
        platform=body.platform,
        repo_url=body.repo_url,
        api_token_encrypted=encrypt_token(body.api_token, settings.secret_key),
        webhook_secret=webhook_secret,
        monitored_branches=body.monitored_branches,
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)

    return {
        "id": config.id,
        "repository_id": config.repository_id,
        "platform": config.platform,
        "repo_url": config.repo_url,
        "monitored_branches": config.monitored_branches,
        "is_active": config.is_active,
        "webhook_url": f"/api/v1/webhooks/{config.platform}/{repo_id}",
        "webhook_secret": webhook_secret,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }


@router.get("", response_model=GitConfigResponse)
async def get_git_config(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_admin),
) -> GitConfigResponse:
    """Get current git config for a repository (token masked)."""
    config = await _get_config_or_404(repo_id, session)
    return GitConfigResponse.model_validate(config)


@router.put("", response_model=GitConfigResponse)
async def update_git_config(
    repo_id: str,
    body: GitConfigUpdate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _user: User = Depends(require_admin),
) -> GitConfigResponse:
    """Update git config for a repository."""
    config = await _get_config_or_404(repo_id, session)

    if body.repo_url is not None:
        config.repo_url = body.repo_url
    if body.api_token is not None:
        config.api_token_encrypted = encrypt_token(body.api_token, settings.secret_key)
    if body.monitored_branches is not None:
        config.monitored_branches = body.monitored_branches
    if body.is_active is not None:
        config.is_active = body.is_active

    await session.commit()
    await session.refresh(config)
    return GitConfigResponse.model_validate(config)


@router.delete("", status_code=204)
async def delete_git_config(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_admin),
) -> Response:
    """Remove Git integration for a repository."""
    config = await _get_config_or_404(repo_id, session)
    await session.delete(config)
    await session.commit()
    return Response(status_code=204)


@router.get("/webhook-url", response_model=WebhookUrlResponse)
async def get_webhook_url(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_admin),
) -> WebhookUrlResponse:
    """Get the webhook URL and secret for copy-paste setup."""
    config = await _get_config_or_404(repo_id, session)
    return WebhookUrlResponse(
        webhook_url=f"/api/v1/webhooks/{config.platform}/{repo_id}",
        webhook_secret=config.webhook_secret,
    )


@router.post("/test")
async def test_git_connectivity(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _user: User = Depends(require_admin),
) -> dict:
    """Test that the stored API token can reach the Git platform."""
    config = await _get_config_or_404(repo_id, session)

    from app.services.crypto import decrypt_token
    from app.services.git_providers import create_provider

    token = decrypt_token(config.api_token_encrypted, settings.secret_key)
    provider = create_provider(config.platform, config.repo_url, token)

    try:
        user = await provider.validate()
        return {"status": "ok", "username": user.username}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
```

- [ ] **Step 4: Register the router**

Add to `app/api/__init__.py`:
```python
from app.api.git_config import router as git_config_router
```
Add `"git_config_router"` to the `__all__` list.

Add to `app/main.py`:
```python
from app.api import git_config_router
# ...
application.include_router(git_config_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_git_config_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend
git add app/api/git_config.py app/api/__init__.py app/main.py tests/unit/test_git_config_api.py
git commit -m "feat(phase5a): add git config CRUD + webhook URL endpoints"
```

---

## Success Criteria

- [ ] `POST /api/v1/webhooks/{platform}/{repo_id}` receives webhooks, verifies signature, creates `PrAnalysis` record
- [ ] Webhook returns 403 on invalid signature, 404 on missing config, 200 on ignored events, 202 on accepted
- [ ] Git config CRUD works: create (201), get (200), update (200), delete (204)
- [ ] `GET /webhook-url` returns the URL and secret for copy-paste
- [ ] `POST /test` validates API token connectivity
- [ ] All tests pass: `uv run pytest tests/unit/test_webhooks_api.py tests/unit/test_git_config_api.py -v`
