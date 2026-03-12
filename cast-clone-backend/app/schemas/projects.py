"""Pydantic v2 schemas for Project CRUD API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    """POST /api/v1/projects request body."""

    name: str = Field(..., min_length=1, max_length=255)
    source_path: str = Field(..., min_length=1, max_length=1024)


class ProjectResponse(BaseModel):
    """Single project response."""

    id: str
    name: str
    source_path: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """GET /api/v1/projects response."""

    projects: list[ProjectResponse]
    total: int
