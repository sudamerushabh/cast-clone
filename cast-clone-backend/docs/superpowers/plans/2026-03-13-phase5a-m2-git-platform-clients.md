# Phase 5a M2 — Git Platform Clients (Webhook Parsing + Diff Fetching)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement webhook parsing, signature verification, and diff fetching for GitHub, GitLab, Bitbucket, and Gitea.

**Architecture:** A `GitPlatformClient` ABC (separate from the existing `GitProvider` which handles repo listing) with four concrete implementations. Each handles: (a) parsing inbound webhook payloads into `PullRequestEvent`, (b) verifying webhook signatures, and (c) fetching PR diffs via the platform REST API. A shared `diff_parser.py` parses unified diff format into `DiffHunk` objects. A factory function selects the right client by platform name.

**Tech Stack:** httpx (async HTTP), hmac/hashlib (signature verification), dataclasses from M1.

**Depends On:** M1 (foundation — `PullRequestEvent`, `PRDiff`, `FileDiff`, `DiffHunk`, `GitPlatform`).

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── git/
│       ├── __init__.py              # CREATE — factory function
│       ├── base.py                  # CREATE — GitPlatformClient ABC
│       ├── diff_parser.py           # CREATE — unified diff → DiffHunk parser
│       ├── github.py                # CREATE — GitHub webhook + diff client
│       ├── gitlab.py                # CREATE — GitLab webhook + diff client
│       ├── bitbucket.py             # CREATE — Bitbucket webhook + diff client
│       └── gitea.py                 # CREATE — Gitea webhook + diff client
└── tests/
    └── unit/
        ├── test_diff_parser.py      # CREATE
        ├── test_webhook_parsing.py  # CREATE — per-platform webhook tests
        └── test_webhook_signature.py # CREATE — signature verification tests
```

---

### Task 1: GitPlatformClient ABC + Diff Parser

**Files:**
- Create: `app/git/__init__.py`
- Create: `app/git/base.py`
- Create: `app/git/diff_parser.py`
- Test: `tests/unit/test_diff_parser.py`

- [ ] **Step 1: Write the failing test for diff parser**

```python
# tests/unit/test_diff_parser.py
"""Tests for unified diff parser."""
import pytest

from app.git.diff_parser import parse_patch_hunks
from app.pr_analysis.models import DiffHunk


class TestParsePatchHunks:
    def test_single_hunk(self):
        patch = (
            "@@ -10,5 +10,8 @@ public class OrderService {\n"
            "+    // new line\n"
            "+    // another new line\n"
            "+    // third new line\n"
            "     existing line\n"
        )
        hunks = parse_patch_hunks(patch)
        assert len(hunks) == 1
        assert hunks[0].old_start == 10
        assert hunks[0].old_count == 5
        assert hunks[0].new_start == 10
        assert hunks[0].new_count == 8

    def test_multiple_hunks(self):
        patch = (
            "@@ -1,3 +1,4 @@\n"
            "+import foo\n"
            " line1\n"
            " line2\n"
            "@@ -20,5 +21,7 @@ class Foo:\n"
            "+    new_method\n"
            "+    another\n"
            "     existing\n"
        )
        hunks = parse_patch_hunks(patch)
        assert len(hunks) == 2
        assert hunks[0].old_start == 1
        assert hunks[1].old_start == 20
        assert hunks[1].new_count == 7

    def test_empty_patch(self):
        assert parse_patch_hunks("") == []
        assert parse_patch_hunks(None) == []

    def test_no_hunk_headers(self):
        patch = "just some text without hunk headers"
        assert parse_patch_hunks(patch) == []

    def test_single_line_hunk(self):
        """@@ -5 +5 @@ means count defaults to 1."""
        patch = "@@ -5 +5 @@\n+new\n"
        hunks = parse_patch_hunks(patch)
        assert len(hunks) == 1
        assert hunks[0].old_count == 1
        assert hunks[0].new_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_diff_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create the base module and diff parser**

```python
# app/git/__init__.py
"""Git platform integration for webhook handling and diff fetching."""
from __future__ import annotations

from app.git.base import GitPlatformClient


def create_platform_client(platform: str) -> GitPlatformClient:
    """Factory: return the right GitPlatformClient for a platform name."""
    if platform == "github":
        from app.git.github import GitHubPlatformClient
        return GitHubPlatformClient()
    elif platform == "gitlab":
        from app.git.gitlab import GitLabPlatformClient
        return GitLabPlatformClient()
    elif platform == "bitbucket":
        from app.git.bitbucket import BitbucketPlatformClient
        return BitbucketPlatformClient()
    elif platform == "gitea":
        from app.git.gitea import GiteaPlatformClient
        return GiteaPlatformClient()
    else:
        raise ValueError(f"Unknown platform: {platform}")


__all__ = ["GitPlatformClient", "create_platform_client"]
```

