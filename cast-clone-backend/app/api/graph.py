"""Graph query API endpoints — all backed by Neo4j Cypher queries."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

import re

from app.schemas.graph import (
    GraphEdgeListResponse,
    GraphEdgeResponse,
    GraphNodeListResponse,
    GraphNodeResponse,
    GraphSearchHit,
    GraphSearchResponse,
    NodeWithNeighborsResponse,
)
from app.services.neo4j import Neo4jGraphStore, get_driver

_VALID_REL_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

router = APIRouter(prefix="/api/v1/graphs", tags=["graph"])


def get_graph_store() -> Neo4jGraphStore:
    """Get a Neo4jGraphStore instance."""
    return Neo4jGraphStore(get_driver())


def _record_to_node(record: dict[str, Any]) -> GraphNodeResponse:
    """Convert a Neo4j record to a GraphNodeResponse."""
    n = record.get("n", record)
    return GraphNodeResponse(
        fqn=n.get("fqn", ""),
        name=n.get("name", ""),
        kind=n.get("kind", ""),
        language=n.get("language"),
        path=n.get("path"),
        line=n.get("line"),
        end_line=n.get("end_line"),
        loc=n.get("loc"),
        complexity=n.get("complexity"),
        visibility=n.get("visibility"),
        properties={
            k: v
            for k, v in n.items()
            if k
            not in {
                "fqn",
                "name",
                "kind",
                "language",
                "path",
                "line",
                "end_line",
                "loc",
                "complexity",
                "visibility",
                "app_name",
            }
        },
    )


def _record_to_edge(record: dict[str, Any]) -> GraphEdgeResponse:
    """Convert a Neo4j record to a GraphEdgeResponse."""
    return GraphEdgeResponse(
        source_fqn=record.get("source_fqn", ""),
        target_fqn=record.get("target_fqn", ""),
        kind=record.get("kind", ""),
        confidence=record.get("confidence", "HIGH"),
        evidence=record.get("evidence", "tree-sitter"),
    )


@router.get("/{project_id}/nodes", response_model=GraphNodeListResponse)
async def list_nodes(
    project_id: str,
    kind: str | None = None,
    language: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> GraphNodeListResponse:
    """List graph nodes for a project, with optional filtering by kind/language."""
    store = get_graph_store()

    # Build WHERE clause
    where_parts = ["n.app_name = $app_name"]
    params: dict[str, Any] = {"app_name": project_id}

    if kind:
        where_parts.append("n.kind = $kind")
        params["kind"] = kind
    if language:
        where_parts.append("n.language = $language")
        params["language"] = language

    where_clause = " AND ".join(where_parts)

    # Count query
    count_cypher = f"MATCH (n) WHERE {where_clause} RETURN count(n) AS count"
    count_result = await store.query_single(count_cypher, params)
    total = count_result["count"] if count_result else 0

    # Data query
    data_cypher = (
        f"MATCH (n) WHERE {where_clause} "
        f"RETURN n ORDER BY n.fqn SKIP $offset LIMIT $limit"
    )
    params["offset"] = offset
    params["limit"] = limit
    records = await store.query(data_cypher, params)

    return GraphNodeListResponse(
        nodes=[_record_to_node(r) for r in records],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{project_id}/edges", response_model=GraphEdgeListResponse)
async def list_edges(
    project_id: str,
    kind: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> GraphEdgeListResponse:
    """List graph edges for a project, with optional filtering by kind."""
    store = get_graph_store()

    where_parts = ["a.app_name = $app_name"]
    params: dict[str, Any] = {"app_name": project_id}

    rel_filter = ""
    if kind:
        if not _VALID_REL_TYPE.match(kind):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid edge kind: {kind}",
            )
        rel_filter = f":{kind}"

    # Count query
    count_cypher = (
        f"MATCH (a)-[r{rel_filter}]->(b) "
        f"WHERE {' AND '.join(where_parts)} "
        f"RETURN count(r) AS count"
    )
    count_result = await store.query_single(count_cypher, params)
    total = count_result["count"] if count_result else 0

    # Data query
    data_cypher = (
        f"MATCH (a)-[r{rel_filter}]->(b) "
        f"WHERE {' AND '.join(where_parts)} "
        f"RETURN a.fqn AS source_fqn, b.fqn AS target_fqn, "
        f"type(r) AS kind, r.confidence AS confidence, r.evidence AS evidence "
        f"SKIP $offset LIMIT $limit"
    )
    params["offset"] = offset
    params["limit"] = limit
    records = await store.query(data_cypher, params)

    return GraphEdgeListResponse(
        edges=[_record_to_edge(r) for r in records],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{project_id}/node/{fqn:path}", response_model=NodeWithNeighborsResponse)
async def get_node(
    project_id: str,
    fqn: str,
) -> NodeWithNeighborsResponse:
    """Get a single node by FQN with its neighbors and edges."""
    store = get_graph_store()

    # Find node
    node_result = await store.query_single(
        "MATCH (n {fqn: $fqn, app_name: $app_name}) RETURN n",
        {"fqn": fqn, "app_name": project_id},
    )
    if node_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node {fqn} not found in project {project_id}",
        )

    node = _record_to_node(node_result)

    # Incoming edges
    incoming_records = await store.query(
        "MATCH (a)-[r]->(n {fqn: $fqn, app_name: $app_name}) "
        "RETURN a.fqn AS source_fqn, n.fqn AS target_fqn, "
        "type(r) AS kind, r.confidence AS confidence, r.evidence AS evidence",
        {"fqn": fqn, "app_name": project_id},
    )
    incoming_edges = [_record_to_edge(r) for r in incoming_records]

    # Outgoing edges
    outgoing_records = await store.query(
        "MATCH (n {fqn: $fqn, app_name: $app_name})-[r]->(b) "
        "RETURN n.fqn AS source_fqn, b.fqn AS target_fqn, "
        "type(r) AS kind, r.confidence AS confidence, r.evidence AS evidence",
        {"fqn": fqn, "app_name": project_id},
    )
    outgoing_edges = [_record_to_edge(r) for r in outgoing_records]

    # Neighbor nodes
    neighbor_records = await store.query(
        "MATCH (n {fqn: $fqn, app_name: $app_name})--(neighbor) "
        "RETURN DISTINCT neighbor AS n",
        {"fqn": fqn, "app_name": project_id},
    )
    neighbors = [_record_to_node(r) for r in neighbor_records]

    return NodeWithNeighborsResponse(
        node=node,
        incoming_edges=incoming_edges,
        outgoing_edges=outgoing_edges,
        neighbors=neighbors,
    )


@router.get("/{project_id}/neighbors/{fqn:path}", response_model=GraphNodeListResponse)
async def get_neighbors(
    project_id: str,
    fqn: str,
    depth: int = 1,
    limit: int = 100,
) -> GraphNodeListResponse:
    """Get neighbor subgraph around a node."""
    store = get_graph_store()

    cypher = (
        "MATCH (n {fqn: $fqn, app_name: $app_name})-[*1..$depth]-(neighbor) "
        "RETURN DISTINCT neighbor AS n LIMIT $limit"
    )
    records = await store.query(
        cypher, {"fqn": fqn, "app_name": project_id, "depth": depth, "limit": limit}
    )

    return GraphNodeListResponse(
        nodes=[_record_to_node(r) for r in records],
        total=len(records),
        offset=0,
        limit=limit,
    )


@router.get("/{project_id}/search", response_model=GraphSearchResponse)
async def search_nodes(
    project_id: str,
    q: str = Query(..., min_length=1),
) -> GraphSearchResponse:
    """Full-text search across graph nodes."""
    store = get_graph_store()

    # Use CONTAINS for basic search; full-text index search in production
    cypher = (
        "MATCH (n) WHERE n.app_name = $app_name "
        "AND (toLower(n.name) CONTAINS toLower($query) "
        "OR toLower(n.fqn) CONTAINS toLower($query)) "
        "RETURN n.fqn AS fqn, n.name AS name, n.kind AS kind, "
        "n.language AS language, 1.0 AS score "
        "LIMIT 50"
    )
    records = await store.query(
        cypher, {"app_name": project_id, "query": q}
    )

    hits = [
        GraphSearchHit(
            fqn=r["fqn"],
            name=r["name"],
            kind=r["kind"],
            language=r.get("language"),
            score=r.get("score", 0.0),
        )
        for r in records
    ]

    return GraphSearchResponse(
        query=q,
        hits=hits,
        total=len(hits),
    )
