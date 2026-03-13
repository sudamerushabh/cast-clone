# app/stages/enricher.py
"""Stage 7: Graph Enricher.

Computes derived metrics, aggregates class-level DEPENDS_ON and module-level
IMPORTS edges, and assigns architectural layers.

Community detection has been moved to Stage 10 (GDS Louvain) which runs
after Neo4j write, using the graphdatascience client.

This stage operates entirely in-memory on the SymbolGraph. It is non-critical:
if it fails, the pipeline continues with a warning.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
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
    3b. Apply layer and framework assignments from plugins to CLASS nodes
    4. Assign architectural layers (create Layer nodes + CONTAINS edges)

    Note: Community detection moved to Stage 10 (GDS Louvain).

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

    # Step 3b: Apply layer + framework assignments from plugins to CLASS nodes
    try:
        applied = _apply_plugin_assignments(context)
        logger.info("enricher.apply_assignments.done", classes_updated=applied)
    except Exception as exc:
        msg = f"Plugin assignment application failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.apply_assignments.failed", error=str(exc))

    # Step 4: Architectural layers
    try:
        layer_count = assign_architectural_layers(graph, app_name=app_name)
        logger.info("enricher.layers.done", layers_created=layer_count)
    except Exception as exc:
        msg = f"Layer assignment failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.layers.failed", error=str(exc))

    # Step 5: Technology nodes (architecture view)
    try:
        tech_count = create_technology_nodes(graph, app_name=app_name)
        logger.info("enricher.technology_nodes.done", tech_nodes_created=tech_count)
    except Exception as exc:
        msg = f"Technology node creation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.technology_nodes.failed", error=str(exc))

    logger.info(
        "enricher.done",
        node_count=graph.node_count,
        edge_count=graph.edge_count,
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


# ── Step 3b: Apply Plugin Assignments ─────────────────────


# Annotation -> framework key mapping for inferring framework from class annotations
_ANNOTATION_TO_FRAMEWORK: dict[str, str] = {
    "Component": "spring-boot",
    "Service": "spring-boot",
    "Repository": "spring-data-jpa",
    "Controller": "spring-web",
    "RestController": "spring-web",
    "Configuration": "spring-boot",
    "Bean": "spring-boot",
    "Entity": "hibernate",
    "Table": "hibernate",
    "MappedSuperclass": "hibernate",
    "Embeddable": "hibernate",
    "RequestMapping": "spring-web",
    "GetMapping": "spring-web",
    "PostMapping": "spring-web",
    "PutMapping": "spring-web",
    "DeleteMapping": "spring-web",
    "PatchMapping": "spring-web",
}


def _apply_plugin_assignments(context: AnalysisContext) -> int:
    """Apply layer and framework assignments from plugins to CLASS node properties.

    Plugins compute ``layer_assignments`` (fqn -> layer name) during Stage 5
    and store them in ``context.layer_assignments``. This function writes those
    assignments to ``node.properties["layer"]`` on CLASS/INTERFACE nodes.

    Also infers ``node.properties["framework"]`` from class annotations using
    ``_ANNOTATION_TO_FRAMEWORK``.

    Returns the number of nodes updated.
    """
    graph = context.graph
    updated = 0

    # Apply layer assignments from plugins
    for fqn, layer_name in context.layer_assignments.items():
        node = graph.get_node(fqn)
        if node is not None and node.kind in (NodeKind.CLASS, NodeKind.INTERFACE):
            if "layer" not in node.properties:
                node.properties["layer"] = layer_name
                updated += 1

    # Infer framework from annotations for all CLASS/INTERFACE nodes
    for node in graph.nodes.values():
        if node.kind not in (NodeKind.CLASS, NodeKind.INTERFACE):
            continue
        if node.properties.get("framework"):
            continue  # already set

        annotations = node.properties.get("annotations", [])
        for ann in annotations:
            fw = _ANNOTATION_TO_FRAMEWORK.get(ann)
            if fw:
                node.properties["framework"] = fw
                if "layer" not in node.properties and fw in _TECHNOLOGY_MAP:
                    node.properties["layer"] = _TECHNOLOGY_MAP[fw].layer_hint
                    updated += 1
                break

    return updated


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


# ── Step 5: Technology Nodes (Architecture View) ─────────


@dataclass(frozen=True)
class _TechnologyInfo:
    display: str
    category: str
    language: str
    layer_hint: str


_TECHNOLOGY_MAP: dict[str, _TechnologyInfo] = {
    "spring-boot": _TechnologyInfo(
        "Spring Boot", "di_container", "java", "Business Logic"
    ),
    "spring-web": _TechnologyInfo(
        "Spring Web", "web_framework", "java", "Presentation"
    ),
    "spring-data-jpa": _TechnologyInfo("Spring Data JPA", "orm", "java", "Data Access"),
    "hibernate": _TechnologyInfo("Hibernate", "orm", "java", "Data Access"),
    "fastapi": _TechnologyInfo("FastAPI", "web_framework", "python", "Presentation"),
    "django": _TechnologyInfo("Django", "web_framework", "python", "Presentation"),
    "django-drf": _TechnologyInfo(
        "Django REST Framework", "web_framework", "python", "Presentation"
    ),
    "django-orm": _TechnologyInfo("Django ORM", "orm", "python", "Data Access"),
    "django-settings": _TechnologyInfo(
        "Django Settings", "configuration", "python", "Configuration"
    ),
    "sqlalchemy": _TechnologyInfo("SQLAlchemy", "orm", "python", "Data Access"),
    "react": _TechnologyInfo(
        "React", "frontend_framework", "typescript", "Presentation"
    ),
    "angular": _TechnologyInfo(
        "Angular", "frontend_framework", "typescript", "Presentation"
    ),
    "express": _TechnologyInfo(
        "Express.js", "web_framework", "javascript", "Presentation"
    ),
    "nestjs": _TechnologyInfo("NestJS", "web_framework", "typescript", "Presentation"),
    "aspnet": _TechnologyInfo(
        "ASP.NET Core", "web_framework", "csharp", "Presentation"
    ),
    "entity-framework": _TechnologyInfo(
        "Entity Framework", "orm", "csharp", "Data Access"
    ),
}

_LANGUAGE_DISPLAY: dict[str, str] = {
    "java": "Java",
    "python": "Python",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "csharp": "C#",
    "go": "Go",
    "kotlin": "Kotlin",
    "scala": "Scala",
    "ruby": "Ruby",
    "rust": "Rust",
}


def create_technology_nodes(graph: SymbolGraph, app_name: str) -> int:
    """Create COMPONENT nodes representing technologies, grouped under Layer nodes.

    Inspects the APPLICATION node's ``detected_frameworks`` list and class-level
    ``framework`` properties to group classes by (layer, technology). Creates
    technology COMPONENT nodes with ``Layer → CONTAINS → Component → CONTAINS → Class``
    edges.

    Returns the number of technology COMPONENT nodes created.
    """
    # Find APPLICATION node to get detected frameworks
    app_node = None
    for node in graph.nodes.values():
        if node.kind == NodeKind.APPLICATION:
            app_node = node
            break

    detected_frameworks: list[str] = []
    if app_node is not None:
        detected_frameworks = app_node.properties.get(
            "detected_frameworks",
            app_node.properties.get("frameworks", []),
        )

    # Group classes by (layer, tech_key)
    # tech_key is either a framework key or "lang:{language}"
    tech_groups: dict[tuple[str, str], list[str]] = defaultdict(list)

    for fqn, node in graph.nodes.items():
        if node.kind != NodeKind.CLASS:
            continue

        layer = node.properties.get("layer")
        framework = node.properties.get("framework")

        if framework and framework in _TECHNOLOGY_MAP:
            info = _TECHNOLOGY_MAP[framework]
            effective_layer = layer or info.layer_hint
            tech_groups[(effective_layer, framework)].append(fqn)
        elif layer:
            # Fallback: group by language
            lang = node.language or "unknown"
            tech_key = f"lang:{lang}"
            tech_groups[(layer, tech_key)].append(fqn)

    # Find existing Layer nodes
    layer_nodes: dict[str, str] = {}  # layer_name -> layer_fqn
    for fqn, node in graph.nodes.items():
        if node.kind == NodeKind.LAYER:
            layer_nodes[node.name] = fqn

    # Count API endpoints per framework
    endpoint_counts: dict[str, int] = defaultdict(int)
    for node in graph.nodes.values():
        if node.kind == NodeKind.API_ENDPOINT:
            fw = node.properties.get("framework", "")
            if fw:
                endpoint_counts[fw] += 1

    # Handle TABLE nodes -> database component
    table_nodes: list[str] = []
    for fqn, node in graph.nodes.items():
        if node.kind == NodeKind.TABLE:
            table_nodes.append(fqn)

    if not tech_groups and not table_nodes:
        return 0

    created = 0

    # Create technology COMPONENT nodes
    for (layer_name, tech_key), member_fqns in tech_groups.items():
        if tech_key in _TECHNOLOGY_MAP:
            info = _TECHNOLOGY_MAP[tech_key]
            display_name = info.display
            category = info.category
            language = info.language
        else:
            # lang:{language} fallback
            lang = tech_key.removeprefix("lang:")
            display_name = f"{_LANGUAGE_DISPLAY.get(lang, lang.title())} Classes"
            category = "language_classes"
            language = lang

        comp_fqn = f"tech:{app_name}:{layer_name}:{tech_key}"

        # Compute LOC total (loc is a top-level GraphNode attribute)
        loc_total = 0
        for cfqn in member_fqns:
            cnode = graph.get_node(cfqn)
            if cnode and cnode.loc:
                loc_total += cnode.loc

        comp_node = GraphNode(
            fqn=comp_fqn,
            name=display_name,
            kind=NodeKind.COMPONENT,
            language=language,
            properties={
                "type": "technology",
                "category": category,
                "layer": layer_name,
                "app_name": app_name,
                "class_count": len(member_fqns),
                "loc_total": loc_total,
                "endpoint_count": endpoint_counts.get(tech_key, 0),
                "table_count": 0,
            },
        )
        graph.add_node(comp_node)
        created += 1

        # Layer -> CONTAINS -> Component
        if layer_name in layer_nodes:
            graph.add_edge(
                GraphEdge(
                    source_fqn=layer_nodes[layer_name],
                    target_fqn=comp_fqn,
                    kind=EdgeKind.CONTAINS,
                )
            )

        # Component -> CONTAINS -> Class
        for class_fqn in member_fqns:
            graph.add_edge(
                GraphEdge(
                    source_fqn=comp_fqn,
                    target_fqn=class_fqn,
                    kind=EdgeKind.CONTAINS,
                )
            )

    # Create database component if TABLE nodes exist
    if table_nodes:
        db_engine = _infer_database_engine(graph, detected_frameworks)
        db_layer = "Data Access"
        db_tech_key = f"db:{db_engine}"
        db_fqn = f"tech:{app_name}:{db_layer}:{db_tech_key}"

        db_node = GraphNode(
            fqn=db_fqn,
            name=_normalize_db_engine(db_engine),
            kind=NodeKind.COMPONENT,
            properties={
                "type": "technology",
                "category": "database",
                "layer": db_layer,
                "app_name": app_name,
                "class_count": 0,
                "loc_total": 0,
                "endpoint_count": 0,
                "table_count": len(table_nodes),
            },
        )
        graph.add_node(db_node)
        created += 1

        if db_layer in layer_nodes:
            graph.add_edge(
                GraphEdge(
                    source_fqn=layer_nodes[db_layer],
                    target_fqn=db_fqn,
                    kind=EdgeKind.CONTAINS,
                )
            )

        for table_fqn in table_nodes:
            graph.add_edge(
                GraphEdge(
                    source_fqn=db_fqn,
                    target_fqn=table_fqn,
                    kind=EdgeKind.CONTAINS,
                )
            )

    return created


def _infer_database_engine(graph: SymbolGraph, detected_frameworks: list[str]) -> str:
    """Infer the database engine from TABLE properties or framework hints."""
    for node in graph.nodes.values():
        if node.kind == NodeKind.TABLE:
            engine = node.properties.get("engine")
            if engine:
                return str(engine)

    # Check for Django config hints
    for node in graph.nodes.values():
        if node.kind == NodeKind.CONFIG_ENTRY:
            if "database" in node.name.lower() and "engine" in node.name.lower():
                val = node.properties.get("value", "")
                if val:
                    return str(val)

    # Framework-based hints
    if any("hibernate" in fw for fw in detected_frameworks):
        return "postgresql"
    if any("sqlalchemy" in fw for fw in detected_frameworks):
        return "postgresql"
    if any("entity-framework" in fw for fw in detected_frameworks):
        return "sqlserver"

    return "database"


def _normalize_db_engine(engine: str) -> str:
    """Convert raw engine string to a display name."""
    engine_lower = engine.lower()
    if "postgres" in engine_lower or "psycopg" in engine_lower:
        return "PostgreSQL"
    if "mysql" in engine_lower or "mariadb" in engine_lower:
        return "MySQL"
    if "sqlite" in engine_lower:
        return "SQLite"
    if "oracle" in engine_lower:
        return "Oracle"
    if "sqlserver" in engine_lower or "mssql" in engine_lower:
        return "SQL Server"
    if "mongo" in engine_lower:
        return "MongoDB"
    if engine == "database":
        return "Database"
    return engine.title()


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
