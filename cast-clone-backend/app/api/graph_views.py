"""Phase 2 graph view API endpoints — drill-down, transactions, code viewer."""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Project
from app.schemas.graph import GraphEdgeResponse, GraphNodeResponse
from app.schemas.graph_views import (
    AggregatedEdgeListResponse,
    AggregatedEdgeResponse,
    ArchitectureLayerResponse,
    ArchitectureLinkResponse,
    ArchitectureResponse,
    ClassListResponse,
    CodeViewerResponse,
    MethodListResponse,
    ModuleListResponse,
    ModuleResponse,
    NodeAncestorResponse,
    NodeAncestryResponse,
    TechnologyNodeResponse,
    TransactionDetailResponse,
    TransactionListResponse,
    TransactionSummary,
)
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/graph-views", tags=["graph-views"])

# Extension-to-language mapping for the code viewer
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".java": "java",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sql": "sql",
    ".xml": "xml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
}


def get_graph_store() -> Neo4jGraphStore:
    """Get a Neo4jGraphStore instance."""
    return Neo4jGraphStore(get_driver())


def _record_to_node(record: dict[str, Any]) -> GraphNodeResponse:
    """Convert a Neo4j record dict to a GraphNodeResponse."""
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


# ── Endpoint 1: List Modules ───────────────────────────────────────────


@router.get("/{project_id}/modules", response_model=ModuleListResponse)
async def list_modules(project_id: str) -> ModuleListResponse:
    """List all modules for a project with aggregated class counts."""
    store = get_graph_store()

    cypher = (
        "MATCH (n) WHERE n.app_name = $app_name AND n.kind = 'MODULE' "
        "OPTIONAL MATCH (n)-[:CONTAINS]->(c) "
        "WHERE c.kind = 'CLASS' OR c.kind = 'INTERFACE' "
        "WITH n, count(c) AS class_count "
        "RETURN n, class_count ORDER BY n.name"
    )
    records = await store.query(cypher, {"app_name": project_id})

    modules = [
        ModuleResponse(
            fqn=r["n"].get("fqn", ""),
            name=r["n"].get("name", ""),
            kind=r["n"].get("kind", "MODULE"),
            language=r["n"].get("language"),
            loc=r["n"].get("loc"),
            file_count=r["n"].get("file_count"),
            class_count=r.get("class_count", 0),
            properties={
                k: v
                for k, v in r["n"].items()
                if k
                not in {
                    "fqn",
                    "name",
                    "kind",
                    "language",
                    "loc",
                    "file_count",
                    "app_name",
                }
            },
        )
        for r in records
    ]

    return ModuleListResponse(modules=modules, total=len(modules))


# ── Endpoint 2: List Classes in Module ──────────────────────────────────


@router.get(
    "/{project_id}/modules/{fqn:path}/classes",
    response_model=ClassListResponse,
)
async def list_classes(project_id: str, fqn: str) -> ClassListResponse:
    """List classes and interfaces within a module."""
    store = get_graph_store()

    cypher = (
        "MATCH (m {fqn: $fqn, app_name: $app_name})-[:CONTAINS]->(c) "
        "WHERE c.app_name = $app_name AND (c.kind = 'CLASS' OR c.kind = 'INTERFACE') "
        "RETURN c AS n ORDER BY c.name"
    )
    records = await store.query(cypher, {"fqn": fqn, "app_name": project_id})

    classes = [_record_to_node(r) for r in records]

    return ClassListResponse(classes=classes, total=len(classes), parent_fqn=fqn)


# ── Endpoint 3: List Methods in Class ───────────────────────────────────


@router.get(
    "/{project_id}/classes/{fqn:path}/methods",
    response_model=MethodListResponse,
)
async def list_methods(project_id: str, fqn: str) -> MethodListResponse:
    """List methods/functions within a class."""
    store = get_graph_store()

    cypher = (
        "MATCH (c {fqn: $fqn, app_name: $app_name})-[:CONTAINS]->(f) "
        "WHERE f.app_name = $app_name AND f.kind = 'FUNCTION' "
        "RETURN f AS n ORDER BY f.name"
    )
    records = await store.query(cypher, {"fqn": fqn, "app_name": project_id})

    methods = [_record_to_node(r) for r in records]

    return MethodListResponse(methods=methods, total=len(methods), parent_fqn=fqn)