```python
# app/git/base.py
"""Abstract base class for Git platform webhook + diff integration."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.pr_analysis.models import PRDiff, PullRequestEvent


class GitPlatformClient(ABC):
    """Abstract client for Git platform interactions (webhooks + diffs)."""

    @abstractmethod
    def parse_webhook(self, headers: dict, body: bytes) -> PullRequestEvent | None:
        """Parse a raw webhook payload into a normalized PullRequestEvent.
        Returns None if the event is not a PR event we care about."""
        ...

    @abstractmethod
    def verify_webhook_signature(
        self, headers: dict, body: bytes, secret: str
    ) -> bool:
        """Verify the webhook signature for security."""
        ...

    @abstractmethod
    async def fetch_diff(
        self, repo_url: str, pr_number: int, token: str
    ) -> PRDiff:
        """Fetch the file-level diff for a PR via the platform API."""
        ...
```

```python
# app/git/diff_parser.py
"""Parse unified diff patch text into DiffHunk objects."""
from __future__ import annotations

import re

from app.pr_analysis.models import DiffHunk

_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE
)


def parse_patch_hunks(patch: str | None) -> list[DiffHunk]:
    """Extract hunk ranges from a unified diff patch string."""
    if not patch:
        return []
    hunks = []
    for m in _HUNK_RE.finditer(patch):
        hunks.append(
            DiffHunk(
                old_start=int(m.group(1)),
                old_count=int(m.group(2)) if m.group(2) else 1,
                new_start=int(m.group(3)),
                new_count=int(m.group(4)) if m.group(4) else 1,
            )
        )
    return hunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_diff_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/git/__init__.py app/git/base.py app/git/diff_parser.py tests/unit/test_diff_parser.py
git commit -m "feat(phase5a): add GitPlatformClient ABC and unified diff parser"
```

---

### Task 2: GitHub Platform Client

**Files:**
- Create: `app/git/github.py`
- Test: `tests/unit/test_webhook_parsing.py`
- Test: `tests/unit/test_webhook_signature.py`

- [ ] **Step 1: Write failing tests for GitHub webhook parsing**

```python
# tests/unit/test_webhook_parsing.py
"""Tests for per-platform webhook parsing."""
import json
import pytest

from app.git.github import GitHubPlatformClient
from app.pr_analysis.models import GitPlatform


class TestGitHubWebhookParsing:
    def setup_method(self):
        self.client = GitHubPlatformClient()

    def test_parse_pr_opened(self):
        payload = {
            "action": "opened",
            "pull_request": {
                "number": 42,
                "title": "Fix order processing",
                "body": "Fixes #123",
                "user": {"login": "alice"},
                "head": {"ref": "fix/order-bug", "sha": "abc123def456"},
                "base": {"ref": "main"},
                "html_url": "https://github.com/org/repo/pull/42",
                "created_at": "2026-03-13T10:00:00Z",
            },
            "repository": {
                "html_url": "https://github.com/org/repo",
            },
        }
        headers = {"x-github-event": "pull_request"}
        body = json.dumps(payload).encode()

        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.platform == GitPlatform.GITHUB
        assert event.pr_number == 42
        assert event.pr_title == "Fix order processing"
        assert event.author == "alice"
        assert event.source_branch == "fix/order-bug"
        assert event.target_branch == "main"
        assert event.action == "opened"
        assert event.commit_sha == "abc123def456"

    def test_parse_pr_synchronize(self):
        """synchronize = new commits pushed to PR."""
        payload = {
            "action": "synchronize",
            "pull_request": {
                "number": 42,
                "title": "Fix order processing",
                "body": "",
                "user": {"login": "alice"},
                "head": {"ref": "fix/order-bug", "sha": "newsha789"},
                "base": {"ref": "main"},
                "html_url": "https://github.com/org/repo/pull/42",
                "created_at": "2026-03-13T10:00:00Z",
            },
            "repository": {"html_url": "https://github.com/org/repo"},
        }
        headers = {"x-github-event": "pull_request"}
        body = json.dumps(payload).encode()

        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.action == "updated"
        assert event.commit_sha == "newsha789"

    def test_ignore_non_pr_event(self):
        headers = {"x-github-event": "push"}
        body = b'{"ref": "refs/heads/main"}'
        assert self.client.parse_webhook(headers, body) is None

    def test_ignore_irrelevant_pr_action(self):
        payload = {
            "action": "labeled",
            "pull_request": {"number": 1},
            "repository": {"html_url": "https://github.com/org/repo"},
        }
        headers = {"x-github-event": "pull_request"}
        body = json.dumps(payload).encode()
        assert self.client.parse_webhook(headers, body) is None

    def test_parse_pr_closed_merged(self):
        payload = {
            "action": "closed",
            "pull_request": {
                "number": 42,
                "title": "Feature",
                "body": "",
                "merged": True,
                "user": {"login": "bob"},
                "head": {"ref": "feature", "sha": "sha1"},
                "base": {"ref": "main"},
                "html_url": "https://github.com/org/repo/pull/42",
                "created_at": "2026-03-13T10:00:00Z",
            },
            "repository": {"html_url": "https://github.com/org/repo"},
        }
        headers = {"x-github-event": "pull_request"}
        body = json.dumps(payload).encode()

        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.action == "merged"
```

