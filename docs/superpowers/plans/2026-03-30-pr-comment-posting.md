# PR Comment Posting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After PR analysis completes, post a markdown summary comment on the PR via the platform API (GitHub/GitLab/Bitbucket/Gitea), opt-in per repository.

**Architecture:** Extend `GitPlatformClient` ABC with `post_comment()`, add a comment formatter that builds markdown from `PrAnalysis`, and a commenter service that wires them together. Invoked from the webhook background task after analysis completes, gated by a `post_pr_comments` flag on `RepositoryGitConfig`.

**Tech Stack:** Python, httpx (async HTTP), FastAPI, SQLAlchemy, Pydantic v2, pytest

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `app/git/base.py` | Add `CommentResult` dataclass + `post_comment` abstract method |
| Modify | `app/git/github.py` | Implement `post_comment` for GitHub API |
| Modify | `app/git/gitlab.py` | Implement `post_comment` for GitLab API |
| Modify | `app/git/bitbucket.py` | Implement `post_comment` for Bitbucket API |
| Modify | `app/git/gitea.py` | Implement `post_comment` for Gitea API |
| Create | `app/pr_analysis/comment_formatter.py` | Format `PrAnalysis` into markdown comment |
| Create | `app/pr_analysis/commenter.py` | Orchestrate format + post |
| Modify | `app/models/db.py` | Add `post_pr_comments` to `RepositoryGitConfig`, `comment_id` + `comment_url` to `PrAnalysis` |
| Modify | `app/schemas/git_config.py` | Add `post_pr_comments` to create/update/response schemas |
| Modify | `app/schemas/pull_requests.py` | Add `comment_url` to `PrAnalysisResponse` |
| Modify | `app/config.py` | Add `base_url` setting |
| Modify | `app/api/webhooks.py` | Call commenter after successful analysis |
| Create | `tests/unit/test_comment_formatter.py` | Test markdown formatting |
| Create | `tests/unit/test_commenter.py` | Test commenter orchestration |
| Create | `tests/unit/test_post_comment.py` | Test platform `post_comment` implementations |

---

### Task 1: Add `CommentResult` and `post_comment` to platform client ABC

**Files:**
- Modify: `cast-clone-backend/app/git/base.py:1-46`
- Test: `cast-clone-backend/tests/unit/test_post_comment.py` (create)

- [ ] **Step 1: Write the failing test for CommentResult import**

Create `cast-clone-backend/tests/unit/test_post_comment.py`:

```python
"""Tests for platform client post_comment implementations."""

from __future__ import annotations

import pytest

from app.git.base import CommentResult


class TestCommentResult:
    def test_dataclass_fields(self):
        result = CommentResult(
            comment_id="123",
            comment_url="https://github.com/owner/repo/pull/1#issuecomment-123",
            platform="github",
        )
        assert result.comment_id == "123"
        assert result.comment_url == "https://github.com/owner/repo/pull/1#issuecomment-123"
        assert result.platform == "github"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_post_comment.py::TestCommentResult::test_dataclass_fields -v`
Expected: FAIL — `ImportError: cannot import name 'CommentResult'`

- [ ] **Step 3: Implement CommentResult and post_comment ABC method**

In `cast-clone-backend/app/git/base.py`, add the dataclass import and `CommentResult` before the class, then add the abstract method:

```python
"""Abstract base class for git platform clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.pr_analysis.models import PRDiff, PullRequestEvent


@dataclass
class CommentResult:
    """Result of posting a comment on a pull request."""

    comment_id: str
    comment_url: str
    platform: str


class GitPlatformClient(ABC):
    """ABC defining the interface for all git platform integrations."""

    @abstractmethod
    def parse_webhook(
        self, headers: dict, body: bytes
    ) -> PullRequestEvent | None:
        """Parse an incoming webhook payload into a PullRequestEvent."""

    @abstractmethod
    def verify_webhook_signature(
        self, headers: dict, body: bytes, secret: str
    ) -> bool:
        """Verify the webhook payload signature using the shared secret."""

    @abstractmethod
    async def fetch_diff(
        self, repo_url: str, pr_number: int, token: str
    ) -> PRDiff:
        """Fetch the diff for a pull/merge request from the platform API."""

    @abstractmethod
    async def post_comment(
        self, repo_url: str, pr_number: int, token: str, body: str
    ) -> CommentResult:
        """Post a comment on a pull/merge request.

        Args:
            repo_url: The repository URL (e.g. https://github.com/owner/repo).
            pr_number: The pull/merge request number.
            token: Authentication token for the platform API.
            body: The markdown comment body.

        Returns:
            A CommentResult with the comment ID and URL.
        """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_post_comment.py::TestCommentResult::test_dataclass_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/git/base.py tests/unit/test_post_comment.py && git commit -m "feat: add CommentResult and post_comment to GitPlatformClient ABC"
```

