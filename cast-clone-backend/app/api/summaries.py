"""REST endpoint for on-demand AI summaries."""

from __future__ import annotations

from anthropic import AsyncAnthropicBedrock
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.summaries import get_or_create_summary
from app.ai.tools import ChatToolContext
from app.api.dependencies import get_current_user
from app.config import get_settings
from app.models.db import Project, User
from app.schemas.summaries import SummaryResponse
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/projects", tags=["summaries"])


async def _resolve_summary_context(
    project_id: str,
    session: AsyncSession,
) -> tuple[str, str | None, AsyncSession]:
    """Resolve project to (app_name, repo_path, session)."""
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {project_id}",
        )
    repo_path = getattr(project, "source_path", None)
    return project.neo4j_app_name, repo_path, session


@router.get(
    "/{project_id}/summary/{node_fqn:path}",
    response_model=SummaryResponse,
)
async def get_summary(
    project_id: str,
    node_fqn: str,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get or generate an AI summary for a code object."""
    app_name, repo_path, db_session = await _resolve_summary_context(
        project_id, session
    )

    settings = get_settings()
    ctx = ChatToolContext(
        graph_store=Neo4jGraphStore(get_driver()),
        app_name=app_name,
        project_id=project_id,
        repo_path=repo_path,
        db_session=db_session,
    )

    client = AsyncAnthropicBedrock(aws_region=settings.aws_region)
    result = await get_or_create_summary(
        ctx=ctx,
        node_fqn=node_fqn,
        client=client,
        model=settings.summary_model,
        max_tokens=settings.summary_max_tokens,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )

    return SummaryResponse(
        fqn=result["fqn"],
        summary=result["summary"],
        cached=result["cached"],
        model=result["model"],
        tokens_used=result.get("tokens_used"),
    )
