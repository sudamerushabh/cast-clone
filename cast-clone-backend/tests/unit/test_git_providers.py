"""Tests for Git provider factory and GitHub adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.git_providers import create_provider
from app.services.git_providers.base import GitProvider
from app.services.git_providers.github import GitHubProvider
from app.services.git_providers.gitlab import GitLabProvider
from app.services.git_providers.gitea import GiteaProvider
from app.services.git_providers.bitbucket import BitbucketProvider


class TestCreateProvider:
    def test_github(self):
        p = create_provider("github", "https://github.com", "tok")
        assert isinstance(p, GitHubProvider)

    def test_gitlab(self):
        p = create_provider("gitlab", "https://gitlab.com", "tok")
        assert isinstance(p, GitLabProvider)

    def test_gitea(self):
        p = create_provider("gitea", "https://gitea.example.com", "tok")
        assert isinstance(p, GiteaProvider)

    def test_bitbucket(self):
        p = create_provider("bitbucket", "https://bitbucket.org", "tok")
        assert isinstance(p, BitbucketProvider)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("svn", "https://example.com", "tok")

    def test_base_url_trailing_slash_stripped(self):
        p = create_provider("github", "https://github.com/", "tok")
        assert p.base_url == "https://github.com"


class TestGitHubProvider:
    @pytest.fixture
    def provider(self) -> GitHubProvider:
        return GitHubProvider("https://github.com", "ghp_test123")

    def test_api_base_github_com(self, provider: GitHubProvider):
        assert provider._api_base == "https://api.github.com"

    def test_api_base_self_hosted(self):
        p = GitHubProvider("https://ghe.corp.com", "tok")
        assert p._api_base == "https://ghe.corp.com/api/v3"

    def test_headers(self, provider: GitHubProvider):
        h = provider._headers
        assert h["Authorization"] == "Bearer ghp_test123"
        assert "application/vnd.github+json" in h["Accept"]

    @pytest.mark.asyncio
    async def test_validate(self, provider: GitHubProvider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "login": "octocat",
            "name": "The Octocat",
            "avatar_url": "https://avatars.githubusercontent.com/u/1",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            user = await provider.validate()
            assert user.username == "octocat"
            assert user.display_name == "The Octocat"

    @pytest.mark.asyncio
    async def test_list_repos(self, provider: GitHubProvider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "full_name": "octocat/hello-world",
                "clone_url": "https://github.com/octocat/hello-world.git",
                "default_branch": "main",
                "description": "A test repo",
                "language": "Python",
                "private": False,
            }
        ]
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            repos, has_more = await provider.list_repos(page=1, per_page=30)
            assert len(repos) == 1
            assert repos[0].full_name == "octocat/hello-world"
            assert not has_more  # 1 < 30

    @pytest.mark.asyncio
    async def test_get_repo(self, provider: GitHubProvider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "full_name": "octocat/hello-world",
            "clone_url": "https://github.com/octocat/hello-world.git",
            "default_branch": "main",
            "description": "A test repo",
            "language": "Python",
            "private": True,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            repo = await provider.get_repo("octocat/hello-world")
            assert repo.full_name == "octocat/hello-world"
            assert repo.is_private is True

    @pytest.mark.asyncio
    async def test_list_branches(self, provider: GitHubProvider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"name": "main"},
            {"name": "develop"},
        ]
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            branches = await provider.list_branches("octocat/hello-world")
            assert branches == ["main", "develop"]
