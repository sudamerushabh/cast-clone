"""Entity Framework Core plugin — DbContext entity-to-database mappings.

Finds DbContext subclasses, resolves DbSet<T> properties to entity registrations,
extracts [Table], [Column], [Key], [ForeignKey] data annotations, and infers
relationships from navigation properties (ICollection<T>, IList<T>, etc.).

Produces:
- Nodes: (:Table), (:Column)
- Edges: (:Class)-[:MAPS_TO {orm: "entity-framework"}]->(:Table)
         (:Table)-[:HAS_COLUMN]->(:Column)
         (:Column)-[:REFERENCES]->(:Column)
         (:DbContext)-[:MANAGES]->(:Entity)
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Collection types that indicate a one-to-many navigation property
_COLLECTION_TYPES = frozenset(
    {
        "ICollection",
        "IEnumerable",
        "IList",
        "List",
        "HashSet",
        "ISet",
    }
)


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------


@dataclass
class _FieldInfo:
    fqn: str
    name: str
    field_type: str
    annotations: set[str]
    annotation_args: dict[str, str]
    type_args: list[str]
    is_property: bool = False
    is_key: bool = False


@dataclass
class _EntityInfo:
    """An entity class registered in a DbContext via DbSet<T>."""

    fqn: str
    name: str
    table_name: str  # from [Table] annotation or DbSet property name
    fields: list[_FieldInfo] = dataclass_field(default_factory=list)


@dataclass
class _DbContextInfo:
    fqn: str
    name: str
    # Maps entity simple name -> (entity FQN, DbSet property name)
    entity_registrations: dict[str, tuple[str, str]] = dataclass_field(
        default_factory=dict,
    )


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class EntityFrameworkPlugin(FrameworkPlugin):
    name = "entity-framework"
    version = "1.0.0"
    supported_languages = {"csharp"}
    depends_on: list[str] = ["aspnet-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        # Check manifest for ASP.NET / EF frameworks
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                name_lower = fw.name.lower()
                if any(
                    k in name_lower
                    for k in (
                        "aspnet",
                        "entity",
                        "efcore",
                    )
                ):
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: check for DbContext subclasses in graph
        for node in context.graph.nodes.values():
            if node.properties.get("base_class") == "DbContext":
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="DbContext subclass found in graph",
                )

        return PluginDetectionResult.not_detected()

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(
            rules=[
                LayerRule(pattern="DbContext", layer="Data Access"),
            ]
        )

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("ef_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []
        layer_assignments: dict[str, str] = {}

        # Build name -> FQN index for O(1) lookups
        name_to_fqn: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind in (NodeKind.CLASS, NodeKind.INTERFACE):
                name_to_fqn[node.name] = node.fqn

        # Step 1: Find all DbContext subclasses and their DbSet<T> registrations
        db_contexts: list[_DbContextInfo] = []
        for node in graph.nodes.values():
            if node.kind != NodeKind.CLASS:
                continue
            if node.properties.get("base_class") != "DbContext":
                continue

            ctx_info = _DbContextInfo(fqn=node.fqn, name=node.name)
            layer_assignments[node.fqn] = "Data Access"

            # Find DbSet<T> properties
            for edge in graph.get_edges_from(node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                field_node = graph.get_node(edge.target_fqn)
                if field_node is None or field_node.kind != NodeKind.FIELD:
                    continue
                field_type = field_node.properties.get("type", "")
                type_args = field_node.properties.get("type_args", [])
                if "DbSet" in field_type and type_args:
                    entity_simple_name = type_args[0]
                    entity_fqn = name_to_fqn.get(entity_simple_name, entity_simple_name)
                    dbset_prop_name = field_node.name
                    ctx_info.entity_registrations[entity_simple_name] = (
                        entity_fqn,
                        dbset_prop_name,
                    )

            db_contexts.append(ctx_info)

        # Step 2: Collect all entities and build _EntityInfo
        entities: dict[str, _EntityInfo] = {}  # keyed by simple name
        for ctx_info in db_contexts:
            for entity_simple_name, (
                entity_fqn,
                dbset_prop_name,
            ) in ctx_info.entity_registrations.items():
                entity_node = graph.get_node(entity_fqn)

                # Table name: [Table("x")] annotation or DbSet prop name
                table_name = dbset_prop_name  # default
                if entity_node:
                    ann_args = entity_node.properties.get("annotation_args", {})
                    annotations = set(entity_node.properties.get("annotations", []))
                    if "Table" in annotations:
                        table_override = ann_args.get("", "")
                        if table_override:
                            table_name = table_override

                entity_info = _EntityInfo(
                    fqn=entity_fqn,
                    name=entity_simple_name,
                    table_name=table_name,
                )

                # Collect fields from entity class
                if entity_node:
                    for containment_edge in graph.get_edges_from(entity_fqn):
                        if containment_edge.kind != EdgeKind.CONTAINS:
                            continue
                        field_node = graph.get_node(containment_edge.target_fqn)
                        if field_node is None or field_node.kind != NodeKind.FIELD:
                            continue

                        field_annotations = set(
                            field_node.properties.get("annotations", [])
                        )
                        field_annotation_args = field_node.properties.get(
                            "annotation_args", {}
                        )
                        field_type_args = field_node.properties.get("type_args", [])

                        entity_info.fields.append(
                            _FieldInfo(
                                fqn=field_node.fqn,
                                name=field_node.name,
                                field_type=field_node.properties.get("type", ""),
                                annotations=field_annotations,
                                annotation_args=field_annotation_args,
                                type_args=field_type_args,
                                is_property=field_node.properties.get(
                                    "is_property", False
                                ),
                                is_key="Key" in field_annotations,
                            )
                        )

                entities[entity_simple_name] = entity_info

                # MANAGES edge: DbContext -> entity
                edges.append(
                    GraphEdge(
                        source_fqn=ctx_info.fqn,
                        target_fqn=entity_fqn,
                        kind=EdgeKind.MANAGES,
                        confidence=Confidence.HIGH,
                        evidence="entity-framework",
                    )
                )

        # Step 3: Create Table/Column nodes and relationship edges
        for entity in entities.values():
            table_fqn = f"table:{entity.table_name}"

            # Create Table node
            table_node = GraphNode(
                fqn=table_fqn,
                name=entity.table_name,
                kind=NodeKind.TABLE,
                properties={"orm": "entity-framework"},
            )
            nodes.append(table_node)

            # MAPS_TO edge: entity class -> table
            edges.append(
                GraphEdge(
                    source_fqn=entity.fqn,
                    target_fqn=table_fqn,
                    kind=EdgeKind.MAPS_TO,
                    confidence=Confidence.HIGH,
                    evidence="entity-framework",
                    properties={"orm": "entity-framework"},
                )
            )

            # Process fields -> columns
            for field_info in entity.fields:
                # Skip navigation properties (collections / references)
                if self._is_collection_navigation(field_info):
                    # One-to-many: infer FK on the "many" side
                    target_entity_name = (
                        field_info.type_args[0] if field_info.type_args else ""
                    )
                    target_entity = entities.get(target_entity_name)
                    if target_entity:
                        self._infer_fk_from_navigation(
                            entity,
                            target_entity,
                            entities,
                            edges,
                            warnings,
                        )
                    continue

                if self._is_reference_navigation(field_info, entities):
                    # Single navigation property (e.g., Author Author) — skip as column,
                    # FK is handled via the matching <Name>Id property or [ForeignKey]
                    continue

                # Determine column name
                col_name = field_info.name  # default
                if "Column" in field_info.annotations:
                    col_override = field_info.annotation_args.get("", "")
                    if col_override:
                        col_name = col_override

                col_fqn = f"{table_fqn}.{col_name}"
                is_fk = "ForeignKey" in field_info.annotations

                col_node = GraphNode(
                    fqn=col_fqn,
                    name=col_name,
                    kind=NodeKind.COLUMN,
                    properties={
                        "is_primary_key": field_info.is_key,
                        "is_foreign_key": is_fk,
                    },
                )
                nodes.append(col_node)

                # HAS_COLUMN edge
                edges.append(
                    GraphEdge(
                        source_fqn=table_fqn,
                        target_fqn=col_fqn,
                        kind=EdgeKind.HAS_COLUMN,
                        confidence=Confidence.HIGH,
                        evidence="entity-framework",
                    )
                )

                # [ForeignKey("Author")] -> REFERENCES edge
                if is_fk:
                    fk_target = field_info.annotation_args.get("", "")
                    if fk_target:
                        target_entity = entities.get(fk_target)
                        if target_entity:
                            target_pk = self._find_pk_column(target_entity)
                            if target_pk:
                                target_col_fqn = (
                                    f"table:{target_entity.table_name}.{target_pk}"
                                )
                                edges.append(
                                    GraphEdge(
                                        source_fqn=col_fqn,
                                        target_fqn=target_col_fqn,
                                        kind=EdgeKind.REFERENCES,
                                        confidence=Confidence.HIGH,
                                        evidence="entity-framework",
                                    )
                                )

        log.info(
            "ef_extract_done",
            db_contexts=len(db_contexts),
            entities=len(entities),
            tables=len([n for n in nodes if n.kind == NodeKind.TABLE]),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    def _is_collection_navigation(self, field_info: _FieldInfo) -> bool:
        """Check if a field is a collection navigation property (one-to-many)."""
        field_type = field_info.field_type
        for coll_type in _COLLECTION_TYPES:
            if field_type == coll_type or field_type.startswith(coll_type + "<"):
                return True
        return False

    def _is_reference_navigation(
        self, field_info: _FieldInfo, entities: dict[str, _EntityInfo]
    ) -> bool:
        """Check if a field is a reference navigation property."""
        # If the field type matches a known entity name, it's a navigation property
        field_type = field_info.field_type
        return field_type in entities

    def _find_pk_column(self, entity: _EntityInfo) -> str | None:
        """Find the primary key column name for an entity."""
        for field_info in entity.fields:
            if field_info.is_key:
                # Check for [Column] override on the PK field
                if "Column" in field_info.annotations:
                    col_override = field_info.annotation_args.get("", "")
                    if col_override:
                        return col_override
                return field_info.name
        return None

    def _infer_fk_from_navigation(
        self,
        owner_entity: _EntityInfo,
        target_entity: _EntityInfo,
        all_entities: dict[str, _EntityInfo],
        edges: list[GraphEdge],
        warnings: list[str],
    ) -> None:
        """Infer FK from a collection navigation.

        E.g. Author.Books -> Book.AuthorId references Author.Id.
        Looks for a conventional FK on the target named <OwnerName>Id.
        """
        expected_fk_name = f"{owner_entity.name}Id"
        owner_pk = self._find_pk_column(owner_entity)
        if not owner_pk:
            return

        for field_info in target_entity.fields:
            if field_info.name == expected_fk_name:
                # Found the FK property — create REFERENCES edge
                fk_col_fqn = f"table:{target_entity.table_name}.{field_info.name}"
                pk_col_fqn = f"table:{owner_entity.table_name}.{owner_pk}"
                edges.append(
                    GraphEdge(
                        source_fqn=fk_col_fqn,
                        target_fqn=pk_col_fqn,
                        kind=EdgeKind.REFERENCES,
                        confidence=Confidence.MEDIUM,
                        evidence="entity-framework:convention",
                    )
                )
                return

        warnings.append(
            f"Collection navigation {owner_entity.name} -> {target_entity.name} "
            f"but no FK property '{expected_fk_name}' found on {target_entity.name}"
        )
