# Phase 4A M7b: Git Connectors — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend model, API, and frontend UI for connecting to GitHub, GitLab, Gitea, and Bitbucket via Personal Access Tokens — enabling users to browse remote repositories and branches through the CodeLens UI.

**Architecture:** New `GitConnector` SQLAlchemy model with Fernet-encrypted PAT storage. Provider adapter pattern (ABC → 4 implementations) for API abstraction. New FastAPI router (`/api/v1/connectors`) with CRUD + test + repo-browsing endpoints. Frontend: connector list page, add-connector form with "Test & Save" flow.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, `cryptography` (Fernet), `httpx` (async HTTP client for provider APIs), pytest + pytest-asyncio

**Dependencies:** Phase 4A M7a (nav shell — `/connectors` route exists as placeholder)

**Spec Reference:** `cast-clone-backend/docs/12-PHASE-4A-FRONTEND-DESIGN-GITCONNECTOR-REPO-ONBOARDING.MD` — Sections 1.2 (GitConnector model), 3 (Git Connectors)

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── api/
│   │   ├── __init__.py                        # MODIFY — export connectors_router
│   │   └── connectors.py                      # CREATE — CRUD + test + repo browsing endpoints
│   ├── models/
│   │   └── db.py                              # MODIFY — add GitConnector model
│   ├── schemas/
│   │   └── connectors.py                      # CREATE — Pydantic request/response schemas
│   ├── services/
│   │   ├── crypto.py                          # CREATE — Fernet encrypt/decrypt helpers
│   │   └── git_providers/
│   │       ├── __init__.py                    # CREATE — factory function
│   │       ├── base.py                        # CREATE — GitProvider ABC + data classes
│   │       ├── github.py                      # CREATE — GitHub provider implementation
│   │       ├── gitlab.py                      # CREATE — GitLab provider implementation
│   │       ├── gitea.py                       # CREATE — Gitea provider implementation
│   │       └── bitbucket.py                   # CREATE — Bitbucket provider implementation
│   ├── config.py                              # MODIFY — add SECRET_KEY setting
│   └── main.py                                # MODIFY — register connectors_router
└── tests/
    └── unit/
        ├── test_crypto.py                     # CREATE — encryption/decryption tests
        ├── test_git_providers.py              # CREATE — provider adapter tests
        └── test_connectors_api.py             # CREATE — API endpoint tests

cast-clone-frontend/
├── lib/
│   ├── types.ts                               # MODIFY — add connector types
│   └── api.ts                                 # MODIFY — add connector API functions
├── components/
│   └── connectors/
│       ├── ConnectorCard.tsx                   # CREATE — connector card with status
│       └── AddConnectorForm.tsx               # CREATE — multi-step add form
└── app/
    ├── connectors/
    │   ├── page.tsx                            # MODIFY — connector list with cards
    │   └── new/
    │       └── page.tsx                        # CREATE — add connector page
```

---

## Task 1: Add SECRET_KEY to Config

**Files:**
- Modify: `cast-clone-backend/app/config.py`

- [ ] **Step 1: Add secret_key and repo_storage_path to Settings**

Add these fields to the `Settings` class in `cast-clone-backend/app/config.py`:

```python
    # Security
    secret_key: str = "change-me-in-production"

    # Repository storage
    repo_storage_path: str = "/data/repos"
    git_clone_timeout: int = 600
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend
git add app/config.py
git commit -m "feat(connectors): add SECRET_KEY and repo storage config"
```

---

## Task 2: Create Crypto Service

**Files:**
- Create: `cast-clone-backend/app/services/crypto.py`
- Create: `cast-clone-backend/tests/unit/test_crypto.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_crypto.py
"""Tests for Fernet token encryption/decryption."""

from __future__ import annotations

import pytest

from app.services.crypto import decrypt_token, encrypt_token


class TestCrypto:
    def test_encrypt_then_decrypt_roundtrip(self):
        secret = "my-secret-key"
        plaintext = "ghp_abc123def456"
        encrypted = encrypt_token(plaintext, secret)
        assert encrypted != plaintext
        assert decrypt_token(encrypted, secret) == plaintext

    def test_different_secrets_produce_different_ciphertext(self):
        plaintext = "ghp_abc123"
        enc1 = encrypt_token(plaintext, "secret-a")
        enc2 = encrypt_token(plaintext, "secret-b")
        assert enc1 != enc2

    def test_decrypt_with_wrong_key_fails(self):
        encrypted = encrypt_token("my-token", "correct-key")
        with pytest.raises(Exception):
            decrypt_token(encrypted, "wrong-key")

    def test_empty_token_roundtrip(self):
        encrypted = encrypt_token("", "key")
        assert decrypt_token(encrypted, "key") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.crypto'`

- [ ] **Step 3: Install cryptography dependency**

Run: `cd cast-clone-backend && uv add cryptography`

- [ ] **Step 4: Implement crypto service**

```python
# app/services/crypto.py
"""Fernet-based token encryption for Git connector PATs."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from an arbitrary secret string."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_token(plaintext: str, secret_key: str) -> str:
    """Encrypt a plaintext token using Fernet with a derived key."""
    f = Fernet(_derive_key(secret_key))
    return f.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str, secret_key: str) -> str:
    """Decrypt a Fernet-encrypted token."""
    f = Fernet(_derive_key(secret_key))
    return f.decrypt(ciphertext.encode()).decode()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_crypto.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend
git add app/services/crypto.py tests/unit/test_crypto.py pyproject.toml uv.lock
git commit -m "feat(connectors): add Fernet crypto service for PAT encryption"
```

---

## Task 3: Add GitConnector Model

**Files:**
- Modify: `cast-clone-backend/app/models/db.py`

- [ ] **Step 1: Add GitConnector class to db.py**

Add the following class to `cast-clone-backend/app/models/db.py`, after the `Base` class and before `Project`:

