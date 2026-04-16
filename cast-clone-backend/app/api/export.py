"""CSV and JSON export API endpoints."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Generator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_current_user
from app.models.db import User
from app.services.neo4j import get_driver

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/export", tags=["export"])


# Whitelist of node property names allowed in the `fields` query param for
# node exports. Only names in this set may be interpolated into Cypher —
# anything else is rejected with 400 to prevent Cypher injection.
_ALLOWED_NODE_FIELDS: frozenset[str] = frozenset({
    "fqn", "name", "kind", "language", "path", "file", "line", "end_line",
    "loc", "complexity", "fan_in", "fan_out", "community_id",
    "layer", "visibility",
})


# Whitelist of edge field names allowed in the `fields` query param for
# edge exports. The Cypher template is fixed; this whitelist is used to
# filter the projected CSV columns (DictWriter fieldnames) only.
_ALLOWED_EDGE_FIELDS: frozenset[str] = frozenset({
    "source", "target", "type", "weight", "confidence", "evidence",
})


def _validate_fields(raw: str, allowed: frozenset[str]) -> list[str]:
    """Validate and parse the `fields` query param against a whitelist.

    Returns the ordered list of validated field names. Raises 400 if the
    caller passes any name outside the whitelist. Empty input yields an
    empty list.
    """
    fields = [f.strip() for f in raw.split(",") if f.strip()]
    bad = [f for f in fields if f not in allowed]
    if bad:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown field(s): {', '.join(bad)}. "
                f"Allowed: {sorted(allowed)}"
            ),
        )
    return fields


async def _neo4j_query(
    cypher: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Run a Cypher query and return results as dicts."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(cypher, **(params or {}))
        return [dict(record) for record in await result.data()]


def _csv_stream(rows: list[dict[str, Any]], fields: list[str]) -> Generator[str]:
    """Generate CSV content from rows."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    yield output.getvalue()
    output.truncate(0)
    output.seek(0)

    for row in rows:
        writer.writerow(row)
        yield output.getvalue()
        output.truncate(0)
        output.seek(0)


@router.get("/{project_id}/nodes.csv")
async def export_nodes_csv(
    project_id: str,
    types: str | None = Query(default=None, description="Comma-separated node kinds"),
    fields: str = Query(default="fqn,name,kind,language,loc,complexity"),
    # TODO(CHAN-54): switch to get_accessible_project(project_id) once the
    # per-project authorization dependency lands so exports are gated by
    # project ownership, not just authentication.
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export node list as CSV."""
    field_list = _validate_fields(fields, _ALLOWED_NODE_FIELDS)

    cypher = "MATCH (n) WHERE n.app_name = $app_name"
    params: dict[str, Any] = {"app_name": project_id}

    if types:
        type_list = [t.strip() for t in types.split(",")]
        cypher += " AND n.kind IN $kinds"
        params["kinds"] = type_list

    # Every name in field_list has been validated against the whitelist, so
    # interpolating them here is safe — they cannot contain Cypher syntax.
    cypher += " RETURN " + ", ".join(f"n.{f} AS {f}" for f in field_list)

    rows = await _neo4j_query(cypher, params)

    return StreamingResponse(
        _csv_stream(rows, field_list),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}_nodes.csv"'
        },
    )


@router.get("/{project_id}/edges.csv")
async def export_edges_csv(
    project_id: str,
    types: str | None = Query(default=None, description="Comma-separated edge types"),
    fields: str = Query(default="source,target,type,weight"),
    # TODO(CHAN-54): switch to get_accessible_project(project_id) once the
    # per-project authorization dependency lands.
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export edge list as CSV."""
    field_list = _validate_fields(fields, _ALLOWED_EDGE_FIELDS)

    cypher = """
    MATCH (a)-[r]->(b)
    WHERE a.app_name = $app_name AND b.app_name = $app_name
    """
    params: dict[str, Any] = {"app_name": project_id}

    if types:
        type_list = [t.strip() for t in types.split(",")]
        cypher += " AND type(r) IN $types"
        params["types"] = type_list

    cypher += """
    RETURN a.fqn AS source, b.fqn AS target, type(r) AS type,
           COALESCE(r.weight, 1) AS weight
    """

    rows = await _neo4j_query(cypher, params)

    return StreamingResponse(
        _csv_stream(rows, field_list),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}_edges.csv"'
        },
    )


@router.get("/{project_id}/graph.json")
async def export_graph_json(
    project_id: str,
    level: str = Query(
        default="class", description="Export level: 'module' or 'class'"
    ),
    # TODO(CHAN-54): switch to get_accessible_project(project_id) once the
    # per-project authorization dependency lands.
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export full graph data as JSON."""
    kind_filter = "n.kind IN ['Module']" if level == "module" else "true"

    nodes_cypher = f"""
    MATCH (n)
    WHERE n.app_name = $app_name AND {kind_filter}
    RETURN n {{
        .fqn, .name, .kind, .language, .loc, .complexity,
        .fan_in, .fan_out, .community_id, .layer, .file, .line
    }} AS node
    """

    edges_cypher = """
    MATCH (a)-[r]->(b)
    WHERE a.app_name = $app_name AND b.app_name = $app_name
    RETURN a.fqn AS source, b.fqn AS target, type(r) AS type,
           COALESCE(r.weight, 1) AS weight
    """

    params: dict[str, Any] = {"app_name": project_id}
    nodes = await _neo4j_query(nodes_cypher, params)
    edges = await _neo4j_query(edges_cypher, params)

    graph_data = {
        "project_id": project_id,
        "level": level,
        "nodes": [n.get("node", n) for n in nodes],
        "edges": edges,
    }

    content = json.dumps(graph_data, indent=2, default=str)

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}_graph.json"'
        },
    )


@router.get("/{project_id}/impact.csv")
async def export_impact_csv(
    project_id: str,
    node: str = Query(..., description="FQN of the starting node"),
    direction: str = Query(default="both", description="downstream, upstream, or both"),
    max_depth: int = Query(default=5, ge=1, le=10),
    # TODO(CHAN-54): switch to get_accessible_project(project_id) once the
    # per-project authorization dependency lands.
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export impact analysis result as CSV."""
    if direction == "downstream":
        path_pattern = "(start)-[*1..{depth}]->(affected)"
    elif direction == "upstream":
        path_pattern = "(affected)-[*1..{depth}]->(start)"
    else:
        path_pattern = "(start)-[*1..{depth}]-(affected)"

    path_pattern = path_pattern.format(depth=max_depth)

    cypher = f"""
    MATCH (start {{fqn: $fqn, app_name: $app_name}})
    MATCH path = {path_pattern}
    WHERE affected.app_name = $app_name
    WITH DISTINCT affected, length(shortestPath((start)-[*]-(affected))) AS depth
    RETURN affected.fqn AS fqn, affected.name AS name,
           affected.kind AS type, depth,
           affected.file AS file, affected.line AS line
    ORDER BY depth, fqn
    """

    params: dict[str, Any] = {"fqn": node, "app_name": project_id}
    rows = await _neo4j_query(cypher, params)

    export_fields = ["fqn", "name", "type", "depth", "file", "line"]
    return StreamingResponse(
        _csv_stream(rows, export_fields),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}_impact.csv"'
        },
    )
