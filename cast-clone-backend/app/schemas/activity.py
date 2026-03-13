"""Pydantic schemas for activity log."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ActivityAuthor(BaseModel):
    """Embedded user info for activity log."""

    id: str
    username: str

    model_config = {"from_attributes": True}


class ActivityLogResponse(BaseModel):
    """Single activity log entry."""

    id: str
    user: ActivityAuthor | None
    action: str
    resource_type: str | None
    resource_id: str | None
    details: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
