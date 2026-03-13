"""Abstract base class for git platform clients."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.pr_analysis.models import PRDiff, PullRequestEvent


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