- [ ] **Step 2: Write failing tests for GitHub signature verification**

```python
# tests/unit/test_webhook_signature.py
"""Tests for webhook signature verification."""
import hashlib
import hmac
import json
import pytest

from app.git.github import GitHubPlatformClient


class TestGitHubSignature:
    def setup_method(self):
        self.client = GitHubPlatformClient()
        self.secret = "test-webhook-secret"

    def test_valid_signature(self):
        body = b'{"test": "payload"}'
        sig = "sha256=" + hmac.new(
            self.secret.encode(), body, hashlib.sha256
        ).hexdigest()
        headers = {"x-hub-signature-256": sig}
        assert self.client.verify_webhook_signature(headers, body, self.secret) is True

    def test_invalid_signature(self):
        body = b'{"test": "payload"}'
        headers = {"x-hub-signature-256": "sha256=invalid"}
        assert self.client.verify_webhook_signature(headers, body, self.secret) is False

    def test_missing_signature_header(self):
        body = b'{"test": "payload"}'
        assert self.client.verify_webhook_signature({}, body, self.secret) is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhook_parsing.py::TestGitHubWebhookParsing tests/unit/test_webhook_signature.py::TestGitHubSignature -v`
Expected: FAIL

- [ ] **Step 4: Implement GitHub platform client**

```python
# app/git/github.py
"""GitHub webhook parsing, signature verification, and diff fetching."""
from __future__ import annotations

import hashlib
import hmac
import json

import httpx

from app.git.base import GitPlatformClient
from app.git.diff_parser import parse_patch_hunks
from app.pr_analysis.models import (
    FileDiff,
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)

_RELEVANT_ACTIONS = {"opened", "synchronize", "closed", "reopened"}


class GitHubPlatformClient(GitPlatformClient):
    def parse_webhook(
        self, headers: dict, body: bytes
    ) -> PullRequestEvent | None:
        event_type = headers.get("x-github-event", "")
        if event_type != "pull_request":
            return None

        payload = json.loads(body)
        action = payload.get("action", "")
        if action not in _RELEVANT_ACTIONS:
            return None

        pr = payload["pull_request"]

        # Normalize action
        if action == "synchronize":
            normalized_action = "updated"
        elif action == "closed" and pr.get("merged"):
            normalized_action = "merged"
        else:
            normalized_action = action

        return PullRequestEvent(
            platform=GitPlatform.GITHUB,
            repo_url=payload["repository"]["html_url"],
            pr_number=pr["number"],
            pr_title=pr["title"],
            pr_description=pr.get("body") or "",
            author=pr["user"]["login"],
            source_branch=pr["head"]["ref"],
            target_branch=pr["base"]["ref"],
            action=normalized_action,
            commit_sha=pr["head"]["sha"],
            created_at=pr.get("created_at", ""),
            raw_payload=payload,
        )

    def verify_webhook_signature(
        self, headers: dict, body: bytes, secret: str
    ) -> bool:
        sig_header = headers.get("x-hub-signature-256", "")
        if not sig_header.startswith("sha256="):
            return False
        expected = hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig_header[7:], expected)

    async def fetch_diff(
        self, repo_url: str, pr_number: int, token: str
    ) -> PRDiff:
        # Extract owner/repo from URL: https://github.com/owner/repo
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]

        api_base = "https://api.github.com"
        # Support GitHub Enterprise: if not github.com, use /api/v3
        if "github.com" not in repo_url:
            base = "/".join(parts[:3])
            api_base = f"{base}/api/v3"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }

        files: list[FileDiff] = []
        page = 1
        total_add = 0
        total_del = 0

        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{api_base}/repos/{owner}/{repo}/pulls/{pr_number}/files",
                    headers=headers,
                    params={"per_page": 100, "page": page},
                    timeout=30,
                )
                resp.raise_for_status()
                items = resp.json()
                if not items:
                    break

                for f in items:
                    status = f["status"]  # added, modified, removed, renamed
                    if status == "removed":
                        status = "deleted"
                    hunks = parse_patch_hunks(f.get("patch"))
                    files.append(
                        FileDiff(
                            path=f["filename"],
                            status=status,
                            old_path=f.get("previous_filename"),
                            additions=f.get("additions", 0),
                            deletions=f.get("deletions", 0),
                            hunks=hunks,
                        )
                    )
                    total_add += f.get("additions", 0)
                    total_del += f.get("deletions", 0)

                if len(items) < 100:
                    break
                page += 1

        return PRDiff(
            files=files,
            total_additions=total_add,
            total_deletions=total_del,
            total_files_changed=len(files),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhook_parsing.py::TestGitHubWebhookParsing tests/unit/test_webhook_signature.py::TestGitHubSignature -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend
git add app/git/github.py tests/unit/test_webhook_parsing.py tests/unit/test_webhook_signature.py
git commit -m "feat(phase5a): implement GitHub webhook parsing + signature verification"
```

