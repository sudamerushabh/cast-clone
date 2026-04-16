"""Project CRUD API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import (
    get_accessible_project,
    get_current_user,
    require_license_writable,
)
from app.models.db import Project, Repository, User
from app.schemas.projects import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
)
from app.services.activity import log_activity
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

    await log_activity(
        session,
        "project.created",
        user_id=user.id,
        resource_type="project",
        resource_id=project.id,
        details={"name": body.name},
    )

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
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(50, ge=1, le=200),
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
    project: Project = Depends(get_accessible_project),
) -> ProjectResponse:
    """Get a single project by ID."""
    return ProjectResponse(
        id=project.id,
        name=project.name,
        source_path=project.source_path,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_license_writable)],
)
async def delete_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    project: Project = Depends(get_accessible_project),
    user: User = Depends(get_current_user),
) -> Response:
    """Delete a project by ID."""
    project_name = project.name
    await session.delete(project)
    await session.commit()

    await log_activity(
        session,
        "project.deleted",
        user_id=user.id,
        resource_type="project",
        resource_id=project_id,
        details={"name": project_name},
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
