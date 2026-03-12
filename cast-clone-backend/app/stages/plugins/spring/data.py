"""Spring Data plugin — repository interface detection and query resolution.

Finds interfaces extending JpaRepository/CrudRepository, resolves the managed
entity type from generics, parses derived query method names (findByEmailAndStatus)
into column references, and parses @Query annotation SQL.

Produces:
- Edges: (:Interface)-[:MANAGES]->(:Class {entity})
         (:Function)-[:READS {columns}]->(:Table)
         (:Function)-[:WRITES {columns}]->(:Table)
"""

from __future__ import annotations

import re
import structlog

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext, EntryPoint
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Spring Data repository base interfaces
_REPO_BASE_INTERFACES = frozenset({
    "JpaRepository", "CrudRepository", "PagingAndSortingRepository",
    "ReactiveCrudRepository", "Repository",
})

# Derived query method prefixes and their access type
_READ_PREFIXES = ("findBy", "getBy", "queryBy", "readBy", "searchBy", "streamBy", "countBy", "existsBy")
_WRITE_PREFIXES = ("deleteBy", "removeBy")

# Keywords that separate field names in derived queries
_QUERY_KEYWORDS = re.compile(
    r"(And|Or|Between|LessThan|GreaterThan|LessThanEqual|GreaterThanEqual|"
    r"After|Before|IsNull|IsNotNull|NotNull|Like|NotLike|StartingWith|"
    r"EndingWith|Containing|OrderBy|Not|In|NotIn|True|False|"
    r"IgnoreCase|AllIgnoreCase|Top\d*|First\d*|Distinct)"
)


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1).lower()


def _parse_derived_query_fields(method_name: str) -> tuple[str, list[str]]:
    """Parse a Spring Data derived query method name into (access_type, [field_names]).

    Examples:
        findByEmail -> ("read", ["email"])
        findByEmailAndStatus -> ("read", ["email", "status"])
        deleteByEmail -> ("write", ["email"])
        countByStatus -> ("read", ["status"])

    Returns ("unknown", []) if the method name doesn't match a known pattern.
    """
    access_type = "unknown"
    remaining = ""

    for prefix in _READ_PREFIXES:
        if method_name.startswith(prefix):
            access_type = "read"
            remaining = method_name[len(prefix):]
            break

    if access_type == "unknown":
        for prefix in _WRITE_PREFIXES:
            if method_name.startswith(prefix):
                access_type = "write"
                remaining = method_name[len(prefix):]
                break

    if access_type == "unknown" or not remaining:
        return access_type, []

    # Remove OrderBy clause
    order_by_idx = remaining.find("OrderBy")
    if order_by_idx >= 0:
        remaining = remaining[:order_by_idx]

    # Split on keywords to extract field names
    # First, split by And/Or which are the main separators
    parts = re.split(r"(?:And|Or)", remaining)

    fields = []
    for part in parts:
        if not part:
            continue
        # Remove trailing condition keywords
        clean = _QUERY_KEYWORDS.sub("", part).strip()
        if clean:
            # Convert PascalCase field name to snake_case column name
            fields.append(_camel_to_snake(clean))

    return access_type, fields


def _extract_table_refs_from_query(query_str: str, entity_to_table: dict[str, str]) -> tuple[set[str], set[str]]:
    """Extract table references from a @Query string (JPQL or native SQL).

    Returns (tables_read, tables_written).
    For JPQL, entity names are mapped to table names.
    For native SQL, table names are used directly.
    """
    tables_read: set[str] = set()
    tables_written: set[str] = set()

    query_upper = query_str.upper().strip()

    # Try to detect if it's a SELECT, INSERT, UPDATE, DELETE
    if query_upper.startswith("SELECT") or query_upper.startswith("FROM"):
        # Extract FROM and JOIN clauses
        # JPQL: FROM User u -> entity name "User"
        # Native: FROM users u -> table name "users"
        from_matches = re.findall(r'\bFROM\s+(\w+)', query_str, re.IGNORECASE)
        join_matches = re.findall(r'\bJOIN\s+(\w+)', query_str, re.IGNORECASE)
        for name in from_matches + join_matches:
            # Check if it's an entity name
            if name in entity_to_table:
                tables_read.add(entity_to_table[name])
            else:
                # Might be a raw table name
                tables_read.add(name)

    elif query_upper.startswith("UPDATE"):
        update_match = re.search(r'\bUPDATE\s+(\w+)', query_str, re.IGNORECASE)
        if update_match:
            name = update_match.group(1)
            if name in entity_to_table:
                tables_written.add(entity_to_table[name])
            else:
                tables_written.add(name)

    elif query_upper.startswith("DELETE"):
        delete_match = re.search(r'\bFROM\s+(\w+)', query_str, re.IGNORECASE)
        if delete_match:
            name = delete_match.group(1)
            if name in entity_to_table:
                tables_written.add(entity_to_table[name])
            else:
                tables_written.add(name)

    elif query_upper.startswith("INSERT"):
        insert_match = re.search(r'\bINTO\s+(\w+)', query_str, re.IGNORECASE)
        if insert_match:
            name = insert_match.group(1)
            if name in entity_to_table:
                tables_written.add(entity_to_table[name])
            else:
                tables_written.add(name)

    return tables_read, tables_written