```python
class GitConnector(Base):
    __tablename__ = "git_connectors"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # github | gitlab | gitea | bitbucket
    base_url: Mapped[str] = mapped_column(
        String(1024), nullable=False
    )  # https://github.com, https://gitlab.company.com, etc.
    auth_method: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pat"
    )  # pat | oauth (v2)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="connected"
    )  # connected | expired | revoked | error
    remote_username: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )  # nullable now, FK to users.id in Phase 4
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 2: Verify the model loads**

Run: `cd cast-clone-backend && uv run python -c "from app.models.db import GitConnector; print(GitConnector.__tablename__)"`
Expected: `git_connectors`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/models/db.py
git commit -m "feat(connectors): add GitConnector SQLAlchemy model"
```

---

## Task 4: Create Git Provider Base + Data Classes

**Files:**
- Create: `cast-clone-backend/app/services/git_providers/__init__.py`
- Create: `cast-clone-backend/app/services/git_providers/base.py`

- [ ] **Step 1: Create the package init with factory function**

```python
# app/services/git_providers/__init__.py
"""Git provider adapters for GitHub, GitLab, Gitea, Bitbucket."""

from __future__ import annotations

from app.services.git_providers.base import GitProvider, GitRepo, GitUser


def create_provider(provider: str, base_url: str, token: str) -> GitProvider:
    """Factory: create the correct provider adapter."""
    if provider == "github":
        from app.services.git_providers.github import GitHubProvider

        return GitHubProvider(base_url, token)
    elif provider == "gitlab":
        from app.services.git_providers.gitlab import GitLabProvider

        return GitLabProvider(base_url, token)
    elif provider == "gitea":
        from app.services.git_providers.gitea import GiteaProvider

        return GiteaProvider(base_url, token)
    elif provider == "bitbucket":
        from app.services.git_providers.bitbucket import BitbucketProvider

        return BitbucketProvider(base_url, token)
    else:
        raise ValueError(f"Unknown provider: {provider}")


__all__ = ["GitProvider", "GitRepo", "GitUser", "create_provider"]
```

- [ ] **Step 2: Create the base ABC and data classes**

