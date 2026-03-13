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
    project_id: str
    platform: str
    repo_url: str
    monitored_branches: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebhookUrlResponse(BaseModel):
    """Response with generated webhook URL and secret."""

    webhook_url: str
    webhook_secret: str