---

### Task 3: GitLab Platform Client

**Files:**
- Create: `app/git/gitlab.py`
- Test: `tests/unit/test_webhook_parsing.py` (append)
- Test: `tests/unit/test_webhook_signature.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_webhook_parsing.py`:

```python
from app.git.gitlab import GitLabPlatformClient


class TestGitLabWebhookParsing:
    def setup_method(self):
        self.client = GitLabPlatformClient()

    def test_parse_mr_opened(self):
        payload = {
            "object_kind": "merge_request",
            "object_attributes": {
                "iid": 15,
                "title": "Add feature",
                "description": "New feature desc",
                "action": "open",
                "source_branch": "feature/new",
                "target_branch": "main",
                "last_commit": {"id": "gitlab_sha_123"},
                "url": "https://gitlab.com/org/repo/-/merge_requests/15",
                "created_at": "2026-03-13 10:00:00 UTC",
            },
            "user": {"username": "carol"},
            "project": {"web_url": "https://gitlab.com/org/repo"},
        }
        headers = {"x-gitlab-event": "Merge Request Hook"}
        body = json.dumps(payload).encode()

        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.platform == GitPlatform.GITLAB
        assert event.pr_number == 15
        assert event.action == "opened"
        assert event.author == "carol"

    def test_parse_mr_update(self):
        payload = {
            "object_kind": "merge_request",
            "object_attributes": {
                "iid": 15,
                "title": "Add feature",
                "description": "",
                "action": "update",
                "source_branch": "feature/new",
                "target_branch": "main",
                "last_commit": {"id": "new_sha"},
                "url": "https://gitlab.com/org/repo/-/merge_requests/15",
                "created_at": "2026-03-13 10:00:00 UTC",
            },
            "user": {"username": "carol"},
            "project": {"web_url": "https://gitlab.com/org/repo"},
        }
        headers = {"x-gitlab-event": "Merge Request Hook"}
        body = json.dumps(payload).encode()

        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.action == "updated"

    def test_ignore_non_mr_event(self):
        headers = {"x-gitlab-event": "Push Hook"}
        body = b'{"ref": "refs/heads/main"}'
        assert self.client.parse_webhook(headers, body) is None
```

Append to `tests/unit/test_webhook_signature.py`:

```python
from app.git.gitlab import GitLabPlatformClient


class TestGitLabSignature:
    def setup_method(self):
        self.client = GitLabPlatformClient()

    def test_valid_token(self):
        secret = "my-gitlab-token"
        headers = {"x-gitlab-token": secret}
        assert self.client.verify_webhook_signature(headers, b"body", secret) is True

    def test_invalid_token(self):
        headers = {"x-gitlab-token": "wrong-token"}
        assert self.client.verify_webhook_signature(headers, b"body", "correct") is False

    def test_missing_token(self):
        assert self.client.verify_webhook_signature({}, b"body", "secret") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhook_parsing.py::TestGitLabWebhookParsing tests/unit/test_webhook_signature.py::TestGitLabSignature -v`
Expected: FAIL

- [ ] **Step 3: Implement GitLab platform client**

