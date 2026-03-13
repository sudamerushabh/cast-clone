"""Phase 3 analysis API endpoints — impact, paths, communities, metrics."""

from __future__ import annotations

from collections import Counter
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.analysis_views import (
    AffectedNode,
    CircularDependenciesResponse,
    CircularDependency,
    CommunitiesResponse,
    CommunityInfo,
    DeadCodeCandidate,
    DeadCodeResponse,
    ImpactAnalysisResponse,
    ImpactSummary,
    MetricsResponse,
    NodeDetailResponse,
    OverviewStats,
    PathEdge,
    PathFinderResponse,
    PathNode,
    RankedItem,
)
from app.services.neo4j import Neo4jGraphStore, get_driver

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis-views"])


def get_graph_store() -> Neo4jGraphStore:
    """Get a Neo4jGraphStore instance."""
    return Neo4jGraphStore(get_driver())


# ── 1. Impact Analysis ──────────────────────────────────


@router.get(
    "/{project_id}/impact/{node_fqn:path}",
    response_model=ImpactAnalysisResponse,
)
async def impact_analysis(
    project_id: str,
    node_fqn: str,
    direction: str = Query("downstream", pattern="^(downstream|upstream|both)$"),
    max_depth: int = Query(5, ge=1, le=10),
) -> ImpactAnalysisResponse:
    """Compute blast radius for a node."""
    store = get_graph_store()

    if direction == "downstream":
        cypher = (
            f"MATCH path = (start {{fqn: $fqn}})"
            f"-[:CALLS|INJECTS|PRODUCES|WRITES*1..{max_depth}]->(affected) "
            "WITH affected, min(length(path)) AS depth "
            "RETURN affected.fqn AS fqn, affected.name AS name, "
            "labels(affected)[0] AS type, affected.path AS file, depth "
            "ORDER BY depth, name"
        )
    elif direction == "upstream":
        cypher = (
            f"MATCH path = (dependent)"
            f"-[:CALLS|INJECTS|CONSUMES|READS*1..{max_depth}]->"
            "(start {fqn: $fqn}) "
            "WITH dependent, min(length(path)) AS depth "
            "RETURN dependent.fqn AS fqn, dependent.name AS name, "
            "labels(dependent)[0] AS type, dependent.path AS file, depth "
            "ORDER BY depth, name"
        )
    else:
        # both: run downstream then upstream and merge
        downstream_cypher = (
            f"MATCH path = (start {{fqn: $fqn}})"
            f"-[:CALLS|INJECTS|PRODUCES|WRITES*1..{max_depth}]->(affected) "
            "WITH affected, min(length(path)) AS depth "
            "RETURN affected.fqn AS fqn, affected.name AS name, "
            "labels(affected)[0] AS type, affected.path AS file, depth "
            "ORDER BY depth, name"
        )
        upstream_cypher = (
            f"MATCH path = (dependent)"
            f"-[:CALLS|INJECTS|CONSUMES|READS*1..{max_depth}]->"
            "(start {fqn: $fqn}) "
            "WITH dependent, min(length(path)) AS depth "
            "RETURN dependent.fqn AS fqn, dependent.name AS name, "
            "labels(dependent)[0] AS type, dependent.path AS file, depth "
            "ORDER BY depth, name"
        )
        down_records = await store.query(downstream_cypher, {"fqn": node_fqn})
        up_records = await store.query(upstream_cypher, {"fqn": node_fqn})
        # Merge: deduplicate by fqn, keep minimum depth
        seen: dict[str, dict[str, Any]] = {}
        for r in down_records + up_records:
            fqn = r["fqn"]
            if fqn not in seen or r["depth"] < seen[fqn]["depth"]:
                seen[fqn] = r
        records = sorted(seen.values(), key=lambda x: (x["depth"], x.get("name", "")))
        return _build_impact_response(node_fqn, direction, max_depth, records)

    records = await store.query(cypher, {"fqn": node_fqn})
    return _build_impact_response(node_fqn, direction, max_depth, records)


