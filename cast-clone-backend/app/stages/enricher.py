# app/stages/enricher.py
"""Stage 7: Graph Enricher.

Computes derived metrics, aggregates class-level DEPENDS_ON and module-level
IMPORTS edges, assigns architectural layers, and runs community detection.

This stage operates entirely in-memory on the SymbolGraph. It is non-critical:
if it fails, the pipeline continues with a warning.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

import structlog

from app.models.enums import EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode

if TYPE_CHECKING:
    from app.models.context import AnalysisContext
    from app.models.graph import SymbolGraph

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ── Public API ───────────────────────────────────────────


async def enrich_graph(context: AnalysisContext) -> None:
    """Run all enrichment steps on the analysis context's graph.

    Steps (in order):
    1. Compute fan-in/fan-out metrics on CLASS nodes
    2. Aggregate class-level DEPENDS_ON edges from method CALLS
    3. Aggregate module-level IMPORTS edges from class DEPENDS_ON
    4. Assign architectural layers (create Layer nodes + CONTAINS edges)
    5. Detect communities (create Community nodes + INCLUDES edges)

    Non-critical: catches exceptions per step, logs warnings, continues.
    """
    graph = context.graph
    app_name = context.project_id

    logger.info(
        "enricher.start",
        node_count=graph.node_count,
        edge_count=graph.edge_count,
    )

    # Step 1: Fan metrics
    try:
        compute_fan_metrics(graph)
        logger.info("enricher.fan_metrics.done")
    except Exception as exc:
        msg = f"Fan metrics computation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.fan_metrics.failed", error=str(exc))

    # Step 2: Class-level DEPENDS_ON
    try:
        depends_on_count = aggregate_class_depends_on(graph)
        logger.info("enricher.depends_on.done", edges_created=depends_on_count)
    except Exception as exc:
        msg = f"Class DEPENDS_ON aggregation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.depends_on.failed", error=str(exc))

    # Step 3: Module-level IMPORTS
    try:
        imports_count = aggregate_module_imports(graph)
        logger.info("enricher.imports.done", edges_created=imports_count)
    except Exception as exc:
        msg = f"Module IMPORTS aggregation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.imports.failed", error=str(exc))

    # Step 4: Architectural layers
    try:
        layer_count = assign_architectural_layers(graph, app_name=app_name)
        logger.info("enricher.layers.done", layers_created=layer_count)
    except Exception as exc:
        msg = f"Layer assignment failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.layers.failed", error=str(exc))

    # Step 5: Community detection
    try:
        community_count = detect_communities(graph, app_name=app_name)
        context.community_count = community_count
        logger.info("enricher.communities.done", community_count=community_count)
    except Exception as exc:
        msg = f"Community detection failed: {exc}"
        context.warnings.append(msg)
        context.community_count = 0
        logger.warning("enricher.communities.failed", error=str(exc))

    logger.info(
        "enricher.done",
        node_count=graph.node_count,
        edge_count=graph.edge_count,
        community_count=context.community_count,
    )


# ── Step 1: Fan-In / Fan-Out Metrics ────────────────────


def compute_fan_metrics(graph: SymbolGraph) -> None:
    """Compute fan-in and fan-out for each CLASS node.

    Fan-in:  count of incoming CALLS edges to this class's methods
             + incoming INJECTS edges to this class.
    Fan-out: count of outgoing CALLS edges from this class's methods.

    Results stored in ``node.properties["fan_in"]`` and ``node.properties["fan_out"]``.
    """
    class_nodes = {
        fqn: node for fqn, node in graph.nodes.items() if node.kind == NodeKind.CLASS
    }

    if not class_nodes:
        return

    # Build method -> owning class lookup from CONTAINS edges
    method_to_class: dict[str, str] = {}
    for edge in graph.edges:
        if edge.kind == EdgeKind.CONTAINS:
            source_node = graph.get_node(edge.source_fqn)
            target_node = graph.get_node(edge.target_fqn)
            if (
                source_node is not None
                and source_node.kind == NodeKind.CLASS
                and target_node is not None
                and target_node.kind == NodeKind.FUNCTION
            ):
                method_to_class[edge.target_fqn] = edge.source_fqn

    # Count fan-in and fan-out per class
    fan_in: dict[str, int] = defaultdict(int)
    fan_out: dict[str, int] = defaultdict(int)

    for edge in graph.edges:
        if edge.kind == EdgeKind.CALLS:
            src_class = method_to_class.get(edge.source_fqn)
            tgt_class = method_to_class.get(edge.target_fqn)

            if tgt_class is not None and tgt_class in class_nodes:
                fan_in[tgt_class] += 1
            if src_class is not None and src_class in class_nodes:
                fan_out[src_class] += 1

        elif edge.kind == EdgeKind.INJECTS:
            # INJECTS is class-to-class, counts as fan_in for target
            if edge.target_fqn in class_nodes:
                fan_in[edge.target_fqn] += 1

    # Write metrics to node properties
    for fqn in class_nodes:
        class_nodes[fqn].properties["fan_in"] = fan_in.get(fqn, 0)
        class_nodes[fqn].properties["fan_out"] = fan_out.get(fqn, 0)


# ── Step 2: Aggregate Class-Level DEPENDS_ON ─────────────


def aggregate_class_depends_on(graph: SymbolGraph) -> int:
    """Aggregate method-level CALLS edges into class-level DEPENDS_ON edges.

    If class A has methods that CALL methods in class B (A != B),
    creates ``A -[:DEPENDS_ON {weight: N}]-> B`` where N is the number
    of distinct method-to-method CALLS edges between the two classes.

    Skips pairs where a DEPENDS_ON edge already exists.

    Returns the number of new DEPENDS_ON edges created.
    """
    class_nodes = {
        fqn for fqn, node in graph.nodes.items() if node.kind == NodeKind.CLASS
    }

    if not class_nodes:
        return 0

    # Build method -> owning class lookup
    method_to_class: dict[str, str] = {}
    for edge in graph.edges:
        if edge.kind == EdgeKind.CONTAINS:
            source_node = graph.get_node(edge.source_fqn)
            target_node = graph.get_node(edge.target_fqn)
            if (
                source_node is not None
                and source_node.kind == NodeKind.CLASS
                and target_node is not None
                and target_node.kind == NodeKind.FUNCTION
            ):
                method_to_class[edge.target_fqn] = edge.source_fqn

    # Count cross-class calls
    cross_class_calls: dict[tuple[str, str], int] = defaultdict(int)
    for edge in graph.edges:
        if edge.kind == EdgeKind.CALLS:
            src_class = method_to_class.get(edge.source_fqn)
            tgt_class = method_to_class.get(edge.target_fqn)
            if (
                src_class is not None
                and tgt_class is not None
                and src_class != tgt_class
                and src_class in class_nodes
                and tgt_class in class_nodes
            ):
                cross_class_calls[(src_class, tgt_class)] += 1

    # Find existing DEPENDS_ON pairs to avoid duplicates
    existing_depends: set[tuple[str, str]] = set()
    for edge in graph.edges:
        if edge.kind == EdgeKind.DEPENDS_ON:
            existing_depends.add((edge.source_fqn, edge.target_fqn))

    # Create new DEPENDS_ON edges
    created = 0
    for (src, tgt), weight in cross_class_calls.items():
        if (src, tgt) not in existing_depends:
            graph.add_edge(
                GraphEdge(
                    source_fqn=src,
                    target_fqn=tgt,
                    kind=EdgeKind.DEPENDS_ON,
                    properties={"weight": weight},
                )
            )
            created += 1

    return created


# ── Step 3: Aggregate Module-Level IMPORTS ───────────────


def aggregate_module_imports(graph: SymbolGraph) -> int:
    """Aggregate class-level DEPENDS_ON edges into module-level IMPORTS edges.

    If module M1 contains classes that DEPEND_ON classes in module M2 (M1 != M2),
    creates ``M1 -[:IMPORTS {weight: N}]-> M2`` where N is the sum of
    class-level DEPENDS_ON weights between the two modules.

    Returns the number of new IMPORTS edges created.
    """
    module_nodes = {
        fqn for fqn, node in graph.nodes.items() if node.kind == NodeKind.MODULE
    }

    if not module_nodes:
        return 0

    # Build class -> module lookup
    class_to_module: dict[str, str] = _build_class_to_module_map(graph)

    # Aggregate DEPENDS_ON weights by module pair
    module_weights: dict[tuple[str, str], int] = defaultdict(int)
    for edge in graph.edges:
        if edge.kind == EdgeKind.DEPENDS_ON:
            src_mod = class_to_module.get(edge.source_fqn)
            tgt_mod = class_to_module.get(edge.target_fqn)
            if (
                src_mod is not None
                and tgt_mod is not None
                and src_mod != tgt_mod
                and src_mod in module_nodes
                and tgt_mod in module_nodes
            ):
                weight = edge.properties.get("weight", 1)
                module_weights[(src_mod, tgt_mod)] += weight

    # Find existing IMPORTS to avoid duplicates
    existing_imports: set[tuple[str, str]] = set()
    for edge in graph.edges:
        if edge.kind == EdgeKind.IMPORTS:
            existing_imports.add((edge.source_fqn, edge.target_fqn))

    # Create IMPORTS edges
    created = 0
    for (src, tgt), weight in module_weights.items():
        if (src, tgt) not in existing_imports:
            graph.add_edge(
                GraphEdge(
                    source_fqn=src,
                    target_fqn=tgt,
                    kind=EdgeKind.IMPORTS,
                    properties={"weight": weight},
                )
            )
            created += 1

    return created


# ── Step 4: Architectural Layer Assignment ───────────────


def assign_architectural_layers(graph: SymbolGraph, app_name: str) -> int:
    """Create Layer nodes and CONTAINS edges from class layer assignments.

    Framework plugins set ``node.properties["layer"]`` on CLASS nodes during
    Stage 5. This function:
    1. Groups classes by their layer name
    2. Creates a Layer node per unique layer
    3. Creates CONTAINS edges: Layer -> Class

    Returns the number of Layer nodes created.
    """
    # Group classes by layer
    layer_members: dict[str, list[str]] = defaultdict(list)
    for fqn, node in graph.nodes.items():
        if node.kind == NodeKind.CLASS:
            layer_name = node.properties.get("layer")
            if layer_name:
                layer_members[layer_name].append(fqn)

    if not layer_members:
        return 0

    # Create Layer nodes and CONTAINS edges
    for layer_name, member_fqns in layer_members.items():
        layer_fqn = f"layer:{app_name}:{layer_name}"

        layer_node = GraphNode(
            fqn=layer_fqn,
            name=layer_name,
            kind=NodeKind.LAYER,
            properties={
                "type": "architectural_layer",
                "app_name": app_name,
                "node_count": len(member_fqns),
            },
        )
        graph.add_node(layer_node)

        for class_fqn in member_fqns:
            graph.add_edge(
                GraphEdge(
                    source_fqn=layer_fqn,
                    target_fqn=class_fqn,
                    kind=EdgeKind.CONTAINS,
                )
            )

    return len(layer_members)


# ── Step 5: Community Detection ──────────────────────────


def detect_communities(graph: SymbolGraph, app_name: str) -> int:
    """Detect communities among CLASS nodes using connected components via BFS.

    Uses DEPENDS_ON edges (undirected) to find connected components. This is a
    simple Python-based approach suitable for Phase 1 since Neo4j GDS is not
    available at this stage (data has not been written to Neo4j yet).

    For each community:
    - Creates a Community node with member count
    - Creates INCLUDES edges: Community -> Class
    - Sets ``community_id`` property on each member class

    Returns the number of communities detected.
    """
    # Collect class nodes
    class_fqns = [
        fqn for fqn, node in graph.nodes.items() if node.kind == NodeKind.CLASS
    ]

    if not class_fqns:
        return 0

    # Build undirected adjacency list from DEPENDS_ON edges
    adjacency: dict[str, set[str]] = defaultdict(set)
    class_set = set(class_fqns)

    for edge in graph.edges:
        if edge.kind == EdgeKind.DEPENDS_ON:
            if edge.source_fqn in class_set and edge.target_fqn in class_set:
                adjacency[edge.source_fqn].add(edge.target_fqn)
                adjacency[edge.target_fqn].add(edge.source_fqn)

    # BFS to find connected components
    visited: set[str] = set()
    communities: list[list[str]] = []

    for fqn in class_fqns:
        if fqn in visited:
            continue

        # BFS from this node
        component: list[str] = []
        queue: deque[str] = deque([fqn])
        visited.add(fqn)

        while queue:
            current = queue.popleft()
            component.append(current)

            for neighbor in adjacency.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        communities.append(component)

    # Create Community nodes and assign community_id to classes
    for idx, members in enumerate(communities):
        community_fqn = f"community:{app_name}:{idx}"

        community_node = GraphNode(
            fqn=community_fqn,
            name=f"Community {idx}",
            kind=NodeKind.COMMUNITY,
            properties={
                "algorithm": "connected_components",
                "node_count": len(members),
                "app_name": app_name,
            },
        )
        graph.add_node(community_node)

        for class_fqn in members:
            # Set community_id on the class node
            node = graph.get_node(class_fqn)
            if node is not None:
                node.properties["community_id"] = idx

            # Create INCLUDES edge
            graph.add_edge(
                GraphEdge(
                    source_fqn=community_fqn,
                    target_fqn=class_fqn,
                    kind=EdgeKind.INCLUDES,
                )
            )

    return len(communities)


# ── Internal Helpers ─────────────────────────────────────


def _build_class_to_module_map(graph: SymbolGraph) -> dict[str, str]:
    """Build a mapping of class FQN -> module FQN.

    Uses two strategies:
    1. Module CONTAINS Class edges
    2. Class ``module_fqn`` property (fallback)
    """
    class_to_module: dict[str, str] = {}

    # Strategy 1: CONTAINS edges from Module -> Class
    for edge in graph.edges:
        if edge.kind == EdgeKind.CONTAINS:
            source_node = graph.get_node(edge.source_fqn)
            target_node = graph.get_node(edge.target_fqn)
            if (
                source_node is not None
                and source_node.kind == NodeKind.MODULE
                and target_node is not None
                and target_node.kind == NodeKind.CLASS
            ):
                class_to_module[edge.target_fqn] = edge.source_fqn

    # Strategy 2: Fallback to module_fqn property
    for fqn, node in graph.nodes.items():
        if node.kind == NodeKind.CLASS and fqn not in class_to_module:
            module_fqn = node.properties.get("module_fqn")
            if module_fqn:
                class_to_module[fqn] = module_fqn

    return class_to_module
