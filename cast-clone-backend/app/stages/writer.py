"""Stage 8: Neo4j Batch Writer.

This is a CRITICAL stage — failure here is fatal and must propagate
to the orchestrator. Unlike non-critical stages, this function does NOT
catch exceptions internally.

Writes the in-memory SymbolGraph from AnalysisContext to Neo4j via the
GraphStore abstraction. Steps:
  1. Clear existing data for this project
  2. Ensure indexes exist
  3. Write Application root node
  4. Write all graph nodes in batches
  5. Write all graph edges in batches
  6. Create full-text search index
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from app.models.enums import NodeKind
from app.models.graph import GraphNode

if TYPE_CHECKING:
    from app.models.context import AnalysisContext
    from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)

FULLTEXT_INDEX_CYPHER = """
CREATE FULLTEXT INDEX idx_node_search IF NOT EXISTS
FOR (n:Class|Function|Interface|Table|APIEndpoint|Module)
ON EACH [n.name, n.fqn]
""".strip()


def _build_application_node(context: AnalysisContext) -> GraphNode:
    """Build the Application root node from pipeline context.

    The Application node is the top of the containment hierarchy:
      Application -> Module -> Class -> Function
    """
    # Collect language names from manifest if available
    languages: list[str] = []
    frameworks: list[str] = []
    total_files = 0
    total_loc = 0

    if context.manifest is not None:
        languages = context.manifest.language_names
        frameworks = [fw.name for fw in context.manifest.detected_frameworks]
        total_files = context.manifest.total_files
        total_loc = context.manifest.total_loc

    return GraphNode(
        fqn=context.project_id,
        name=context.project_id,
        kind=NodeKind.APPLICATION,
        properties={
            "languages": languages,
            "frameworks": frameworks,
            "total_files": total_files,
            "total_loc": total_loc,
            "total_nodes": context.graph.node_count,
            "total_edges": context.graph.edge_count,
        },
    )


async def write_to_neo4j(
    context: AnalysisContext,
    store: GraphStore,
) -> None:
    """Write the entire SymbolGraph to Neo4j.

    This is a CRITICAL pipeline stage. Any exception raised here will
    propagate to the orchestrator and abort the analysis run.

    Args:
        context: The shared pipeline state containing the graph to persist.
        store: The GraphStore implementation (injected for testability).

    Raises:
        Any exception from the store — this stage does not swallow errors.
    """
    start = time.monotonic()
    project_id = context.project_id

    logger.info(
        "writer.start",
        project_id=project_id,
        node_count=context.graph.node_count,
        edge_count=context.graph.edge_count,
    )

    # Step 1: Clear existing data for this project
    logger.info("writer.clear_project", project_id=project_id)
    await store.clear_project(project_id)

    # Step 2: Ensure indexes exist
    logger.info("writer.ensure_indexes")
    await store.ensure_indexes()

    # Step 3: Write Application root node first
    app_node = _build_application_node(context)
    logger.info("writer.write_application_node", fqn=app_node.fqn)
    nodes_written = await store.write_nodes_batch([app_node], project_id)

    # Step 4: Write all graph nodes
    all_nodes = list(context.graph.nodes.values())
    if all_nodes:
        logger.info("writer.write_nodes", count=len(all_nodes))
        nodes_written += await store.write_nodes_batch(all_nodes, project_id)
    else:
        logger.info("writer.write_nodes", count=0)

    # Step 5: Write all graph edges (nodes must exist first — edges reference by FQN)
    all_edges = context.graph.edges
    logger.info("writer.write_edges", count=len(all_edges))
    edges_written = await store.write_edges_batch(all_edges)

    # Step 6: Create full-text search index
    logger.info("writer.create_fulltext_index")
    await store.query(FULLTEXT_INDEX_CYPHER)

    duration = time.monotonic() - start
    logger.info(
        "writer.complete",
        project_id=project_id,
        nodes_written=nodes_written,
        edges_written=edges_written,
        duration_seconds=round(duration, 2),
    )
