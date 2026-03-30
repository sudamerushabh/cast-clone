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
        """Parse an incoming webhook payload into a PullRequestEvent.

        Returns None if the event is not a pull/merge request event or
        if the action is not relevant.
        """

    @abstractmethod
    def verify_webhook_signature(
        self, headers: dict, body: bytes, secret: str
    ) -> bool:
        """Verify the webhook payload signature using the shared secret.

        Returns False if the signature header is missing or invalid.
        """

    @abstractmethod
    async def fetch_diff(
        self, repo_url: str, pr_number: int, token: str
    ) -> PRDiff:
        """Fetch the diff for a pull/merge request from the platform API.

        Args:
            repo_url: The repository URL (e.g. https://github.com/owner/repo).
            pr_number: The pull/merge request number.
            token: Authentication token for the platform API.

        Returns:
            A PRDiff containing all file diffs.
        """

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
