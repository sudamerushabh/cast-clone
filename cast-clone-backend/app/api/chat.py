# app/api/chat.py
"""AI chat endpoint — agentic architecture assistant with SSE streaming."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat import build_system_prompt, chat_stream
from app.ai.tools import ChatToolContext
from app.api.dependencies import get_current_user
from app.config import Settings, get_settings
from app.models.db import Project, User
from app.schemas.chat import ChatRequest
from app.services.ai_provider import get_ai_config
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session
from app.services.rate_limit import (
    ChatLockBusy,
    RateLimitExceeded,
    chat_lock,
    check_rate_limit,
)
from app.services.redis import get_redis

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/projects", tags=["chat"])


async def _resolve_project_context(
    project_id: str,
    session: AsyncSession,
) -> tuple[str, list[str], list[str], str | None]:
    """Resolve project_id to (app_name, languages, frameworks, repo_path).

    Queries Neo4j for language/framework metadata since the graph nodes
    store this information (populated during analysis Stage 1/7).
    """
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if not project:
        return project_id, [], [], None

    app_name = project.neo4j_app_name
    repo_path = project.source_path

    # Query Neo4j for language + framework metadata
    store = Neo4jGraphStore(get_driver())
    lang_records = await store.query(
        "MATCH (n {app_name: $name}) WHERE n.language IS NOT NULL "
        "RETURN DISTINCT n.language AS language",
        {"name": app_name},
    )
    languages = [r["language"] for r in lang_records if r.get("language")]

    fw_records = await store.query(
        "MATCH (n {app_name: $name}) WHERE n.kind = 'Component' AND n.name IS NOT NULL "
        "RETURN DISTINCT n.name AS framework",
        {"name": app_name},
    )
    frameworks = [r["framework"] for r in fw_records if r.get("framework")]

    return app_name, languages, frameworks, repo_path


@router.post("/{project_id}/chat")
async def chat(
    project_id: str,
    request: Request,
    body: ChatRequest,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Chat with the AI architecture assistant.

    Returns an SSE stream with thinking blocks, tool calls, and text responses.
    Rate-limited (10 req/min per user) and locked to 1 active stream per user.
    """
    user_id = str(_user.id)
    redis = get_redis()

    # Per-user sliding-window rate limit (survives across workers/restarts).
    try:
        await check_rate_limit(
            redis,
            f"rl:chat:{user_id}",
            window_seconds=60,
            max_requests=10,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Chat rate limit exceeded",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    # Concurrency guard: acquire the lock before streaming so we can reject
    # the request cleanly with 429 rather than mid-stream.
    try:
        lock_ctx = chat_lock(redis, user_id, ttl_seconds=300)
        await lock_ctx.__aenter__()
    except ChatLockBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "You already have an active chat stream. "
                "Please wait for it to complete."
            ),
        ) from exc

    try:
        app_name, languages, frameworks, repo_path = await _resolve_project_context(
            project_id,
            session,
        )

        # Build page-aware or generic system prompt
        page_context = body.page_context if body.include_page_context else None
        system_prompt = build_system_prompt(
            app_name=app_name,
            frameworks=frameworks,
            languages=languages,
            page_context=page_context,
            tone=body.tone,
        )

        ctx = ChatToolContext(
            graph_store=Neo4jGraphStore(get_driver()),
            app_name=app_name,
            project_id=project_id,
            repo_path=repo_path,
            db_session=session,
        )

        ai_config = await get_ai_config(session)
    except Exception:
        await lock_ctx.__aexit__(None, None, None)
        raise

    async def event_generator():
        try:
            async for event in chat_stream(
                ctx=ctx,
                message=body.message,
                history=body.history,
                system_prompt=system_prompt,
                ai_config=ai_config,
            ):
                if await request.is_disconnected():
                    break
                yield event
        except Exception as exc:
            logger.error(
                "chat_stream_generator_error",
                error=str(exc),
            )
        finally:
            await lock_ctx.__aexit__(None, None, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
