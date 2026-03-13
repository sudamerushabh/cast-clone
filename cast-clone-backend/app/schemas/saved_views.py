"""Pydantic schemas for saved views."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SavedViewCreate(BaseModel):
    """Request to save the current graph state."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    state: dict[str, Any]


class SavedViewUpdate(BaseModel):
    """Request to update a saved view."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    state: dict[str, Any] | None = None


class SavedViewAuthor(BaseModel):
    """Embedded author info."""

    id: str
    username: str

    model_config = {"from_attributes": True}


class SavedViewResponse(BaseModel):
    """Saved view with author info."""

    id: str
    project_id: str
    name: str
    description: str | None
    author: SavedViewAuthor
    state: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SavedViewListItem(BaseModel):
    """Saved view summary for list (without full state)."""

    id: str
    project_id: str
    name: str
    description: str | None
    author: SavedViewAuthor
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
