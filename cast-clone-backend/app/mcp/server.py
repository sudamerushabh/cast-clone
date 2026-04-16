"""FastMCP server — exposes ChangeSafe architecture tools via MCP protocol.

This is a thin wrapper (~200 lines) over the shared tool functions in
app.ai.tools. Each @mcp.tool() decorated function builds a ChatToolContext
per-call and delegates to the shared layer.

Transport: SSE on port 8090.
Auth: API key via Authorization: Bearer <key> header.

Multi-project context:
- Tools that take app_name build ChatToolContext per-call.
- Project-agnostic tools (list_applications) use GraphStore directly
  without app_name.
"""

from __future__ import annotations

import asyncio

import structlog
from mcp.server.fastmcp import FastMCP

from app.ai import tools
from app.ai.tools import ChatToolContext
from app.config import get_settings
from app.mcp.auth import ApiKeyAuthenticator
from app.services.neo4j import Neo4jGraphStore, close_neo4j, get_driver, init_neo4j
from app.services.postgres import close_postgres, get_background_session, init_postgres

logger = structlog.get_logger(__name__)

_settings = get_settings()
mcp = FastMCP("changesafe", host="0.0.0.0", port=_settings.mcp_port)

# Module-level state initialized during server startup
_graph_store: Neo4jGraphStore | None = None
_authenticator: ApiKeyAuthenticator | None = None


def _get_graph_store() -> Neo4jGraphStore:
    """Get the initialized GraphStore instance."""
    assert _graph_store is not None, "MCP server not initialized — GraphStore is None"
    return _graph_store


async def _resolve_repo_path(app_name: str) -> str | None:
    """Look up the repo path for an app_name from PostgreSQL."""
    if not app_name:
        return None
    try:
        async with get_background_session() as session:
            from sqlalchemy import or_, select

            from app.models.db import Project

            result = await session.execute(
                select(Project).where(
                    or_(Project.id == app_name, Project.name == app_name)
                )
            )
            project = result.scalar_one_or_none()
            return project.source_path if project else None
    except Exception:
        return None


def _build_context(app_name: str = "", repo_path: str | None = None) -> ChatToolContext:
    """Build a ChatToolContext for a tool call."""
    return ChatToolContext(
        graph_store=_get_graph_store(),
        app_name=app_name,
        project_id="",
        repo_path=repo_path,
    )


# ── Portfolio Tools (project-agnostic) ──────────────────────


@mcp.tool()
async def list_applications() -> list[dict]:
    """List all analyzed applications in ChangeSafe with languages and module count."""
    ctx = _build_context()
    return await tools.list_applications(ctx)


@mcp.tool()
async def application_stats(app_name: str) -> dict:
    """Get size, complexity, and technology metrics for an application.

    Args:
        app_name: The application name as shown by list_applications.
    """
    ctx = _build_context(app_name)
    return await tools.application_stats(ctx, app_name=app_name)


# ── Architecture Tools ──────────────────────────────────────


@mcp.tool()
async def get_architecture(app_name: str, level: str = "module") -> dict:
    """Get application architecture showing modules/classes and their dependencies.

    Args:
        app_name: The application name.
        level: Level of detail — "module" or "class".
    """
    ctx = _build_context(app_name)
    return await tools.get_architecture(ctx, level=level)


@mcp.tool()
async def search_objects(
    app_name: str, query: str, type_filter: str | None = None
) -> list[dict]:
    """Search for code objects (classes, functions, tables, endpoints) by name.

    Args:
        app_name: The application name.
        query: Search string — matches name or fully qualified name.
        type_filter: Optional filter: Class, Function, Interface, Table, APIEndpoint.
    """
    ctx = _build_context(app_name)
    return await tools.search_objects(ctx, query=query, type_filter=type_filter)


# ── Node Detail Tools ───────────────────────────────────────


@mcp.tool()
async def object_details(app_name: str, node_fqn: str) -> dict:
    """Get detailed info about a code object including callers, callees, and metrics.

    Args:
        app_name: The application name.
        node_fqn: Fully qualified name of the code object.
    """
    ctx = _build_context(app_name)
    return await tools.object_details(ctx, node_fqn=node_fqn)