```python
# app/services/git_providers/base.py
"""Abstract base class for Git provider adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GitUser:
    """Authenticated user info from the provider."""

    username: str
    display_name: str | None = None
    avatar_url: str | None = None


@dataclass
class GitRepo:
    """Repository info from the provider."""

    full_name: str  # "owner/repo"
    clone_url: str  # HTTPS clone URL (no token embedded)
    default_branch: str
    description: str | None = None
    language: str | None = None
    is_private: bool = False


class GitProvider(ABC):
    """Abstract interface for Git hosting provider APIs."""

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    @abstractmethod
    async def validate(self) -> GitUser:
        """Validate the token and return the authenticated user.

        Raises httpx.HTTPStatusError on auth failure.
        """
        ...

    @abstractmethod
    async def list_repos(
        self,
        page: int = 1,
        per_page: int = 30,
        search: str | None = None,
    ) -> tuple[list[GitRepo], bool]:
        """List repos. Returns (repos, has_more_pages)."""
        ...

    @abstractmethod
    async def get_repo(self, full_name: str) -> GitRepo:
        """Get a single repo by full_name (owner/repo)."""
        ...

    @abstractmethod
    async def list_branches(self, full_name: str) -> list[str]:
        """List branch names for a repo."""
        ...
```

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/services/git_providers/
git commit -m "feat(connectors): add GitProvider ABC and data classes"
```

---

## Task 5: Implement GitHub Provider

**Files:**
- Create: `cast-clone-backend/app/services/git_providers/github.py`
- Create: `cast-clone-backend/tests/unit/test_git_providers.py`

- [ ] **Step 1: Install httpx dependency**

Run: `cd cast-clone-backend && uv add httpx`

- [ ] **Step 2: Write failing tests for GitHub provider**

```python
# tests/unit/test_git_providers.py
"""Tests for Git provider adapters.

Uses httpx mock to avoid real API calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.git_providers import create_provider
from app.services.git_providers.base import GitProvider, GitRepo, GitUser


class TestCreateProvider:
    def test_creates_github(self):
        p = create_provider("github", "https://github.com", "token")
        assert isinstance(p, GitProvider)

    def test_creates_gitlab(self):
        p = create_provider("gitlab", "https://gitlab.com", "token")
        assert isinstance(p, GitProvider)

    def test_creates_gitea(self):
        p = create_provider("gitea", "https://gitea.example.com", "token")
        assert isinstance(p, GitProvider)

    def test_creates_bitbucket(self):
        p = create_provider("bitbucket", "https://bitbucket.org", "token")
        assert isinstance(p, GitProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("azure", "https://dev.azure.com", "token")


class TestGitHubProvider:
    @pytest.fixture
    def provider(self):
        return create_provider("github", "https://github.com", "ghp_test123")

    @pytest.mark.asyncio
    async def test_validate_success(self, provider):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "login": "testuser",
            "name": "Test User",
            "avatar_url": "https://avatars.githubusercontent.com/u/1",
        }
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            user = await provider.validate()
            assert user.username == "testuser"
            assert user.display_name == "Test User"

    @pytest.mark.asyncio
    async def test_list_repos(self, provider):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "full_name": "testuser/repo1",
                "clone_url": "https://github.com/testuser/repo1.git",
                "default_branch": "main",
                "description": "Test repo",
                "language": "Java",
                "private": False,
            },
        ]
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            repos, has_more = await provider.list_repos(page=1, per_page=30)
            assert len(repos) == 1
            assert repos[0].full_name == "testuser/repo1"
            assert repos[0].default_branch == "main"

    @pytest.mark.asyncio
    async def test_list_branches(self, provider):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"name": "main"},
            {"name": "develop"},
            {"name": "feature/auth"},
        ]
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            branches = await provider.list_branches("testuser/repo1")
            assert branches == ["main", "develop", "feature/auth"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_git_providers.py -v`
Expected: FAIL — `ModuleNotFoundError` for github module

- [ ] **Step 4: Implement GitHub provider**

```python
# app/services/git_providers/github.py
"""GitHub provider adapter."""

from __future__ import annotations

import httpx

from app.services.git_providers.base import GitProvider, GitRepo, GitUser


class GitHubProvider(GitProvider):
    """GitHub (cloud + Enterprise) provider."""

    @property
    def _api_base(self) -> str:
        """Derive API base URL from base_url."""
        if self.base_url == "https://github.com":
            return "https://api.github.com"
        # GitHub Enterprise: https://github.company.com → /api/v3
        return f"{self.base_url}/api/v3"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def validate(self) -> GitUser:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/user",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return GitUser(
                username=data["login"],
                display_name=data.get("name"),
                avatar_url=data.get("avatar_url"),
            )

    async def list_repos(
        self,
        page: int = 1,
        per_page: int = 30,
        search: str | None = None,
    ) -> tuple[list[GitRepo], bool]:
        async with httpx.AsyncClient() as client:
            params: dict[str, str | int] = {
                "page": page,
                "per_page": per_page,
                "sort": "updated",
                "direction": "desc",
            }
            if search:
                params["q"] = f"{search} in:name fork:true"
                resp = await client.get(
                    f"{self._api_base}/search/repositories",
                    headers=self._headers,
                    params=params,
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])
            else:
                resp = await client.get(
                    f"{self._api_base}/user/repos",
                    headers=self._headers,
                    params=params,
                    timeout=15,
                )
                resp.raise_for_status()
                items = resp.json()

            repos = [
                GitRepo(
                    full_name=r["full_name"],
                    clone_url=r["clone_url"],
                    default_branch=r.get("default_branch", "main"),
                    description=r.get("description"),
                    language=r.get("language"),
                    is_private=r.get("private", False),
                )
                for r in items
            ]
            has_more = len(items) == per_page
            return repos, has_more

    async def get_repo(self, full_name: str) -> GitRepo:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/repos/{full_name}",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            r = resp.json()
            return GitRepo(
                full_name=r["full_name"],
                clone_url=r["clone_url"],
                default_branch=r.get("default_branch", "main"),
                description=r.get("description"),
                language=r.get("language"),
                is_private=r.get("private", False),
            )

    async def list_branches(self, full_name: str) -> list[str]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/repos/{full_name}/branches",
                headers=self._headers,
                params={"per_page": 100},
                timeout=10,
            )
            resp.raise_for_status()
            return [b["name"] for b in resp.json()]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_git_providers.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend
git add app/services/git_providers/github.py tests/unit/test_git_providers.py pyproject.toml uv.lock
git commit -m "feat(connectors): implement GitHub provider adapter with tests"
```

---

## Task 6: Implement GitLab, Gitea, Bitbucket Providers

**Files:**
- Create: `cast-clone-backend/app/services/git_providers/gitlab.py`
- Create: `cast-clone-backend/app/services/git_providers/gitea.py`
- Create: `cast-clone-backend/app/services/git_providers/bitbucket.py`

- [ ] **Step 1: Implement GitLab provider**

```python
# app/services/git_providers/gitlab.py
"""GitLab provider adapter."""

from __future__ import annotations

from urllib.parse import quote_plus

import httpx

from app.services.git_providers.base import GitProvider, GitRepo, GitUser


class GitLabProvider(GitProvider):
    """GitLab (cloud + self-hosted) provider."""

    @property
    def _api_base(self) -> str:
        return f"{self.base_url}/api/v4"

    @property
    def _headers(self) -> dict[str, str]:
        return {"PRIVATE-TOKEN": self.token}

    async def validate(self) -> GitUser:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/user",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return GitUser(
                username=data["username"],
                display_name=data.get("name"),
                avatar_url=data.get("avatar_url"),
            )

    async def list_repos(
        self,
        page: int = 1,
        per_page: int = 30,
        search: str | None = None,
    ) -> tuple[list[GitRepo], bool]:
        async with httpx.AsyncClient() as client:
            params: dict[str, str | int] = {
                "page": page,
                "per_page": per_page,
                "order_by": "updated_at",
                "sort": "desc",
                "membership": "true",
            }
            if search:
                params["search"] = search
            resp = await client.get(
                f"{self._api_base}/projects",
                headers=self._headers,
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json()
            repos = [
                GitRepo(
                    full_name=r["path_with_namespace"],
                    clone_url=r["http_url_to_repo"],
                    default_branch=r.get("default_branch", "main"),
                    description=r.get("description"),
                    language=None,  # GitLab doesn't return language in list
                    is_private=r.get("visibility") == "private",
                )
                for r in items
            ]
            has_more = len(items) == per_page
            return repos, has_more

    async def get_repo(self, full_name: str) -> GitRepo:
        async with httpx.AsyncClient() as client:
            encoded = quote_plus(full_name)
            resp = await client.get(
                f"{self._api_base}/projects/{encoded}",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            r = resp.json()
            return GitRepo(
                full_name=r["path_with_namespace"],
                clone_url=r["http_url_to_repo"],
                default_branch=r.get("default_branch", "main"),
                description=r.get("description"),
                language=None,
                is_private=r.get("visibility") == "private",
            )

    async def list_branches(self, full_name: str) -> list[str]:
        async with httpx.AsyncClient() as client:
            encoded = quote_plus(full_name)
            resp = await client.get(
                f"{self._api_base}/projects/{encoded}/repository/branches",
                headers=self._headers,
                params={"per_page": 100},
                timeout=10,
            )
            resp.raise_for_status()
            return [b["name"] for b in resp.json()]
```

- [ ] **Step 2: Implement Gitea provider**

```python
# app/services/git_providers/gitea.py
"""Gitea provider adapter."""

from __future__ import annotations

import httpx

from app.services.git_providers.base import GitProvider, GitRepo, GitUser


class GiteaProvider(GitProvider):
    """Gitea (self-hosted) provider."""

    @property
    def _api_base(self) -> str:
        return f"{self.base_url}/api/v1"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"token {self.token}"}

    async def validate(self) -> GitUser:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/user",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return GitUser(
                username=data["login"],
                display_name=data.get("full_name"),
                avatar_url=data.get("avatar_url"),
            )

    async def list_repos(
        self,
        page: int = 1,
        per_page: int = 30,
        search: str | None = None,
    ) -> tuple[list[GitRepo], bool]:
        async with httpx.AsyncClient() as client:
            params: dict[str, str | int] = {
                "page": page,
                "limit": per_page,
                "sort": "updated",
                "order": "desc",
            }
            if search:
                params["q"] = search
                url = f"{self._api_base}/repos/search"
            else:
                url = f"{self._api_base}/user/repos"
            resp = await client.get(
                url, headers=self._headers, params=params, timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            repos = [
                GitRepo(
                    full_name=r["full_name"],
                    clone_url=r["clone_url"],
                    default_branch=r.get("default_branch", "main"),
                    description=r.get("description"),
                    language=r.get("language"),
                    is_private=r.get("private", False),
                )
                for r in items
            ]
            has_more = len(items) == per_page
            return repos, has_more

    async def get_repo(self, full_name: str) -> GitRepo:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/repos/{full_name}",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            r = resp.json()
            return GitRepo(
                full_name=r["full_name"],
                clone_url=r["clone_url"],
                default_branch=r.get("default_branch", "main"),
                description=r.get("description"),
                language=r.get("language"),
                is_private=r.get("private", False),
            )

    async def list_branches(self, full_name: str) -> list[str]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/repos/{full_name}/branches",
                headers=self._headers,
                params={"limit": 100},
                timeout=10,
            )
            resp.raise_for_status()
            return [b["name"] for b in resp.json()]
```

- [ ] **Step 3: Implement Bitbucket provider**

```python
# app/services/git_providers/bitbucket.py
"""Bitbucket provider adapter."""

from __future__ import annotations

import httpx

from app.services.git_providers.base import GitProvider, GitRepo, GitUser


class BitbucketProvider(GitProvider):
    """Bitbucket Cloud provider."""

    @property
    def _api_base(self) -> str:
        if self.base_url == "https://bitbucket.org":
            return "https://api.bitbucket.org/2.0"
        return f"{self.base_url}/2.0"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def validate(self) -> GitUser:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/user",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return GitUser(
                username=data.get("username", data.get("nickname", "")),
                display_name=data.get("display_name"),
                avatar_url=data.get("links", {})
                .get("avatar", {})
                .get("href"),
            )

    async def list_repos(
        self,
        page: int = 1,
        per_page: int = 30,
        search: str | None = None,
    ) -> tuple[list[GitRepo], bool]:
        async with httpx.AsyncClient() as client:
            params: dict[str, str | int] = {
                "page": page,
                "pagelen": per_page,
                "sort": "-updated_on",
                "role": "member",
            }
            if search:
                params["q"] = f'name ~ "{search}"'
            resp = await client.get(
                f"{self._api_base}/repositories",
                headers=self._headers,
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("values", [])
            repos = [
                GitRepo(
                    full_name=r["full_name"],
                    clone_url=next(
                        (
                            link["href"]
                            for link in r.get("links", {}).get("clone", [])
                            if link["name"] == "https"
                        ),
                        "",
                    ),
                    default_branch=r.get("mainbranch", {}).get("name", "main"),
                    description=r.get("description"),
                    language=r.get("language"),
                    is_private=r.get("is_private", False),
                )
                for r in items
            ]
            has_more = data.get("next") is not None
            return repos, has_more

    async def get_repo(self, full_name: str) -> GitRepo:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/repositories/{full_name}",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            r = resp.json()
            return GitRepo(
                full_name=r["full_name"],
                clone_url=next(
                    (
                        link["href"]
                        for link in r.get("links", {}).get("clone", [])
                        if link["name"] == "https"
                    ),
                    "",
                ),
                default_branch=r.get("mainbranch", {}).get("name", "main"),
                description=r.get("description"),
                language=r.get("language"),
                is_private=r.get("is_private", False),
            )

    async def list_branches(self, full_name: str) -> list[str]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_base}/repositories/{full_name}/refs/branches",
                headers=self._headers,
                params={"pagelen": 100},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return [b["name"] for b in data.get("values", [])]
```

- [ ] **Step 4: Run all provider tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_git_providers.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/services/git_providers/gitlab.py app/services/git_providers/gitea.py app/services/git_providers/bitbucket.py
git commit -m "feat(connectors): implement GitLab, Gitea, Bitbucket provider adapters"
```

---

## Task 7: Create Pydantic Schemas for Connectors

**Files:**
- Create: `cast-clone-backend/app/schemas/connectors.py`

- [ ] **Step 1: Create connector schemas**

```python
# app/schemas/connectors.py
"""Pydantic v2 schemas for Git connector API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Request schemas ──────────────────────────────────────────


