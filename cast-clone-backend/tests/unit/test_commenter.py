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
