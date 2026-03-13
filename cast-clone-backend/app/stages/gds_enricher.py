# app/stages/gds_enricher.py
"""Stage 10: GDS Louvain Community Detection.

Runs after Stage 8 (Neo4j write) and Stage 9 (transactions).
Projects an in-memory GDS graph from Neo4j, runs Louvain community
detection, writes communityId back to Class nodes, then drops the
projection.

Non-critical: if GDS fails, pipeline continues with a warning.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from app.models.context import AnalysisContext

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _create_gds_client(driver: AsyncDriver) -> Any:
    """Create a GDS client from app settings.

    Separated for testability — tests mock this function.
    The GDS Python client is synchronous and uses its own connection,
    independent of the async Neo4j driver.
    """
    from graphdatascience import GraphDataScience

    from app.config import get_settings

    settings = get_settings()
    return GraphDataScience(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


async def run_gds_community_detection(
    context: AnalysisContext,
    driver: AsyncDriver,
) -> dict[str, Any]:
    """Run Louvain community detection via Neo4j GDS.

    1. Project an in-memory graph (Class nodes, CALLS + DEPENDS_ON edges)
    2. Run Louvain algorithm (writes communityId to nodes)
    3. Drop the projection
    4. Update context.community_count

    Returns dict with communityCount and modularity.
    Non-critical: catches all exceptions and returns zeros on failure.
    """
    result: dict[str, Any] = {"communityCount": 0, "modularity": 0.0}
    projection_name = f"{context.project_id}_communities"
    graph_proj = None

    try:
        gds = _create_gds_client(driver)
        logger.info("gds_enricher.start", project_id=context.project_id)

        # Project the graph first so we can clean it up on failure
        graph_proj, stats = await asyncio.to_thread(
            gds.graph.project,
            projection_name,
            {"Class": {"properties": ["fqn"]}},
            {
                "CALLS": {"orientation": "UNDIRECTED"},
                "DEPENDS_ON": {"orientation": "UNDIRECTED"},
            },
        )

        node_count = stats.get("nodeCount", 0) if isinstance(stats, dict) else 0
        if node_count == 0:
            context.community_count = 0
            return result

        louvain_result = await asyncio.to_thread(
            gds.louvain.write, graph_proj, writeProperty="communityId"
        )
        if not isinstance(louvain_result, dict):
            louvain_result = dict(louvain_result)

        community_count = louvain_result.get("communityCount", 0)
        modularity = louvain_result.get("modularity", 0.0)

        result = {
            "communityCount": community_count,
            "modularity": modularity,
        }
        context.community_count = community_count

        logger.info(
            "gds_enricher.louvain.done",
            community_count=community_count,
            modularity=round(modularity, 4),
        )

    except Exception as exc:
        msg = f"GDS community detection failed: {exc}"
        context.warnings.append(msg)
        context.community_count = 0
        logger.warning("gds_enricher.failed", error=str(exc))

    finally:
        if graph_proj is not None:
            try:
                graph_proj.drop()
                logger.info("gds_enricher.projection_dropped")
            except Exception as drop_exc:
                logger.warning(
                    "gds_enricher.projection_drop_failed", error=str(drop_exc)
                )

    return result