class ConnectorCreate(BaseModel):
    """Request body for creating a new Git connector."""

    name: str = Field(min_length=1, max_length=255)
    provider: Literal["github", "gitlab", "gitea", "bitbucket"]
    base_url: str = Field(min_length=1, max_length=1024)
    token: str = Field(min_length=1)


class ConnectorUpdate(BaseModel):
    """Request body for updating a connector (name and/or token)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    token: str | None = Field(None, min_length=1)


# ── Response schemas ─────────────────────────────────────────


class ConnectorResponse(BaseModel):
    """Response for a single connector. Token is NEVER returned."""

    model_config = {"from_attributes": True}

    id: str
    name: str
    provider: str
    base_url: str
    auth_method: str
    status: str
    remote_username: str | None = None
    created_at: datetime
    updated_at: datetime


class ConnectorListResponse(BaseModel):
    """Response for listing connectors."""

    connectors: list[ConnectorResponse]
    total: int


class ConnectorTestResponse(BaseModel):
    """Response for testing a connector."""

    status: str  # connected | error
    remote_username: str | None = None
    error: str | None = None


# ── Repo browsing schemas ────────────────────────────────────


class RemoteRepoResponse(BaseModel):
    """A repository as seen from the Git provider (not yet cloned)."""

    full_name: str
    clone_url: str
    default_branch: str
    description: str | None = None
    language: str | None = None
    is_private: bool = False


class RemoteRepoListResponse(BaseModel):
    """Paginated list of remote repos from a provider."""

    repos: list[RemoteRepoResponse]
    has_more: bool
    page: int
    per_page: int


class BranchListResponse(BaseModel):
    """List of branches for a remote repo."""

    branches: list[str]
    default_branch: str
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend
git add app/schemas/connectors.py
git commit -m "feat(connectors): add Pydantic schemas for connector API"
```

---

## Task 8: Write Failing Tests for Connector API

**Files:**
- Create: `cast-clone-backend/tests/unit/test_connectors_api.py`

- [ ] **Step 1: Write the test file**

```python
# tests/unit/test_connectors_api.py
"""Tests for Git connector API endpoints.

