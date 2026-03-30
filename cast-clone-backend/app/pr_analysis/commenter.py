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