---

### Task 2: Implement `post_comment` for GitHub

**Files:**
- Modify: `cast-clone-backend/app/git/github.py:82-138`
- Test: `cast-clone-backend/tests/unit/test_post_comment.py`

- [ ] **Step 1: Write the failing test**

Append to `cast-clone-backend/tests/unit/test_post_comment.py`:

```python
import httpx
import respx

from app.git.github import GitHubPlatformClient


class TestGitHubPostComment:
    @pytest.mark.asyncio
    @respx.mock
    async def test_post_comment_success(self):
        route = respx.post(
            "https://api.github.com/repos/owner/repo/issues/42/comments"
        ).mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 999,
                    "html_url": "https://github.com/owner/repo/pull/42#issuecomment-999",
                },
            )
        )

        client = GitHubPlatformClient()
        result = await client.post_comment(
            repo_url="https://github.com/owner/repo",
            pr_number=42,
            token="ghp_test",
            body="## Analysis\nLooks good",
        )

        assert result.comment_id == "999"
        assert result.comment_url == "https://github.com/owner/repo/pull/42#issuecomment-999"
        assert result.platform == "github"
        assert route.called
        req = route.calls[0].request
        assert req.headers["authorization"] == "Bearer ghp_test"

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_comment_with_git_suffix(self):
        respx.post(
            "https://api.github.com/repos/owner/repo/issues/1/comments"
        ).mock(
            return_value=httpx.Response(
                201,
                json={"id": 1, "html_url": "https://github.com/owner/repo/pull/1#issuecomment-1"},
            )
        )

        client = GitHubPlatformClient()
        result = await client.post_comment(
            repo_url="https://github.com/owner/repo.git",
            pr_number=1,
            token="tok",
            body="test",
        )
        assert result.comment_id == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_post_comment.py::TestGitHubPostComment -v`
Expected: FAIL — `TypeError: Can't instantiate abstract class GitHubPlatformClient with abstract method post_comment`

- [ ] **Step 3: Implement post_comment on GitHubPlatformClient**

Add this method to `GitHubPlatformClient` in `cast-clone-backend/app/git/github.py`, after the `fetch_diff` method. Also add the `CommentResult` import:

```python
from app.git.base import CommentResult, GitPlatformClient
```

(Replace the existing `from app.git.base import GitPlatformClient` line.)

Then add the method at the end of the class:

```python
    async def post_comment(
        self, repo_url: str, pr_number: int, token: str, body: str
    ) -> CommentResult:
        parsed = urlparse(repo_url)
        path_parts = parsed.path.strip("/").removesuffix(".git").split("/")
        owner, repo = path_parts[0], path_parts[1]

        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json={"body": body})
            resp.raise_for_status()
            data = resp.json()

        return CommentResult(
            comment_id=str(data["id"]),
            comment_url=data["html_url"],
            platform="github",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_post_comment.py::TestGitHubPostComment -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/git/github.py tests/unit/test_post_comment.py && git commit -m "feat: implement post_comment for GitHub platform client"
```

---

### Task 3: Implement `post_comment` for GitLab

**Files:**
- Modify: `cast-clone-backend/app/git/gitlab.py:72-138`
- Test: `cast-clone-backend/tests/unit/test_post_comment.py`

- [ ] **Step 1: Write the failing test**

Append to `cast-clone-backend/tests/unit/test_post_comment.py`:

```python
from app.git.gitlab import GitLabPlatformClient


class TestGitLabPostComment:
    @pytest.mark.asyncio
    @respx.mock
    async def test_post_comment_success(self):
        route = respx.post(
            "https://gitlab.com/api/v4/projects/group%2Fproject/merge_requests/7/notes"
        ).mock(
            return_value=httpx.Response(
                201,
                json={"id": 555, "body": "## Analysis"},
            )
        )

        client = GitLabPlatformClient()
        result = await client.post_comment(
            repo_url="https://gitlab.com/group/project",
            pr_number=7,
            token="glpat-test",
            body="## Analysis",
        )

        assert result.comment_id == "555"
        assert "group/project" in result.comment_url
        assert "merge_requests/7" in result.comment_url
        assert result.platform == "gitlab"
        assert route.called
        req = route.calls[0].request
        assert req.headers["private-token"] == "glpat-test"

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_comment_nested_group(self):
        respx.post(
            "https://gitlab.com/api/v4/projects/org%2Fsub%2Frepo/merge_requests/1/notes"
        ).mock(
            return_value=httpx.Response(201, json={"id": 1, "body": "test"}),
        )

        client = GitLabPlatformClient()
        result = await client.post_comment(
            repo_url="https://gitlab.com/org/sub/repo",
            pr_number=1,
            token="tok",
            body="test",
        )
        assert result.comment_id == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_post_comment.py::TestGitLabPostComment -v`
