"""Response models for AI usage tracking endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UsageLogResponse(BaseModel):
    """Single AI usage log entry."""

    id: str
    project_id: str
    user_id: str | None
    source: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UsageBySourceItem(BaseModel):
    """Aggregated usage stats for a single source (chat, summary, etc.)."""

    source: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    count: int


class UsageByProjectItem(BaseModel):
    """Aggregated usage stats for a single project."""

    project_id: str
    project_name: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    count: int


class UsageSummaryResponse(BaseModel):
    """Aggregated AI usage summary for the admin dashboard."""

    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float
    by_source: list[UsageBySourceItem]
    by_project: list[UsageByProjectItem]
