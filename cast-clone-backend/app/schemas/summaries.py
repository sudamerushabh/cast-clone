"""Request/response models for the AI summary endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class SummaryResponse(BaseModel):
    """Response from the summary endpoint."""

    fqn: str
    summary: str
    cached: bool
    model: str
    tokens_used: int | None = None
