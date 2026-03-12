"""Hibernate/JPA plugin — entity-to-table mapping, column extraction, FK relationships.

Finds @Entity classes, derives table/column names, and resolves relationship
annotations (@OneToMany, @ManyToOne, @ManyToMany, @OneToOne) into REFERENCES
edges between columns and MAPS_TO edges between entities and tables.

Produces:
- Nodes: (:Table), (:Column)
- Edges: (:Class)-[:MAPS_TO {orm: "hibernate"}]->(:Table)
         (:Table)-[:HAS_COLUMN]->(:Column)
         (:Column)-[:REFERENCES]->(:Column)
"""

from __future__ import annotations

import re
import structlog
from dataclasses import dataclass, field as dataclass_field

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


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case: 'firstName' -> 'first_name', 'User' -> 'user'."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1).lower()


def _pluralize(name: str) -> str:
    """Naive pluralization: add 's' (handles common cases)."""
    if name.endswith("s") or name.endswith("x") or name.endswith("z"):
        return name + "es"
    if name.endswith("y") and len(name) > 1 and name[-2] not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def _derive_table_name(class_name: str) -> str:
    """Derive table name from entity class name: 'User' -> 'users', 'OrderItem' -> 'order_items'."""
    return _pluralize(_camel_to_snake(class_name))


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------


@dataclass
class _FieldInfo:
    fqn: str
    name: str
    field_type: str
    column_name: str
    annotations: set[str]
    annotation_args: dict[str, str]
    type_args: list[str]
    is_id: bool = False


@dataclass
class _EntityInfo:
    fqn: str
    name: str
    table_name: str
    fields: list[_FieldInfo] = dataclass_field(default_factory=list)