def _build_impact_response(
    node_fqn: str,
    direction: str,
    max_depth: int,
    records: list[dict[str, Any]],
) -> ImpactAnalysisResponse:
    """Build an ImpactAnalysisResponse from query records."""
    affected = [
        AffectedNode(
            fqn=r["fqn"],
            name=r["name"],
            type=r["type"],
            file=r.get("file"),
            depth=r["depth"],
        )
        for r in records
    ]

    by_type: dict[str, int] = dict(Counter(a.type for a in affected))
    by_depth: dict[str, int] = dict(Counter(str(a.depth) for a in affected))

    return ImpactAnalysisResponse(
        node=node_fqn,
        direction=direction,
        max_depth=max_depth,
        summary=ImpactSummary(
            total=len(affected),
            by_type=by_type,
            by_depth=by_depth,
        ),
        affected=affected,
    )


# ── 2. Path Finder ──────────────────────────────────────


@router.get(
    "/{project_id}/path",
    response_model=PathFinderResponse,
)
async def find_path(
    project_id: str,
    from_fqn: str = Query(...),
    to_fqn: str = Query(...),
    max_depth: int = Query(10, ge=1, le=20),
) -> PathFinderResponse:
    """Find shortest path between two nodes."""
    store = get_graph_store()

    cypher = (
        f"MATCH path = shortestPath("
        f"(a {{fqn: $fromFqn}})-[*..{max_depth}]-(b {{fqn: $toFqn}}))"
        " RETURN [n IN nodes(path) |"
        " {fqn: n.fqn, name: n.name, type: labels(n)[0]}]"
        " AS nodes,"
        " [r IN relationships(path) |"
        " {type: type(r), source: startNode(r).fqn,"
        " target: endNode(r).fqn}] AS edges,"
        " length(path) AS pathLength"
    )
    records = await store.query(cypher, {"fromFqn": from_fqn, "toFqn": to_fqn})

    if not records:
        return PathFinderResponse(
            from_fqn=from_fqn,
            to_fqn=to_fqn,
            nodes=[],
            edges=[],
            path_length=0,
        )

    record = records[0]
    nodes = [PathNode(**n) for n in record["nodes"]]
    edges = [PathEdge(**e) for e in record["edges"]]

    return PathFinderResponse(
        from_fqn=from_fqn,
        to_fqn=to_fqn,
        nodes=nodes,
        edges=edges,
        path_length=record["pathLength"],
    )


# ── 3. Communities ──────────────────────────────────────


@router.get(
    "/{project_id}/communities",
    response_model=CommunitiesResponse,
)
async def list_communities(project_id: str) -> CommunitiesResponse:
    """List all detected communities."""
    store = get_graph_store()

    cypher = (
        "MATCH (c:Class) "
        "WHERE c.communityId IS NOT NULL AND c.app_name = $appName "
        "WITH c.communityId AS communityId, "
        "collect(c.name) AS members, count(*) AS size "
        "RETURN communityId, size, members ORDER BY size DESC"
    )
    records = await store.query(cypher, {"appName": project_id})

    communities = [
        CommunityInfo(
            community_id=r["communityId"],
            size=r["size"],
            members=r["members"],
        )
        for r in records
    ]

    return CommunitiesResponse(
        communities=communities,
        total=len(communities),
    )


# ── 4. Circular Dependencies ────────────────────────────


@router.get(
    "/{project_id}/circular-dependencies",
    response_model=CircularDependenciesResponse,
)
async def circular_dependencies(
    project_id: str,
    level: str = Query("module", pattern="^(module|class)$"),
) -> CircularDependenciesResponse:
    """Detect circular dependency cycles."""
    store = get_graph_store()

    if level == "module":
        cypher = (
            "MATCH path = (m:Module)-[:IMPORTS*2..6]->(m) "
            "WHERE m.app_name = $appName "
            "WITH [n IN nodes(path) | n.name] AS cycle, length(path) AS cycleLength "
            "RETURN DISTINCT cycle, cycleLength ORDER BY cycleLength LIMIT 50"
        )
    else:
        cypher = (
            "MATCH path = (c:Class)-[:DEPENDS_ON*2..4]->(c) "
            "WHERE c.app_name = $appName "
            "WITH [n IN nodes(path) | n.fqn] AS cycle, length(path) AS cycleLength "
            "RETURN DISTINCT cycle, cycleLength ORDER BY cycleLength LIMIT 50"
        )

    records = await store.query(cypher, {"appName": project_id})

    cycles = [
        CircularDependency(
            cycle=r["cycle"],
            cycle_length=r["cycleLength"],
        )
        for r in records
    ]

    return CircularDependenciesResponse(
        cycles=cycles,
        total=len(cycles),
        level=level,
    )