Expected: FAIL — `TypeError: Can't instantiate abstract class GitLabPlatformClient with abstract method post_comment`

- [ ] **Step 3: Implement post_comment on GitLabPlatformClient**

In `cast-clone-backend/app/git/gitlab.py`, update the import:

```python
from app.git.base import CommentResult, GitPlatformClient
```

Add the method at the end of the class:

```python
    async def post_comment(
        self, repo_url: str, pr_number: int, token: str, body: str
    ) -> CommentResult:
        parsed = urlparse(repo_url)
        project_path = parsed.path.strip("/").removesuffix(".git")
        encoded_path = quote(project_path, safe="")

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        url = (
            f"{base_url}/api/v4/projects/{encoded_path}"
            f"/merge_requests/{pr_number}/notes"
        )
        headers = {"PRIVATE-TOKEN": token}

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json={"body": body})
            resp.raise_for_status()
            data = resp.json()

        comment_url = (
            f"{repo_url}/-/merge_requests/{pr_number}#note_{data['id']}"
        )

        return CommentResult(
            comment_id=str(data["id"]),
            comment_url=comment_url,
            platform="gitlab",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_post_comment.py::TestGitLabPostComment -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/git/gitlab.py tests/unit/test_post_comment.py && git commit -m "feat: implement post_comment for GitLab platform client"
```

---

### Task 4: Implement `post_comment` for Bitbucket

**Files:**
- Modify: `cast-clone-backend/app/git/bitbucket.py:79-138`
- Test: `cast-clone-backend/tests/unit/test_post_comment.py`

- [ ] **Step 1: Write the failing test**

Append to `cast-clone-backend/tests/unit/test_post_comment.py`:

```python
from app.git.bitbucket import BitbucketPlatformClient


class TestBitbucketPostComment:
    @pytest.mark.asyncio
    @respx.mock
    async def test_post_comment_success(self):
        route = respx.post(
            "https://api.bitbucket.org/2.0/repositories/workspace/repo/pullrequests/99/comments"
        ).mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 777,
                    "links": {
                        "html": {
                            "href": "https://bitbucket.org/workspace/repo/pull-requests/99#comment-777"
                        }
                    },
                },
            )
        )

        client = BitbucketPlatformClient()
        result = await client.post_comment(
            repo_url="https://bitbucket.org/workspace/repo",
            pr_number=99,
            token="bb_token",
            body="## Analysis",
        )

        assert result.comment_id == "777"
        assert result.comment_url == "https://bitbucket.org/workspace/repo/pull-requests/99#comment-777"
        assert result.platform == "bitbucket"
        assert route.called
        req = route.calls[0].request
        assert req.headers["authorization"] == "Bearer bb_token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_post_comment.py::TestBitbucketPostComment -v`
Expected: FAIL — `TypeError: Can't instantiate abstract class BitbucketPlatformClient with abstract method post_comment`

- [ ] **Step 3: Implement post_comment on BitbucketPlatformClient**

In `cast-clone-backend/app/git/bitbucket.py`, update the import:

```python
from app.git.base import CommentResult, GitPlatformClient
```

Add the method at the end of the class:

```python
    async def post_comment(
        self, repo_url: str, pr_number: int, token: str, body: str
    ) -> CommentResult:
        parsed = urlparse(repo_url)
        path_parts = parsed.path.strip("/").removesuffix(".git").split("/")
        workspace, repo = path_parts[0], path_parts[1]

        url = (
            f"https://api.bitbucket.org/2.0/repositories"
            f"/{workspace}/{repo}/pullrequests/{pr_number}/comments"
        )
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=headers, json={"content": {"raw": body}}
            )
            resp.raise_for_status()
            data = resp.json()

        return CommentResult(
            comment_id=str(data["id"]),
            comment_url=data["links"]["html"]["href"],
            platform="bitbucket",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_post_comment.py::TestBitbucketPostComment -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/git/bitbucket.py tests/unit/test_post_comment.py && git commit -m "feat: implement post_comment for Bitbucket platform client"
```

---

### Task 5: Implement `post_comment` for Gitea

**Files:**
- Modify: `cast-clone-backend/app/git/gitea.py:79-132`
- Test: `cast-clone-backend/tests/unit/test_post_comment.py`

- [ ] **Step 1: Write the failing test**

