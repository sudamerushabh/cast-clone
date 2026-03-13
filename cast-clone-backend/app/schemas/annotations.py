"""Pydantic schemas for annotations and tags."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PREDEFINED_TAGS = frozenset(
    {
        "deprecated",
        "tech-debt",
        "critical-path",
        "security-sensitive",
        "needs-review",
    }
)

TagName = Literal[
    "deprecated",
    "tech-debt",
    "critical-path",
    "security-sensitive",
    "needs-review",
]


class AnnotationCreate(BaseModel):
    """Create an annotation on a node."""

    node_fqn: str = Field(max_length=500)
    content: str = Field(min_length=1)


class AnnotationUpdate(BaseModel):
    """Update an annotation's content."""

    content: str = Field(min_length=1)


class AnnotationAuthor(BaseModel):
    """Embedded author info."""

    id: str
    username: str

    model_config = {"from_attributes": True}


class AnnotationResponse(BaseModel):
    """Annotation with author info."""

    id: str
    project_id: str
    node_fqn: str
    content: str
    author: AnnotationAuthor
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TagCreate(BaseModel):
    """Add a tag to a node."""

    node_fqn: str = Field(max_length=500)
    tag_name: TagName


class TagResponse(BaseModel):
    """Tag with author info."""

    id: str
    project_id: str
    node_fqn: str
    tag_name: str
    author: AnnotationAuthor
    created_at: datetime

    model_config = {"from_attributes": True}
