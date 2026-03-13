"""Pydantic v2 schemas for webhook API."""

from __future__ import annotations

from pydantic import BaseModel


class WebhookResponse(BaseModel):
    """Response returned after receiving a webhook event."""

    status: str
    message: str | None = None
    pr_analysis_id: str | None = None
