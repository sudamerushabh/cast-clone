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
