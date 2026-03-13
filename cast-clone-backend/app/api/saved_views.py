"""Saved views CRUD API endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_user
from app.models.db import SavedView, User
from app.schemas.saved_views import (
    SavedViewCreate,
    SavedViewListItem,
    SavedViewResponse,
    SavedViewUpdate,
)
from app.services.postgres import get_session

logger = structlog.get_logger()

project_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/views", tags=["saved-views"]
)
view_router = APIRouter(prefix="/api/v1/views", tags=["saved-views"])


@project_router.post("", response_model=SavedViewResponse, status_code=201)
async def save_view(
    project_id: str,
    req: SavedViewCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SavedViewResponse:
    """Save the current graph state as a named view."""
    view = SavedView(
        project_id=project_id,
        name=req.name,
        description=req.description,
        author_id=user.id,
        state=req.state,
    )
    session.add(view)
    await session.commit()

    result = await session.execute(
        select(SavedView)
        .options(joinedload(SavedView.author))
        .where(SavedView.id == view.id)
    )
    view = result.scalar_one()

    logger.info("view_saved", view_id=view.id, name=req.name)
    return SavedViewResponse.model_validate(view, from_attributes=True)


@project_router.get("", response_model=list[SavedViewListItem])
async def list_views(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[SavedViewListItem]:
    """List all saved views for a project (without full state)."""
    result = await session.execute(
        select(SavedView)
        .options(joinedload(SavedView.author))
        .where(SavedView.project_id == project_id)
        .order_by(SavedView.updated_at.desc())
    )
    views = result.scalars().unique().all()
    return [SavedViewListItem.model_validate(v, from_attributes=True) for v in views]


@view_router.get("/{view_id}", response_model=SavedViewResponse)
async def get_view(
    view_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> SavedViewResponse:
    """Load a saved view with full state."""
    result = await session.execute(
        select(SavedView)
        .options(joinedload(SavedView.author))
        .where(SavedView.id == view_id)
    )
    view = result.scalar_one_or_none()
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    return SavedViewResponse.model_validate(view, from_attributes=True)


@view_router.put("/{view_id}", response_model=SavedViewResponse)
async def update_view(
    view_id: str,
    req: SavedViewUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SavedViewResponse:
    """Update a saved view. Only the author can edit."""
    result = await session.execute(
        select(SavedView)
        .options(joinedload(SavedView.author))
        .where(SavedView.id == view_id)
    )
    view = result.scalar_one_or_none()
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    if view.author_id != user.id:
        raise HTTPException(status_code=403, detail="Only the author can edit")

    if req.name is not None:
        view.name = req.name
    if req.description is not None:
        view.description = req.description
    if req.state is not None:
        view.state = req.state

    await session.commit()

    # Re-query with author loaded to avoid lazy-load error
    result = await session.execute(
        select(SavedView)
        .options(joinedload(SavedView.author))
        .where(SavedView.id == view_id)
    )
    view = result.scalar_one()

    return SavedViewResponse.model_validate(view, from_attributes=True)


@view_router.delete("/{view_id}", status_code=204)
async def delete_view(
    view_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """Delete a saved view. Author or admin can delete."""
    result = await session.execute(select(SavedView).where(SavedView.id == view_id))
    view = result.scalar_one_or_none()
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    if view.author_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=403, detail="Only the author or admin can delete"
        )

    await session.delete(view)
    await session.commit()

    logger.info("view_deleted", view_id=view_id)
