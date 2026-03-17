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
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
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

        # Step 2b: Apply Fluent API configurations (overrides data annotations)
        self._apply_fluent_configurations(
            db_contexts, entities, name_to_fqn, edges, warnings, graph, nodes,
        )

        # Step 2c: Apply IEntityTypeConfiguration<T> classes
        for node in graph.nodes.values():
            if node.kind != NodeKind.CLASS:
                continue
            implements = node.properties.get("implements", [])
            for impl in implements:
                if impl.startswith("IEntityTypeConfiguration<") and impl.endswith(">"):
                    fluent_configs = node.properties.get("fluent_configurations", [])
                    if fluent_configs:
                        self._process_fluent_config_list(
                            fluent_configs, entities, name_to_fqn, edges, warnings, graph, nodes,
                        )
                    layer_assignments[node.fqn] = "Data Access"

        # Step 3: Parse migration classes for ground-truth schema operations
        self._parse_migrations(graph, entities, edges, warnings)

        # Step 4: Create Table/Column nodes and relationship edges
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
                # Skip [NotMapped] properties — they have no database column
                if "NotMapped" in field_info.annotations:
                    continue

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
                            all_entities=entities,
                            edges=edges,
                            warnings=warnings,
                            nav_field=field_info,
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

                # Convention-based PK: "Id" or "{ClassName}Id"
                is_pk = field_info.is_key
                if not is_pk:
                    is_pk = field_info.name == "Id" or field_info.name == f"{entity.name}Id"

                col_props: dict[str, object] = {
                    "is_primary_key": is_pk,
                    "is_foreign_key": is_fk,
                    "is_nullable": "Required" not in field_info.annotations,
                }
                max_len = field_info.annotation_args.get("MaxLength")
                if max_len is not None:
                    col_props["max_length"] = max_len

                col_node = GraphNode(
                    fqn=col_fqn,
                    name=col_name,
                    kind=NodeKind.COLUMN,
                    properties=col_props,
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
        # 1. Explicit [Key] annotation
        for field_info in entity.fields:
            if field_info.is_key:
                # Check for [Column] override on the PK field
                if "Column" in field_info.annotations:
                    col_override = field_info.annotation_args.get("", "")
                    if col_override:
                        return col_override
                return field_info.name

        # 2. Convention: "Id" or "{ClassName}Id"
        for field_info in entity.fields:
            if field_info.name == "Id" or field_info.name == f"{entity.name}Id":
                return field_info.name

        return None

    def _infer_fk_from_navigation(
        self,
        owner_entity: _EntityInfo,
        target_entity: _EntityInfo,
        all_entities: dict[str, _EntityInfo],
        edges: list[GraphEdge],
        warnings: list[str],
        nav_field: _FieldInfo | None = None,
    ) -> None:
        """Infer FK from a collection navigation.

        E.g. Author.Books -> Book.AuthorId references Author.Id.
        Looks for a conventional FK on the target named <OwnerName>Id.
        If [InverseProperty("NavName")] is present, derives FK as <NavName>Id.
        """
        # Determine expected FK name(s) to search for
        expected_fk_names: list[str] = []

        # [InverseProperty] takes priority — derive FK from the nav property name
        if nav_field and "InverseProperty" in nav_field.annotations:
            inverse_nav_name = nav_field.annotation_args.get("InverseProperty", "")
            if inverse_nav_name:
                expected_fk_names.append(f"{inverse_nav_name}Id")

        # Fallback: conventional <OwnerName>Id
        expected_fk_names.append(f"{owner_entity.name}Id")

        owner_pk = self._find_pk_column(owner_entity)
        if not owner_pk:
            return

        for expected_fk_name in expected_fk_names:
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
            f"but no FK property '{expected_fk_names[0]}' found on {target_entity.name}"
        )

    def _apply_fluent_configurations(
        self,
        db_contexts: list[_DbContextInfo],
        entities: dict[str, _EntityInfo],
        name_to_fqn: dict[str, str],
        edges: list[GraphEdge],
        warnings: list[str],
        graph: SymbolGraph,
        nodes: list[GraphNode],
    ) -> None:
        """Apply Fluent API configurations from DbContext.OnModelCreating.

        Fluent API has higher precedence than data annotations in EF Core,
        so this is called after the initial entity/table name resolution to
        allow overrides.
        """
        for ctx_info in db_contexts:
            ctx_node = graph.get_node(ctx_info.fqn)
            if ctx_node is None:
                continue
            fluent_configs: list[dict[str, str]] = ctx_node.properties.get(
                "fluent_configurations", []
            )
            if not fluent_configs:
                continue

            self._process_fluent_config_list(
                fluent_configs, entities, name_to_fqn, edges, warnings, graph, nodes,
            )

    def _process_fluent_config_list(
        self,
        fluent_configs: list[dict[str, object]],
        entities: dict[str, _EntityInfo],
        name_to_fqn: dict[str, str],
        edges: list[GraphEdge],
        warnings: list[str],
        graph: SymbolGraph,
        nodes: list[GraphNode],
    ) -> None:
        """Process a list of fluent configuration dicts.

        Shared by _apply_fluent_configurations (DbContext) and
        IEntityTypeConfiguration<T> processing.
        """
        for config in fluent_configs:
            entity_name = str(config.get("entity", ""))
            entity_info = entities.get(entity_name)
            if entity_info is None:
                warnings.append(
                    f"Fluent config references unknown entity '{entity_name}'"
                )
                continue

            # Table name override: .ToTable("name")
            if "table" in config:
                entity_info.table_name = str(config["table"])

            # Column name override: .Property(x => x.Prop).HasColumnName("name")
            if "property" in config and "column" in config:
                prop_name = str(config["property"])
                col_name = str(config["column"])
                for field_info in entity_info.fields:
                    if field_info.name == prop_name:
                        # Inject a Column annotation override so column creation picks it up
                        field_info.annotations.add("Column")
                        field_info.annotation_args[""] = col_name
                        break

            # Composite key: .HasKey(x => new { x.A, x.B })
            if "composite_key" in config:
                composite_fields = config["composite_key"]
                if isinstance(composite_fields, list):
                    for field_info in entity_info.fields:
                        if field_info.name in composite_fields:
                            field_info.is_key = True

            # Relationship: .HasOne().WithMany().HasForeignKey()
            if "has_one" in config and "foreign_key" in config:
                target_entity_name = str(config["has_one"])
                fk_field_name = str(config["foreign_key"])
                target_entity = entities.get(target_entity_name)
                if target_entity is None:
                    warnings.append(
                        f"Fluent relationship on '{entity_name}' references "
                        f"unknown target entity '{target_entity_name}'"
                    )
                    continue

                target_pk = self._find_pk_column(target_entity)
                fk_col_fqn = f"table:{entity_info.table_name}.{fk_field_name}"
                if target_pk:
                    pk_col_fqn = f"table:{target_entity.table_name}.{target_pk}"
                else:
                    # Fallback: reference the table itself
                    pk_col_fqn = f"table:{target_entity.table_name}"

                edges.append(
                    GraphEdge(
                        source_fqn=fk_col_fqn,
                        target_fqn=pk_col_fqn,
                        kind=EdgeKind.REFERENCES,
                        confidence=Confidence.HIGH,
                        evidence="entity-framework:fluent-api",
                    )
                )

            # Many-to-many: .HasMany().WithMany().UsingEntity()
            if "has_many" in config and "with_many" in config:
                target_entity_name = str(config["has_many"])
                join_table_name = str(
                    config.get("using_entity", f"{entity_name}{target_entity_name}")
                )
                # Resolve target: try direct name first, then match by table_name
                target_entity = entities.get(target_entity_name)
                if target_entity is None:
                    for ent in entities.values():
                        if ent.table_name == target_entity_name:
                            target_entity = ent
                            target_entity_name = ent.name
                            break
                if entity_info and target_entity:
                    join_fqn = f"table:{join_table_name}"
                    nodes.append(
                        GraphNode(
                            fqn=join_fqn,
                            name=join_table_name,
                            kind=NodeKind.TABLE,
                            properties={"orm": "entity-framework", "is_join_table": True},
                        )
                    )
                    source_pk = self._find_pk_column(entity_info)
                    target_pk = self._find_pk_column(target_entity)
                    if source_pk:
                        edges.append(
                            GraphEdge(
                                source_fqn=f"{join_fqn}.{entity_name}Id",
                                target_fqn=f"table:{entity_info.table_name}.{source_pk}",
                                kind=EdgeKind.REFERENCES,
                                confidence=Confidence.HIGH,
                                evidence="entity-framework:fluent-api",
                            )
                        )
                    if target_pk:
                        edges.append(
                            GraphEdge(
                                source_fqn=f"{join_fqn}.{target_entity_name}Id",
                                target_fqn=f"table:{target_entity.table_name}.{target_pk}",
                                kind=EdgeKind.REFERENCES,
                                confidence=Confidence.HIGH,
                                evidence="entity-framework:fluent-api",
                            )
                        )

    def _parse_migrations(
        self,
        graph: SymbolGraph,
        entities: dict[str, _EntityInfo],
        edges: list[GraphEdge],
        warnings: list[str],
    ) -> None:
        """Parse migration classes for ground-truth schema operations."""
        for node in graph.nodes.values():
            migration_ops = node.properties.get("migration_operations")
            if not migration_ops:
                continue

            for op in migration_ops:
                if op.get("operation") == "AddForeignKey":
                    table = op.get("table", "")
                    column = op.get("column", "")
                    principal_table = op.get("principal_table", "")
                    principal_column = op.get("principal_column", "")
                    if table and column and principal_table and principal_column:
                        edges.append(
                            GraphEdge(
                                source_fqn=f"table:{table}.{column}",
                                target_fqn=f"table:{principal_table}.{principal_column}",
                                kind=EdgeKind.REFERENCES,
                                confidence=Confidence.HIGH,
                                evidence="entity-framework:migration",
                            )
                        )