# ── Endpoint 4: Aggregated Edges ────────────────────────────────────────


class AggregationLevel(StrEnum):
    module = "module"
    klass = "class"


@router.get(
    "/{project_id}/edges/aggregated",
    response_model=AggregatedEdgeListResponse,
)
async def aggregated_edges(
    project_id: str,
    level: AggregationLevel = Query(
        ..., description="Aggregation level: module or class"
    ),
    parent: str | None = Query(
        None, description="Parent FQN (required for class level)"
    ),
) -> AggregatedEdgeListResponse:
    """Return aggregated edges between modules or classes."""
    store = get_graph_store()

    if level == AggregationLevel.klass:
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="'parent' query parameter is required "
                "for class-level aggregation",
            )
        # Class-level: aggregate method-to-method CALLS up to class pairs,
        # plus any direct class-to-class DEPENDS_ON edges.
        # Both source and target classes must be children of this module
        # (or any module) to avoid edges to bogus stub classes.
        cypher = (
            # Branch 1: method-level CALLS aggregated to owning classes
            "MATCH (m {fqn: $parent, app_name: $app_name})-[:CONTAINS]->(c1) "
            "WHERE c1.kind IN ['CLASS', 'INTERFACE'] "
            "MATCH (c1)-[:CONTAINS]->(f1)-[:CALLS]->(f2)<-[:CONTAINS]-(c2) "
            "WHERE c2.kind IN ['CLASS', 'INTERFACE'] AND c1 <> c2 "
            "AND EXISTS { MATCH (:Module)-[:CONTAINS]->(c2) } "
            "RETURN c1.fqn AS source, c2.fqn AS target, "
            "count(*) AS weight, 'CALLS' AS kind "
            "UNION ALL "
            # Branch 2: direct class-to-class DEPENDS_ON
            "MATCH (m {fqn: $parent, app_name: $app_name})"
            "-[:CONTAINS]->(c1) "
            "WHERE c1.kind IN ['CLASS', 'INTERFACE'] "
            "MATCH (c1)-[:DEPENDS_ON]->(c2) "
            "WHERE c2.kind IN ['CLASS', 'INTERFACE'] "
            "AND c1 <> c2 "
            "AND EXISTS { MATCH (:Module)-[:CONTAINS]->(c2) } "
            "RETURN c1.fqn AS source, c2.fqn AS target, "
            "count(*) AS weight, 'DEPENDS_ON' AS kind"
        )
        records = await store.query(cypher, {"parent": parent, "app_name": project_id})
        # Group by (source, target, kind)
        merged: dict[tuple[str, str, str], int] = {}
        for r in records:
            key = (r["source"], r["target"], r["kind"])
            merged[key] = merged.get(key, 0) + r["weight"]
        records = [
            {"source": k[0], "target": k[1], "weight": v, "kind": k[2]}
            for k, v in sorted(merged.items(), key=lambda x: -x[1])
        ]
    else:
        # Module-level: aggregate method-to-method CALLS across module
        # boundaries, plus direct class-to-class DEPENDS_ON.
        cypher = (
            # Branch 1: method-level CALLS traced through containment
            "MATCH (m1)-[:CONTAINS]->(c1)-[:CONTAINS]->(f1)"
            "-[:CALLS]->"
            "(f2)<-[:CONTAINS]-(c2)<-[:CONTAINS]-(m2) "
            "WHERE m1.app_name = $app_name AND m1.kind = 'MODULE' "
            "AND m2.kind = 'MODULE' AND m1 <> m2 "
            "RETURN m1.fqn AS source, m2.fqn AS target, "
            "count(*) AS weight, 'CALLS' AS kind "
            "UNION ALL "
            # Branch 2: direct class-to-class DEPENDS_ON
            "MATCH (m1)-[:CONTAINS]->(c1)"
            "-[:DEPENDS_ON]->(c2)<-[:CONTAINS]-(m2) "
            "WHERE m1.app_name = $app_name "
            "AND m1.kind = 'MODULE' "
            "AND m2.kind = 'MODULE' AND m1 <> m2 "
            "AND c1.kind IN ['CLASS', 'INTERFACE'] "
            "AND c2.kind IN ['CLASS', 'INTERFACE'] "
            "RETURN m1.fqn AS source, m2.fqn AS target, "
            "count(*) AS weight, 'DEPENDS_ON' AS kind"
        )
        records = await store.query(cypher, {"app_name": project_id})
        # Group by (source, target, kind) — keep CALLS and DEPENDS_ON separate
        merged = {}
        for r in records:
            key = (r["source"], r["target"], r["kind"])
            merged[key] = merged.get(key, 0) + r["weight"]
        records = [
            {"source": k[0], "target": k[1], "weight": v, "kind": k[2]}
            for k, v in sorted(merged.items(), key=lambda x: -x[1])
        ]

    edges = [
        AggregatedEdgeResponse(
            source=r["source"],
            target=r["target"],
            weight=r["weight"],
            kind=r.get("kind", "CALLS"),
        )
        for r in records
    ]

    return AggregatedEdgeListResponse(edges=edges, total=len(edges), level=level.value)


