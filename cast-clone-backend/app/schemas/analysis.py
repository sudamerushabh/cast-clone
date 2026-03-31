"""Pydantic v2 schemas for Analysis API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AnalysisTriggerResponse(BaseModel):
    """POST /api/v1/projects/{id}/analyze response."""

    project_id: str
    run_id: str
    status: str
    message: str


class AnalysisStageStatus(BaseModel):
    """Status of a single pipeline stage."""

    name: str
    label: str
    status: str  # pending | running | completed | skipped
    description: str
    progress: int | None = None  # 0-100, only set for running stage


class AnalysisStatusResponse(BaseModel):
    """GET /api/v1/projects/{id}/status response."""

    project_id: str
    status: str
    current_stage: str | None = None
    stages: list[AnalysisStageStatus] = []
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AnalysisRunResponse(BaseModel):
    """Single analysis run detail."""

    id: str
    project_id: str
    status: str
    stage: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    node_count: int | None = None
    edge_count: int | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}