Append to `cast-clone-backend/tests/unit/test_post_comment.py`:

```python
from app.git.gitea import GiteaPlatformClient


class TestGiteaPostComment:
    @pytest.mark.asyncio
    @respx.mock
    async def test_post_comment_success(self):
        route = respx.post(
            "https://gitea.example.com/api/v1/repos/owner/repo/issues/10/comments"
        ).mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 333,
                    "html_url": "https://gitea.example.com/owner/repo/pulls/10#issuecomment-333",
                },
            )
        )

        client = GiteaPlatformClient()
        result = await client.post_comment(
            repo_url="https://gitea.example.com/owner/repo",
            pr_number=10,
            token="gitea_token",
            body="## Analysis",
        )

        assert result.comment_id == "333"
        assert result.comment_url == "https://gitea.example.com/owner/repo/pulls/10#issuecomment-333"
        assert result.platform == "gitea"
        assert route.called
        req = route.calls[0].request
        assert req.headers["authorization"] == "token gitea_token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_post_comment.py::TestGiteaPostComment -v`
Expected: FAIL — `TypeError: Can't instantiate abstract class GiteaPlatformClient with abstract method post_comment`

- [ ] **Step 3: Implement post_comment on GiteaPlatformClient**

In `cast-clone-backend/app/git/gitea.py`, update the import:

```python
from app.git.base import CommentResult, GitPlatformClient
```

Add the method at the end of the class:

```python
    async def post_comment(
        self, repo_url: str, pr_number: int, token: str, body: str
    ) -> CommentResult:
        parsed = urlparse(repo_url)
        path_parts = parsed.path.strip("/").removesuffix(".git").split("/")
        owner, repo = path_parts[0], path_parts[1]

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        url = f"{base_url}/api/v1/repos/{owner}/{repo}/issues/{pr_number}/comments"
        headers = {"Authorization": f"token {token}"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json={"body": body})
            resp.raise_for_status()
            data = resp.json()

        return CommentResult(
            comment_id=str(data["id"]),
            comment_url=data["html_url"],
            platform="gitea",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_post_comment.py::TestGiteaPostComment -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/git/gitea.py tests/unit/test_post_comment.py && git commit -m "feat: implement post_comment for Gitea platform client"
```

---

### Task 6: Add DB columns and schema fields

**Files:**
- Modify: `cast-clone-backend/app/models/db.py:264-293` (RepositoryGitConfig) and `295-341` (PrAnalysis)
- Modify: `cast-clone-backend/app/schemas/git_config.py:1-83`
- Modify: `cast-clone-backend/app/schemas/pull_requests.py:50-81`
- Modify: `cast-clone-backend/app/config.py:6-63`

- [ ] **Step 1: Add `post_pr_comments` to RepositoryGitConfig model**

In `cast-clone-backend/app/models/db.py`, add after the `is_active` field (line 280):

```python
    post_pr_comments: Mapped[bool] = mapped_column(default=False)
```

- [ ] **Step 2: Add `comment_id` and `comment_url` to PrAnalysis model**

In `cast-clone-backend/app/models/db.py`, add after the `ai_summary_tokens` field (line 332):

```python
    comment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comment_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

- [ ] **Step 3: Update git config schemas**

In `cast-clone-backend/app/schemas/git_config.py`:

Add to `GitConfigCreate` (after `monitored_branches` field):
```python
    post_pr_comments: bool = False
```

Add to `GitConfigUpdate` (after `monitored_branches` field):
```python
    post_pr_comments: bool | None = None
```

Add to `GitConfigResponse` (after `is_active` field):
```python
    post_pr_comments: bool
```

Add to `EnableWebhooksRequest` (after `auto_register` field):
```python
    post_pr_comments: bool = False
```

Add to `EnableWebhooksResponse` (after `is_active` field):
```python
    post_pr_comments: bool
```

- [ ] **Step 4: Update PR analysis response schema**

In `cast-clone-backend/app/schemas/pull_requests.py`, add to `PrAnalysisResponse` (after `ai_summary_tokens`):

```python
    comment_url: str | None = None
```

- [ ] **Step 5: Add `base_url` to Settings**

In `cast-clone-backend/app/config.py`, add after the `auth_disabled` field (line 24):

```python
    base_url: str = "http://localhost:3000"
```

- [ ] **Step 6: Verify existing tests still pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pr_schemas.py tests/unit/test_webhook_parsing.py -v`
Expected: PASS (no breakage from new fields)

- [ ] **Step 7: Commit**

```bash
cd cast-clone-backend && git add app/models/db.py app/schemas/git_config.py app/schemas/pull_requests.py app/config.py && git commit -m "feat: add DB columns and schema fields for PR commenting"
```

