"""FastAPI Pydantic deep-extraction plugin (M3).

Tags Pydantic BaseModel subclasses, extracts Field constraints from
class-body and Annotated forms, tags validator functions, and links
FastAPI endpoints to their request/response Pydantic models via
ACCEPTS and RETURNS edges. Optionally fuzzy-matches Pydantic fields
to SQLAlchemy columns via MAPS_TO edges.

Depends on FastAPIPlugin (must run first so APIEndpoint nodes exist)
and is best paired with SQLAlchemyPlugin (for MAPS_TO targets).
"""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Matches a single kwarg inside a Field(...) call. Captures name and raw value.
_FIELD_KWARG_RE = re.compile(
    r"(\w+)\s*=\s*"
    r"(\"[^\"]*\"|'[^']*'|\([^)]*\)|\[[^\]]*\]|[^,)\s]+)"
)

# Matches `response_model=X` inside a FastAPI route decorator. Captures the
# bare type expression (e.g. `TodoRead`, `list[TodoRead]`, `pkg.mod.TodoRead`).
_RESPONSE_MODEL_RE = re.compile(r"response_model\s*=\s*([A-Za-z_][\w\.\[\]]+)")

# Matches a Pydantic validator decorator and (optionally) the first quoted
# positional arg (the target field name). Group 1: kind. Group 2/3: target.
_VALIDATOR_DECORATOR_RE = re.compile(
    r"^@(field_validator|model_validator|validator|root_validator)\b"
    r"(?:\(\s*\"([^\"]+)\"|\(\s*'([^']+)'|)"
)

_RECOGNISED_CONSTRAINTS = frozenset(
    {
        "min_length",
        "max_length",
        "ge",
        "gt",
        "le",
        "lt",
        "multiple_of",
        "pattern",
        "default",
        "max_digits",
        "decimal_places",
    }
)


def _parse_field_constraints(raw_value: str) -> dict[str, str]:
    """Pull recognised Pydantic Field() constraints out of a raw RHS string.

    Accepts both ``Field(min_length=3)`` (class-body) and bare ``min_length=3``
    (already stripped of outer ``Field(``). Returns an empty dict if the value
    does not look like a Pydantic Field call.
    """
    if "Field(" not in raw_value and "=" not in raw_value:
        return {}

    inside = raw_value
    field_start = raw_value.find("Field(")
    if field_start != -1:
        open_paren = raw_value.find("(", field_start)
        # Find matching close paren respecting nesting.
        depth = 0
        end = -1
        # Note: this walker does NOT track string state. A `)` inside a string
        # literal (e.g., `description="(hello)"`) terminates the walk early and
        # silently drops constraints after that point. Acceptable for the bounded
        # fixture set; revisit if false-negatives surface.
        for idx in range(open_paren, len(raw_value)):
            ch = raw_value[idx]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = idx
                    break
        if end == -1:
            return {}
        inside = raw_value[open_paren + 1 : end]

    constraints: dict[str, str] = {}
    for match in _FIELD_KWARG_RE.finditer(inside):
        name = match.group(1)
        if name not in _RECOGNISED_CONSTRAINTS:
            continue
        raw = match.group(2).strip()
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            raw = raw[1:-1]
        constraints[name] = raw
    return constraints


# Module-level toggle for Pydantic→ORM MAPS_TO linking. Default ON per DD-2.
# Tests monkeypatch this constant; production runs never mutate it.
ENABLE_PYDANTIC_ORM_LINKING = True

# Python type-name → set of compatible SQL type names. Both sides are normalised
# (Python: outer wrapper / `| None` stripped; SQL: uppercased and `(...)` stripped)
# before lookup. Keys are bare Python builtins; values are upper-case SQL types.
_PY_TO_SQL_TYPES: dict[str, frozenset[str]] = {
    "str": frozenset({"VARCHAR", "TEXT", "CHAR", "STRING", "CITEXT"}),
    "int": frozenset({"INTEGER", "BIGINT", "SMALLINT", "INT"}),
    "bool": frozenset({"BOOLEAN", "BOOL"}),
    "float": frozenset(
        {"REAL", "FLOAT", "DOUBLE", "DOUBLE PRECISION", "NUMERIC", "DECIMAL"}
    ),
    "datetime": frozenset({"TIMESTAMP", "DATETIME", "TIMESTAMPTZ"}),
    "date": frozenset({"DATE"}),
}


