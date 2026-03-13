"""Tests for git clone/checkout/pull service."""

from __future__ import annotations

from app.services.clone import build_authenticated_url, strip_token_from_url


class TestUrlHelpers:
    def test_build_authenticated_url_github(self):
        url = build_authenticated_url(
            "https://github.com/owner/repo.git", "ghp_token123"
        )
        assert url == "https://ghp_token123@github.com/owner/repo.git"

    def test_build_authenticated_url_gitlab(self):
        url = build_authenticated_url(
            "https://gitlab.com/owner/repo.git", "glpat-xxx"
        )
        assert url == "https://glpat-xxx@gitlab.com/owner/repo.git"

    def test_strip_token_from_url(self):
        url = strip_token_from_url(
            "https://ghp_token123@github.com/owner/repo.git"
        )
        assert url == "https://github.com/owner/repo.git"

    def test_strip_token_no_token(self):
        url = strip_token_from_url("https://github.com/owner/repo.git")
        assert url == "https://github.com/owner/repo.git"
