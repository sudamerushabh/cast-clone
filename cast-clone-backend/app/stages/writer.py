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
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode

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


def _create_stub_hierarchy(
    context: AnalysisContext,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Create stub Function and Class nodes for CALLS targets missing from the graph.

    For a missing target like 'com.example.OwnerRepository.findAll':
      1. Create a Function stub node
      2. If parent class 'com.example.OwnerRepository' is also missing, create a Class stub
      3. Create CONTAINS edges: class -> function, and module -> class if a module matches
    """
    existing_fqns = set(context.graph.nodes.keys())
    stub_nodes: list[GraphNode] = []
    stub_edges: list[GraphEdge] = []
    created_stubs: set[str] = set()

    # Build class_fqn -> module_fqn map from existing CONTAINS edges
    class_to_module: dict[str, str] = {}
    for edge in context.graph.edges:
        if edge.kind == EdgeKind.CONTAINS:
            src = context.graph.get_node(edge.source_fqn)
            tgt = context.graph.get_node(edge.target_fqn)
            if (
                src
                and tgt
                and src.kind == NodeKind.MODULE
                and tgt.kind in (NodeKind.CLASS, NodeKind.INTERFACE)
            ):
                class_to_module[edge.target_fqn] = edge.source_fqn

    # Build package -> module_fqn map for stub class placement
    package_to_module: dict[str, str] = {}
    for class_fqn, module_fqn in class_to_module.items():
        pkg = class_fqn.rsplit(".", 1)[0] if "." in class_fqn else ""
        if pkg:
            package_to_module[pkg] = module_fqn

    for edge in context.graph.edges:
        if edge.kind != EdgeKind.CALLS:
            continue

        target_fqn = edge.target_fqn
        if target_fqn in existing_fqns or target_fqn in created_stubs:
            continue

        # Parse: "com.example.Repo.findAll" -> class="com.example.Repo", method="findAll"
        dot_idx = target_fqn.rfind(".")
        if dot_idx <= 0:
            continue

        class_fqn = target_fqn[:dot_idx]
        method_name = target_fqn[dot_idx + 1 :]

        # Infer language from source node
        source_node = context.graph.get_node(edge.source_fqn)
        language = source_node.language if source_node else None

        # Create stub function node
        stub_nodes.append(
            GraphNode(
                fqn=target_fqn,
                name=method_name,
                kind=NodeKind.FUNCTION,
                language=language,
                properties={"stub": True},
            )
        )
        created_stubs.add(target_fqn)

        # Create stub class if needed
        if class_fqn not in existing_fqns and class_fqn not in created_stubs:
            class_name = class_fqn.rsplit(".", 1)[-1]
            stub_nodes.append(
                GraphNode(
                    fqn=class_fqn,
                    name=class_name,
                    kind=NodeKind.CLASS,
                    language=language,
                    properties={"stub": True},
                )
            )
            created_stubs.add(class_fqn)

            # Link stub class to its module via package prefix
            pkg = class_fqn.rsplit(".", 1)[0] if "." in class_fqn else ""
            module_fqn = package_to_module.get(pkg)
            if module_fqn:
                stub_edges.append(
                    GraphEdge(
                        source_fqn=module_fqn,
                        target_fqn=class_fqn,
                        kind=EdgeKind.CONTAINS,
                        confidence=Confidence.HIGH,
                        evidence="stub-hierarchy",
                    )
                )

        # CONTAINS edge: class -> function
        stub_edges.append(
            GraphEdge(
                source_fqn=class_fqn,
                target_fqn=target_fqn,
                kind=EdgeKind.CONTAINS,
                confidence=Confidence.HIGH,
                evidence="stub-hierarchy",
            )
        )

    return stub_nodes, stub_edges


ProgressCallback = Callable[[int], Awaitable[None]]


async def write_to_neo4j(
    context: AnalysisContext,
    store: GraphStore,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Write the entire SymbolGraph to Neo4j.

    This is a CRITICAL pipeline stage. Any exception raised here will
    propagate to the orchestrator and abort the analysis run.

    Args:
        context: The shared pipeline state containing the graph to persist.
        store: The GraphStore implementation (injected for testability).
        on_progress: Optional async callback receiving percentage (0-100).

    Raises:
        Any exception from the store — this stage does not swallow errors.
    """
    start = time.monotonic()
    project_id = context.project_id

    async def _report(pct: int) -> None:
        if on_progress:
            await on_progress(min(pct, 100))

    logger.info(
        "writer.start",
        project_id=project_id,
        node_count=context.graph.node_count,
        edge_count=context.graph.edge_count,
    )

    # Step 1: Clear existing data for this project (5%)
    logger.info("writer.clear_project", project_id=project_id)
    await store.clear_project(project_id)
    await _report(5)

    # Step 2: Ensure indexes exist (8%)
    logger.info("writer.ensure_indexes")
    await store.ensure_indexes()
    await _report(8)

    # Step 3: Write Application root node first
    app_node = _build_application_node(context)
    logger.info("writer.write_application_node", fqn=app_node.fqn)
    nodes_written = await store.write_nodes_batch([app_node], project_id)
    await _report(10)

    # Step 4: Write all graph nodes (10-35%)
    all_nodes = list(context.graph.nodes.values())
    if all_nodes:
        logger.info("writer.write_nodes", count=len(all_nodes))
        nodes_written += await store.write_nodes_batch(all_nodes, project_id)
    await _report(35)

    # Step 4b: Create stub nodes for CALLS edge targets that don't exist (35-45%)
    stub_nodes, stub_edges = _create_stub_hierarchy(context)
    if stub_nodes:
        logger.info("writer.write_stub_nodes", count=len(stub_nodes))
        nodes_written += await store.write_nodes_batch(stub_nodes, project_id)
    if stub_edges:
        logger.info("writer.write_stub_edges", count=len(stub_edges))
    await _report(45)

    # Step 5: Write all graph edges — slowest part (45-95%)
    all_edges = context.graph.edges + stub_edges
    logger.info("writer.write_edges", count=len(all_edges))
    batch_size = 1000
    total_edges = len(all_edges)
    edges_written = 0
    for i in range(0, total_edges, batch_size):
        batch = all_edges[i : i + batch_size]
        edges_written += await store.write_edges_batch(batch)
        pct = 45 + int(50 * min(i + batch_size, total_edges) / max(total_edges, 1))
        await _report(pct)

    # Step 6: Create full-text search index (95-100%)
    logger.info("writer.create_fulltext_index")
    await store.query(FULLTEXT_INDEX_CYPHER)
    await _report(100)

    duration = time.monotonic() - start
    logger.info(
        "writer.complete",
        project_id=project_id,
        nodes_written=nodes_written,
        edges_written=edges_written,
        duration_seconds=round(duration, 2),
    )