# ── 5. Dead Code ────────────────────────────────────────


@router.get(
    "/{project_id}/dead-code",
    response_model=DeadCodeResponse,
)
async def dead_code(
    project_id: str,
    node_type: str = Query("function", alias="type"),
    min_loc: int = Query(0, alias="minLoc"),
) -> DeadCodeResponse:
    """Find dead code candidates (nodes with no incoming calls)."""
    store = get_graph_store()

    if node_type == "function":
        cypher = (
            "MATCH (f:Function) "
            "WHERE f.app_name = $appName "
            "AND NOT (f)<-[:CALLS]-() "
            "AND NOT (f)<-[:HANDLES]-(:APIEndpoint) "
            "AND NOT (f)<-[:CONSUMES]-(:MessageTopic) "
            "AND f.loc >= $minLoc "
            "RETURN f.fqn AS fqn, f.name AS name, f.path AS path, "
            "f.line AS line, f.loc AS loc "
            "ORDER BY f.loc DESC LIMIT 100"
        )
    else:
        cypher = (
            "MATCH (c:Class) "
            "WHERE c.app_name = $appName "
            "AND NOT (c)<-[:DEPENDS_ON]-() "
            "AND NOT (c)<-[:CALLS]-() "
            "AND c.loc >= $minLoc "
            "RETURN c.fqn AS fqn, c.name AS name, c.path AS path, "
            "c.line AS line, c.loc AS loc "
            "ORDER BY c.loc DESC LIMIT 100"
        )

    records = await store.query(cypher, {"appName": project_id, "minLoc": min_loc})

    candidates = [
        DeadCodeCandidate(
            fqn=r["fqn"],
            name=r["name"],
            path=r.get("path"),
            line=r.get("line"),
            loc=r.get("loc"),
        )
        for r in records
    ]

    return DeadCodeResponse(
        candidates=candidates,
        total=len(candidates),
        type_filter=node_type,
    )


# ── 6. Metrics Dashboard ────────────────────────────────


@router.get(
    "/{project_id}/metrics",
    response_model=MetricsResponse,
)
async def metrics(project_id: str) -> MetricsResponse:
    """Get overview metrics for a project."""
    store = get_graph_store()

    # Overview stats
    overview_cypher = (
        "MATCH (n) WHERE n.app_name = $appName "
        "RETURN "
        "sum(CASE WHEN n.kind = 'MODULE' THEN 1 ELSE 0 END) AS modules, "
        "sum(CASE WHEN n.kind = 'CLASS' THEN 1 ELSE 0 END) AS classes, "
        "sum(CASE WHEN n.kind = 'FUNCTION' THEN 1 ELSE 0 END) AS functions, "
        "sum(CASE WHEN n.loc IS NOT NULL THEN n.loc ELSE 0 END) AS totalLoc"
    )
    overview_record = await store.query_single(overview_cypher, {"appName": project_id})
    overview = OverviewStats(
        modules=overview_record.get("modules", 0) if overview_record else 0,
        classes=overview_record.get("classes", 0) if overview_record else 0,
        functions=overview_record.get("functions", 0) if overview_record else 0,
        total_loc=overview_record.get("totalLoc", 0) if overview_record else 0,
    )

    # Most complex (top 10)
    complex_records = await store.query(
        "MATCH (c:Class) WHERE c.app_name = $appName AND c.complexity IS NOT NULL "
        "RETURN c.fqn AS fqn, c.name AS name, c.complexity AS value "
        "ORDER BY value DESC LIMIT 10",
        {"appName": project_id},
    )
    most_complex = [RankedItem(**r) for r in complex_records]

    # Highest fan-in (top 10)
    fan_in_records = await store.query(
        "MATCH (caller)-[:CALLS]->(target:Function) "
        "WHERE target.app_name = $appName "
        "WITH target, count(DISTINCT caller) AS value "
        "RETURN target.fqn AS fqn, target.name AS name, value "
        "ORDER BY value DESC LIMIT 10",
        {"appName": project_id},
    )
    highest_fan_in = [RankedItem(**r) for r in fan_in_records]

    # Highest fan-out (top 10)
    fan_out_records = await store.query(
        "MATCH (source:Function)-[:CALLS]->(callee) "
        "WHERE source.app_name = $appName "
        "WITH source, count(DISTINCT callee) AS value "
        "RETURN source.fqn AS fqn, source.name AS name, value "
        "ORDER BY value DESC LIMIT 10",
        {"appName": project_id},
    )
    highest_fan_out = [RankedItem(**r) for r in fan_out_records]

    # Community count
    community_records = await store.query(
        "MATCH (c:Class) WHERE c.app_name = $appName AND c.communityId IS NOT NULL "
        "WITH DISTINCT c.communityId AS cid "
        "RETURN count(cid) AS count",
        {"appName": project_id},
    )
    community_count = community_records[0]["count"] if community_records else 0

    # Circular dependency count
    circ_records = await store.query(
        "MATCH path = (m:Module)-[:IMPORTS*2..6]->(m) "
        "WHERE m.app_name = $appName "
        "WITH [n IN nodes(path) | n.name] AS cycle "
        "RETURN count(DISTINCT cycle) AS count",
        {"appName": project_id},
    )
    circular_dependency_count = circ_records[0]["count"] if circ_records else 0

    # Dead code count
    dead_records = await store.query(
        "MATCH (f:Function) WHERE f.app_name = $appName "
        "AND NOT (f)<-[:CALLS]-() "
        "AND NOT (f)<-[:HANDLES]-(:APIEndpoint) "
        "RETURN count(f) AS count",
        {"appName": project_id},
    )
    dead_code_count = dead_records[0]["count"] if dead_records else 0

    return MetricsResponse(
        overview=overview,
        most_complex=most_complex,
        highest_fan_in=highest_fan_in,
        highest_fan_out=highest_fan_out,
        community_count=community_count,
        circular_dependency_count=circular_dependency_count,
        dead_code_count=dead_code_count,
    )


