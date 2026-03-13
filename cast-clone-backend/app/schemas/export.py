"""Pydantic schemas for export query parameters."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NodeExportParams(BaseModel):
    """Query parameters for node CSV export."""

    types: str | None = Field(
        default=None,
        description="Comma-separated node kinds to include (e.g., 'Class,Function')",
    )
    fields: str = Field(
        default="fqn,name,kind,language,loc,complexity",
        description="Comma-separated fields to include in export",
    )


class EdgeExportParams(BaseModel):
    """Query parameters for edge CSV export."""

    types: str | None = Field(
        default=None,
        description="Comma-separated edge types to include (e.g., 'CALLS,DEPENDS_ON')",
    )
    fields: str = Field(
        default="source,target,type,weight",
        description="Comma-separated fields to include in export",
    )


class GraphExportParams(BaseModel):
    """Query parameters for JSON graph export."""

    level: str = Field(
        default="class",
        description="Export level: 'module' or 'class'",
    )
