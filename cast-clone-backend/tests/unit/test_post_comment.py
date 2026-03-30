"""Tests for platform client post_comment implementations."""

from __future__ import annotations

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
