# app/ai/tools.py
"""Shared AI tool functions — used by both the chat backend and the MCP server.

Each function wraps a Cypher query against GraphStore. All functions are async
and return plain dicts/lists (JSON-serializable).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from app.services.neo4j import GraphStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


@dataclass
class ChatToolContext:
    """Shared context passed to all tool functions."""

    graph_store: GraphStore
    app_name: str
    project_id: str
    repo_path: str | None = None  # Cloned repo path (for get_source_code)
    db_session: AsyncSession | None = None  # For PostgreSQL writes (M2: summaries)


# ── Portfolio Tools ──────────────────────────────────────────


async def list_applications(ctx: ChatToolContext) -> list[dict]:
    """List all analyzed applications in ChangeSafe."""
    from sqlalchemy import select

    from app.models.db import Project, Repository
    from app.services.postgres import get_background_session

    # Get module counts from Neo4j
    graph_results = await ctx.graph_store.query(
        "MATCH (n) WHERE n.app_name IS NOT NULL "
        "WITH DISTINCT n.app_name AS name "
        "OPTIONAL MATCH (m {app_name: name, kind: 'MODULE'}) "
        "RETURN name, count(m) AS module_count"
    )

    # Enrich with repository name and branch from PostgreSQL
    app_ids = [r["name"] for r in graph_results]
    repo_lookup: dict[str, dict] = {}
    if app_ids:
        try:
            async with get_background_session() as session:
                result = await session.execute(
                    select(
                        Project.id,
                        Project.branch,
                        Repository.repo_full_name,
                    )
                    .join(Repository, Project.repository_id == Repository.id)
                    .where(Project.id.in_(app_ids))
                )
                for row in result.all():
                    repo_lookup[row.id] = {
                        "repository": row.repo_full_name,
                        "branch": row.branch,
                    }
        except Exception as exc:
            logger.warning("list_applications_pg_enrichment_failed", error=str(exc))

    return [
        {
            "app_name": r["name"],
            "repository": repo_lookup.get(r["name"], {}).get("repository", "unknown"),
            "branch": repo_lookup.get(r["name"], {}).get("branch", "unknown"),
            "module_count": r["module_count"],
        }
        for r in graph_results
    ]


async def application_stats(ctx: ChatToolContext, app_name: str | None = None) -> dict:
    """Get size, complexity, and technology metrics for an application."""
    name = app_name or ctx.app_name
    records = await ctx.graph_store.query(
        "MATCH (n) WHERE n.app_name = $name "
        "RETURN labels(n)[0] AS type, count(n) AS count, sum(n.loc) AS total_loc",
        {"name": name},
    )
    by_type = {r["type"]: r["count"] for r in records if r["type"]}
    total_loc = sum(r["total_loc"] or 0 for r in records)
    return {"app_name": name, "by_type": by_type, "total_loc": total_loc}


# ── Architecture Tools ───────────────────────────────────────


async def get_architecture(
    ctx: ChatToolContext,
    level: str = "module",
) -> dict:
    """Get application architecture at module or class level."""
    if level == "module":
        nodes = await ctx.graph_store.query(
            "MATCH (m) WHERE m.app_name = $name AND m.kind = 'MODULE' "
            "RETURN m.fqn AS fqn, m.name AS name, 'MODULE' AS type, m.loc AS loc",
            {"name": ctx.app_name},
        )
        edges = await ctx.graph_store.query(
            "MATCH (a)-[r:IMPORTS|DEPENDS_ON]->(b) "
            "WHERE a.app_name = $name AND b.app_name = $name "
            "AND a.kind = 'MODULE' AND b.kind = 'MODULE' "
            "RETURN a.fqn AS source, b.fqn AS target, "
            "type(r) AS kind, r.weight AS weight",
            {"name": ctx.app_name},
        )
    else:
        nodes = await ctx.graph_store.query(
            "MATCH (c) WHERE c.app_name = $name AND c.kind = 'CLASS' "
            "RETURN c.fqn AS fqn, c.name AS name, "
            "'CLASS' AS type, c.loc AS loc "
            "LIMIT 500",
            {"name": ctx.app_name},
        )
        edges = await ctx.graph_store.query(
            "MATCH (a)-[r:DEPENDS_ON]->(b) "
            "WHERE a.app_name = $name AND b.app_name = $name "
            "AND a.kind = 'CLASS' AND b.kind = 'CLASS' "
            "RETURN a.fqn AS source, b.fqn AS target, "
            "type(r) AS kind, r.weight AS weight "
            "LIMIT 2000",
            {"name": ctx.app_name},
        )
    return {"nodes": nodes, "edges": edges}


async def search_objects(
    ctx: ChatToolContext,
    query: str,
    type_filter: str | None = None,
) -> list[dict]:
    """Search for code objects by name. Optionally filter by type."""
    where_parts = [
        "n.app_name = $app_name",
        "(toLower(n.name) CONTAINS toLower($query) "
        "OR toLower(n.fqn) CONTAINS toLower($query))",
    ]
    params: dict = {"app_name": ctx.app_name, "query": query}

    if type_filter:
        where_parts.append("labels(n)[0] = $type_filter")
        params["type_filter"] = type_filter

    cypher = (
        f"MATCH (n) WHERE {' AND '.join(where_parts)} "
        "RETURN n.fqn AS fqn, n.name AS name, labels(n)[0] AS type, "
        "n.language AS language, n.path AS path "
        "LIMIT 50"
    )
    return await ctx.graph_store.query(cypher, params)


# ── Node Details Tools ───────────────────────────────────────


async def object_details(ctx: ChatToolContext, node_fqn: str) -> dict:
    """Get detailed info about a specific code object including callers and callees."""
    node = await ctx.graph_store.query_single(
        "MATCH (n {fqn: $fqn, app_name: $app_name}) "
        "RETURN n.fqn AS fqn, n.name AS name, labels(n)[0] AS type, "
        "  n.language AS language, n.path AS path, n.line AS line, "
        "  n.end_line AS end_line, n.loc AS loc, n.complexity AS complexity, "
        "  n.communityId AS community_id",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )
    if not node:
        return {"node": None, "callers": [], "callees": []}

    callers = await ctx.graph_store.query(
        "MATCH (caller)-[:CALLS]->(n {fqn: $fqn, app_name: $app_name}) "
        "RETURN caller.fqn AS fqn, caller.name AS name, labels(caller)[0] AS type "
        "LIMIT 50",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )
    callees = await ctx.graph_store.query(
        "MATCH (n {fqn: $fqn, app_name: $app_name})-[:CALLS]->(callee) "
        "RETURN callee.fqn AS fqn, callee.name AS name, labels(callee)[0] AS type "
        "LIMIT 50",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )

    node["fan_in"] = len(callers)
    node["fan_out"] = len(callees)
    return {"node": node, "callers": callers, "callees": callees}


# ── Analysis Tools ───────────────────────────────────────────


async def impact_analysis(
    ctx: ChatToolContext,
    node_fqn: str,
    depth: int = 5,
    direction: str = "both",
) -> dict:
    """Compute the blast radius of changing a specific code object."""
    depth = min(depth, 10)

    if direction == "upstream":
        cypher = (
            "MATCH (start {fqn: $fqn, app_name: $app_name})-[:CONTAINS*0..10]->(seed) "
            "WITH collect(DISTINCT seed.fqn) AS seed_fqns "
            f"MATCH (dep {{app_name: $app_name}})"
            "-[:CALLS|IMPLEMENTS|DEPENDS_ON|INHERITS"
            f"|INJECTS|CONSUMES|READS*1..{depth}]->(target) "
            "WHERE target.fqn IN seed_fqns AND dep.fqn <> $fqn "
            "WITH DISTINCT dep, 1 AS depth "
            "RETURN dep.fqn AS fqn, dep.name AS name, "
            "  labels(dep)[0] AS type, dep.path AS file, depth "
            "ORDER BY name LIMIT 100"
        )
    else:  # downstream or both
        cypher = (
            f"MATCH path = (start {{fqn: $fqn, app_name: $app_name}})"
            "-[:CALLS|INJECTS|IMPLEMENTS|PRODUCES"
            "|WRITES|READS|CONTAINS"
            f"|DEPENDS_ON*1..{depth}]->(affected) "
            "WHERE affected.app_name = $app_name AND affected.fqn <> $fqn "
            "WITH affected, min(length(path)) AS depth "
            "RETURN affected.fqn AS fqn, affected.name AS name, "
            "  labels(affected)[0] AS type, affected.path AS file, depth "
            "ORDER BY depth, name LIMIT 100"
        )

    records = await ctx.graph_store.query(
        cypher, {"fqn": node_fqn, "app_name": ctx.app_name}
    )
    by_type = dict(Counter(r["type"] for r in records))
    return {"affected": records, "total": len(records), "by_type": by_type}


async def find_path(ctx: ChatToolContext, from_fqn: str, to_fqn: str) -> dict:
    """Find the shortest connection path between two code objects."""
    records = await ctx.graph_store.query(
        "MATCH path = shortestPath("
        "(a {fqn: $source, app_name: $app_name})"
        "-[:CALLS|IMPLEMENTS|DEPENDS_ON|INJECTS|INHERITS|READS|WRITES|PRODUCES|CONSUMES*..10]-"
        "(b {fqn: $target, app_name: $app_name})) "
        "RETURN [n IN nodes(path) | "
        "{fqn: n.fqn, name: n.name, type: labels(n)[0]}] AS nodes, "
        "[r IN relationships(path) | {type: type(r), "
        "source: startNode(r).fqn, "
        "target: endNode(r).fqn}] AS edges, "
        "length(path) AS path_length",
        {"source": from_fqn, "target": to_fqn, "app_name": ctx.app_name},
    )
    if not records:
        return {"nodes": [], "edges": [], "path_length": 0}
    return records[0]


async def list_transactions(ctx: ChatToolContext) -> list[dict]:
    """List all end-to-end transaction flows in an application."""
    return await ctx.graph_store.query(
        "MATCH (t:Transaction {app_name: $app_name}) "
        "RETURN t.name AS name, t.http_method AS http_method, "
        "t.url_path AS url_path, t.node_count AS node_count, t.depth AS depth",
        {"app_name": ctx.app_name},
    )


async def transaction_graph(ctx: ChatToolContext, transaction_name: str) -> dict:
    """Get the full call graph for a specific transaction."""
    nodes = await ctx.graph_store.query(
        "MATCH (t:Transaction {name: $name, app_name: $app_name})-[:INCLUDES]->(n) "
        "RETURN n.fqn AS fqn, n.name AS name, labels(n)[0] AS type, n.path AS path",
        {"name": transaction_name, "app_name": ctx.app_name},
    )
    edges = await ctx.graph_store.query(
        "MATCH (t:Transaction {name: $name, app_name: $app_name})-[:INCLUDES]->(a) "
        "MATCH (t)-[:INCLUDES]->(b) "
        "MATCH (a)-[r:CALLS]->(b) "
        "RETURN a.fqn AS source, b.fqn AS target, type(r) AS kind",
        {"name": transaction_name, "app_name": ctx.app_name},
    )
    return {"nodes": nodes, "edges": edges}


async def get_source_code(ctx: ChatToolContext, node_fqn: str) -> dict:
    """Get the source code for a specific code object."""
    node = await ctx.graph_store.query_single(
        "MATCH (n {fqn: $fqn, app_name: $app_name}) "
        "RETURN n.path AS path, n.line AS line, "
        "n.end_line AS end_line",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )
    if not node:
        return {"error": "Node not found"}

    result: dict = {"fqn": node_fqn, "file": node.get("path"), "line": node.get("line")}

    if not ctx.repo_path or not node.get("path"):
        return result  # Metadata only — no repo access

    resolved = Path(ctx.repo_path, node["path"]).resolve()
    repo_resolved = Path(ctx.repo_path).resolve()
    if not str(resolved).startswith(str(repo_resolved)):
        return {**result, "error": "Path traversal not allowed"}

    if not resolved.is_file():
        return {**result, "error": f"File not found: {node['path']}"}

    try:
        text = resolved.read_text(errors="replace")
        lines = text.split("\n")
        start = max((node.get("line") or 1) - 1, 0)
        end = min(node.get("end_line") or len(lines), len(lines))
        if end - start > 200:
            end = start + 200
        selected = lines[start:end]
        numbered = "\n".join(
            f"{start + i + 1}: {line}" for i, line in enumerate(selected)
        )
        result["code"] = numbered
    except Exception as exc:
        result["error"] = f"Cannot read file: {exc}"

    return result


# ── Summary Tools ────────────────────────────────────────────
# Added in M2. Requires db_session on ChatToolContext.


async def get_or_generate_summary(ctx: ChatToolContext, node_fqn: str) -> dict:
    """Get AI summary for a node. Returns cached if available."""
    from anthropic import AsyncAnthropicBedrock

    from app.ai.summaries import (
        get_or_create_summary as summaries_get_or_create_summary,
    )
    from app.config import get_settings

    settings = get_settings()
    client = AsyncAnthropicBedrock(aws_region=settings.aws_region)
    return await summaries_get_or_create_summary(
        ctx=ctx,
        node_fqn=node_fqn,
        client=client,
        model=settings.summary_model,
        max_tokens=settings.summary_max_tokens,
    )
