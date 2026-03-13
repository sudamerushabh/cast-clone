"""Annotation CRUD API endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_user
from app.models.db import Annotation, User
from app.schemas.annotations import (
    AnnotationCreate,
    AnnotationResponse,
    AnnotationUpdate,
)
from app.services.postgres import get_session

logger = structlog.get_logger()

# Project-scoped routes
project_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/annotations", tags=["annotations"]
)

# Direct annotation routes (for update/delete by annotation ID)
annotation_router = APIRouter(prefix="/api/v1/annotations", tags=["annotations"])


@project_router.post("", response_model=AnnotationResponse, status_code=201)
async def create_annotation(
    project_id: str,
    req: AnnotationCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AnnotationResponse:
    """Create an annotation on a node."""
    annotation = Annotation(
        project_id=project_id,
        node_fqn=req.node_fqn,
        content=req.content,
        author_id=user.id,
    )
    session.add(annotation)
    await session.commit()

    # Re-query with author loaded
    result = await session.execute(
        select(Annotation)
        .options(joinedload(Annotation.author))
        .where(Annotation.id == annotation.id)
    )
    annotation = result.scalar_one()

    logger.info(
        "annotation_created",
        annotation_id=annotation.id,
        project_id=project_id,
        node_fqn=req.node_fqn,
    )
    return AnnotationResponse.model_validate(annotation, from_attributes=True)


@project_router.get("", response_model=list[AnnotationResponse])
async def list_annotations(
    project_id: str,
    node_fqn: str = Query(..., description="FQN of the node"),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[AnnotationResponse]:
    """Get all annotations for a node in a project."""
    result = await session.execute(
        select(Annotation)
        .options(joinedload(Annotation.author))
        .where(
            Annotation.project_id == project_id,
            Annotation.node_fqn == node_fqn,
        )
        .order_by(Annotation.created_at.desc())
    )
    annotations = result.scalars().unique().all()
    return [
        AnnotationResponse.model_validate(a, from_attributes=True) for a in annotations
    ]


@annotation_router.put("/{annotation_id}", response_model=AnnotationResponse)
async def update_annotation(
    annotation_id: str,
    req: AnnotationUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AnnotationResponse:
    """Update an annotation. Only the author can edit."""
    result = await session.execute(
        select(Annotation)
        .options(joinedload(Annotation.author))
        .where(Annotation.id == annotation_id)
    )
    annotation = result.scalar_one_or_none()
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if annotation.author_id != user.id:
        raise HTTPException(status_code=403, detail="Only the author can edit")

    annotation.content = req.content
    await session.commit()
    await session.refresh(annotation)

    return AnnotationResponse.model_validate(annotation, from_attributes=True)


@annotation_router.delete("/{annotation_id}", status_code=204)
async def delete_annotation(
    annotation_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """Delete an annotation. Author or admin can delete."""
    result = await session.execute(
        select(Annotation).where(Annotation.id == annotation_id)
    )
    annotation = result.scalar_one_or_none()
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if annotation.author_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=403, detail="Only the author or admin can delete"
        )

    await session.delete(annotation)
    await session.commit()

    logger.info("annotation_deleted", annotation_id=annotation_id)