Uses FastAPI TestClient with mocked database and provider.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_session():
    """Mock the SQLAlchemy async session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def mock_dependencies(mock_session):
    """Mock database session and crypto for all tests."""
    with (
        patch(
            "app.api.connectors.get_session",
            return_value=mock_session,
        ),
        patch("app.api.connectors.encrypt_token", return_value="encrypted_xxx"),
        patch("app.api.connectors.decrypt_token", return_value="ghp_realtoken"),
    ):
        yield


class TestCreateConnector:
    def test_create_connector_success(self, client, mock_session):
        mock_provider = AsyncMock()
        mock_provider.validate = AsyncMock(
            return_value=MagicMock(username="testuser", display_name="Test")
        )

        with patch(
            "app.api.connectors.create_provider", return_value=mock_provider
        ):
            mock_session.add = MagicMock()
            # Make refresh populate the object
            async def fake_refresh(obj):
                obj.id = "conn-123"
                obj.created_at = datetime.now(timezone.utc)
                obj.updated_at = datetime.now(timezone.utc)

            mock_session.refresh = AsyncMock(side_effect=fake_refresh)

            resp = client.post(
                "/api/v1/connectors",
                json={
                    "name": "My GitHub",
                    "provider": "github",
                    "base_url": "https://github.com",
                    "token": "ghp_test123",
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My GitHub"
        assert data["provider"] == "github"
        assert data["remote_username"] == "testuser"
        # Token must NOT be in response
        assert "token" not in data
        assert "encrypted_token" not in data

    def test_create_connector_invalid_provider(self, client):
        resp = client.post(
            "/api/v1/connectors",
            json={
                "name": "Bad",
                "provider": "azure",
                "base_url": "https://dev.azure.com",
                "token": "xxx",
            },
        )
        assert resp.status_code == 422


class TestListConnectors:
    def test_list_connectors(self, client, mock_session):
        mock_connector = MagicMock()
        mock_connector.id = "conn-1"
        mock_connector.name = "My GitHub"
        mock_connector.provider = "github"
        mock_connector.base_url = "https://github.com"
        mock_connector.auth_method = "pat"
        mock_connector.status = "connected"
        mock_connector.remote_username = "testuser"
        mock_connector.created_at = datetime.now(timezone.utc)
        mock_connector.updated_at = datetime.now(timezone.utc)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_connector]
        mock_session.execute = AsyncMock(return_value=mock_result)

        resp = client.get("/api/v1/connectors")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["connectors"][0]["name"] == "My GitHub"


class TestDeleteConnector:
    def test_delete_connector(self, client, mock_session):
        mock_connector = MagicMock()
        mock_connector.id = "conn-1"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_connector
        mock_session.execute = AsyncMock(return_value=mock_result)

        resp = client.delete("/api/v1/connectors/conn-1")
        assert resp.status_code == 204

    def test_delete_connector_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        resp = client.delete("/api/v1/connectors/nonexistent")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_connectors_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.connectors'`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add tests/unit/test_connectors_api.py
git commit -m "test: add failing tests for connector API endpoints"
```

---

## Task 9: Implement Connector API Router

**Files:**
- Create: `cast-clone-backend/app/api/connectors.py`

- [ ] **Step 1: Write the connector router**

```python
# app/api/connectors.py
"""Git connector CRUD + repo browsing API endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.db import GitConnector
from app.schemas.connectors import (
    BranchListResponse,
    ConnectorCreate,
    ConnectorListResponse,
    ConnectorResponse,
    ConnectorTestResponse,
    ConnectorUpdate,
    RemoteRepoListResponse,
    RemoteRepoResponse,
)
from app.services.crypto import decrypt_token, encrypt_token
from app.services.git_providers import create_provider
from app.services.postgres import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


def _get_secret_key() -> str:
    return Settings().secret_key


# ── CRUD ─────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_connector(
    body: ConnectorCreate,
    session: AsyncSession = Depends(get_session),
) -> ConnectorResponse:
    """Create a new Git connector. Validates the token first."""
    secret_key = _get_secret_key()

    # Validate token with the provider
    provider = create_provider(body.provider, body.base_url, body.token)
    try:
        user = await provider.validate()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Token validation failed: {exc}",
        ) from exc

    connector = GitConnector(
        name=body.name,
        provider=body.provider,
        base_url=body.base_url,
        encrypted_token=encrypt_token(body.token, secret_key),
        status="connected",
        remote_username=user.username,
    )
    session.add(connector)
    await session.commit()
    await session.refresh(connector)

    return ConnectorResponse.model_validate(connector)


