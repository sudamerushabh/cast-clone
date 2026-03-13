"""Pydantic v2 schemas for Git configuration API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GitConfigCreate(BaseModel):
    """POST request body for creating a git configuration."""

    platform: Literal["github", "gitlab", "bitbucket", "gitea"]
    repo_url: str = Field(..., max_length=500)
    api_token: str = Field(..., min_length=1)
    monitored_branches: list[str] = Field(
        default_factory=lambda: ["main", "master", "develop"]
    )


class GitConfigUpdate(BaseModel):
    """PATCH request body for updating a git configuration."""

    platform: Literal["github", "gitlab", "bitbucket", "gitea"] | None = None
    repo_url: str | None = Field(default=None, max_length=500)
    api_token: str | None = Field(default=None, min_length=1)
    monitored_branches: list[str] | None = None


class GitConfigResponse(BaseModel):
    """Response schema for git configuration (excludes api_token)."""

    id: str
    repository_id: str
    platform: str
    repo_url: str
    monitored_branches: list[str] | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebhookUrlResponse(BaseModel):
    """Response with generated webhook URL and secret."""

    webhook_url: str
    webhook_secret: str


class EnableWebhooksRequest(BaseModel):
    """Simplified request to enable PR webhooks — derives platform/token from connector."""

    monitor_all_branches: bool = True
    monitored_branches: list[str] | None = None
    auto_register: bool = False


class EnableWebhooksResponse(BaseModel):
    """Response after enabling webhooks."""

    webhook_url: str
    webhook_secret: str
    platform: str
    monitored_branches: list[str] | None  # None = all branches
    is_active: bool
    auto_registered: bool = False
    auto_register_error: str | None = None


class AutoRegisterRequest(BaseModel):
    """Request to auto-register webhook on the git platform."""
    pass


class AutoRegisterResponse(BaseModel):
    """Response from auto-register attempt."""

    success: bool
    error: str | None = None
