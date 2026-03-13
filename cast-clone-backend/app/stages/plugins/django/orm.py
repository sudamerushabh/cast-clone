"""Django ORM plugin -- model-to-table mapping, ForeignKey/M2M/O2O resolution.

Finds classes inheriting from ``models.Model``, derives table names using
Django conventions (``{app_label}_{model_lower}``), extracts columns from
model fields, and resolves relationship fields (ForeignKey, ManyToManyField,
OneToOneField) into REFERENCES edges.

Produces:
- Nodes: (:Table), (:Column)
- Edges: (:Class)-[:MAPS_TO {orm: "django"}]->(:Table)
         (:Table)-[:HAS_COLUMN]->(:Column)
         (:Column)-[:REFERENCES]->(:Column)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Regex patterns for Django model field parsing
# ---------------------------------------------------------------------------

_MODEL_FIELD_RE = re.compile(r"^models\.(\w+)\(")
_FK_TARGET_RE = re.compile(r"^models\.(?:ForeignKey|OneToOneField)\(\s*(\w+)")
_M2M_TARGET_RE = re.compile(r"^models\.ManyToManyField\(\s*(\w+)")
_PK_RE = re.compile(r"primary_key\s*=\s*True")


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------


@dataclass
class _FieldInfo:
    fqn: str
    name: str
    value: str
    field_type: str  # e.g. "AutoField", "CharField", "ForeignKey"
    is_pk: bool = False
    is_fk: bool = False
    is_o2o: bool = False
    is_m2m: bool = False
    fk_target_name: str = ""  # short class name of the FK target


@dataclass
class _ModelInfo:
    fqn: str
    name: str
    table_name: str
    fields: list[_FieldInfo] = dataclass_field(default_factory=list)


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class DjangoORMPlugin(FrameworkPlugin):
    name = "django-orm"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = ["django-settings"]

    # -----------------------------------------------------------------------
    # Detection
    # -----------------------------------------------------------------------

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        # Check manifest for Django framework
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "django" in fw.name.lower() and "rest" not in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: look for classes inheriting from models.Model
        for edge in context.graph.edges:
            if edge.kind == EdgeKind.INHERITS and "models.Model" in edge.target_fqn:
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="Class inheriting from models.Model found in graph",
                )

        return PluginDetectionResult.not_detected()

    # -----------------------------------------------------------------------
    # Extraction
    # -----------------------------------------------------------------------

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("django_orm_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []
        layer_assignments: dict[str, str] = {}

        # 1. Collect all Django model classes
        models = self._collect_models(graph)
        log.info("django_orm_models_found", count=len(models))

        # Build name -> ModelInfo lookup for FK resolution
        model_by_name: dict[str, _ModelInfo] = {m.name: m for m in models.values()}

        # 2. Create Table + Column nodes for each model
        for model in models.values():
            table_fqn = f"table:{model.table_name}"

            # Table node
            table_node = GraphNode(
                fqn=table_fqn,
                name=model.table_name,
                kind=NodeKind.TABLE,
                properties={
                    "column_count": len(
                        [f for f in model.fields if not f.name.startswith("_")]
                    )
                },
            )
            nodes.append(table_node)

            # MAPS_TO edge: model class -> table
            edges.append(
                GraphEdge(
                    source_fqn=model.fqn,
                    target_fqn=table_fqn,
                    kind=EdgeKind.MAPS_TO,
                    confidence=Confidence.HIGH,
                    evidence="django-orm",
                    properties={"orm": "django"},
                )
            )

            # Layer assignment
            layer_assignments[model.fqn] = "Data Access"

            # Columns from regular fields + FK/O2O fields
            for field_info in model.fields:
                # Skip metadata fields (start with _)
                if field_info.name.startswith("_"):
                    continue

                # ManyToManyField -> handled separately (junction table)
                if field_info.is_m2m:
                    self._handle_m2m(
                        field_info,
                        model,
                        model_by_name,
                        table_fqn,
                        nodes,
                        edges,
                    )
                    continue

                # For FK / O2O, Django creates a {field}_id column
                if field_info.is_fk or field_info.is_o2o:
                    col_name = f"{field_info.name}_id"
                else:
                    col_name = field_info.name

                col_fqn = f"{table_fqn}.{col_name}"
                col_node = GraphNode(
                    fqn=col_fqn,
                    name=col_name,
                    kind=NodeKind.COLUMN,
                    properties={
                        "type": field_info.field_type,
                        "is_primary_key": field_info.is_pk,
                        "is_foreign_key": field_info.is_fk or field_info.is_o2o,
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
                        evidence="django-orm",
                    )
                )

                # REFERENCES edge for FK / O2O
                if field_info.is_fk or field_info.is_o2o:
                    target_model = model_by_name.get(field_info.fk_target_name)
                    if target_model:
                        target_table_fqn = f"table:{target_model.table_name}"
                        # Reference the PK of the target table (default: id)
                        target_pk = self._find_pk_column(target_model)
                        edges.append(
                            GraphEdge(
                                source_fqn=col_fqn,
                                target_fqn=f"{target_table_fqn}.{target_pk}",
                                kind=EdgeKind.REFERENCES,
                                confidence=Confidence.HIGH,
                                evidence="django-orm",
                            )
                        )

        log.info(
            "django_orm_extract_complete",
            models=len(models),
            tables=len([n for n in nodes if n.kind == NodeKind.TABLE]),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _collect_models(self, graph: SymbolGraph) -> dict[str, _ModelInfo]:
        """Find all classes inheriting from models.Model and extract their fields."""
        models: dict[str, _ModelInfo] = {}

        # Find classes that inherit from models.Model
        model_fqns: set[str] = set()
        for edge in graph.edges:
            if edge.kind == EdgeKind.INHERITS and "models.Model" in edge.target_fqn:
                model_fqns.add(edge.source_fqn)

        for fqn in model_fqns:
            class_node = graph.get_node(fqn)
            if class_node is None or class_node.kind != NodeKind.CLASS:
                continue

            # Derive table name
            table_name = self._derive_table_name(graph, class_node)

            model_info = _ModelInfo(
                fqn=fqn,
                name=class_node.name,
                table_name=table_name,
            )

            # Collect fields via CONTAINS edges
            for edge in graph.get_edges_from(fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                field_node = graph.get_node(edge.target_fqn)
                if field_node is None or field_node.kind != NodeKind.FIELD:
                    continue

                value = field_node.properties.get("value", "")
                field_type_match = _MODEL_FIELD_RE.match(value)
                field_type = field_type_match.group(1) if field_type_match else ""

                is_pk = bool(_PK_RE.search(value))

                # FK / O2O detection
                fk_match = _FK_TARGET_RE.match(value)
                is_fk = fk_match is not None and "ForeignKey" in value
                is_o2o = fk_match is not None and "OneToOneField" in value
                fk_target = fk_match.group(1) if fk_match else ""

                # M2M detection
                m2m_match = _M2M_TARGET_RE.match(value)
                is_m2m = m2m_match is not None

                model_info.fields.append(
                    _FieldInfo(
                        fqn=field_node.fqn,
                        name=field_node.name,
                        value=value,
                        field_type=field_type,
                        is_pk=is_pk,
                        is_fk=is_fk,
                        is_o2o=is_o2o,
                        is_m2m=is_m2m,
                        fk_target_name=fk_target
                        if (is_fk or is_o2o)
                        else (m2m_match.group(1) if m2m_match else ""),
                    )
                )

            models[fqn] = model_info

        return models

    def _derive_table_name(self, graph: SymbolGraph, class_node: GraphNode) -> str:
        """Derive table name: _meta_db_table override or {app}_{model_lower}."""
        # Check for custom db_table via _meta_db_table field
        for edge in graph.get_edges_from(class_node.fqn):
            if edge.kind != EdgeKind.CONTAINS:
                continue
            field_node = graph.get_node(edge.target_fqn)
            if field_node and field_node.name == "_meta_db_table":
                raw = field_node.properties.get("value", "")
                # Strip quotes: '"custom_users"' -> 'custom_users'
                return raw.strip("\"' ")

        # Convention: {app_label}_{model_lower}
        # FQN like "myapp.models.User" -> app_label = "myapp"
        parts = class_node.fqn.split(".")
        app_label = parts[0] if parts else ""
        model_lower = class_node.name.lower()
        return f"{app_label}_{model_lower}"

    def _find_pk_column(self, model: _ModelInfo) -> str:
        """Find the primary key column name for a model. Defaults to 'id'."""
        for field_info in model.fields:
            if field_info.is_pk:
                return field_info.name
        return "id"

    def _handle_m2m(
        self,
        field_info: _FieldInfo,
        source_model: _ModelInfo,
        model_by_name: dict[str, _ModelInfo],
        source_table_fqn: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> None:
        """Create junction table + FK columns for a ManyToManyField."""
        target_model = model_by_name.get(field_info.fk_target_name)
        if target_model is None:
            return

        # Junction table: {app}_{source_model}_{field_name}
        parts = source_model.fqn.split(".")
        app_label = parts[0] if parts else ""
        junction_name = f"{app_label}_{source_model.name.lower()}_{field_info.name}"
        junction_fqn = f"table:{junction_name}"

        # Junction table node
        junction_node = GraphNode(
            fqn=junction_fqn,
            name=junction_name,
            kind=NodeKind.TABLE,
            properties={"is_junction": True},
        )
        nodes.append(junction_node)

        # FK column -> source table
        source_pk = self._find_pk_column(source_model)
        src_fk_col_name = f"{source_model.name.lower()}_id"
        src_fk_col_fqn = f"{junction_fqn}.{src_fk_col_name}"
        nodes.append(
            GraphNode(
                fqn=src_fk_col_fqn,
                name=src_fk_col_name,
                kind=NodeKind.COLUMN,
                properties={"is_foreign_key": True},
            )
        )
        edges.append(
            GraphEdge(
                source_fqn=junction_fqn,
                target_fqn=src_fk_col_fqn,
                kind=EdgeKind.HAS_COLUMN,
                confidence=Confidence.HIGH,
                evidence="django-orm",
            )
        )
        edges.append(
            GraphEdge(
                source_fqn=src_fk_col_fqn,
                target_fqn=f"{source_table_fqn}.{source_pk}",
                kind=EdgeKind.REFERENCES,
                confidence=Confidence.HIGH,
                evidence="django-orm",
            )
        )

        # FK column -> target table
        target_pk = self._find_pk_column(target_model)
        tgt_fk_col_name = f"{target_model.name.lower()}_id"
        tgt_fk_col_fqn = f"{junction_fqn}.{tgt_fk_col_name}"
        nodes.append(
            GraphNode(
                fqn=tgt_fk_col_fqn,
                name=tgt_fk_col_name,
                kind=NodeKind.COLUMN,
                properties={"is_foreign_key": True},
            )
        )
        edges.append(
            GraphEdge(
                source_fqn=junction_fqn,
                target_fqn=tgt_fk_col_fqn,
                kind=EdgeKind.HAS_COLUMN,
                confidence=Confidence.HIGH,
                evidence="django-orm",
            )
        )
        edges.append(
            GraphEdge(
                source_fqn=tgt_fk_col_fqn,
                target_fqn=f"table:{target_model.table_name}.{target_pk}",
                kind=EdgeKind.REFERENCES,
                confidence=Confidence.HIGH,
                evidence="django-orm",
            )
        )