@router.get("", response_model=ConnectorListResponse)
async def list_connectors(
    session: AsyncSession = Depends(get_session),
) -> ConnectorListResponse:
    """List all Git connectors."""
    result = await session.execute(select(GitConnector).order_by(GitConnector.created_at.desc()))
    connectors = result.scalars().all()
    return ConnectorListResponse(
        connectors=[ConnectorResponse.model_validate(c) for c in connectors],
        total=len(connectors),
    )


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(
    connector_id: str,
    session: AsyncSession = Depends(get_session),
) -> ConnectorResponse:
    """Get a single connector by ID."""
    result = await session.execute(
        select(GitConnector).where(GitConnector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    return ConnectorResponse.model_validate(connector)


@router.put("/{connector_id}", response_model=ConnectorResponse)
async def update_connector(
    connector_id: str,
    body: ConnectorUpdate,
    session: AsyncSession = Depends(get_session),
) -> ConnectorResponse:
    """Update connector name and/or token."""
    result = await session.execute(
        select(GitConnector).where(GitConnector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    if body.name is not None:
        connector.name = body.name

    if body.token is not None:
        secret_key = _get_secret_key()
        # Re-validate with new token
        provider = create_provider(
            connector.provider, connector.base_url, body.token
        )
        try:
            user = await provider.validate()
            connector.encrypted_token = encrypt_token(body.token, secret_key)
            connector.status = "connected"
            connector.remote_username = user.username
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Token validation failed: {exc}",
            ) from exc

    await session.commit()
    await session.refresh(connector)
    return ConnectorResponse.model_validate(connector)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a connector and cascade-delete its repos."""
    result = await session.execute(
        select(GitConnector).where(GitConnector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    await session.delete(connector)
    await session.commit()


# ── Test ─────────────────────────────────────────────────────


@router.post("/{connector_id}/test", response_model=ConnectorTestResponse)
async def test_connector(
    connector_id: str,
    session: AsyncSession = Depends(get_session),
) -> ConnectorTestResponse:
    """Re-validate a connector's token."""
    result = await session.execute(
        select(GitConnector).where(GitConnector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    secret_key = _get_secret_key()
    token = decrypt_token(connector.encrypted_token, secret_key)
    provider = create_provider(connector.provider, connector.base_url, token)

    try:
        user = await provider.validate()
        connector.status = "connected"
        connector.remote_username = user.username
        await session.commit()
        return ConnectorTestResponse(
            status="connected", remote_username=user.username
        )
    except Exception as exc:
        connector.status = "error"
        await session.commit()
        return ConnectorTestResponse(status="error", error=str(exc))


# ── Repo browsing ────────────────────────────────────────────


@router.get(
    "/{connector_id}/repos",
    response_model=RemoteRepoListResponse,
)
async def list_remote_repos(
    connector_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    search: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> RemoteRepoListResponse:
    """List repositories from the remote provider (live, no cache)."""
    result = await session.execute(
        select(GitConnector).where(GitConnector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    secret_key = _get_secret_key()
    token = decrypt_token(connector.encrypted_token, secret_key)
    provider = create_provider(connector.provider, connector.base_url, token)

    try:
        repos, has_more = await provider.list_repos(page, per_page, search)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch repos: {exc}",
        ) from exc

    return RemoteRepoListResponse(
        repos=[RemoteRepoResponse(**r.__dict__) for r in repos],
        has_more=has_more,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/{connector_id}/repos/{owner}/{repo}",
    response_model=RemoteRepoResponse,
)
async def get_remote_repo(
    connector_id: str,
    owner: str,
    repo: str,
    session: AsyncSession = Depends(get_session),
) -> RemoteRepoResponse:
    """Get a single repo from the provider."""
    result = await session.execute(
        select(GitConnector).where(GitConnector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    secret_key = _get_secret_key()
    token = decrypt_token(connector.encrypted_token, secret_key)
    provider = create_provider(connector.provider, connector.base_url, token)

    try:
        repo_info = await provider.get_repo(f"{owner}/{repo}")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch repo: {exc}",
        ) from exc

    return RemoteRepoResponse(**repo_info.__dict__)


@router.get(
    "/{connector_id}/repos/{owner}/{repo}/branches",
    response_model=BranchListResponse,
)
async def list_remote_branches(
    connector_id: str,
    owner: str,
    repo: str,
    session: AsyncSession = Depends(get_session),
) -> BranchListResponse:
    """List branches for a remote repo."""
    result = await session.execute(
        select(GitConnector).where(GitConnector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    secret_key = _get_secret_key()
    token = decrypt_token(connector.encrypted_token, secret_key)
    full_name = f"{owner}/{repo}"
    provider = create_provider(connector.provider, connector.base_url, token)

    try:
        branches = await provider.list_branches(full_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch branches: {exc}",
        ) from exc

    # Determine default branch
    try:
        repo_info = await provider.get_repo(full_name)
        default_branch = repo_info.default_branch
    except Exception:
        default_branch = "main"

    return BranchListResponse(branches=branches, default_branch=default_branch)
```

- [ ] **Step 2: Run tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_connectors_api.py -v`
Expected: FAIL — router not registered yet

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/api/connectors.py
git commit -m "feat(connectors): implement connector CRUD + repo browsing API"
```

---

## Task 10: Register Connector Router

**Files:**
- Modify: `cast-clone-backend/app/api/__init__.py`
- Modify: `cast-clone-backend/app/main.py`

- [ ] **Step 1: Export from api/__init__.py**

Add to `app/api/__init__.py`:

```python
from app.api.connectors import router as connectors_router
```

And add `"connectors_router"` to the `__all__` list.

- [ ] **Step 2: Register in main.py**

Add to `app/main.py` imports:

```python
from app.api import connectors_router
```

Add in the router registration section:

```python
application.include_router(connectors_router)
```

- [ ] **Step 3: Run tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_connectors_api.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend
git add app/api/__init__.py app/main.py
git commit -m "feat(connectors): register connectors router in FastAPI app"
```

---

## Task 11: Add Frontend Connector Types and API Functions

**Files:**
- Modify: `cast-clone-frontend/lib/types.ts`
- Modify: `cast-clone-frontend/lib/api.ts`

- [ ] **Step 1: Add connector types to types.ts**

Add to the end of `cast-clone-frontend/lib/types.ts`:

```typescript
// ─── Phase 4A: Git Connector types ──────────────────────────────────────────

export type ConnectorProvider = "github" | "gitlab" | "gitea" | "bitbucket";
export type ConnectorStatus = "connected" | "expired" | "revoked" | "error";

export interface ConnectorResponse {
  id: string;
  name: string;
  provider: ConnectorProvider;
  base_url: string;
  auth_method: string;
  status: ConnectorStatus;
  remote_username: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectorListResponse {
  connectors: ConnectorResponse[];
  total: number;
}

export interface CreateConnectorRequest {
  name: string;
  provider: ConnectorProvider;
  base_url: string;
  token: string;
}

export interface ConnectorTestResponse {
  status: string;
  remote_username: string | null;
  error: string | null;
}

export interface RemoteRepoResponse {
  full_name: string;
  clone_url: string;
  default_branch: string;
  description: string | null;
  language: string | null;
  is_private: boolean;
}

export interface RemoteRepoListResponse {
  repos: RemoteRepoResponse[];
  has_more: boolean;
  page: number;
  per_page: number;
}

export interface BranchListResponse {
  branches: string[];
  default_branch: string;
}
```

- [ ] **Step 2: Add connector API functions to api.ts**

Add to the end of `cast-clone-frontend/lib/api.ts`:

```typescript
// ─── Connector endpoints (Phase 4A) ─────────────────────────────────────────

import type {
  ConnectorListResponse,
  ConnectorResponse,
  ConnectorTestResponse,
  CreateConnectorRequest,
  RemoteRepoListResponse,
  RemoteRepoResponse,
  BranchListResponse,
} from "./types";

export async function createConnector(
  data: CreateConnectorRequest,
): Promise<ConnectorResponse> {
  return apiFetch<ConnectorResponse>("/api/v1/connectors", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function listConnectors(): Promise<ConnectorListResponse> {
  return apiFetch<ConnectorListResponse>("/api/v1/connectors");
}

export async function getConnector(id: string): Promise<ConnectorResponse> {
  return apiFetch<ConnectorResponse>(`/api/v1/connectors/${id}`);
}

export async function deleteConnector(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/connectors/${id}`, {
    method: "DELETE",
  });
}

export async function testConnector(
  id: string,
): Promise<ConnectorTestResponse> {
  return apiFetch<ConnectorTestResponse>(`/api/v1/connectors/${id}/test`, {
    method: "POST",
  });
}

export async function listRemoteRepos(
  connectorId: string,
  page: number = 1,
  perPage: number = 30,
  search?: string,
): Promise<RemoteRepoListResponse> {
  const params = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
  });
  if (search) params.set("search", search);
  return apiFetch<RemoteRepoListResponse>(
    `/api/v1/connectors/${connectorId}/repos?${params.toString()}`,
  );
}

export async function getRemoteRepo(
  connectorId: string,
  owner: string,
  repo: string,
): Promise<RemoteRepoResponse> {
  return apiFetch<RemoteRepoResponse>(
    `/api/v1/connectors/${connectorId}/repos/${owner}/${repo}`,
  );
}

export async function listRemoteBranches(
  connectorId: string,
  owner: string,
  repo: string,
): Promise<BranchListResponse> {
  return apiFetch<BranchListResponse>(
    `/api/v1/connectors/${connectorId}/repos/${owner}/${repo}/branches`,
  );
}
```

Note: The imports should be merged into the existing import block at the top of `api.ts`, not added as a separate import.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
cd cast-clone-frontend
git add lib/types.ts lib/api.ts
git commit -m "feat(connectors): add frontend connector types and API client functions"
```

---

## Task 12: Create ConnectorCard Component

**Files:**
- Create: `cast-clone-frontend/components/connectors/ConnectorCard.tsx`

- [ ] **Step 1: Create ConnectorCard.tsx**

```tsx
// cast-clone-frontend/components/connectors/ConnectorCard.tsx
"use client";

import * as React from "react";
import { GitBranch, Github, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ConnectorResponse } from "@/lib/types";

interface ConnectorCardProps {
  connector: ConnectorResponse;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
}

const providerLabels: Record<string, string> = {
  github: "GitHub",
  gitlab: "GitLab",
  gitea: "Gitea",
  bitbucket: "Bitbucket",
};

const statusColors: Record<string, string> = {
  connected: "bg-green-500/10 text-green-700 dark:text-green-400",
  expired: "bg-yellow-500/10 text-yellow-700 dark:text-yellow-400",
  revoked: "bg-red-500/10 text-red-700 dark:text-red-400",
  error: "bg-red-500/10 text-red-700 dark:text-red-400",
};

export function ConnectorCard({
  connector,
  onDelete,
  onTest,
}: ConnectorCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base font-medium">
          {connector.name}
        </CardTitle>
        <Badge
          variant="outline"
          className={statusColors[connector.status] ?? ""}
        >
          {connector.status}
        </Badge>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-2 text-sm text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <GitBranch className="size-3.5" />
            <span>{providerLabels[connector.provider] ?? connector.provider}</span>
          </div>
          {connector.remote_username && (
            <div className="flex items-center gap-1.5">
              <Github className="size-3.5" />
              <span>{connector.remote_username}</span>
            </div>
          )}
          <div className="truncate text-xs">{connector.base_url}</div>
        </div>
        <div className="mt-3 flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onTest(connector.id)}
          >
            Test
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive"
            onClick={() => onDelete(connector.id)}
          >
            <Trash2 className="mr-1 size-3.5" />
            Delete
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add components/connectors/ConnectorCard.tsx
git commit -m "feat(connectors): add ConnectorCard component"
```

---

## Task 13: Create AddConnectorForm Component

**Files:**
- Create: `cast-clone-frontend/components/connectors/AddConnectorForm.tsx`

- [ ] **Step 1: Create AddConnectorForm.tsx**

```tsx
// cast-clone-frontend/components/connectors/AddConnectorForm.tsx
"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createConnector } from "@/lib/api";
import type { ConnectorProvider } from "@/lib/types";

const providers: { value: ConnectorProvider; label: string; defaultUrl: string }[] = [
  { value: "github", label: "GitHub", defaultUrl: "https://github.com" },
  { value: "gitlab", label: "GitLab", defaultUrl: "https://gitlab.com" },
  { value: "gitea", label: "Gitea", defaultUrl: "" },
  { value: "bitbucket", label: "Bitbucket", defaultUrl: "https://bitbucket.org" },
];

export function AddConnectorForm() {
  const router = useRouter();
  const [selectedProvider, setSelectedProvider] =
    React.useState<ConnectorProvider | null>(null);
  const [name, setName] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState("");
  const [token, setToken] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  function handleProviderSelect(p: ConnectorProvider) {
    setSelectedProvider(p);
    const provider = providers.find((x) => x.value === p);
    if (provider?.defaultUrl) {
      setBaseUrl(provider.defaultUrl);
    }
    setName("");
    setToken("");
    setError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedProvider) return;

    setLoading(true);
    setError(null);

    try {
      await createConnector({
        name,
        provider: selectedProvider,
        base_url: baseUrl,
        token,
      });
      router.push("/connectors");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create connector");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      {/* Step 1: Select provider */}
      <div>
        <h2 className="mb-3 text-sm font-medium">Select Provider</h2>
        <div className="grid grid-cols-2 gap-3">
          {providers.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => handleProviderSelect(p.value)}
              className={`rounded-lg border p-3 text-left text-sm transition-colors ${
                selectedProvider === p.value
                  ? "border-primary bg-primary/5"
                  : "hover:border-muted-foreground/30"
              }`}
            >
              <span className="font-medium">{p.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Step 2: Configuration form */}
      {selectedProvider && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Configure Connection</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <Label htmlFor="conn-name">Connection Name</Label>
                <Input
                  id="conn-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={`My ${providers.find((p) => p.value === selectedProvider)?.label}`}
                  required
                />
              </div>
              <div>
                <Label htmlFor="conn-url">Base URL</Label>
                <Input
                  id="conn-url"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://github.com"
                  required
                />
              </div>
              <div>
                <Label htmlFor="conn-token">Personal Access Token</Label>
                <Input
                  id="conn-token"
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="ghp_xxxxxxxxxxxx"
                  required
                />
              </div>

              {error && (
                <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                  {error}
                </div>
              )}

              <div className="flex gap-2">
                <Button type="submit" disabled={loading}>
                  {loading ? "Testing & Saving..." : "Test & Save"}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => router.push("/connectors")}
                >
                  Cancel
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add components/connectors/AddConnectorForm.tsx
git commit -m "feat(connectors): add AddConnectorForm with provider selection"
```

---

## Task 14: Wire Up Connectors Pages

**Files:**
- Modify: `cast-clone-frontend/app/connectors/page.tsx`
- Create: `cast-clone-frontend/app/connectors/new/page.tsx`

- [ ] **Step 1: Update connectors list page**

```tsx
// cast-clone-frontend/app/connectors/page.tsx
"use client";

import * as React from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConnectorCard } from "@/components/connectors/ConnectorCard";
import {
  listConnectors,
  deleteConnector,
  testConnector,
} from "@/lib/api";
import type { ConnectorResponse } from "@/lib/types";

export default function ConnectorsPage() {
  const [connectors, setConnectors] = React.useState<ConnectorResponse[]>([]);
  const [loading, setLoading] = React.useState(true);

  async function load() {
    try {
      const data = await listConnectors();
      setConnectors(data.connectors);
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    load();
  }, []);

  async function handleDelete(id: string) {
    await deleteConnector(id);
    setConnectors((prev) => prev.filter((c) => c.id !== id));
  }

  async function handleTest(id: string) {
    const result = await testConnector(id);
    // Refresh to show updated status
    await load();
  }

  if (loading) {
    return (
      <div className="p-6">
        <p className="text-muted-foreground">Loading connectors...</p>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Git Connectors</h1>
        <Button asChild>
          <Link href="/connectors/new">
            <Plus className="mr-1.5 size-4" />
            Add Connector
          </Link>
        </Button>
      </div>

      {connectors.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="text-muted-foreground">
            No connectors yet. Add one to start browsing repositories.
          </p>
          <Button asChild className="mt-4">
            <Link href="/connectors/new">
              <Plus className="mr-1.5 size-4" />
              Add Your First Connector
            </Link>
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {connectors.map((c) => (
            <ConnectorCard
              key={c.id}
              connector={c}
              onDelete={handleDelete}
              onTest={handleTest}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create add connector page**

```tsx
// cast-clone-frontend/app/connectors/new/page.tsx
import { AddConnectorForm } from "@/components/connectors/AddConnectorForm";

export default function NewConnectorPage() {
  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold">Add Git Connector</h1>
      <AddConnectorForm />
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles and dev server runs**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
cd cast-clone-frontend
git add app/connectors/
git commit -m "feat(connectors): wire up connectors list and add-connector pages"
```

---

## Task 15: Run Full Test Suite + Lint

- [ ] **Step 1: Run backend unit tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run backend lint**

Run: `cd cast-clone-backend && uv run ruff check app/api/connectors.py app/schemas/connectors.py app/services/crypto.py app/services/git_providers/`
Expected: No errors

- [ ] **Step 3: Run frontend typecheck**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 4: Run frontend lint**

Run: `cd cast-clone-frontend && npm run lint`
Expected: No errors

- [ ] **Step 5: Fix any issues and commit**

```bash
cd cast-clone-backend && git add -A && git commit -m "fix: address lint issues from Phase 4A M7b"
cd ../cast-clone-frontend && git add -A && git commit -m "fix: address lint issues from Phase 4A M7b frontend"
```

---

## Verification Checklist

After all tasks are complete, confirm:

- [ ] `app/services/crypto.py` exists with `encrypt_token()` and `decrypt_token()` — tests pass
- [ ] `app/models/db.py` contains `GitConnector` model with encrypted_token field
- [ ] `app/services/git_providers/` contains base.py + 4 provider implementations
- [ ] `create_provider()` factory works for all 4 providers
- [ ] `app/schemas/connectors.py` exists with 8 Pydantic schemas (token NEVER in response)
- [ ] `app/api/connectors.py` exists with 9 endpoints (CRUD + test + repo browsing)
- [ ] Connector router registered in `main.py`
- [ ] Frontend `lib/types.ts` has connector types
- [ ] Frontend `lib/api.ts` has 8 connector API functions
- [ ] `/connectors` page shows card grid with add button
- [ ] `/connectors/new` page has provider selector + form
- [ ] All backend tests pass
- [ ] All frontend typechecks pass