---

### Task 7: Build comment formatter

**Files:**
- Create: `cast-clone-backend/app/pr_analysis/comment_formatter.py`
- Create: `cast-clone-backend/tests/unit/test_comment_formatter.py`

- [ ] **Step 1: Write the failing tests**

Create `cast-clone-backend/tests/unit/test_comment_formatter.py`:

```python
"""Tests for PR comment markdown formatter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.pr_analysis.comment_formatter import format_pr_comment


def _make_pr_record(
    risk_level: str = "Medium",
    blast_radius: int = 20,
    files_changed: int = 5,
    additions: int = 100,
    deletions: int = 30,
    changed_node_count: int = 3,
    impact_summary: dict | None = None,
    drift_report: dict | None = None,
    ai_summary: str | None = "This PR modifies the order processing pipeline.",
    pr_number: int = 42,
    repository_id: str = "repo-1",
    id: str = "analysis-1",
) -> MagicMock:
    record = MagicMock()
    record.id = id
    record.repository_id = repository_id
    record.pr_number = pr_number
    record.risk_level = risk_level
    record.blast_radius_total = blast_radius
    record.files_changed = files_changed
    record.additions = additions
    record.deletions = deletions
    record.changed_node_count = changed_node_count
    record.ai_summary = ai_summary
    record.impact_summary = impact_summary or {
        "total_blast_radius": blast_radius,
        "by_type": {"Class": 2, "Function": 10},
        "downstream_count": 15,
        "upstream_count": 5,
        "cross_tech": [],
        "transactions_affected": [],
    }
    record.drift_report = drift_report or {"has_drift": False}
    return record


class TestFormatPrComment:
    def test_contains_risk_level(self):
        record = _make_pr_record(risk_level="High")
        result = format_pr_comment(record)
        assert "High" in result

    def test_contains_blast_radius(self):
        record = _make_pr_record(blast_radius=45)
        result = format_pr_comment(record)
        assert "45" in result

    def test_contains_file_stats(self):
        record = _make_pr_record(files_changed=12, additions=340, deletions=89)
        result = format_pr_comment(record)
        assert "12" in result
        assert "+340" in result
        assert "-89" in result

    def test_contains_ai_summary(self):
        record = _make_pr_record(ai_summary="The order service was refactored.")
        result = format_pr_comment(record)
        assert "The order service was refactored." in result

    def test_no_ai_section_when_empty(self):
        record = _make_pr_record(ai_summary=None)
        result = format_pr_comment(record)
        assert "AI Analysis" not in result

    def test_no_drift_section_when_no_drift(self):
        record = _make_pr_record(drift_report={"has_drift": False})
        result = format_pr_comment(record)
        assert "Architecture Drift" not in result

    def test_drift_section_shown_when_drift(self):
        record = _make_pr_record(drift_report={
            "has_drift": True,
            "potential_new_module_deps": [
                {"from_module": "api", "to_module": "database"}
            ],
            "circular_deps_affected": [["a", "b", "a"]],
            "new_files_outside_modules": [],
        })
        result = format_pr_comment(record)
        assert "Architecture Drift" in result
        assert "api" in result
        assert "database" in result

    def test_no_cross_tech_section_when_empty(self):
        record = _make_pr_record(impact_summary={
            "total_blast_radius": 5,
            "by_type": {},
            "downstream_count": 3,
            "upstream_count": 2,
            "cross_tech": [],
            "transactions_affected": [],
        })
        result = format_pr_comment(record)
        assert "Cross-Technology" not in result

    def test_cross_tech_section_shown(self):
        record = _make_pr_record(impact_summary={
            "total_blast_radius": 5,
            "by_type": {},
            "downstream_count": 3,
            "upstream_count": 2,
            "cross_tech": [
                {"kind": "api_endpoint", "name": "POST /orders", "detail": "used by OrderService"}
            ],
            "transactions_affected": ["CreateOrder"],
        })
        result = format_pr_comment(record)
        assert "Cross-Technology" in result
        assert "POST /orders" in result

    def test_transactions_shown(self):
        record = _make_pr_record(impact_summary={
            "total_blast_radius": 5,
            "by_type": {},
            "downstream_count": 3,
            "upstream_count": 2,
            "cross_tech": [],
            "transactions_affected": ["CreateOrder", "ProcessPayment"],
        })
        result = format_pr_comment(record)
        assert "CreateOrder" in result
        assert "ProcessPayment" in result

    def test_footer_link_with_base_url(self):
        record = _make_pr_record()
        result = format_pr_comment(record, base_url="https://codelens.example.com")
        assert "https://codelens.example.com" in result

    def test_no_footer_link_without_base_url(self):
        record = _make_pr_record()
        result = format_pr_comment(record)
        assert "View full analysis" not in result

    def test_risk_emoji_high(self):
        record = _make_pr_record(risk_level="High")
        result = format_pr_comment(record)
        assert "\U0001f534" in result  # red circle

    def test_risk_emoji_medium(self):
        record = _make_pr_record(risk_level="Medium")
        result = format_pr_comment(record)
        assert "\U0001f7e1" in result  # yellow circle

    def test_risk_emoji_low(self):
        record = _make_pr_record(risk_level="Low")
        result = format_pr_comment(record)
        assert "\U0001f7e2" in result  # green circle
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_comment_formatter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pr_analysis.comment_formatter'`