# ── Endpoint 5: List Transactions ───────────────────────────────────────


@router.get(
    "/{project_id}/transactions",
    response_model=TransactionListResponse,
)
async def list_transactions(project_id: str) -> TransactionListResponse:
    """List all transaction nodes for a project."""
    store = get_graph_store()

    cypher = (
        "MATCH (n) WHERE n.app_name = $app_name AND n.kind = 'TRANSACTION' "
        "RETURN n ORDER BY n.name"
    )
    records = await store.query(cypher, {"app_name": project_id})

    transactions = [
        TransactionSummary(
            fqn=r["n"].get("fqn", ""),
            name=r["n"].get("name", ""),
            kind=r["n"].get("kind", "TRANSACTION"),
            properties={
                k: v
                for k, v in r["n"].items()
                if k not in {"fqn", "name", "kind", "app_name"}
            },
        )
        for r in records
    ]

    return TransactionListResponse(transactions=transactions, total=len(transactions))


# ── Endpoint 6: Transaction Detail ──────────────────────────────────────


@router.get(
    "/{project_id}/transactions/{fqn:path}",
    response_model=TransactionDetailResponse,
)
async def get_transaction(project_id: str, fqn: str) -> TransactionDetailResponse:
    """Get the full call graph for a specific transaction."""
    store = get_graph_store()

    # First, verify the transaction exists
    txn_result = await store.query_single(
        "MATCH (n {fqn: $fqn, app_name: $app_name}) "
        "WHERE n.kind = 'TRANSACTION' RETURN n",
        {"fqn": fqn, "app_name": project_id},
    )
    if txn_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {fqn} not found in project {project_id}",
        )

    # Get all nodes included in the transaction
    node_records = await store.query(
        "MATCH (t {fqn: $fqn, app_name: $app_name})-[:INCLUDES]->(f) RETURN f AS n",
        {"fqn": fqn, "app_name": project_id},
    )
    nodes = [_record_to_node(r) for r in node_records]

    # Get edges between the included nodes.
    # Include CALLS (including virtual-dispatch synthetic edges), WRITES,
    # READS (data flow), INJECTS (Spring DI), and DEPENDS_ON.
    # IMPLEMENTS edges are not needed here — the enricher's virtual dispatch
    # step already creates CALLS edges from interface → implementation methods.
    edge_records = await store.query(
        "MATCH (t {fqn: $fqn, app_name: $app_name})-[:INCLUDES]->(f1) "
        "MATCH (f1)-[r:CALLS|WRITES|READS|INJECTS|DEPENDS_ON]->(f2) "
        "WHERE (t)-[:INCLUDES]->(f2) "
        "RETURN f1.fqn AS source_fqn, f2.fqn AS target_fqn, "
        "type(r) AS kind, r.confidence AS confidence, r.evidence AS evidence",
        {"fqn": fqn, "app_name": project_id},
    )
    edges = [_record_to_edge(r) for r in edge_records]

    txn_node = txn_result["n"]
    return TransactionDetailResponse(
        fqn=txn_node.get("fqn", ""),
        name=txn_node.get("name", ""),
        nodes=nodes,
        edges=edges,
    )


