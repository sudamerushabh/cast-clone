"""SQLAlchemy plugin.

Detects SQLAlchemy declarative models (classes with __tablename__),
extracts Column definitions, resolves ForeignKey references, and
produces Table/Column nodes + MAPS_TO/HAS_COLUMN/REFERENCES edges.

Produces:
- Table nodes: (:Table {name})
- Column nodes: (:Column {name, is_primary_key, column_type})
- MAPS_TO edges: (:Class)-[:MAPS_TO {orm: "sqlalchemy"}]->(:Table)
- HAS_COLUMN edges: (:Table)-[:HAS_COLUMN]->(:Column)
- REFERENCES edges: (:Column)-[:REFERENCES]->(:Column)
- Layer assignments: model classes -> Data Access
"""

from __future__ import annotations

import re
from typing import Any

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

# Regex patterns for parsing Column/mapped_column values
_COLUMN_RE = re.compile(r"^(Column|mapped_column)\(")
# Captures the first positional argument of ``mapped_column``/``Column`` —
# the SQL type, e.g. ``Integer``, ``String(255)``, ``DateTime(timezone=True)``,
# ``ForeignKey("users.id")``.  ``ForeignKey`` is filtered downstream because
# its first arg is a column reference, not a type literal.
_COLUMN_TYPE_RE = re.compile(
    r"^(?:Column|mapped_column)\(\s*([A-Z][A-Za-z0-9_]*)(?:\([^)]*\))?"
)
# No closing-paren anchor — intentional: kwargs like ondelete="CASCADE"
# may follow the target string.
_FK_RE = re.compile(r'ForeignKey\(\s*["\']([^"\']+)["\']')
_PK_RE = re.compile(r"primary_key\s*=\s*True")
_RELATIONSHIP_RE = re.compile(r"^relationship\(")
_TABLENAME_RE = re.compile(r'^["\']([^"\']+)["\']$')


class SQLAlchemyPlugin(FrameworkPlugin):
    name = "sqlalchemy"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "sqlalchemy" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        for node in context.graph.nodes.values():
            if (
                node.kind == NodeKind.FIELD
                and node.language == "python"
                and node.name == "__tablename__"
            ):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="__tablename__ field found in graph",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("sqlalchemy_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        models = self._find_models(graph)
        log.info("sqlalchemy_models_found", count=len(models))

        for model_fqn, table_name in models.items():
            table_fqn = f"table:{table_name}"
            table_node = GraphNode(
                fqn=table_fqn,
                name=table_name,
                kind=NodeKind.TABLE,
                properties={"orm": "sqlalchemy"},
            )
            nodes.append(table_node)

            edges.append(
                GraphEdge(
                    source_fqn=model_fqn,
                    target_fqn=table_fqn,
                    kind=EdgeKind.MAPS_TO,
                    confidence=Confidence.HIGH,
                    evidence="sqlalchemy-tablename",
                    properties={"orm": "sqlalchemy"},
                )
            )

            layer_assignments[model_fqn] = "Data Access"

            col_nodes, col_edges, fk_edges = self._extract_columns(
                graph, model_fqn, table_name
            )
            nodes.extend(col_nodes)
            edges.extend(col_edges)
            edges.extend(fk_edges)

        log.info(
            "sqlalchemy_extract_complete",
            tables=len(models),
            columns=len([n for n in nodes if n.kind == NodeKind.COLUMN]),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    def _find_models(self, graph: SymbolGraph) -> dict[str, str]:
        """Find classes with __tablename__ field. Returns {class_fqn: table_name}."""
        models: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind != NodeKind.CLASS or node.language != "python":
                continue
            for edge in graph.get_edges_from(node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                child = graph.nodes.get(edge.target_fqn)
                if (
                    child
                    and child.kind == NodeKind.FIELD
                    and child.name == "__tablename__"
                ):
                    value = child.properties.get("value", "").strip()
                    match = _TABLENAME_RE.match(value)
                    if match:
                        models[node.fqn] = match.group(1)
                    break
        return models

    def _extract_columns(
        self,
        graph: SymbolGraph,
        model_fqn: str,
        table_name: str,
    ) -> tuple[list[GraphNode], list[GraphEdge], list[GraphEdge]]:
        """Extract Column nodes and FK edges from a model's fields."""
        col_nodes: list[GraphNode] = []
        has_col_edges: list[GraphEdge] = []
        fk_edges: list[GraphEdge] = []
        table_fqn = f"table:{table_name}"

        for edge in graph.get_edges_from(model_fqn):
            if edge.kind != EdgeKind.CONTAINS:
                continue
            field_node = graph.nodes.get(edge.target_fqn)
            if not field_node or field_node.kind != NodeKind.FIELD:
                continue

            field_name = field_node.name
            value = field_node.properties.get("value", "")

            if field_name.startswith("__"):
                continue
            if _RELATIONSHIP_RE.match(value):
                continue
            if not _COLUMN_RE.match(value):
                continue

            is_pk = bool(_PK_RE.search(value))
            col_props: dict[str, Any] = {
                "is_primary_key": is_pk,
                "table": table_name,
            }
            # Pull the SQL type literal off the first positional arg.
            # ``ForeignKey(...)`` matches the regex but is a column reference,
            # not a type — skip it.  Falls through to no-type for non-matching
            # columns; downstream linkers (Pydantic MAPS_TO) treat empty type
            # as "do not match", which is the safe default.
            type_match = _COLUMN_TYPE_RE.match(value)
            if type_match and type_match.group(1) != "ForeignKey":
                col_props["type"] = type_match.group(1)
            col_fqn = f"table:{table_name}.{field_name}"
            col_node = GraphNode(
                fqn=col_fqn,
                name=field_name,
                kind=NodeKind.COLUMN,
                properties=col_props,
            )
            col_nodes.append(col_node)

            has_col_edges.append(
                GraphEdge(
                    source_fqn=table_fqn,
                    target_fqn=col_fqn,
                    kind=EdgeKind.HAS_COLUMN,
                    confidence=Confidence.HIGH,
                    evidence="sqlalchemy-column",
                )
            )

            fk_match = _FK_RE.search(value)
            if fk_match:
                fk_target = fk_match.group(1)
                parts = fk_target.split(".")
                if len(parts) == 2:
                    target_table, target_col = parts
                    target_col_fqn = f"table:{target_table}.{target_col}"
                    fk_edges.append(
                        GraphEdge(
                            source_fqn=col_fqn,
                            target_fqn=target_col_fqn,
                            kind=EdgeKind.REFERENCES,
                            confidence=Confidence.HIGH,
                            evidence="sqlalchemy-foreignkey",
                        )
                    )

        return col_nodes, has_col_edges, fk_edges
