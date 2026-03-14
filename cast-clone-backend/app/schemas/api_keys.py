"""Request/response models for API key management."""

from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    """Request body for creating a new API key."""

    name: str = Field(..., min_length=1, max_length=100)


class ApiKeyCreateResponse(BaseModel):
    """Response when creating a key — includes the raw key (shown once)."""

    id: str
    name: str
    raw_key: str
    created_at: datetime | str
    model_config = {"from_attributes": True}


class ApiKeyResponse(BaseModel):
    """Response for listing keys — no raw key exposed."""

    id: str
    name: str
    is_active: bool
    created_at: datetime | str
    last_used_at: datetime | str | None
    model_config = {"from_attributes": True}
