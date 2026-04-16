"""Project CRUD API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user
from app.models.db import Project, Repository, User
from app.schemas.projects import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
)
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


async def _load_project_with_repo(
    session: AsyncSession, project_id: str
) -> Project | None:
    """Load a project with its repository eager-loaded for ownership checks."""
    result = await session.execute(
        select(Project)
        .options(selectinload(Project.repository))
        .where(Project.id == project_id)
    )
    return result.scalar_one_or_none()


def _user_can_access_project(project: Project, user: User) -> bool:
    """Ownership check: admin can always access, otherwise must own the
    parent repository. Projects without a repository have no owner (legacy
    path) — authenticated access is sufficient.
    """
    if user.role == "admin":
        return True
    if project.repository is None:
        # No ownership chain available — any authenticated user may read.
        return True
    return project.repository.created_by == user.id


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectListResponse:
    """List projects. Admins see everything; members see projects whose parent
    repository they created, plus legacy projects without a repository."""
    base = select(Project).options(selectinload(Project.repository))
    count_base = select(func.count(Project.id))

    if user.role != "admin":
        # Projects with no repository OR projects whose repo was created by this user
        filter_clause = (Project.repository_id.is_(None)) | (
            Project.repository_id.in_(
                select(Repository.id).where(Repository.created_by == user.id)
            )
        )
        base = base.where(filter_clause)
        count_base = count_base.where(filter_clause)

    count_result = await session.execute(count_base)
    total = count_result.scalar_one()

    result = await session.execute(
        base.order_by(Project.created_at.desc()).offset(offset).limit(limit)
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
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    """Get a single project by ID."""
    project = await _load_project_with_repo(session, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    if not _user_can_access_project(project, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
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
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a project by ID."""
    project = await _load_project_with_repo(session, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    if not _user_can_access_project(project, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )

    await session.delete(project)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