# ── Endpoint 7: Architecture View ──────────────────────────────────────


@router.get("/{project_id}/architecture", response_model=ArchitectureResponse)
async def get_architecture(project_id: str) -> ArchitectureResponse:
    """Return the architecture view: technology layers, components, and links."""
    store = get_graph_store()

    # 1. Get APPLICATION node metadata
    app_result = await store.query_single(
        "MATCH (a) WHERE a.app_name = $app_name AND a.kind = 'APPLICATION' RETURN a",
        {"app_name": project_id},
    )
    languages: list[str] = []
    frameworks: list[str] = []
    if app_result:
        a = app_result["a"]
        languages = a.get("detected_languages", a.get("languages", []))
        frameworks = a.get("detected_frameworks", a.get("frameworks", []))

    # 2. Get Layer -> CONTAINS -> Component hierarchy
    layer_records = await store.query(
        "MATCH (l) WHERE l.app_name = $app_name AND l.kind = 'LAYER' "
        "OPTIONAL MATCH (l)-[:CONTAINS]->(t) "
        "WHERE t.kind = 'COMPONENT' AND t.type = 'technology' "
        "RETURN l, collect(t) AS techs ORDER BY l.name",
        {"app_name": project_id},
    )

    layers: list[ArchitectureLayerResponse] = []
    for r in layer_records:
        l_node = r["l"]
        techs_raw = r["techs"]

        tech_nodes: list[TechnologyNodeResponse] = []
        total_classes = 0
        total_loc = 0

        for t in techs_raw:
            if t is None:
                continue
            class_count = t.get("class_count", 0)
            loc_total = t.get("loc_total", 0)
            total_classes += class_count
            total_loc += loc_total

            tech_nodes.append(
                TechnologyNodeResponse(
                    fqn=t.get("fqn", ""),
                    name=t.get("name", ""),
                    category=t.get("category", ""),
                    language=t.get("language"),
                    layer=t.get("layer", ""),
                    class_count=class_count,
                    loc_total=loc_total,
                    endpoint_count=t.get("endpoint_count", 0),
                    table_count=t.get("table_count", 0),
                    properties={
                        k: v
                        for k, v in t.items()
                        if k
                        not in {
                            "fqn",
                            "name",
                            "kind",
                            "category",
                            "language",
                            "layer",
                            "class_count",
                            "loc_total",
                            "endpoint_count",
                            "table_count",
                            "app_name",
                            "type",
                        }
                    },
                )
            )

        layers.append(
            ArchitectureLayerResponse(
                fqn=l_node.get("fqn", ""),
                name=l_node.get("name", ""),
                technologies=tech_nodes,
                total_classes=total_classes,
                total_loc=total_loc,
            )
        )

    # 3. Aggregate class-level edges up to Component pairs
    link_records = await store.query(
        "MATCH (t1 {app_name: $app_name, "
        "kind: 'COMPONENT', type: 'technology'})"
        "-[:CONTAINS]->(c1)"
        "-[r:CALLS|DEPENDS_ON|INJECTS|READS|"
        "WRITES|CALLS_API|MAPS_TO]->"
        "(c2)<-[:CONTAINS]-"
        "(t2 {app_name: $app_name, "
        "kind: 'COMPONENT', type: 'technology'}) "
        "WHERE t1 <> t2 "
        "RETURN t1.fqn AS source, "
        "t2.fqn AS target, "
        "type(r) AS kind, count(*) AS cnt",
        {"app_name": project_id},
    )

    # Merge by (source, target) -> aggregate weight and collect kinds
    link_map: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for r in link_records:
        pair = (r["source"], r["target"])
        link_map[pair][r["kind"]] += r["cnt"]

    links: list[ArchitectureLinkResponse] = []
    for (src, tgt), kinds_map in sorted(
        link_map.items(), key=lambda x: -sum(x[1].values())
    ):
        links.append(
            ArchitectureLinkResponse(
                source=src,
                target=tgt,
                weight=sum(kinds_map.values()),
                kinds=sorted(kinds_map.keys()),
            )
        )

    return ArchitectureResponse(
        app_name=project_id,
        languages=languages,
        frameworks=frameworks,
        layers=layers,
        links=links,
    )