```python
# app/git/gitlab.py
"""GitLab webhook parsing, signature verification, and diff fetching."""
from __future__ import annotations

import json
import re

import httpx

from app.git.base import GitPlatformClient
from app.git.diff_parser import parse_patch_hunks
from app.pr_analysis.models import (
    FileDiff,
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)

_RELEVANT_ACTIONS = {"open", "update", "close", "reopen", "merge"}


class GitLabPlatformClient(GitPlatformClient):
    def parse_webhook(
        self, headers: dict, body: bytes
    ) -> PullRequestEvent | None:
        event_type = headers.get("x-gitlab-event", "")
        if event_type != "Merge Request Hook":
            return None

        payload = json.loads(body)
        attrs = payload.get("object_attributes", {})
        action = attrs.get("action", "")
        if action not in _RELEVANT_ACTIONS:
            return None

        # Normalize action names
        action_map = {"open": "opened", "update": "updated", "close": "closed", "reopen": "opened", "merge": "merged"}
        normalized = action_map.get(action, action)

        return PullRequestEvent(
            platform=GitPlatform.GITLAB,
            repo_url=payload["project"]["web_url"],
            pr_number=attrs["iid"],
            pr_title=attrs["title"],
            pr_description=attrs.get("description") or "",
            author=payload["user"]["username"],
            source_branch=attrs["source_branch"],
            target_branch=attrs["target_branch"],
            action=normalized,
            commit_sha=attrs["last_commit"]["id"],
            created_at=attrs.get("created_at", ""),
            raw_payload=payload,
        )

    def verify_webhook_signature(
        self, headers: dict, body: bytes, secret: str
    ) -> bool:
        # GitLab uses a simple shared secret token in X-Gitlab-Token
        token = headers.get("x-gitlab-token", "")
        if not token:
            return False
        return token == secret

    async def fetch_diff(
        self, repo_url: str, pr_number: int, token: str
    ) -> PRDiff:
        # Extract project path from URL: https://gitlab.com/org/repo
        # GitLab API uses URL-encoded project path
        parts = repo_url.rstrip("/").split("/")
        # Find base URL and project path
        # For https://gitlab.com/org/repo → base=https://gitlab.com, path=org/repo
        base_url = "/".join(parts[:3])
        project_path = "/".join(parts[3:])
        encoded_path = project_path.replace("/", "%2F")

        headers_dict = {"PRIVATE-TOKEN": token}

        files: list[FileDiff] = []
        total_add = 0
        total_del = 0

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base_url}/api/v4/projects/{encoded_path}/merge_requests/{pr_number}/changes",
                headers=headers_dict,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            for change in data.get("changes", []):
                diff_text = change.get("diff", "")
                hunks = parse_patch_hunks(diff_text)

                if change.get("new_file"):
                    status = "added"
                elif change.get("deleted_file"):
                    status = "deleted"
                elif change.get("renamed_file"):
                    status = "renamed"
                else:
                    status = "modified"

                adds = sum(1 for line in diff_text.split("\n") if line.startswith("+") and not line.startswith("+++"))
                dels = sum(1 for line in diff_text.split("\n") if line.startswith("-") and not line.startswith("---"))

                files.append(
                    FileDiff(
                        path=change["new_path"],
                        status=status,
                        old_path=change.get("old_path") if status == "renamed" else None,
                        additions=adds,
                        deletions=dels,
                        hunks=hunks,
                    )
                )
                total_add += adds
                total_del += dels

        return PRDiff(
            files=files,
            total_additions=total_add,
            total_deletions=total_del,
            total_files_changed=len(files),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhook_parsing.py::TestGitLabWebhookParsing tests/unit/test_webhook_signature.py::TestGitLabSignature -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/git/gitlab.py tests/unit/test_webhook_parsing.py tests/unit/test_webhook_signature.py
git commit -m "feat(phase5a): implement GitLab webhook parsing + diff fetching"
```

---

### Task 4: Bitbucket Platform Client

**Files:**
- Create: `app/git/bitbucket.py`
- Test: `tests/unit/test_webhook_parsing.py` (append)
- Test: `tests/unit/test_webhook_signature.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_webhook_parsing.py`:

```python
from app.git.bitbucket import BitbucketPlatformClient


class TestBitbucketWebhookParsing:
    def setup_method(self):
        self.client = BitbucketPlatformClient()

    def test_parse_pr_created(self):
        payload = {
            "pullrequest": {
                "id": 7,
                "title": "Bitbucket PR",
                "description": "desc",
                "author": {"nickname": "dave"},
                "source": {"branch": {"name": "feature/bb"}, "commit": {"hash": "bb_sha"}},
                "destination": {"branch": {"name": "main"}},
                "links": {"html": {"href": "https://bitbucket.org/org/repo/pull-requests/7"}},
                "created_on": "2026-03-13T10:00:00Z",
            },
            "repository": {
                "links": {"html": {"href": "https://bitbucket.org/org/repo"}},
                "full_name": "org/repo",
            },
        }
        headers = {"x-event-key": "pullrequest:created"}
        body = json.dumps(payload).encode()

        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.platform == GitPlatform.BITBUCKET
        assert event.pr_number == 7
        assert event.action == "opened"

    def test_parse_pr_updated(self):
        payload = {
            "pullrequest": {
                "id": 7, "title": "BB PR", "description": "",
                "author": {"nickname": "dave"},
                "source": {"branch": {"name": "feat"}, "commit": {"hash": "newsha"}},
                "destination": {"branch": {"name": "main"}},
                "links": {"html": {"href": "https://bitbucket.org/org/repo/pull-requests/7"}},
                "created_on": "2026-03-13T10:00:00Z",
            },
            "repository": {
                "links": {"html": {"href": "https://bitbucket.org/org/repo"}},
                "full_name": "org/repo",
            },
        }
        headers = {"x-event-key": "pullrequest:updated"}
        body = json.dumps(payload).encode()

        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.action == "updated"

    def test_ignore_non_pr_event(self):
        headers = {"x-event-key": "repo:push"}
        body = b'{}'
        assert self.client.parse_webhook(headers, body) is None
```