def _python_type_compatible(py_type: str, sql_type: str) -> bool:
    """Return True if a Python annotation string is compatible with a SQL type.

    Handles common wrappers: ``Optional[str]``/``str | None`` → ``str``,
    ``VARCHAR(255)`` → ``VARCHAR``. Unknown Python types map to no SQL types
    (returns False).
    """
    if not py_type or not sql_type:
        return False
    py_norm = py_type.strip().split("[")[0].split("|")[0].strip()
    sql_norm = sql_type.strip().upper().split("(")[0].strip()
    allowed = _PY_TO_SQL_TYPES.get(py_norm, frozenset())
    return sql_norm in allowed


# FQNs accepted as Pydantic base classes for INHERITS-edge detection.
# Bare names cover pre-SCIP (tree-sitter only) output where the supertype
# identifier is unresolved; qualified forms cover post-SCIP. RootModel is
# the v2 root-type base and is recognised here for forward compatibility
# with downstream tasks (tagging/extraction).
PYDANTIC_BASE_MODEL_NAMES = frozenset(
    {
        "BaseModel",
        "pydantic.BaseModel",
        "pydantic.main.BaseModel",
        "RootModel",
        "pydantic.RootModel",
        "pydantic.main.RootModel",
    }
)


def _is_pydantic_base_target(target: str) -> bool:
    """True if INHERITS target FQN refers to pydantic.BaseModel or pydantic.RootModel.

    Accepts bare/qualified pydantic FQNs, OR a qualified name ending in
    `.BaseModel`/`.RootModel` whose package path *contains* the literal
    segment "pydantic" — this rejects user bases like `app.base.BaseModel`
    (e.g. SQLAlchemy declarative) while still tolerating reexports such as
    `pydantic.v1.BaseModel`.
    """
    if target in PYDANTIC_BASE_MODEL_NAMES:
        return True
    if (target.endswith(".BaseModel") or target.endswith(".RootModel")) and (
        "pydantic" in target.split(".")
    ):
        return True
    return False


def _find_pydantic_model_fqns(graph: SymbolGraph) -> set[str]:
    """Return source FQNs of every class with an INHERITS edge to a Pydantic base."""
    return {
        edge.source_fqn
        for edge in graph.edges
        if edge.kind == EdgeKind.INHERITS and _is_pydantic_base_target(edge.target_fqn)
    }


