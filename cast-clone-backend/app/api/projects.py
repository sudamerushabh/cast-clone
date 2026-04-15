"""Project CRUD API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_license_writable
from app.models.db import Project
from app.schemas.projects import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
)
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_license_writable)],
)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    """Create a new project."""
    project = Project(
        name=body.name,
        source_path=body.source_path,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    return ProjectResponse(
        id=project.id,
        name=project.name,
        source_path=project.source_path,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    offset: int = 0,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> ProjectListResponse:
    """List all projects with pagination."""
    # Count total
    count_result = await session.execute(select(func.count(Project.id)))
    total = count_result.scalar_one()

    # Fetch page
    result = await session.execute(
        select(Project)
        .order_by(Project.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    projects = result.scalars().all()

    return ProjectListResponse(
        projects=[
            ProjectResponse(
                id=p.id,
                name=p.name,
                source_path=p.source_path,
                status=p.status,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
            for p in projects
        ],
        total=total,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    """Get a single project by ID."""
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    return ProjectResponse(
        id=project.id,
        name=project.name,
        source_path=project.source_path,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a project by ID."""
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    await session.delete(project)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
