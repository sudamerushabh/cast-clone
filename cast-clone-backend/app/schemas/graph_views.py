"""Pydantic v2 schemas for Phase 2 graph view endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.graph import GraphEdgeResponse, GraphNodeResponse


class ModuleResponse(BaseModel):
    """A module node with aggregated metrics."""

    fqn: str
    name: str
    kind: str = "MODULE"
    language: str | None = None
    loc: int | None = None
    file_count: int | None = None
    class_count: int | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ModuleListResponse(BaseModel):
    """List of modules for a project."""

    modules: list[ModuleResponse]
    total: int


class ClassListResponse(BaseModel):
    """List of classes within a module."""

    classes: list[GraphNodeResponse]
    total: int
    parent_fqn: str


class MethodListResponse(BaseModel):
    """List of methods within a class."""

    methods: list[GraphNodeResponse]
    total: int
    parent_fqn: str


class AggregatedEdgeResponse(BaseModel):
    """An aggregated edge between two higher-level nodes."""

    source: str
    target: str
    weight: int


class AggregatedEdgeListResponse(BaseModel):
    """List of aggregated edges."""

    edges: list[AggregatedEdgeResponse]
    total: int
    level: str


class TransactionSummary(BaseModel):
    """Summary of a transaction for listing."""

    fqn: str
    name: str
    kind: str = "TRANSACTION"
    properties: dict[str, Any] = Field(default_factory=dict)


class TransactionListResponse(BaseModel):
    """List of transactions for a project."""

    transactions: list[TransactionSummary]
    total: int


class TransactionDetailResponse(BaseModel):
    """Full call graph for a single transaction."""

    fqn: str
    name: str
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class CodeViewerResponse(BaseModel):
    """Source code content for the code viewer."""

    content: str
    language: str
    start_line: int
    highlight_line: int | None = None
    total_lines: int