# ── Endpoint 8: Code Viewer ─────────────────────────────────────────────


@router.get("/{project_id}/code", response_model=CodeViewerResponse)
async def get_code(
    project_id: str,
    file: str = Query(..., description="Relative file path within the project"),
    line: int | None = Query(None, description="Line to highlight"),
    context: int = Query(30, description="Lines of context around highlight line"),
    session: AsyncSession = Depends(get_session),
) -> CodeViewerResponse:
    """Read source code from the project's filesystem."""
    # Look up the project to get source_path
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # Build and validate the full path (prevent path traversal)
    source_dir = Path(project.source_path).resolve()
    full_path = (source_dir / file).resolve()

    if not full_path.is_relative_to(source_dir):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path: path traversal detected",
        )

    if not full_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {file}",
        )

    # Guard against very large files (2 MB limit)
    max_file_bytes = 2 * 1024 * 1024
    if full_path.stat().st_size > max_file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large to display in code viewer",
        )

    # Read the file
    async with aiofiles.open(full_path, encoding="utf-8", errors="replace") as f:
        all_lines = await f.readlines()

    total_lines = len(all_lines)

    # If a highlight line is given, return a window around it
    if line is not None:
        start = max(0, line - context - 1)
        end = min(total_lines, line + context)
        content = "".join(all_lines[start:end])
        start_line = start + 1
    else:
        content = "".join(all_lines)
        start_line = 1

    # Infer language from extension
    ext = full_path.suffix.lower()
    language = _EXT_TO_LANGUAGE.get(ext, "plaintext")

    return CodeViewerResponse(
        content=content,
        language=language,
        start_line=start_line,
        highlight_line=line,
        total_lines=total_lines,
    )


# ── Endpoint 9: Node Ancestry ─────────────────────────────────────────────


@router.get(
    "/{project_id}/ancestry/{fqn:path}",
    response_model=NodeAncestryResponse,
)
async def get_node_ancestry(project_id: str, fqn: str) -> NodeAncestryResponse:
    """Return the containment path from the root module down to a node.

    This is used by the graph search to know which modules/classes to
    drill into in order to reveal a search result in the graph.
    """
    store = get_graph_store()

    # Walk up CONTAINS edges to find ancestor chain
    cypher = (
        "MATCH path = (ancestor)-[:CONTAINS*]->(n {fqn: $fqn, app_name: $app_name}) "
        "WHERE ancestor.app_name = $app_name AND NOT ()-[:CONTAINS]->(ancestor) "
        "RETURN [node IN nodes(path) | {fqn: node.fqn, name: node.name, kind: node.kind}] AS chain "
        "LIMIT 1"
    )
    result = await store.query_single(cypher, {"fqn": fqn, "app_name": project_id})

    if result is None:
        # Node exists but has no parent — it might be a top-level module itself
        node_result = await store.query_single(
            "MATCH (n {fqn: $fqn, app_name: $app_name}) "
            "RETURN n.fqn AS fqn, n.name AS name, n.kind AS kind",
            {"fqn": fqn, "app_name": project_id},
        )
        if node_result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Node {fqn} not found in project {project_id}",
            )
        return NodeAncestryResponse(
            fqn=fqn,
            ancestors=[
                NodeAncestorResponse(
                    fqn=node_result["fqn"],
                    name=node_result["name"],
                    kind=node_result["kind"],
                )
            ],
        )

    chain = result["chain"]
    ancestors = [
        NodeAncestorResponse(fqn=item["fqn"], name=item["name"], kind=item["kind"])
        for item in chain
    ]

    return NodeAncestryResponse(fqn=fqn, ancestors=ancestors)