# ── 7. Enhanced Node Details ────────────────────────────


@router.get(
    "/{project_id}/node/{node_fqn:path}/details",
    response_model=NodeDetailResponse,
)
async def node_details(
    project_id: str,
    node_fqn: str,
) -> NodeDetailResponse:
    """Get enhanced details for a specific node."""
    store = get_graph_store()

    # Get the node
    node_record = await store.query_single(
        "MATCH (n {fqn: $fqn, app_name: $appName}) "
        "OPTIONAL MATCH (caller)-[:CALLS]->(n) "
        "OPTIONAL MATCH (n)-[:CALLS]->(callee) "
        "RETURN n.fqn AS fqn, n.name AS name, labels(n)[0] AS type, "
        "n.language AS language, n.path AS path, n.line AS line, "
        "n.loc AS loc, n.complexity AS complexity, "
        "count(DISTINCT caller) AS fan_in, count(DISTINCT callee) AS fan_out, "
        "n.communityId AS communityId",
        {"fqn": node_fqn, "appName": project_id},
    )

    if node_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node {node_fqn} not found",
        )

    # Get callers
    caller_records = await store.query(
        "MATCH (caller)-[:CALLS]->(n {fqn: $fqn, app_name: $appName}) "
        "RETURN caller.fqn AS fqn, caller.name AS name, labels(caller)[0] AS type",
        {"fqn": node_fqn, "appName": project_id},
    )
    callers = [PathNode(**r) for r in caller_records]

    # Get callees
    callee_records = await store.query(
        "MATCH (n {fqn: $fqn, app_name: $appName})-[:CALLS]->(callee) "
        "RETURN callee.fqn AS fqn, callee.name AS name, labels(callee)[0] AS type",
        {"fqn": node_fqn, "appName": project_id},
    )
    callees = [PathNode(**r) for r in callee_records]

    return NodeDetailResponse(
        fqn=node_record["fqn"],
        name=node_record["name"],
        type=node_record["type"],
        language=node_record.get("language"),
        path=node_record.get("path"),
        line=node_record.get("line"),
        loc=node_record.get("loc"),
        complexity=node_record.get("complexity"),
        fan_in=node_record.get("fan_in", 0),
        fan_out=node_record.get("fan_out", 0),
        community_id=node_record.get("communityId"),
        callers=callers,
        callees=callees,
    )
