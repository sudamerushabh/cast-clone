"""Pydantic v2 schemas for Git Connector API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConnectorCreate(BaseModel):
    """POST /api/v1/connectors request body."""

    name: str = Field(..., min_length=1, max_length=255)
    provider: Literal["github", "gitlab", "gitea", "bitbucket"]
    base_url: str = Field(..., min_length=1, max_length=1024)
    token: str = Field(..., min_length=1)


class ConnectorUpdate(BaseModel):
    """PUT /api/v1/connectors/{id} request body."""

    name: str | None = Field(None, min_length=1, max_length=255)
    token: str | None = Field(None, min_length=1)


class ConnectorResponse(BaseModel):
    """Single connector response (no token exposed)."""

    id: str
    name: str
    provider: str
    base_url: str
    auth_method: str
    status: str
    remote_username: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectorListResponse(BaseModel):
    """GET /api/v1/connectors response."""

    connectors: list[ConnectorResponse]
    total: int


class ConnectorTestResponse(BaseModel):
    """POST /api/v1/connectors/{id}/test response."""

    status: str
    remote_username: str | None = None
    error: str | None = None


class RemoteRepoResponse(BaseModel):
    """Single remote repository."""

    full_name: str
    clone_url: str
    default_branch: str
    description: str | None = None
    language: str | None = None
    is_private: bool = False


class RemoteRepoListResponse(BaseModel):
    """GET /api/v1/connectors/{id}/repos response."""

    repos: list[RemoteRepoResponse]
    has_more: bool
    page: int
    per_page: int


class BranchListResponse(BaseModel):
    """GET /api/v1/connectors/{id}/repos/{owner}/{repo}/branches response."""

    branches: list[str]
    default_branch: str | None = None