- [ ] **Step 3: Implement the comment formatter**

Create `cast-clone-backend/app/pr_analysis/comment_formatter.py`:

```python
"""Format PR analysis results into a markdown comment for posting to Git platforms."""

from __future__ import annotations

_RISK_EMOJI = {
    "High": "\U0001f534",    # red circle
    "Medium": "\U0001f7e1",  # yellow circle
    "Low": "\U0001f7e2",     # green circle
}


def format_pr_comment(pr_record, base_url: str | None = None) -> str:
    """Build a markdown comment from a completed PrAnalysis record.

    Args:
        pr_record: A PrAnalysis ORM instance with completed analysis data.
        base_url: Optional CodeLens UI base URL for the "View full analysis" link.

    Returns:
        A markdown string ready to post as a PR comment.
    """
    risk = pr_record.risk_level or "Unknown"
    emoji = _RISK_EMOJI.get(risk, "\u2753")
    blast = pr_record.blast_radius_total or 0
    files = pr_record.files_changed or 0
    adds = pr_record.additions or 0
    dels = pr_record.deletions or 0

    impact = pr_record.impact_summary or {}
    drift = pr_record.drift_report or {}

    sections: list[str] = []

    # Header
    sections.append("## CodeLens Architecture Analysis\n")
    sections.append(
        f"**Risk Level:** {emoji} {risk} "
        f"| **Blast Radius:** {blast} nodes "
        f"| **Files Changed:** {files} (+{adds} / -{dels})\n"
    )

    # Impact summary
    downstream = impact.get("downstream_count", 0)
    upstream = impact.get("upstream_count", 0)
    by_type = impact.get("by_type", {})
    type_breakdown = ", ".join(f"{v} {k}" for k, v in by_type.items()) if by_type else ""
    changed = pr_record.changed_node_count or 0
    changed_line = f"**Changed nodes:** {changed}"
    if type_breakdown:
        changed_line += f" ({type_breakdown})"

    impact_lines = [
        f"### Impact Summary\n",
        f"- {changed_line}",
        f"- **Downstream affected:** {downstream} nodes",
        f"- **Upstream dependents:** {upstream} nodes",
    ]

    transactions = impact.get("transactions_affected", [])
    if transactions:
        impact_lines.append(f"- **Transactions affected:** {', '.join(transactions)}")

    sections.append("\n".join(impact_lines) + "\n")

    # Cross-technology impact (conditional)
    cross_tech = impact.get("cross_tech", [])
    if cross_tech:
        ct_lines = ["### Cross-Technology Impact\n"]
        for ct in cross_tech:
            ct_lines.append(f"- {ct['kind']}: `{ct['name']}`")
        sections.append("\n".join(ct_lines) + "\n")

    # Architecture drift (conditional)
    if drift.get("has_drift"):
        drift_lines = ["### Architecture Drift\n"]
        for dep in drift.get("potential_new_module_deps", []):
            drift_lines.append(
                f"- New module dependency: `{dep['from_module']}` \u2192 `{dep['to_module']}`"
            )
        for cycle in drift.get("circular_deps_affected", []):
            drift_lines.append(
                f"- Circular dependency: {' \u2192 '.join(f'`{m}`' for m in cycle)}"
            )
        for f in drift.get("new_files_outside_modules", []):
            drift_lines.append(f"- New file outside modules: `{f}`")
        sections.append("\n".join(drift_lines) + "\n")

    # AI analysis (conditional)
    if pr_record.ai_summary:
        sections.append(f"### AI Analysis\n\n{pr_record.ai_summary}\n")

    # Footer
    footer = "\n---\n*Generated by CodeLens"
    if base_url:
        url = (
            f"{base_url.rstrip('/')}/projects/{pr_record.repository_id}"
            f"/pull-requests/{pr_record.id}"
        )
        footer += f" \u2022 [View full analysis]({url})"
    footer += "*"
    sections.append(footer)

    return "\n".join(sections)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_comment_formatter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/pr_analysis/comment_formatter.py tests/unit/test_comment_formatter.py && git commit -m "feat: add PR comment markdown formatter"
```