Append to `tests/unit/test_webhook_signature.py`:

```python
from app.git.bitbucket import BitbucketPlatformClient


class TestBitbucketSignature:
    def setup_method(self):
        self.client = BitbucketPlatformClient()
        self.secret = "bb-secret"

    def test_valid_signature(self):
        body = b'{"test": "data"}'
        sig = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {"x-hub-signature": f"sha256={sig}"}
        assert self.client.verify_webhook_signature(headers, body, self.secret) is True

    def test_invalid_signature(self):
        headers = {"x-hub-signature": "sha256=bad"}
        assert self.client.verify_webhook_signature(headers, b"data", self.secret) is False

    def test_missing_header(self):
        assert self.client.verify_webhook_signature({}, b"data", self.secret) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhook_parsing.py::TestBitbucketWebhookParsing tests/unit/test_webhook_signature.py::TestBitbucketSignature -v`
Expected: FAIL

- [ ] **Step 3: Implement Bitbucket platform client**

```python
# app/git/bitbucket.py
"""Bitbucket webhook parsing, signature verification, and diff fetching."""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json

import httpx

from app.git.base import GitPlatformClient
from app.git.diff_parser import parse_patch_hunks
from app.pr_analysis.models import (
    FileDiff,
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)

_EVENT_MAP = {
    "pullrequest:created": "opened",
    "pullrequest:updated": "updated",
    "pullrequest:fulfilled": "merged",
    "pullrequest:rejected": "closed",
}


class BitbucketPlatformClient(GitPlatformClient):
    def parse_webhook(
        self, headers: dict, body: bytes
    ) -> PullRequestEvent | None:
        event_key = headers.get("x-event-key", "")
        if event_key not in _EVENT_MAP:
            return None

        payload = json.loads(body)
        pr = payload.get("pullrequest", {})
        if not pr:
            return None

        return PullRequestEvent(
            platform=GitPlatform.BITBUCKET,
            repo_url=payload["repository"]["links"]["html"]["href"],
            pr_number=pr["id"],
            pr_title=pr["title"],
            pr_description=pr.get("description") or "",
            author=pr["author"]["nickname"],
            source_branch=pr["source"]["branch"]["name"],
            target_branch=pr["destination"]["branch"]["name"],
            action=_EVENT_MAP[event_key],
            commit_sha=pr["source"]["commit"]["hash"],
            created_at=pr.get("created_on", ""),
            raw_payload=payload,
        )

    def verify_webhook_signature(
        self, headers: dict, body: bytes, secret: str
    ) -> bool:
        sig_header = headers.get("x-hub-signature", "")
        if not sig_header.startswith("sha256="):
            return False
        expected = hmac_mod.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac_mod.compare_digest(sig_header[7:], expected)

    async def fetch_diff(
        self, repo_url: str, pr_number: int, token: str
    ) -> PRDiff:
        # Extract workspace/repo from URL: https://bitbucket.org/workspace/repo
        parts = repo_url.rstrip("/").split("/")
        workspace, repo = parts[-2], parts[-1]

        headers = {"Authorization": f"Bearer {token}"}
        files: list[FileDiff] = []
        total_add = 0
        total_del = 0

        async with httpx.AsyncClient() as client:
            # Get diffstat for file-level info
            url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo}/pullrequests/{pr_number}/diffstat"
            while url:
                resp = await client.get(url, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                for entry in data.get("values", []):
                    status_map = {"added": "added", "modified": "modified", "removed": "deleted", "renamed": "renamed"}
                    status = status_map.get(entry.get("status", "modified"), "modified")

                    files.append(
                        FileDiff(
                            path=entry.get("new", {}).get("path", "") or entry.get("old", {}).get("path", ""),
                            status=status,
                            old_path=entry.get("old", {}).get("path") if status == "renamed" else None,
                            additions=entry.get("lines_added", 0),
                            deletions=entry.get("lines_removed", 0),
                            hunks=[],  # Bitbucket diffstat doesn't include hunks
                        )
                    )
                    total_add += entry.get("lines_added", 0)
                    total_del += entry.get("lines_removed", 0)

                url = data.get("next")

        return PRDiff(
            files=files,
            total_additions=total_add,
            total_deletions=total_del,
            total_files_changed=len(files),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhook_parsing.py::TestBitbucketWebhookParsing tests/unit/test_webhook_signature.py::TestBitbucketSignature -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/git/bitbucket.py tests/unit/test_webhook_parsing.py tests/unit/test_webhook_signature.py
git commit -m "feat(phase5a): implement Bitbucket webhook parsing + diff fetching"
```