class FastAPIPydanticPlugin(FrameworkPlugin):
    name = "fastapi_pydantic"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = ["fastapi"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        for edge in context.graph.edges:
            if edge.kind != EdgeKind.INHERITS:
                continue
            if _is_pydantic_base_target(edge.target_fqn):
                return PluginDetectionResult(
                    confidence=Confidence.HIGH,
                    reason="Pydantic BaseModel subclass found via INHERITS edge",
                )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        graph = context.graph
        model_fqns = _find_pydantic_model_fqns(graph)
        logger.info(
            "fastapi_pydantic_extract_start",
            pydantic_models=len(model_fqns),
        )
        for fqn in model_fqns:
            node = graph.get_node(fqn)
            if node is None:
                continue
            node.properties["is_pydantic_model"] = True

        constraints_applied = self._apply_field_constraints(graph, model_fqns)
        validators_tagged = self._tag_validators(graph, model_fqns)
        edges: list[GraphEdge] = []
        edges.extend(self._emit_accepts_edges(graph, model_fqns))
        edges.extend(self._emit_returns_edges(graph, model_fqns))
        edges.extend(self._emit_maps_to_edges(graph, model_fqns))

        logger.info(
            "fastapi_pydantic_extract_end",
            pydantic_models=len(model_fqns),
            field_constraints=constraints_applied,
            validators=validators_tagged,
            accepts_edges=sum(1 for e in edges if e.kind == EdgeKind.ACCEPTS),
            returns_edges=sum(1 for e in edges if e.kind == EdgeKind.RETURNS),
            maps_to_edges=sum(1 for e in edges if e.kind == EdgeKind.MAPS_TO),
        )
        return PluginResult(
            nodes=[],
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=[],
        )

    def _resolve_pydantic_type(
        self,
        graph: SymbolGraph,
        type_source: str,
        model_fqns: set[str],
        scope_module: str,
    ) -> str | None:
        """Resolve a type-annotation string (e.g., 'TodoCreate' or 'list[TodoRead]')
        to a Pydantic model FQN. Returns None if no match.
        """
        if not type_source:
            return None

        # Strip generic wrappers: list[X], List[X], Optional[X], Union[X, None] → X.
        inner = type_source.strip()
        for wrapper in ("list[", "List[", "Optional[", "Union["):
            if inner.startswith(wrapper) and inner.endswith("]"):
                inner = inner[len(wrapper) : -1]
                # Drop a trailing ", None" for Union[X, None].
                if inner.endswith(", None"):
                    inner = inner[: -len(", None")]
                break

        inner = inner.split("|")[0].strip()  # `X | None` → `X`
        if not inner:
            return None

        # Exact FQN match.
        if inner in model_fqns:
            return inner

        # Same-module FQN match.
        candidate = f"{scope_module}.{inner}" if scope_module else inner
        if candidate in model_fqns:
            return candidate

        # Fallback: endswith `.Name` search.
        for fqn in model_fqns:
            if fqn.endswith(f".{inner}"):
                return fqn

        return None

    def _emit_accepts_edges(
        self, graph: SymbolGraph, model_fqns: set[str]
    ) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for handles_edge in graph.edges:
            if handles_edge.kind != EdgeKind.HANDLES:
                continue
            handler = graph.get_node(handles_edge.source_fqn)
            endpoint = graph.get_node(handles_edge.target_fqn)
            if (
                handler is None
                or endpoint is None
                or handler.kind != NodeKind.FUNCTION
                or endpoint.kind != NodeKind.API_ENDPOINT
            ):
                continue
            scope_module = handler.fqn.rsplit(".", 1)[0] if "." in handler.fqn else ""
            for param in handler.properties.get("params", []):
                type_source = param.get("type", "")
                target = self._resolve_pydantic_type(
                    graph, type_source, model_fqns, scope_module
                )
                if target is None:
                    continue
                edges.append(
                    GraphEdge(
                        source_fqn=endpoint.fqn,
                        target_fqn=target,
                        kind=EdgeKind.ACCEPTS,
                        confidence=Confidence.HIGH,
                        evidence="fastapi-body-param",
                    )
                )
        return edges

    def _emit_returns_edges(
        self, graph: SymbolGraph, model_fqns: set[str]
    ) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for handles_edge in graph.edges:
            if handles_edge.kind != EdgeKind.HANDLES:
                continue
            handler = graph.get_node(handles_edge.source_fqn)
            endpoint = graph.get_node(handles_edge.target_fqn)
            if (
                handler is None
                or endpoint is None
                or handler.kind != NodeKind.FUNCTION
                or endpoint.kind != NodeKind.API_ENDPOINT
            ):
                continue
            scope_module = handler.fqn.rsplit(".", 1)[0] if "." in handler.fqn else ""

            target: str | None = None
            evidence: str | None = None

            # Preferred: response_model= kwarg in any decorator annotation.
            for deco in handler.properties.get("annotations", []):
                match = _RESPONSE_MODEL_RE.search(deco)
                if not match:
                    continue
                resolved = self._resolve_pydantic_type(
                    graph, match.group(1), model_fqns, scope_module
                )
                if resolved is not None:
                    target = resolved
                    evidence = "fastapi-response-model"
                    break

            # Fallback: function return-type annotation.
            if target is None:
                return_type = handler.properties.get("return_type", "")
                resolved = self._resolve_pydantic_type(
                    graph, return_type, model_fqns, scope_module
                )
                if resolved is not None:
                    target = resolved
                    evidence = "fastapi-return-annotation"

            if target is None or evidence is None:
                continue

            edges.append(
                GraphEdge(
                    source_fqn=endpoint.fqn,
                    target_fqn=target,
                    kind=EdgeKind.RETURNS,
                    confidence=Confidence.HIGH,
                    evidence=evidence,
                )
            )
        return edges

    def _apply_field_constraints(self, graph: SymbolGraph, model_fqns: set[str]) -> int:
        applied = 0
        for edge in graph.edges:
            if edge.kind != EdgeKind.CONTAINS:
                continue
            if edge.source_fqn not in model_fqns:
                continue
            field_node = graph.get_node(edge.target_fqn)
            if field_node is None or field_node.kind != NodeKind.FIELD:
                continue
            combined: dict[str, str] = {}
            type_source = field_node.properties.get("type", "")
            value_source = field_node.properties.get("value", "")
            combined.update(_parse_field_constraints(type_source))
            combined.update(_parse_field_constraints(value_source))
            if combined:
                existing = field_node.properties.get("constraints", {})
                field_node.properties["constraints"] = {**existing, **combined}
                applied += 1
        return applied

    def _tag_validators(self, graph: SymbolGraph, model_fqns: set[str]) -> int:
        tagged = 0
        for edge in graph.edges:
            if edge.kind != EdgeKind.CONTAINS:
                continue
            if edge.source_fqn not in model_fqns:
                continue
            func = graph.get_node(edge.target_fqn)
            if func is None or func.kind != NodeKind.FUNCTION:
                continue
            for deco in func.properties.get("annotations", []):
                match = _VALIDATOR_DECORATOR_RE.match(deco)
                if not match:
                    continue
                kind = match.group(1)
                target = match.group(2) or match.group(3)
                func.properties["is_validator"] = True
                func.properties["validator_kind"] = kind
                if target:
                    func.properties["target_field"] = target
                tagged += 1
                break
        return tagged

    def _emit_maps_to_edges(
        self, graph: SymbolGraph, model_fqns: set[str]
    ) -> list[GraphEdge]:
        """Heuristically link Pydantic fields to SQLAlchemy columns.

        Match requires identical column name AND compatible Python/SQL types.
        Confidence is MEDIUM if exactly one candidate column matches a field,
        LOW per-candidate when multiple columns match. Reads the module-level
        ``ENABLE_PYDANTIC_ORM_LINKING`` toggle on each call so tests can disable
        the pass via monkeypatch.
        """
        # Read the toggle each call — DO NOT cache at import or in __init__.
        if not ENABLE_PYDANTIC_ORM_LINKING:
            return []

        # Index columns by name for O(1) candidate lookup per field.
        columns_by_name: dict[str, list[GraphNode]] = {}
        for node in graph.nodes.values():
            if node.kind != NodeKind.COLUMN:
                continue
            columns_by_name.setdefault(node.name, []).append(node)

        if not columns_by_name:
            return []

        edges: list[GraphEdge] = []
        for edge in graph.edges:
            if edge.kind != EdgeKind.CONTAINS:
                continue
            if edge.source_fqn not in model_fqns:
                continue
            field_node = graph.get_node(edge.target_fqn)
            if field_node is None or field_node.kind != NodeKind.FIELD:
                continue

            candidates = columns_by_name.get(field_node.name, [])
            if not candidates:
                continue

            py_type = field_node.properties.get("type", "")
            compatible = [
                col
                for col in candidates
                if _python_type_compatible(py_type, col.properties.get("type", ""))
            ]
            if not compatible:
                continue

            if len(compatible) == 1:
                col = compatible[0]
                edges.append(
                    GraphEdge(
                        source_fqn=field_node.fqn,
                        target_fqn=col.fqn,
                        kind=EdgeKind.MAPS_TO,
                        confidence=Confidence.MEDIUM,
                        evidence="pydantic-orm-name-and-type",
                        properties={
                            "source": "pydantic",
                            "confidence_reason": "name_and_type_match",
                        },
                    )
                )
            else:
                for col in compatible:
                    edges.append(
                        GraphEdge(
                            source_fqn=field_node.fqn,
                            target_fqn=col.fqn,
                            kind=EdgeKind.MAPS_TO,
                            confidence=Confidence.LOW,
                            evidence="pydantic-orm-name-and-type-ambiguous",
                            properties={
                                "source": "pydantic",
                                "confidence_reason": "ambiguous_multiple_candidates",
                            },
                        )
                    )
        return edges

    def get_layer_classification(self) -> LayerRules:
        return LayerRules.empty()
