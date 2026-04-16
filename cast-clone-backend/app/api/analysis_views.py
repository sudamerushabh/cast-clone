"""Phase 3 analysis API endpoints — impact, paths, communities, metrics."""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.summaries import (
    compute_trace_hash,
    generate_trace_chat_reply,
    generate_trace_summary_text,
)
from app.api.dependencies import get_accessible_project, get_current_user
from app.config import get_settings
from app.models.db import (
    AiSummary,
    AiTraceChatMessage,
    AnalysisRun,
    Project,
    User,
)
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
    TraceChatHistoryResponse,
    TraceChatMessage,
    TraceChatSendRequest,
    TraceChatSendResponse,
    TraceEdge,
    TraceNode,
    TraceRouteResponse,
    TraceSummaryResponse,
)
from app.services.ai_provider import (
    create_bedrock_client,
    create_openai_client,
    get_ai_config,
)
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis-views"])


async def get_graph_store() -> Neo4jGraphStore:
    """Get a Neo4jGraphStore instance (FastAPI dependency)."""
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
    # NOTE: Cypher does not support parameterized relationship hop counts;
    # max_depth is validated via Query(ge=1, le=10) to prevent injection.
    max_depth: int = Query(5, ge=1, le=10),
    _: Project = Depends(get_accessible_project),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> ImpactAnalysisResponse:
    """Compute blast radius for a node."""
    # Edge types used by impact analysis (broader than trace route)
    _down_edges = (
        "CALLS|INJECTS|IMPLEMENTS|PRODUCES"
        "|WRITES|READS|CONTAINS|DEPENDS_ON"
    )
    _up_edges = (
        "CALLS|IMPLEMENTS|DEPENDS_ON|INHERITS"
        "|INJECTS|CONSUMES|READS|INCLUDES"
    )
    try:
        if direction == "downstream":
            cypher = (
                "MATCH path = (start "
                "{fqn: $fqn, app_name: $appName})"
                f"-[:{_down_edges}*1..{max_depth}]"
                "->(affected) "
                "WHERE affected.app_name = $appName "
                "AND affected.fqn <> $fqn "
                "WITH affected, min(length(path)) AS depth "
                "RETURN affected.fqn AS fqn, "
                "affected.name AS name, "
                "labels(affected)[0] AS type, "
                "affected.path AS file, depth "
                "ORDER BY depth, name"
            )
            records = await store.query(
                cypher,
                {"fqn": node_fqn, "appName": project_id},
            )
        elif direction == "upstream":
            cypher = (
                "MATCH (start "
                "{fqn: $fqn, app_name: $appName})"
                "-[:CONTAINS*0..10]->(seed) "
                "WITH collect(DISTINCT seed.fqn) "
                "AS seed_fqns "
                "MATCH (dependent "
                f"{{app_name: $appName}})"
                f"-[:{_up_edges}*1..{max_depth}]"
                "->(target) "
                "WHERE target.fqn IN seed_fqns "
                "AND dependent.fqn <> $fqn "
                "AND NOT dependent.fqn "
                "STARTS WITH $fqnPrefix "
                "WITH DISTINCT dependent, 1 AS depth "
                "RETURN dependent.fqn AS fqn, "
                "dependent.name AS name, "
                "labels(dependent)[0] AS type, "
                "dependent.path AS file, depth "
                "ORDER BY depth, name"
            )
            records = await store.query(
                cypher,
                {
                    "fqn": node_fqn,
                    "appName": project_id,
                    "fqnPrefix": node_fqn + ".",
                },
            )
        else:
            # both: run downstream then upstream and merge
            downstream_cypher = (
                "MATCH path = (start "
                "{fqn: $fqn, app_name: $appName})"
                f"-[:{_down_edges}*1..{max_depth}]"
                "->(affected) "
                "WHERE affected.app_name = $appName "
                "AND affected.fqn <> $fqn "
                "WITH affected, min(length(path)) AS depth "
                "RETURN affected.fqn AS fqn, "
                "affected.name AS name, "
                "labels(affected)[0] AS type, "
                "affected.path AS file, depth "
                "ORDER BY depth, name"
            )
            upstream_cypher = (
                "MATCH (start "
                "{fqn: $fqn, app_name: $appName})"
                "-[:CONTAINS*0..10]->(seed) "
                "WITH collect(DISTINCT seed.fqn) "
                "AS seed_fqns "
                "MATCH (dependent "
                f"{{app_name: $appName}})"
                f"-[:{_up_edges}*1..{max_depth}]"
                "->(target) "
                "WHERE target.fqn IN seed_fqns "
                "AND dependent.fqn <> $fqn "
                "AND NOT dependent.fqn "
                "STARTS WITH $fqnPrefix "
                "WITH DISTINCT dependent, 1 AS depth "
                "RETURN dependent.fqn AS fqn, "
                "dependent.name AS name, "
                "labels(dependent)[0] AS type, "
                "dependent.path AS file, depth "
                "ORDER BY depth, name"
            )
            fqn_params = {
                "fqn": node_fqn,
                "appName": project_id,
                "fqnPrefix": node_fqn + ".",
            }
            down_records = await store.query(
                downstream_cypher, {"fqn": node_fqn, "appName": project_id}
            )
            up_records = await store.query(
                upstream_cypher, fqn_params
            )
            # Merge: deduplicate by fqn, keep minimum depth
            seen: dict[str, dict[str, Any]] = {}
            for r in down_records + up_records:
                fqn = r["fqn"]
                if fqn not in seen or r["depth"] < seen[fqn]["depth"]:
                    seen[fqn] = r
            records = sorted(
                seen.values(), key=lambda x: (x["depth"], x.get("name", ""))
            )
            return _build_impact_response(node_fqn, direction, max_depth, records)

        return _build_impact_response(node_fqn, direction, max_depth, records)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("impact_analysis_failed", node_fqn=node_fqn, error=str(exc))
        raise HTTPException(status_code=500, detail="Analysis query failed") from exc


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


