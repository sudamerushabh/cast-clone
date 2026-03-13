"""Tests for webhook parsing across all git platform clients."""

from __future__ import annotations

import json

import pytest

from app.git import create_platform_client
from app.git.bitbucket import BitbucketPlatformClient
from app.git.gitea import GiteaPlatformClient
from app.git.github import GitHubPlatformClient
from app.git.gitlab import GitLabPlatformClient
from app.pr_analysis.models import GitPlatform


# ---------------------------------------------------------------------------
# Helpers to build minimal webhook payloads
# ---------------------------------------------------------------------------

def _github_payload(
    action: str = "opened", merged: bool = False
) -> dict:
    return {
        "action": action,
        "pull_request": {
            "number": 42,
            "title": "Add feature",
            "body": "Description",
            "user": {"login": "alice"},
            "head": {"ref": "feature-branch", "sha": "abc123"},
            "base": {"ref": "main"},
            "merged": merged,
            "created_at": "2025-01-01T00:00:00Z",
        },
        "repository": {"html_url": "https://github.com/owner/repo"},
    }


def _gitlab_payload(action: str = "open") -> dict:
    return {
        "object_attributes": {
            "iid": 7,
            "title": "MR title",
            "description": "MR desc",
            "action": action,
            "source_branch": "feat",
            "target_branch": "main",
            "last_commit": {"id": "def456"},
            "created_at": "2025-02-01T00:00:00Z",
        },
        "user": {"username": "bob"},
        "project": {"web_url": "https://gitlab.com/group/project"},
    }


def _bitbucket_payload() -> dict:
    return {
        "pullrequest": {
            "id": 99,
            "title": "BB PR",
            "description": "BB desc",
            "author": {"username": "charlie"},
            "source": {
                "branch": {"name": "fix"},
                "commit": {"hash": "aaa111"},
            },
            "destination": {
                "branch": {"name": "develop"},
            },
            "created_on": "2025-03-01T00:00:00Z",
        },
        "repository": {
            "links": {"html": {"href": "https://bitbucket.org/ws/repo"}},
        },
    }


def _gitea_payload(
    action: str = "opened", merged: bool = False
) -> dict:
    return {
        "action": action,
        "pull_request": {
            "number": 5,
            "title": "Gitea PR",
            "body": "Gitea desc",
            "user": {"login": "dave"},
            "head": {"ref": "patch", "sha": "bbb222"},
            "base": {"ref": "main"},
            "merged": merged,
            "created_at": "2025-04-01T00:00:00Z",
        },
        "repository": {"html_url": "https://gitea.example.com/org/repo"},
    }


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

class TestGitHubWebhookParsing:
    def setup_method(self) -> None:
        self.client = GitHubPlatformClient()

    def test_pr_opened(self) -> None:
        headers = {"x-github-event": "pull_request"}
        body = json.dumps(_github_payload("opened")).encode()
        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.platform == GitPlatform.github
        assert event.action == "opened"
        assert event.pr_number == 42
        assert event.author == "alice"

    def test_synchronize_normalized_to_updated(self) -> None:
        headers = {"x-github-event": "pull_request"}
        body = json.dumps(_github_payload("synchronize")).encode()
        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.action == "updated"

    def test_closed_and_merged(self) -> None:
        headers = {"x-github-event": "pull_request"}
        body = json.dumps(
            _github_payload("closed", merged=True)
        ).encode()
        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.action == "merged"

    def test_ignore_non_pr_event(self) -> None:
        headers = {"x-github-event": "push"}
        body = json.dumps({}).encode()
        assert self.client.parse_webhook(headers, body) is None

    def test_ignore_irrelevant_action(self) -> None:
        headers = {"x-github-event": "pull_request"}
        body = json.dumps(_github_payload("labeled")).encode()
        assert self.client.parse_webhook(headers, body) is None


# ---------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------

class TestGitLabWebhookParsing:
    def setup_method(self) -> None:
        self.client = GitLabPlatformClient()

    def test_mr_opened(self) -> None:
        headers = {"x-gitlab-event": "Merge Request Hook"}
        body = json.dumps(_gitlab_payload("open")).encode()
        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.platform == GitPlatform.gitlab
        assert event.action == "opened"
        assert event.pr_number == 7

    def test_update_normalized(self) -> None:
        headers = {"x-gitlab-event": "Merge Request Hook"}
        body = json.dumps(_gitlab_payload("update")).encode()
        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.action == "updated"

    def test_ignore_non_mr_event(self) -> None:
        headers = {"x-gitlab-event": "Push Hook"}
        body = json.dumps({}).encode()
        assert self.client.parse_webhook(headers, body) is None


# ---------------------------------------------------------------------------
# Bitbucket
# ---------------------------------------------------------------------------

class TestBitbucketWebhookParsing:
    def setup_method(self) -> None:
        self.client = BitbucketPlatformClient()

    def test_pr_created(self) -> None:
        headers = {"x-event-key": "pullrequest:created"}
        body = json.dumps(_bitbucket_payload()).encode()
        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.platform == GitPlatform.bitbucket
        assert event.action == "opened"
        assert event.pr_number == 99

    def test_pr_updated(self) -> None:
        headers = {"x-event-key": "pullrequest:updated"}
        body = json.dumps(_bitbucket_payload()).encode()
        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.action == "updated"

    def test_ignore_non_pr_event(self) -> None:
        headers = {"x-event-key": "repo:push"}
        body = json.dumps({}).encode()
        assert self.client.parse_webhook(headers, body) is None


# ---------------------------------------------------------------------------
# Gitea
# ---------------------------------------------------------------------------

class TestGiteaWebhookParsing:
    def setup_method(self) -> None:
        self.client = GiteaPlatformClient()

    def test_pr_opened(self) -> None:
        headers = {"x-gitea-event": "pull_request"}
        body = json.dumps(_gitea_payload("opened")).encode()
        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.platform == GitPlatform.gitea
        assert event.action == "opened"
        assert event.pr_number == 5

    def test_synchronized_normalized_to_updated(self) -> None:
        headers = {"x-gitea-event": "pull_request"}
        body = json.dumps(_gitea_payload("synchronized")).encode()
        event = self.client.parse_webhook(headers, body)
        assert event is not None
        assert event.action == "updated"

    def test_ignore_non_pr_event(self) -> None:
        headers = {"x-gitea-event": "push"}
        body = json.dumps({}).encode()
        assert self.client.parse_webhook(headers, body) is None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class TestFactory:
    @pytest.mark.parametrize(
        "platform,expected_type",
        [
            ("github", GitHubPlatformClient),
            ("gitlab", GitLabPlatformClient),
            ("bitbucket", BitbucketPlatformClient),
            ("gitea", GiteaPlatformClient),
        ],
    )
    def test_create_known_platform(
        self, platform: str, expected_type: type
    ) -> None:
        client = create_platform_client(platform)
        assert isinstance(client, expected_type)

    def test_unknown_platform_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown git platform"):
            create_platform_client("unknown")