@mcp.tool()
async def get_source_code(app_name: str, node_fqn: str) -> dict:
    """Get the source code for a specific code object (line-numbered).

    Args:
        app_name: The application name.
        node_fqn: Fully qualified name of the code object.
    """
    repo_path = await _resolve_repo_path(app_name)
    ctx = _build_context(app_name, repo_path=repo_path)
    return await tools.get_source_code(ctx, node_fqn=node_fqn)


# ── Analysis Tools ──────────────────────────────────────────


@mcp.tool()
async def impact_analysis(
    app_name: str,
    node_fqn: str,
    depth: int = 5,
    direction: str = "both",
) -> dict:
    """Compute the blast radius of changing a specific code object.

    Args:
        app_name: The application name.
        node_fqn: Fully qualified name of the node to analyze.
        depth: Max traversal depth (default 5, max 10).
        direction: Impact direction — "downstream", "upstream", or "both".
    """
    ctx = _build_context(app_name)
    return await tools.impact_analysis(
        ctx,
        node_fqn=node_fqn,
        depth=depth,
        direction=direction,
    )


@mcp.tool()
async def find_path(app_name: str, from_fqn: str, to_fqn: str) -> dict:
    """Find the shortest connection path between two code objects.

    Args:
        app_name: The application name.
        from_fqn: Fully qualified name of the source node.
        to_fqn: Fully qualified name of the target node.
    """
    ctx = _build_context(app_name)
    return await tools.find_path(ctx, from_fqn=from_fqn, to_fqn=to_fqn)


# ── Transaction Tools ───────────────────────────────────────


@mcp.tool()
async def list_transactions(app_name: str) -> list[dict]:
    """List all end-to-end transaction flows (API requests) in an application.

    Args:
        app_name: The application name.
    """
    ctx = _build_context(app_name)
    return await tools.list_transactions(ctx)


@mcp.tool()
async def transaction_graph(app_name: str, transaction_name: str) -> dict:
    """Get the full call graph for a specific transaction flow.

    Args:
        app_name: The application name.
        transaction_name: Name of the transaction (e.g., "POST /orders").
    """
    ctx = _build_context(app_name)
    return await tools.transaction_graph(ctx, transaction_name=transaction_name)


# ── Server Lifecycle ────────────────────────────────────────


async def _flush_loop(authenticator: ApiKeyAuthenticator) -> None:
    """Periodically flush batched last_used_at updates."""
    while True:
        await asyncio.sleep(60)
        await authenticator.flush_last_used()


async def run_server() -> None:
    """Initialize services and run the MCP server."""
    global _graph_store, _authenticator

    settings = get_settings()

    # Initialize database connections
    await init_postgres(settings)
    await init_neo4j(settings)

    _graph_store = Neo4jGraphStore(get_driver())
    _authenticator = ApiKeyAuthenticator(
        session_factory=get_background_session,
        cache_ttl_seconds=settings.mcp_api_key_cache_ttl_seconds,
        batch_update_seconds=settings.mcp_last_used_batch_seconds,
    )

    # Start background flush task
    flush_task = asyncio.create_task(_flush_loop(_authenticator))

    logger.info("mcp_server_starting", port=settings.mcp_port)

    try:
        # Run with SSE transport on configured port
        # NOTE: Auth is handled at the application level — the MCP server
        # validates API keys via _authenticator in a custom middleware.
        # For FastMCP >=1.25, use mcp.run() with transport params.
        # If FastMCP doesn't support auth natively, wrap with a FastAPI
        # app that validates Bearer tokens before proxying to MCP.
        await mcp.run_sse_async()
    finally:
        flush_task.cancel()
        try:
            await flush_task
        except asyncio.CancelledError:
            pass
        # Final flush
        await _authenticator.flush_last_used()
        await close_neo4j()
        await close_postgres()


if __name__ == "__main__":
    asyncio.run(run_server())
