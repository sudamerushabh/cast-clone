"""Abstract base class for Git provider adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GitUser:
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


@dataclass
class GitRepo:
    full_name: str
    clone_url: str
    default_branch: str
    description: str | None = None
    language: str | None = None
    is_private: bool = False


@dataclass
class WebhookCreateResult:
    """Result of registering a webhook on a remote git platform."""

    success: bool
    webhook_id: str | None = None
    error: str | None = None


class GitProvider(ABC):
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    @abstractmethod
    async def validate(self) -> GitUser: ...

    @abstractmethod
    async def list_repos(
        self, page: int = 1, per_page: int = 30, search: str | None = None
    ) -> tuple[list[GitRepo], bool]: ...

    @abstractmethod
    async def get_repo(self, full_name: str) -> GitRepo: ...

    @abstractmethod
    async def list_branches(self, full_name: str) -> list[str]: ...

    async def create_webhook(
        self, full_name: str, webhook_url: str, secret: str,
    ) -> WebhookCreateResult:
        """Register a webhook on the remote repository.

        Default implementation returns failure — subclasses override with
        platform-specific API calls.
        """
        return WebhookCreateResult(
            success=False, error="Webhook auto-registration not supported for this platform"
        )