---

### Task 5: Gitea Platform Client

**Files:**
- Create: `app/git/gitea.py`
- Test: `tests/unit/test_webhook_parsing.py` (append)
- Test: `tests/unit/test_webhook_signature.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_webhook_parsing.py`:

```python
from app.git.gitea import GiteaPlatformClient


class TestGiteaWebhookParsing:
    def setup_method(self):
        self.client = GiteaPlatformClient()

    def test_parse_pr_opened(self):
        payload = {
            "action": "opened",
            "pull_request": {
                "number": 3,
                "title": "Gitea PR",
                "body": "From Gitea",
                "user": {"login": "eve"},
                "head": {"ref": "feature/gitea", "sha": "gitea_sha"},
                "base": {"ref": "main"},
                "html_url": "https://gitea.local/org/repo/pulls/3",
                "created_at": "2026-03-13T10:00:00Z",
            },
            "repository": {
                "html_url": "https://gitea.local/org/repo",
            },
        }
        headers = {"x-gitea-event": "pull_request"}
        body = json.dumps(payload).encode()

        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.platform == GitPlatform.GITEA
        assert event.pr_number == 3
        assert event.author == "eve"

    def test_parse_pr_synchronized(self):
        payload = {
            "action": "synchronized",
            "pull_request": {
                "number": 3, "title": "Gitea PR", "body": "",
                "user": {"login": "eve"},
                "head": {"ref": "feature/gitea", "sha": "new_sha"},
                "base": {"ref": "main"},
                "html_url": "https://gitea.local/org/repo/pulls/3",
                "created_at": "2026-03-13T10:00:00Z",
            },
            "repository": {"html_url": "https://gitea.local/org/repo"},
        }
        headers = {"x-gitea-event": "pull_request"}
        body = json.dumps(payload).encode()

        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.action == "updated"

    def test_ignore_non_pr_event(self):
        headers = {"x-gitea-event": "push"}
        body = b'{}'
        assert self.client.parse_webhook(headers, body) is None
```

Append to `tests/unit/test_webhook_signature.py`:

```python
from app.git.gitea import GiteaPlatformClient


class TestGiteaSignature:
    def setup_method(self):
        self.client = GiteaPlatformClient()
        self.secret = "gitea-secret"

    def test_valid_signature(self):
        body = b'{"test": "data"}'
        sig = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {"x-gitea-signature": sig}
        assert self.client.verify_webhook_signature(headers, body, self.secret) is True

    def test_invalid_signature(self):
        headers = {"x-gitea-signature": "badsig"}
        assert self.client.verify_webhook_signature(headers, b"data", self.secret) is False

    def test_missing_header(self):
        assert self.client.verify_webhook_signature({}, b"data", self.secret) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhook_parsing.py::TestGiteaWebhookParsing tests/unit/test_webhook_signature.py::TestGiteaSignature -v`
Expected: FAIL

- [ ] **Step 3: Implement Gitea platform client**