# ── 1b. Trace Route ────────────────────────────────────

# Node kinds meaningful for execution trace (filter out FIELD, COLUMN, etc.)
_TRACE_NODE_KINDS = (
    "FUNCTION",
    "CLASS",
    "INTERFACE",
    "API_ENDPOINT",
    "TABLE",
    "STORED_PROCEDURE",
    "ROUTE",
)

# Execution-flow + data-access edges (READS/WRITES connect repo → table).
# IMPLEMENTS bridges .NET interface methods to concrete implementations.
# Structural edges (CONTAINS, DEPENDS_ON, IMPORTS) are still excluded.
# Node kind filtering prevents READS/WRITES noise from FIELDs/COLUMNs.
_TRACE_EDGE_TYPES = (
    "CALLS|HANDLES|CALLS_API|PRODUCES|CONSUMES|READS|WRITES|IMPLEMENTS"
)

# Canonical layer ordering for swim-lane display (top to bottom)
_LAYER_ORDER = ["api", "service", "repository", "database", "other"]

_DB_KINDS = {"TABLE", "STORED_PROCEDURE", "VIEW", "COLUMN"}
_API_KINDS = {"API_ENDPOINT", "ROUTE"}
_CONTROLLER_RE = re.compile(r"controller", re.IGNORECASE)
_REPO_RE = re.compile(r"repositor|\.repo\b", re.IGNORECASE)
_SERVICE_RE = re.compile(r"service", re.IGNORECASE)


def _detect_layer(
    fqn: str,
    kind: str,
    rw_source_fqns: set[str],
) -> str:
    """Classify a node into an architectural layer.

    Args:
        fqn: Fully qualified name of the node.
        kind: Node kind (FUNCTION, TABLE, etc.).
        rw_source_fqns: Set of FQNs that are sources of
            READS/WRITES edges (i.e., repository methods).

    Returns one of: api, service, repository, database, other.
    Rules are checked in priority order; first match wins.
    """
    if kind in _DB_KINDS:
        return "database"
    if kind in _API_KINDS or _CONTROLLER_RE.search(fqn):
        return "api"
    if _REPO_RE.search(fqn) or fqn in rw_source_fqns:
        return "repository"
    if _SERVICE_RE.search(fqn):
        return "service"
    return "other"


