"""Pydantic v2 schemas for Repository API endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RepositoryCreate(BaseModel):
    connector_id: str
    repo_full_name: str
    branches: list[str] = Field(min_length=1)
    auto_analyze: bool = False


class BranchAddRequest(BaseModel):
    branch: str = Field(min_length=1)
    auto_analyze: bool = False


class ProjectBranchResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    branch: str | None
    status: str
    last_analyzed_at: datetime | None = None
    node_count: int | None = None
    edge_count: int | None = None


class RepositoryResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    connector_id: str
    repo_full_name: str
    default_branch: str
    description: str | None = None
    language: str | None = None
    is_private: bool = False
    clone_status: str
    clone_error: str | None = None
    local_path: str | None = None
    last_synced_at: datetime | None = None
    created_at: datetime
    projects: list[ProjectBranchResponse] = Field(default_factory=list)


class RepositoryListResponse(BaseModel):
    repositories: list[RepositoryResponse]
    total: int


class CloneStatusResponse(BaseModel):
    clone_status: str
    clone_error: str | None = None


class SnapshotPoint(BaseModel):
    run_id: str
    analyzed_at: datetime
    commit_sha: str | None = None
    summary: dict = Field(default_factory=dict)


class EvolutionTimelineResponse(BaseModel):
    repo_id: str
    branch: str
    snapshots: list[SnapshotPoint]


class BranchCompareResponse(BaseModel):
    branch_a: str
    branch_b: str
    diff: dict = Field(default_factory=dict)