class SpringDataPlugin(FrameworkPlugin):
    name = "spring-data"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = ["spring-di", "hibernate"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "spring" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("spring_data_extract_start")

        graph = context.graph
        edges: list[GraphEdge] = []
        warnings: list[str] = []

        # Build entity name -> table FQN mapping from MAPS_TO edges (produced by Hibernate plugin)
        entity_to_table: dict[str, str] = {}  # entity class name -> table FQN
        entity_name_to_table_name: dict[str, str] = {}  # entity class name -> table name
        for edge in graph.edges:
            if edge.kind == EdgeKind.MAPS_TO:
                entity_node = graph.get_node(edge.source_fqn)
                table_node = graph.get_node(edge.target_fqn)
                if entity_node and table_node:
                    entity_to_table[entity_node.name] = edge.target_fqn
                    entity_name_to_table_name[entity_node.name] = table_node.name

        # Find repository interfaces
        for node in graph.nodes.values():
            if not node.properties.get("is_interface", False):
                continue
            implements = set(node.properties.get("implements", []))
            if not (implements & _REPO_BASE_INTERFACES):
                continue

            type_args = node.properties.get("type_args", [])
            if not type_args:
                continue

            entity_name = type_args[0]

            # MANAGES edge: repository -> entity
            entity_fqn = self._find_entity_fqn(graph, entity_name)
            if entity_fqn:
                edges.append(GraphEdge(
                    source_fqn=node.fqn,
                    target_fqn=entity_fqn,
                    kind=EdgeKind.MANAGES,
                    confidence=Confidence.HIGH,
                    evidence="spring-data",
                ))

            # Get the table FQN for this entity
            table_fqn = entity_to_table.get(entity_name)
            if not table_fqn:
                warnings.append(f"No table mapping found for entity '{entity_name}' in repo '{node.fqn}'")
                continue

            # Process methods
            for containment_edge in graph.get_edges_from(node.fqn):
                if containment_edge.kind != EdgeKind.CONTAINS:
                    continue
                method = graph.get_node(containment_edge.target_fqn)
                if method is None or method.kind != NodeKind.FUNCTION:
                    continue

                method_annotations = set(method.properties.get("annotations", []))
                method_annotation_args = method.properties.get("annotation_args", {})

                # Check @Query annotation first
                if "Query" in method_annotations:
                    query_str = method_annotation_args.get("Query", "")
                    if query_str:
                        reads, writes = _extract_table_refs_from_query(
                            query_str, entity_name_to_table_name
                        )
                        for table_name in reads:
                            t_fqn = f"table:{table_name}"
                            if graph.get_node(t_fqn) or t_fqn == table_fqn:
                                edges.append(GraphEdge(
                                    source_fqn=method.fqn,
                                    target_fqn=t_fqn,
                                    kind=EdgeKind.READS,
                                    confidence=Confidence.HIGH,
                                    evidence="spring-data",
                                    properties={"query_type": "SELECT"},
                                ))
                        for table_name in writes:
                            t_fqn = f"table:{table_name}"
                            edges.append(GraphEdge(
                                source_fqn=method.fqn,
                                target_fqn=t_fqn,
                                kind=EdgeKind.WRITES,
                                confidence=Confidence.HIGH,
                                evidence="spring-data",
                                properties={"query_type": "MODIFY"},
                            ))
                    continue

                # Parse derived query method name
                access_type, columns = _parse_derived_query_fields(method.name)
                if access_type == "read":
                    edges.append(GraphEdge(
                        source_fqn=method.fqn,
                        target_fqn=table_fqn,
                        kind=EdgeKind.READS,
                        confidence=Confidence.HIGH,
                        evidence="spring-data",
                        properties={
                            "query_type": "FIND",
                            "columns": columns,
                        },
                    ))
                elif access_type == "write":
                    edges.append(GraphEdge(
                        source_fqn=method.fqn,
                        target_fqn=table_fqn,
                        kind=EdgeKind.WRITES,
                        confidence=Confidence.HIGH,
                        evidence="spring-data",
                        properties={
                            "query_type": "DELETE",
                            "columns": columns,
                        },
                    ))

        log.info("spring_data_extract_done", edges=len(edges))

        return PluginResult(
            nodes=[],
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=warnings,
        )

    def _find_entity_fqn(self, graph: SymbolGraph, entity_name: str) -> str | None:
        """Find the FQN of an entity class by its simple name."""
        for node in graph.nodes.values():
            if node.kind == NodeKind.CLASS and node.name == entity_name:
                annotations = node.properties.get("annotations", [])
                if "Entity" in annotations:
                    return node.fqn
        return None