@router.get(
    "/{project_id}/trace/{node_fqn:path}",
    response_model=TraceRouteResponse,
)
async def trace_route(
    project_id: str,
    node_fqn: str,
    # NOTE: Cypher does not support parameterized relationship hop counts;
    # max_depth is validated via Query(ge=1, le=10) to prevent injection.
    max_depth: int = Query(5, ge=1, le=10),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> TraceRouteResponse:
    """Compute the execution trace (call chain) for a node.

    Unlike impact analysis which follows all relationship types,
    trace route only follows execution-flow edges (CALLS, HANDLES,
    CALLS_API, PRODUCES, CONSUMES) and filters to meaningful node
    kinds (functions, classes, endpoints, tables).

    Returns BFS-ordered sequence numbers for visualizing call order.
    """
    try:
        # ── Fetch center node metadata ──────────────────────────
        center_cypher = (
            "MATCH (n {fqn: $fqn, app_name: $appName}) "
            "RETURN n.fqn AS fqn, n.name AS name, n.kind AS kind"
        )
        center_record = await store.query_single(
            center_cypher, {"fqn": node_fqn, "appName": project_id}
        )
        if center_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Node {node_fqn} not found",
            )
        center_name = center_record["name"]
        center_kind = center_record["kind"] or "FUNCTION"

        # ── Downstream: functions called by this node ───────────
        downstream_cypher = (
            f"MATCH path = (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:{_TRACE_EDGE_TYPES}*1..{max_depth}]->(affected) "
            "WHERE affected.app_name = $appName "
            "AND affected.fqn <> $fqn "
            "AND affected.kind IN $kinds "
            "WITH affected, min(length(path)) AS depth "
            "RETURN affected.fqn AS fqn, affected.name AS name, "
            "affected.kind AS kind, affected.path AS file, "
            "affected.language AS language, depth "
            "ORDER BY depth, name"
        )

        # ── Upstream: functions that call this node ─────────────
        upstream_cypher = (
            f"MATCH path = (caller)"
            f"-[:{_TRACE_EDGE_TYPES}*1..{max_depth}]->"
            "(target {fqn: $fqn, app_name: $appName}) "
            "WHERE caller.app_name = $appName "
            "AND caller.fqn <> $fqn "
            "AND caller.kind IN $kinds "
            "WITH caller, min(length(path)) AS depth "
            "RETURN caller.fqn AS fqn, caller.name AS name, "
            "caller.kind AS kind, caller.path AS file, "
            "caller.language AS language, depth "
            "ORDER BY depth, name"
        )

        params = {
            "fqn": node_fqn,
            "appName": project_id,
            "kinds": list(_TRACE_NODE_KINDS),
        }
        down_records, up_records = await _parallel_queries(
            store, downstream_cypher, upstream_cypher, params
        )

        # ── Fetch edges FIRST (need rw_source_fqns for layer) ──
        all_fqns = (
            [node_fqn]
            + [r["fqn"] for r in down_records]
            + [r["fqn"] for r in up_records]
        )

        edges_cypher = (
            f"MATCH (a)-[r:{_TRACE_EDGE_TYPES}]->(b) "
            "WHERE a.fqn IN $fqns AND b.fqn IN $fqns "
            "AND a.app_name = $appName "
            "AND b.app_name = $appName "
            "RETURN DISTINCT a.fqn AS source, "
            "b.fqn AS target, type(r) AS type"
        )
        edge_records = await store.query(
            edges_cypher,
            {"fqns": all_fqns, "appName": project_id},
        )

        rw_source_fqns: set[str] = set()
        for r in edge_records:
            if r["type"] in ("READS", "WRITES"):
                rw_source_fqns.add(r["source"])

        # ── Hide interface methods when concrete impl is in trace ─
        # For each IMPLEMENTS edge whose source (interface method) and
        # target (concrete method) are both in the trace, drop the
        # interface method. This removes visually duplicate pairs like
        # `IStockSubscriptionService.Foo` + `StockSubscriptionService.Foo`
        # that appear whenever a trace crosses a .NET DI boundary.
        trace_fqn_set = set(all_fqns)
        iface_methods_to_hide: set[str] = set()
        for r in edge_records:
            if (
                r["type"] == "IMPLEMENTS"
                and r["source"] in trace_fqn_set
                and r["target"] in trace_fqn_set
            ):
                iface_methods_to_hide.add(r["source"])

        if iface_methods_to_hide:
            down_records = [
                r for r in down_records
                if r["fqn"] not in iface_methods_to_hide
            ]
            up_records = [
                r for r in up_records
                if r["fqn"] not in iface_methods_to_hide
            ]
            edge_records = [
                r for r in edge_records
                if r["source"] not in iface_methods_to_hide
                and r["target"] not in iface_methods_to_hide
            ]

        # ── Build trace nodes with layer + sequence ────────────
        downstream_nodes = [
            TraceNode(
                fqn=r["fqn"],
                name=r["name"],
                kind=r["kind"] or "FUNCTION",
                file=r.get("file"),
                language=r.get("language"),
                depth=r["depth"],
                sequence=idx + 1,
                direction="downstream",
                layer=_detect_layer(
                    r["fqn"],
                    r["kind"] or "FUNCTION",
                    rw_source_fqns,
                ),
            )
            for idx, r in enumerate(down_records)
        ]

        upstream_nodes = [
            TraceNode(
                fqn=r["fqn"],
                name=r["name"],
                kind=r["kind"] or "FUNCTION",
                file=r.get("file"),
                language=r.get("language"),
                depth=r["depth"],
                sequence=idx + 1,
                direction="upstream",
                layer=_detect_layer(
                    r["fqn"],
                    r["kind"] or "FUNCTION",
                    rw_source_fqns,
                ),
            )
            for idx, r in enumerate(up_records)
        ]

        # ── Build edge list ────────────────────────────────────
        downstream_fqn_seq = {
            n.fqn: n.sequence for n in downstream_nodes
        }
        upstream_fqn_seq = {
            n.fqn: n.sequence for n in upstream_nodes
        }

        trace_edges = [
            TraceEdge(
                source=r["source"],
                target=r["target"],
                type=r["type"],
                sequence=downstream_fqn_seq.get(
                    r["target"],
                    upstream_fqn_seq.get(r["source"]),
                ),
            )
            for r in edge_records
        ]
        trace_edges.sort(
            key=lambda e: (e.sequence or 999, e.source)
        )

        # ── Layer aggregation ──────────────────────────────────
        center_layer = _detect_layer(
            node_fqn, center_kind, rw_source_fqns
        )
        all_layers = {center_layer}
        for n in downstream_nodes:
            all_layers.add(n.layer)
        for n in upstream_nodes:
            all_layers.add(n.layer)
        layers_present = [
            la for la in _LAYER_ORDER if la in all_layers
        ]

        return TraceRouteResponse(
            center_fqn=node_fqn,
            center_name=center_name,
            center_kind=center_kind,
            center_layer=center_layer,
            max_depth=max_depth,
            upstream=upstream_nodes,
            downstream=downstream_nodes,
            edges=trace_edges,
            upstream_count=len(upstream_nodes),
            downstream_count=len(downstream_nodes),
            layers_present=layers_present,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("trace_route_failed", node_fqn=node_fqn, error=str(exc))
        raise HTTPException(status_code=500, detail="Trace route query failed") from exc


async def _parallel_queries(
    store: Neo4jGraphStore,
    cypher_a: str,
    cypher_b: str,
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run two Cypher queries in parallel using asyncio.gather."""

    results = await asyncio.gather(
        store.query(cypher_a, params),
        store.query(cypher_b, params),
    )
    return results[0], results[1]


def _friendly_ai_error(provider: str, exc: Exception) -> str:
    """Translate provider exceptions into user-actionable messages.

    These strings surface directly in the AI summary panel via the
    503 response `detail` field. The frontend treats 503 as a
    configuration error and renders a "Configure AI" link.
    """
    name = type(exc).__name__
    msg = str(exc).lower()
    provider_label = provider.title() if provider else "AI"

    # Authentication / authorization
    if name in ("PermissionDeniedError", "NoCredentialsError"):
        return (
            f"{provider_label} credentials are invalid or missing. "
            "Update the provider configuration in Settings."
        )
    if name == "AuthenticationError" or "unauthorized" in msg:
        return (
            f"{provider_label} authentication failed. "
            "Check your API key in Settings."
        )

    # Quota / rate limits
    if name == "RateLimitError" or "quota" in msg or "rate limit" in msg:
        return (
            f"{provider_label} rate limit or quota exceeded. "
            "Wait a moment and retry, or check quota in Settings."
        )

    # Network / connectivity
    if name in (
        "EndpointConnectionError",
        "ConnectionError",
        "APIConnectionError",
        "ReadTimeoutError",
    ):
        return (
            f"Cannot reach {provider_label}. "
            "Check network connectivity and retry."
        )

    # Model availability
    if "model" in msg and ("not found" in msg or "does not exist" in msg):
        return (
            f"{provider_label} model is unavailable in this region. "
            "Pick a different model in Settings."
        )

    # Fallback
    return (
        f"{provider_label} request failed ({name}). "
        "Check AI configuration in Settings."
    )


# ── 1c. Trace Summary ─────────────────────────────────


@router.get(
    "/{project_id}/trace-summary/{node_fqn:path}",
    response_model=TraceSummaryResponse,
)
async def trace_summary(
    project_id: str,
    node_fqn: str,
    max_depth: int = Query(5, ge=1, le=10),
    store: Neo4jGraphStore = Depends(get_graph_store),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> TraceSummaryResponse:
    """Generate an AI summary of a node's trace route."""
    trace_resp = await trace_route(
        project_id=project_id,
        node_fqn=node_fqn,
        max_depth=max_depth,
        store=store,
    )

    if (
        not trace_resp.upstream
        and not trace_resp.downstream
    ):
        return TraceSummaryResponse(
            fqn=node_fqn,
            summary="No upstream or downstream "
            "connections found for this node.",
            layers_involved=[],
            tables_touched=[],
            cached=False,
        )

    # Deduplicate tables by (name, access_type). The same table often
    # gets hit by multiple READS edges in a trace — we only want to
    # list each distinct (table, access) pair once for the AI prompt
    # and for the response badge list.
    seen_tables: set[tuple[str, str]] = set()
    tables_touched: list[dict[str, str]] = []
    for edge in trace_resp.edges:
        if edge.type in ("READS", "WRITES"):
            target_name = edge.target.split(":")[-1]
            pair = (target_name, edge.type)
            if pair in seen_tables:
                continue
            seen_tables.add(pair)
            tables_touched.append(
                {
                    "name": target_name,
                    "access_type": edge.type,
                }
            )

    trace_context = {
        "center": {
            "name": trace_resp.center_name,
            "kind": trace_resp.center_kind,
            "layer": trace_resp.center_layer,
            "fqn": trace_resp.center_fqn,
        },
        "upstream": [
            {
                "name": n.name,
                "kind": n.kind,
                "layer": n.layer,
                "fqn": n.fqn,
                "sequence": n.sequence,
            }
            for n in trace_resp.upstream
        ],
        "downstream": [
            {
                "name": n.name,
                "kind": n.kind,
                "layer": n.layer,
                "fqn": n.fqn,
                "sequence": n.sequence,
            }
            for n in trace_resp.downstream
        ],
        "tables_touched": tables_touched,
        "layers_involved": trace_resp.layers_present,
    }

    current_hash = compute_trace_hash(trace_context)
    cache_key = f"trace:{node_fqn}"
    result = await session.execute(
        sa_select(AiSummary).where(
            AiSummary.project_id == project_id,
            AiSummary.node_fqn == cache_key,
        )
    )
    cached = result.scalar_one_or_none()

    unique_table_names = list(
        dict.fromkeys(t["name"] for t in tables_touched)
    )

    if cached and cached.graph_hash == current_hash:
        return TraceSummaryResponse(
            fqn=node_fqn,
            summary=cached.summary,
            layers_involved=trace_resp.layers_present,
            tables_touched=unique_table_names,
            cached=True,
            model=cached.model,
            tokens_used=cached.tokens_used,
        )

    settings = get_settings()
    ai_config = await get_ai_config(session)
    if ai_config.provider == "openai":
        client = create_openai_client(ai_config)
    else:
        client = create_bedrock_client(ai_config)

    try:
        summary_text, tokens_used = (
            await generate_trace_summary_text(
                client=client,
                model=ai_config.summary_model,
                max_tokens=settings.summary_max_tokens,
                trace_context=trace_context,
                ai_config=ai_config,
            )
        )
    except Exception as exc:  # noqa: BLE001
        # Surface AI provider failures as a structured response
        # (invalid credentials, quota exceeded, network errors, etc.)
        # so the frontend can display its "AI unavailable" state
        # instead of crashing with a 500.
        logger.error(
            "trace_summary_ai_call_failed",
            project_id=project_id,
            node_fqn=node_fqn,
            provider=ai_config.provider,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        detail = _friendly_ai_error(ai_config.provider, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        ) from exc

    from sqlalchemy.dialects.postgresql import (
        insert as pg_insert,
    )

    # Link this summary to the latest completed analysis run for the
    # project so we can audit "this cache entry was generated against
    # which scan." Optional — fine if no run exists yet.
    latest_run_result = await session.execute(
        sa_select(AnalysisRun.id)
        .where(AnalysisRun.project_id == project_id)
        .order_by(AnalysisRun.started_at.desc())
        .limit(1)
    )
    latest_run_id = latest_run_result.scalar_one_or_none()

    stmt = (
        pg_insert(AiSummary)
        .values(
            project_id=project_id,
            analysis_run_id=latest_run_id,
            node_fqn=cache_key,
            summary=summary_text,
            model=ai_config.summary_model,
            graph_hash=current_hash,
            tokens_used=tokens_used,
        )
        .on_conflict_do_update(
            index_elements=["project_id", "node_fqn"],
            set_={
                "analysis_run_id": latest_run_id,
                "summary": summary_text,
                "model": ai_config.summary_model,
                "graph_hash": current_hash,
                "tokens_used": tokens_used,
            },
        )
    )
    await session.execute(stmt)
    await session.commit()

    return TraceSummaryResponse(
        fqn=node_fqn,
        summary=summary_text,
        layers_involved=trace_resp.layers_present,
        tables_touched=unique_table_names,
        cached=False,
        model=ai_config.summary_model,
        tokens_used=tokens_used,
    )


# ── 1d. Trace Follow-up Chat ─────────────────────────────


def _chat_row_to_dto(row: AiTraceChatMessage) -> TraceChatMessage:
    return TraceChatMessage(
        id=row.id,
        role=row.role,
        content=row.content,
        created_at=row.created_at.isoformat(),
        model=row.model,
        tokens_used=row.tokens_used,
    )


@router.get(
    "/{project_id}/trace-chat/{node_fqn:path}",
    response_model=TraceChatHistoryResponse,
)
async def trace_chat_history(
    project_id: str,
    node_fqn: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> TraceChatHistoryResponse:
    """Load persisted follow-up Q&A messages for a trace node."""
    result = await session.execute(
        sa_select(AiTraceChatMessage)
        .where(
            AiTraceChatMessage.project_id == project_id,
            AiTraceChatMessage.node_fqn == node_fqn,
        )
        .order_by(AiTraceChatMessage.created_at.asc())
    )
    rows = result.scalars().all()
    return TraceChatHistoryResponse(
        fqn=node_fqn,
        messages=[_chat_row_to_dto(r) for r in rows],
    )


@router.delete(
    "/{project_id}/trace-chat/{node_fqn:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def trace_chat_clear(
    project_id: str,
    node_fqn: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> Response:
    """Delete all follow-up messages for a node (user-initiated reset)."""
    from sqlalchemy import delete as sa_delete

    await session.execute(
        sa_delete(AiTraceChatMessage).where(
            AiTraceChatMessage.project_id == project_id,
            AiTraceChatMessage.node_fqn == node_fqn,
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/trace-chat/{node_fqn:path}",
    response_model=TraceChatSendResponse,
)
async def trace_chat_send(
    project_id: str,
    node_fqn: str,
    body: TraceChatSendRequest,
    store: Neo4jGraphStore = Depends(get_graph_store),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> TraceChatSendResponse:
    """Ask a follow-up question about a trace route.

    The endpoint is stateful-on-the-server: we load the stored
    summary and conversation history for `(project_id, node_fqn)`,
    append the new question, call the LLM, then persist both the
    user message and the assistant's response. The client just
    sends the question; server returns the assistant's reply.
    """
    question = body.question.strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty",
        )
    if len(question) > 4000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question exceeds 4000 characters",
        )

    # Rebuild trace context (same as summary endpoint) so the
    # chat is grounded in the actual trace topology, not stale data.
    trace_resp = await trace_route(
        project_id=project_id,
        node_fqn=node_fqn,
        max_depth=body.max_depth,
        store=store,
    )

    seen_tables: set[tuple[str, str]] = set()
    tables_touched: list[dict[str, str]] = []
    for edge in trace_resp.edges:
        if edge.type in ("READS", "WRITES"):
            target_name = edge.target.split(":")[-1]
            pair = (target_name, edge.type)
            if pair in seen_tables:
                continue
            seen_tables.add(pair)
            tables_touched.append(
                {"name": target_name, "access_type": edge.type}
            )

    trace_context = {
        "center": {
            "name": trace_resp.center_name,
            "kind": trace_resp.center_kind,
            "layer": trace_resp.center_layer,
            "fqn": trace_resp.center_fqn,
        },
        "upstream": [
            {
                "name": n.name,
                "kind": n.kind,
                "layer": n.layer,
                "fqn": n.fqn,
                "sequence": n.sequence,
            }
            for n in trace_resp.upstream
        ],
        "downstream": [
            {
                "name": n.name,
                "kind": n.kind,
                "layer": n.layer,
                "fqn": n.fqn,
                "sequence": n.sequence,
            }
            for n in trace_resp.downstream
        ],
        "tables_touched": tables_touched,
        "layers_involved": trace_resp.layers_present,
    }
    current_hash = compute_trace_hash(trace_context)

    # Load existing summary (used as the primer assistant turn).
    summary_cache_key = f"trace:{node_fqn}"
    summary_row_result = await session.execute(
        sa_select(AiSummary).where(
            AiSummary.project_id == project_id,
            AiSummary.node_fqn == summary_cache_key,
        )
    )
    summary_row = summary_row_result.scalar_one_or_none()
    summary_text = summary_row.summary if summary_row else None

    # Load prior chat history, oldest-first.
    history_result = await session.execute(
        sa_select(AiTraceChatMessage)
        .where(
            AiTraceChatMessage.project_id == project_id,
            AiTraceChatMessage.node_fqn == node_fqn,
        )
        .order_by(AiTraceChatMessage.created_at.asc())
    )
    history_rows = history_result.scalars().all()
    history_payload = [
        {"role": r.role, "content": r.content} for r in history_rows
    ]

    # Call the LLM with the assembled context.
    settings = get_settings()
    ai_config = await get_ai_config(session)
    if ai_config.provider == "openai":
        client = create_openai_client(ai_config)
    else:
        client = create_bedrock_client(ai_config)

    try:
        answer_text, tokens_used = await generate_trace_chat_reply(
            client=client,
            model=ai_config.summary_model,
            max_tokens=settings.summary_max_tokens,
            trace_context=trace_context,
            summary_text=summary_text,
            history=history_payload,
            question=question,
            ai_config=ai_config,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "trace_chat_ai_call_failed",
            project_id=project_id,
            node_fqn=node_fqn,
            provider=ai_config.provider,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_friendly_ai_error(ai_config.provider, exc),
        ) from exc

    # Resolve analysis_run for audit.
    latest_run_result = await session.execute(
        sa_select(AnalysisRun.id)
        .where(AnalysisRun.project_id == project_id)
        .order_by(AnalysisRun.started_at.desc())
        .limit(1)
    )
    latest_run_id = latest_run_result.scalar_one_or_none()

    # Persist user + assistant messages atomically.
    user_row = AiTraceChatMessage(
        project_id=project_id,
        analysis_run_id=latest_run_id,
        node_fqn=node_fqn,
        role="user",
        content=question,
        graph_hash=current_hash,
    )
    assistant_row = AiTraceChatMessage(
        project_id=project_id,
        analysis_run_id=latest_run_id,
        node_fqn=node_fqn,
        role="assistant",
        content=answer_text,
        model=ai_config.summary_model,
        tokens_used=tokens_used,
        graph_hash=current_hash,
    )
    session.add_all([user_row, assistant_row])
    await session.commit()
    await session.refresh(user_row)
    await session.refresh(assistant_row)

    return TraceChatSendResponse(
        fqn=node_fqn,
        user_message=_chat_row_to_dto(user_row),
        assistant_message=_chat_row_to_dto(assistant_row),
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
    # NOTE: Cypher does not support parameterized relationship hop counts;
    # max_depth is validated via Query(ge=1, le=20) to prevent injection.
    max_depth: int = Query(10, ge=1, le=20),
    _: Project = Depends(get_accessible_project),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> PathFinderResponse:
    """Find shortest path between two nodes."""
    try:
        cypher = (
            f"MATCH path = shortestPath("
            f"(a {{fqn: $fromFqn, app_name: $appName}})"
            f"-[:CALLS|IMPLEMENTS|DEPENDS_ON|INJECTS|INHERITS"
            f"|READS|WRITES|PRODUCES|CONSUMES|STARTS_AT*..{max_depth}]-"
            f"(b {{fqn: $toFqn, app_name: $appName}}))"
            " RETURN [n IN nodes(path) |"
            " {fqn: n.fqn, name: n.name, type: labels(n)[0]}]"
            " AS nodes,"
            " [r IN relationships(path) |"
            " {type: type(r), source: startNode(r).fqn,"
            " target: endNode(r).fqn}] AS edges,"
            " length(path) AS pathLength"
        )
        records = await store.query(
            cypher, {"fromFqn": from_fqn, "toFqn": to_fqn, "appName": project_id}
        )

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
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "find_path_failed", from_fqn=from_fqn, to_fqn=to_fqn, error=str(exc)
        )
        raise HTTPException(status_code=500, detail="Analysis query failed") from exc


# ── 3. Communities ──────────────────────────────────────


@router.get(
    "/{project_id}/communities",
    response_model=CommunitiesResponse,
)
async def list_communities(
    project_id: str,
    _: Project = Depends(get_accessible_project),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> CommunitiesResponse:
    """List all detected communities."""
    try:
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
    except Exception as exc:
        logger.error("list_communities_failed", project_id=project_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Analysis query failed") from exc


# ── 4. Circular Dependencies ────────────────────────────


@router.get(
    "/{project_id}/circular-dependencies",
    response_model=CircularDependenciesResponse,
)
async def circular_dependencies(
    project_id: str,
    level: str = Query("module", pattern="^(module|class)$"),
    _: Project = Depends(get_accessible_project),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> CircularDependenciesResponse:
    """Detect circular dependency cycles."""
    try:
        if level == "module":
            cypher = (
                "MATCH path = (m:Module)-[:IMPORTS*2..6]->(m) "
                "WHERE m.app_name = $appName "
                "WITH [n IN nodes(path) | n.name] AS cycle, "
                "length(path) AS cycleLength "
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
    except Exception as exc:
        logger.error(
            "circular_dependencies_failed", project_id=project_id, error=str(exc)
        )
        raise HTTPException(status_code=500, detail="Analysis query failed") from exc


# ── 5. Dead Code ────────────────────────────────────────


@router.get(
    "/{project_id}/dead-code",
    response_model=DeadCodeResponse,
)
async def dead_code(
    project_id: str,
    node_type: str = Query("function", alias="type"),
    min_loc: int = Query(0, alias="minLoc"),
    _: Project = Depends(get_accessible_project),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> DeadCodeResponse:
    """Find dead code candidates (nodes with no incoming calls)."""
    try:
        if node_type == "function":
            cypher = (
                "MATCH (f:Function) "
                "WHERE f.app_name = $appName "
                "AND NOT (f)<-[:CALLS]-() "
                "AND NOT (f)<-[:HANDLES]-(:APIEndpoint) "
                "AND NOT (f)<-[:CONSUMES]-(:MessageTopic) "
                "AND f.loc >= $minLoc "
                "AND NOT f.is_constructor "
                "AND NOT any(ann IN coalesce(f.annotations, []) "
                "WHERE ann IN "
                "['PostConstruct', 'EventListener', 'Scheduled', 'Bean', 'Test']) "
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
    except Exception as exc:
        logger.error("dead_code_failed", project_id=project_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Analysis query failed") from exc


# ── 6. Metrics Dashboard ────────────────────────────────


@router.get(
    "/{project_id}/metrics",
    response_model=MetricsResponse,
)
async def metrics(
    project_id: str,
    _: Project = Depends(get_accessible_project),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> MetricsResponse:
    """Get overview metrics for a project."""
    try:
        # Overview stats
        overview_cypher = (
            "MATCH (n) WHERE n.app_name = $appName "
            "RETURN "
            "sum(CASE WHEN n.kind = 'MODULE' THEN 1 ELSE 0 END) AS modules, "
            "sum(CASE WHEN n.kind = 'CLASS' THEN 1 ELSE 0 END) AS classes, "
            "sum(CASE WHEN n.kind = 'FUNCTION' THEN 1 ELSE 0 END) AS functions, "
            "sum(CASE WHEN n.loc IS NOT NULL THEN n.loc ELSE 0 END) AS totalLoc"
        )
        overview_record = await store.query_single(
            overview_cypher, {"appName": project_id}
        )
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
    except Exception as exc:
        logger.error("metrics_failed", project_id=project_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Analysis query failed") from exc


# ── 7. Enhanced Node Details ────────────────────────────


@router.get(
    "/{project_id}/node/{node_fqn:path}/details",
    response_model=NodeDetailResponse,
)
async def node_details(
    project_id: str,
    node_fqn: str,
    _: Project = Depends(get_accessible_project),
    store: Neo4jGraphStore = Depends(get_graph_store),
) -> NodeDetailResponse:
    """Get enhanced details for a specific node."""
    try:
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
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("node_details_failed", node_fqn=node_fqn, error=str(exc))
        raise HTTPException(status_code=500, detail="Analysis query failed") from exc