---

### Task 8: Build commenter service

**Files:**
- Create: `cast-clone-backend/app/pr_analysis/commenter.py`
- Create: `cast-clone-backend/tests/unit/test_commenter.py`

- [ ] **Step 1: Write the failing test**

Create `cast-clone-backend/tests/unit/test_commenter.py`:

```python
"""Tests for the PR commenter orchestration service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.git.base import CommentResult
from app.pr_analysis.commenter import post_analysis_comment


def _make_pr_record() -> MagicMock:
    record = MagicMock()
    record.id = "analysis-1"
    record.repository_id = "repo-1"
    record.pr_number = 42
    record.pr_url = "https://github.com/owner/repo/pull/42"
    record.risk_level = "Medium"
    record.blast_radius_total = 20
    record.files_changed = 5
    record.additions = 100
    record.deletions = 30
    record.changed_node_count = 3
    record.ai_summary = "Looks fine."
    record.impact_summary = {
        "total_blast_radius": 20,
        "by_type": {},
        "downstream_count": 10,
        "upstream_count": 5,
        "cross_tech": [],
        "transactions_affected": [],
    }
    record.drift_report = {"has_drift": False}
    return record


class TestPostAnalysisComment:
    @pytest.mark.asyncio
    async def test_calls_platform_client_and_returns_result(self):
        expected = CommentResult(
            comment_id="999",
            comment_url="https://github.com/owner/repo/pull/42#issuecomment-999",
            platform="github",
        )

        mock_client = MagicMock()
        mock_client.post_comment = AsyncMock(return_value=expected)

        with patch(
            "app.pr_analysis.commenter.create_platform_client",
            return_value=mock_client,
        ):
            result = await post_analysis_comment(
                pr_record=_make_pr_record(),
                platform="github",
                api_token="tok",
            )

        assert result.comment_id == "999"
        assert result.comment_url == "https://github.com/owner/repo/pull/42#issuecomment-999"
        mock_client.post_comment.assert_called_once()
        call_args = mock_client.post_comment.call_args
        assert call_args.kwargs["pr_number"] == 42
        assert call_args.kwargs["token"] == "tok"
        assert "CodeLens" in call_args.kwargs["body"]

    @pytest.mark.asyncio
    async def test_passes_base_url_to_formatter(self):
        expected = CommentResult(comment_id="1", comment_url="url", platform="github")
        mock_client = MagicMock()
        mock_client.post_comment = AsyncMock(return_value=expected)

        with patch(
            "app.pr_analysis.commenter.create_platform_client",
            return_value=mock_client,
        ):
            await post_analysis_comment(
                pr_record=_make_pr_record(),
                platform="github",
                api_token="tok",
                base_url="https://codelens.example.com",
            )

        body = mock_client.post_comment.call_args.kwargs["body"]
        assert "https://codelens.example.com" in body

    @pytest.mark.asyncio
    async def test_extracts_repo_url_from_pr_url(self):
        expected = CommentResult(comment_id="1", comment_url="url", platform="github")
        mock_client = MagicMock()
        mock_client.post_comment = AsyncMock(return_value=expected)

        with patch(
            "app.pr_analysis.commenter.create_platform_client",
            return_value=mock_client,
        ):
            await post_analysis_comment(
                pr_record=_make_pr_record(),
                platform="github",
                api_token="tok",
            )

        call_args = mock_client.post_comment.call_args
        assert call_args.kwargs["repo_url"] == "https://github.com/owner/repo"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_commenter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pr_analysis.commenter'`

- [ ] **Step 3: Implement the commenter service**

Create `cast-clone-backend/app/pr_analysis/commenter.py`:

```python
"""Orchestrate formatting and posting PR analysis comments."""

from __future__ import annotations

import structlog

from app.git import create_platform_client
from app.git.base import CommentResult
from app.pr_analysis.comment_formatter import format_pr_comment

logger = structlog.get_logger(__name__)


def _extract_repo_url(pr_url: str) -> str:
    """Extract repository URL from a PR URL.

    Example: https://github.com/owner/repo/pull/42 -> https://github.com/owner/repo
    """
    parts = pr_url.split("/")
    for i, p in enumerate(parts):
        if p in ("pull", "pulls", "merge_requests", "pull-requests"):
            return "/".join(parts[:i])
    return pr_url


async def post_analysis_comment(
    pr_record,
    platform: str,
    api_token: str,
    base_url: str | None = None,
) -> CommentResult:
    """Format and post a PR analysis comment.

    Args:
        pr_record: A completed PrAnalysis ORM instance.
        platform: Git platform name (github, gitlab, bitbucket, gitea).
        api_token: Decrypted API token for the platform.
        base_url: Optional CodeLens UI base URL for analysis link.

    Returns:
        CommentResult with the posted comment's ID and URL.
    """
    body = format_pr_comment(pr_record, base_url=base_url)
    repo_url = _extract_repo_url(pr_record.pr_url)
    client = create_platform_client(platform)

    result = await client.post_comment(
        repo_url=repo_url,
        pr_number=pr_record.pr_number,
        token=api_token,
        body=body,
    )

    logger.info(
        "pr_comment_posted",
        analysis_id=pr_record.id,
        platform=platform,
        comment_id=result.comment_id,
    )

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_commenter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/pr_analysis/commenter.py tests/unit/test_commenter.py && git commit -m "feat: add PR commenter service"
```

---

### Task 9: Wire commenting into the webhook background task

**Files:**
- Modify: `cast-clone-backend/app/api/webhooks.py:140-273`

- [ ] **Step 1: Pass `post_pr_comments` into the background task**

In `cast-clone-backend/app/api/webhooks.py`, update the `background_tasks.add_task` call (around line 142) to include the flag:

Change:
```python
    background_tasks.add_task(
        _run_analysis_background,
        pr_analysis_id=pr_analysis.id,
        repo_id=repo_id,
        api_token_encrypted=config.api_token_encrypted,
        platform=platform,
        secret_key=settings.secret_key,
    )
```

To:
```python
    background_tasks.add_task(
        _run_analysis_background,
        pr_analysis_id=pr_analysis.id,
        repo_id=repo_id,
        api_token_encrypted=config.api_token_encrypted,
        platform=platform,
        secret_key=settings.secret_key,
        post_pr_comments=config.post_pr_comments,
    )
```

- [ ] **Step 2: Add the parameter to the background function signature**

Update the `_run_analysis_background` function signature (line 158) to accept the new parameter:

Change:
```python
async def _run_analysis_background(
    pr_analysis_id: str,
    repo_id: str,
    api_token_encrypted: str,
    platform: str,
    secret_key: str,
) -> None:
```

To:
```python
async def _run_analysis_background(
    pr_analysis_id: str,
    repo_id: str,
    api_token_encrypted: str,
    platform: str,
    secret_key: str,
    post_pr_comments: bool = False,
) -> None:
```

- [ ] **Step 3: Add commenting logic after `run_pr_analysis` call**

After the `run_pr_analysis(...)` call (line 264-272), and before the end of the try block, add the commenting logic. Insert after line 272 (the closing paren of `run_pr_analysis`):

```python
        # Post comment on PR if enabled
        if post_pr_comments and pr_record.status == "completed":
            try:
                from app.pr_analysis.commenter import post_analysis_comment

                settings = get_settings()
                comment_result = await post_analysis_comment(
                    pr_record=pr_record,
                    platform=platform,
                    api_token=api_token,
                    base_url=settings.base_url,
                )
                pr_record.comment_id = comment_result.comment_id
                pr_record.comment_url = comment_result.comment_url
                await session.commit()
            except Exception as exc:
                logger.warning(
                    "pr_comment_failed",
                    analysis_id=pr_analysis_id,
                    error=str(exc),
                    exc_info=True,
                )
```

- [ ] **Step 4: Verify the full test suite still passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/api/webhooks.py && git commit -m "feat: wire PR commenting into webhook background task"
```

---

### Task 10: End-to-end smoke test

**Files:**
- All files from previous tasks (read-only verification)

- [ ] **Step 1: Run the full unit test suite**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Run linting**

Run: `cd cast-clone-backend && uv run ruff check app/pr_analysis/comment_formatter.py app/pr_analysis/commenter.py app/git/base.py app/git/github.py app/git/gitlab.py app/git/bitbucket.py app/git/gitea.py app/api/webhooks.py`
Expected: No errors

- [ ] **Step 3: Run formatting check**

Run: `cd cast-clone-backend && uv run ruff format --check app/pr_analysis/comment_formatter.py app/pr_analysis/commenter.py app/git/base.py app/git/github.py app/git/gitlab.py app/git/bitbucket.py app/git/gitea.py app/api/webhooks.py`
Expected: No reformatting needed (or fix and recommit)

- [ ] **Step 4: Commit any lint/format fixes if needed**

```bash
cd cast-clone-backend && git add -u && git commit -m "style: fix lint/format issues in PR commenting code"
```

(Skip this step if no fixes were needed.)
