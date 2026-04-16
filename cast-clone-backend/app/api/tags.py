"""Tag CRUD API endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_user
from app.models.db import Tag, User
from app.schemas.annotations import TagCreate, TagResponse
from app.services.activity import log_activity
from app.services.postgres import get_session

logger = structlog.get_logger()

project_router = APIRouter(prefix="/api/v1/projects/{project_id}/tags", tags=["tags"])
tag_router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


@project_router.post("", response_model=TagResponse, status_code=201)
async def add_tag(
    project_id: str,
    req: TagCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TagResponse:
    """Add a tag to a node. Duplicate tag on same node returns 409."""
    # Check for existing tag
    existing = await session.execute(
        select(Tag).where(
            Tag.project_id == project_id,
            Tag.node_fqn == req.node_fqn,
            Tag.tag_name == req.tag_name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tag already exists on this node")

    tag = Tag(
        project_id=project_id,
        node_fqn=req.node_fqn,
        tag_name=req.tag_name,
        author_id=user.id,
    )
    session.add(tag)
    await session.commit()

    result = await session.execute(
        select(Tag).options(joinedload(Tag.author)).where(Tag.id == tag.id)
    )
    tag = result.scalar_one()

    await log_activity(
        session, "tag.created", user_id=user.id,
        resource_type="tag", resource_id=tag.id,
        details={"tag_name": req.tag_name, "node_fqn": req.node_fqn},
    )
    return TagResponse.model_validate(tag, from_attributes=True)


@project_router.get("", response_model=list[TagResponse])
async def list_tags(
    project_id: str,
    node_fqn: str | None = Query(default=None),
    tag_name: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[TagResponse]:
    """List tags filtered by node FQN or tag name (or both)."""
    query = (
        select(Tag).options(joinedload(Tag.author)).where(Tag.project_id == project_id)
    )

    if node_fqn:
        query = query.where(Tag.node_fqn == node_fqn)
    if tag_name:
        query = query.where(Tag.tag_name == tag_name)

    query = query.order_by(Tag.created_at.desc())
    result = await session.execute(query)
    tags = result.scalars().unique().all()
    return [TagResponse.model_validate(t, from_attributes=True) for t in tags]


@tag_router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """Remove a tag. Author or admin can remove."""
    result = await session.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.author_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=403, detail="Only the author or admin can remove"
        )

    tag_name = tag.tag_name
    await session.delete(tag)
    await session.commit()

    await log_activity(
        session, "tag.deleted", user_id=user.id,
        resource_type="tag", resource_id=tag_id,
        details={"tag_name": tag_name},
    )