```python
# app/git/gitea.py
"""Gitea webhook parsing, signature verification, and diff fetching.

Gitea's webhook format is very similar to GitHub's — same field names
and structure for pull_request events. Signature uses X-Gitea-Signature
(raw HMAC-SHA256 hex, no 'sha256=' prefix).
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json

import httpx

from app.git.base import GitPlatformClient
from app.git.diff_parser import parse_patch_hunks
from app.pr_analysis.models import (
    FileDiff,
    GitPlatform,
    PRDiff,
    PullRequestEvent,
)

_RELEVANT_ACTIONS = {"opened", "synchronized", "closed", "reopened"}


class GiteaPlatformClient(GitPlatformClient):
    def parse_webhook(
        self, headers: dict, body: bytes
    ) -> PullRequestEvent | None:
        event_type = headers.get("x-gitea-event", "")
        if event_type != "pull_request":
            return None

        payload = json.loads(body)
        action = payload.get("action", "")
        if action not in _RELEVANT_ACTIONS:
            return None

        pr = payload["pull_request"]

        if action == "synchronized":
            normalized = "updated"
        elif action == "closed" and pr.get("merged"):
            normalized = "merged"
        else:
            normalized = action

        return PullRequestEvent(
            platform=GitPlatform.GITEA,
            repo_url=payload["repository"]["html_url"],
            pr_number=pr["number"],
            pr_title=pr["title"],
            pr_description=pr.get("body") or "",
            author=pr["user"]["login"],
            source_branch=pr["head"]["ref"],
            target_branch=pr["base"]["ref"],
            action=normalized,
            commit_sha=pr["head"]["sha"],
            created_at=pr.get("created_at", ""),
            raw_payload=payload,
        )

    def verify_webhook_signature(
        self, headers: dict, body: bytes, secret: str
    ) -> bool:
        sig = headers.get("x-gitea-signature", "")
        if not sig:
            return False
        expected = hmac_mod.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac_mod.compare_digest(sig, expected)

    async def fetch_diff(
        self, repo_url: str, pr_number: int, token: str
    ) -> PRDiff:
        # Gitea API: /api/v1/repos/{owner}/{repo}/pulls/{index}/files
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
        base_url = "/".join(parts[:3])

        headers = {"Authorization": f"token {token}"}
        files: list[FileDiff] = []
        total_add = 0
        total_del = 0

        async with httpx.AsyncClient() as client:
            page = 1
            while True:
                resp = await client.get(
                    f"{base_url}/api/v1/repos/{owner}/{repo}/pulls/{pr_number}/files",
                    headers=headers,
                    params={"limit": 50, "page": page},
                    timeout=30,
                )
                resp.raise_for_status()
                items = resp.json()
                if not items:
                    break

                for f in items:
                    status = f.get("status", "modified")
                    if status == "removed":
                        status = "deleted"
                    hunks = parse_patch_hunks(f.get("patch"))
                    files.append(
                        FileDiff(
                            path=f["filename"],
                            status=status,
                            old_path=f.get("previous_filename"),
                            additions=f.get("additions", 0),
                            deletions=f.get("deletions", 0),
                            hunks=hunks,
                        )
                    )
                    total_add += f.get("additions", 0)
                    total_del += f.get("deletions", 0)

                if len(items) < 50:
                    break
                page += 1

        return PRDiff(
            files=files,
            total_additions=total_add,
            total_deletions=total_del,
            total_files_changed=len(files),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhook_parsing.py::TestGiteaWebhookParsing tests/unit/test_webhook_signature.py::TestGiteaSignature -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/git/gitea.py tests/unit/test_webhook_parsing.py tests/unit/test_webhook_signature.py
git commit -m "feat(phase5a): implement Gitea webhook parsing + diff fetching"
```

---

### Task 6: Factory Function + Integration Tests

**Files:**
- Modify: `app/git/__init__.py` (already created in Task 1)
- Test: `tests/unit/test_webhook_parsing.py` (append)

- [ ] **Step 1: Write failing test for factory**

Append to `tests/unit/test_webhook_parsing.py`:

```python
from app.git import create_platform_client
from app.git.github import GitHubPlatformClient
from app.git.gitlab import GitLabPlatformClient
from app.git.bitbucket import BitbucketPlatformClient
from app.git.gitea import GiteaPlatformClient


class TestCreatePlatformClient:
    def test_github(self):
        assert isinstance(create_platform_client("github"), GitHubPlatformClient)

    def test_gitlab(self):
        assert isinstance(create_platform_client("gitlab"), GitLabPlatformClient)

    def test_bitbucket(self):
        assert isinstance(create_platform_client("bitbucket"), BitbucketPlatformClient)

    def test_gitea(self):
        assert isinstance(create_platform_client("gitea"), GiteaPlatformClient)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown platform"):
            create_platform_client("svn")
```

- [ ] **Step 2: Run test to verify it passes** (factory was created in Task 1)

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_webhook_parsing.py::TestCreatePlatformClient -v`
Expected: PASS

- [ ] **Step 3: Run all M2 tests together**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_diff_parser.py tests/unit/test_webhook_parsing.py tests/unit/test_webhook_signature.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend
git add tests/unit/test_webhook_parsing.py
git commit -m "feat(phase5a): add platform client factory tests"
```

---

## Success Criteria

- [ ] All 4 platform clients parse webhooks into normalized `PullRequestEvent`
- [ ] All 4 platform clients verify webhook signatures correctly
- [ ] All 4 platform clients have `fetch_diff` implementation (GitHub, GitLab, Gitea use patch hunks; Bitbucket uses diffstat)
- [ ] Factory function returns the correct client for each platform
- [ ] Unified diff parser correctly extracts hunk ranges
- [ ] All tests pass: `uv run pytest tests/unit/test_diff_parser.py tests/unit/test_webhook_parsing.py tests/unit/test_webhook_signature.py -v`
