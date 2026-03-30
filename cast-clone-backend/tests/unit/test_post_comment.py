"""Tests for platform client post_comment implementations."""

from __future__ import annotations

import pytest
import httpx
import respx

from app.git.base import CommentResult
from app.git.github import GitHubPlatformClient
from app.git.gitlab import GitLabPlatformClient
from app.git.bitbucket import BitbucketPlatformClient
from app.git.gitea import GiteaPlatformClient


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