class HibernateJPAPlugin(FrameworkPlugin):
    name = "hibernate"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = ["spring-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                name_lower = fw.name.lower()
                if "hibernate" in name_lower or "jpa" in name_lower or "spring" in name_lower:
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: check for @Entity annotations
        for node in context.graph.nodes.values():
            annotations = node.properties.get("annotations", [])
            if "Entity" in annotations:
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="@Entity annotations found in graph",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("hibernate_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []

        # Collect all entities first (needed for cross-entity FK resolution)
        entities: dict[str, _EntityInfo] = {}

        for class_node in graph.nodes.values():
            if class_node.kind != NodeKind.CLASS:
                continue
            annotations = set(class_node.properties.get("annotations", []))
            if "Entity" not in annotations:
                continue

            annotation_args = class_node.properties.get("annotation_args", {})

            # Derive table name
            table_name = annotation_args.get("Table") or _derive_table_name(class_node.name)

            entity_info = _EntityInfo(
                fqn=class_node.fqn,
                name=class_node.name,
                table_name=table_name,
                fields=[],
            )

            # Collect fields
            for containment_edge in graph.get_edges_from(class_node.fqn):
                if containment_edge.kind != EdgeKind.CONTAINS:
                    continue
                field_node = graph.get_node(containment_edge.target_fqn)
                if field_node is None or field_node.kind != NodeKind.FIELD:
                    continue
                field_annotations = set(field_node.properties.get("annotations", []))
                field_annotation_args = field_node.properties.get("annotation_args", {})
                field_type_args = field_node.properties.get("type_args", [])

                # Derive column name
                column_name = field_annotation_args.get("Column") or _camel_to_snake(field_node.name)

                entity_info.fields.append(_FieldInfo(
                    fqn=field_node.fqn,
                    name=field_node.name,
                    field_type=field_node.properties.get("type", ""),
                    column_name=column_name,
                    annotations=field_annotations,
                    annotation_args=field_annotation_args,
                    type_args=field_type_args,
                    is_id="Id" in field_annotations,
                ))

            entities[class_node.name] = entity_info

        # Now create Table/Column nodes and relationship edges
        for entity in entities.values():
            table_fqn = f"table:{entity.table_name}"

            # Create Table node
            table_node = GraphNode(
                fqn=table_fqn,
                name=entity.table_name,
                kind=NodeKind.TABLE,
                properties={"column_count": len(entity.fields)},
            )
            nodes.append(table_node)

            # MAPS_TO edge: entity -> table
            edges.append(GraphEdge(
                source_fqn=entity.fqn,
                target_fqn=table_fqn,
                kind=EdgeKind.MAPS_TO,
                confidence=Confidence.HIGH,
                evidence="hibernate",
                properties={"orm": "hibernate"},
            ))

            # Create Column nodes for non-relationship fields + @Id + @JoinColumn
            for field_info in entity.fields:
                # Skip collection-type relationship fields without @JoinColumn
                is_relationship = bool(
                    field_info.annotations & {"OneToMany", "ManyToMany"}
                    and "JoinColumn" not in field_info.annotations
                    and "JoinTable" not in field_info.annotations
                )
                if is_relationship:
                    continue

                # For @ManyToOne/@OneToOne with @JoinColumn, use the JoinColumn name
                if ("ManyToOne" in field_info.annotations or "OneToOne" in field_info.annotations):
                    if "JoinColumn" in field_info.annotations:
                        col_name = field_info.annotation_args.get("JoinColumn", field_info.column_name)
                    else:
                        col_name = field_info.column_name
                else:
                    col_name = field_info.column_name

                col_fqn = f"{table_fqn}.{col_name}"
                col_node = GraphNode(
                    fqn=col_fqn,
                    name=col_name,
                    kind=NodeKind.COLUMN,
                    properties={
                        "type": field_info.field_type,
                        "is_primary_key": field_info.is_id,
                        "is_foreign_key": bool(
                            field_info.annotations & {"ManyToOne", "OneToOne", "JoinColumn"}
                            - {"Id"}
                        ),
                    },
                )
                nodes.append(col_node)

                # HAS_COLUMN edge: table -> column
                edges.append(GraphEdge(
                    source_fqn=table_fqn,
                    target_fqn=col_fqn,
                    kind=EdgeKind.HAS_COLUMN,
                    confidence=Confidence.HIGH,
                    evidence="hibernate",
                ))

                # REFERENCES edge for FK columns
                if "ManyToOne" in field_info.annotations or "OneToOne" in field_info.annotations:
                    target_entity_name = field_info.field_type
                    target_entity = entities.get(target_entity_name)
                    if target_entity:
                        # Find the PK column of the target entity
                        target_pk = self._find_pk_column(target_entity)
                        if target_pk:
                            target_col_fqn = f"table:{target_entity.table_name}.{target_pk}"
                            edges.append(GraphEdge(
                                source_fqn=col_fqn,
                                target_fqn=target_col_fqn,
                                kind=EdgeKind.REFERENCES,
                                confidence=Confidence.HIGH,
                                evidence="hibernate",
                            ))

            # Handle @ManyToMany with @JoinTable
            for field_info in entity.fields:
                if "ManyToMany" not in field_info.annotations:
                    continue
                if "JoinTable" not in field_info.annotations:
                    continue

                junction_table_name = field_info.annotation_args.get("JoinTable", "")
                if not junction_table_name:
                    continue

                junction_fqn = f"table:{junction_table_name}"
                junction_node = GraphNode(
                    fqn=junction_fqn,
                    name=junction_table_name,
                    kind=NodeKind.TABLE,
                    properties={"is_junction": True},
                )
                nodes.append(junction_node)

                # FK from junction to owning entity
                owning_pk = self._find_pk_column(entity)
                if owning_pk:
                    fk_col_name = f"{_camel_to_snake(entity.name)}_id"
                    fk_col_fqn = f"{junction_fqn}.{fk_col_name}"
                    fk_col_node = GraphNode(
                        fqn=fk_col_fqn, name=fk_col_name, kind=NodeKind.COLUMN,
                        properties={"is_foreign_key": True},
                    )
                    nodes.append(fk_col_node)
                    edges.append(GraphEdge(
                        source_fqn=junction_fqn, target_fqn=fk_col_fqn,
                        kind=EdgeKind.HAS_COLUMN, confidence=Confidence.HIGH, evidence="hibernate",
                    ))
                    edges.append(GraphEdge(
                        source_fqn=fk_col_fqn,
                        target_fqn=f"table:{entity.table_name}.{owning_pk}",
                        kind=EdgeKind.REFERENCES, confidence=Confidence.HIGH, evidence="hibernate",
                    ))

                # FK from junction to target entity
                target_entity_name = field_info.type_args[0] if field_info.type_args else ""
                target_entity = entities.get(target_entity_name)
                if target_entity:
                    target_pk = self._find_pk_column(target_entity)
                    if target_pk:
                        fk_col_name2 = f"{_camel_to_snake(target_entity_name)}_id"
                        fk_col_fqn2 = f"{junction_fqn}.{fk_col_name2}"
                        fk_col_node2 = GraphNode(
                            fqn=fk_col_fqn2, name=fk_col_name2, kind=NodeKind.COLUMN,
                            properties={"is_foreign_key": True},
                        )
                        nodes.append(fk_col_node2)
                        edges.append(GraphEdge(
                            source_fqn=junction_fqn, target_fqn=fk_col_fqn2,
                            kind=EdgeKind.HAS_COLUMN, confidence=Confidence.HIGH, evidence="hibernate",
                        ))
                        edges.append(GraphEdge(
                            source_fqn=fk_col_fqn2,
                            target_fqn=f"table:{target_entity.table_name}.{target_pk}",
                            kind=EdgeKind.REFERENCES, confidence=Confidence.HIGH, evidence="hibernate",
                        ))

        log.info("hibernate_extract_done", entities=len(entities), tables=len([n for n in nodes if n.kind == NodeKind.TABLE]))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=warnings,
        )

    def _find_pk_column(self, entity: _EntityInfo) -> str | None:
        """Find the primary key column name for an entity."""
        for field_info in entity.fields:
            if field_info.is_id:
                return field_info.column_name
        return None
