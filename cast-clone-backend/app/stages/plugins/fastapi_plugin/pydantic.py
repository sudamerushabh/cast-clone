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
from app.models.graph import SymbolGraph
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

        logger.info(
            "fastapi_pydantic_extract_end",
            pydantic_models=len(model_fqns),
            field_constraints=constraints_applied,
        )
        return PluginResult.empty()

    def _apply_field_constraints(
        self, graph: SymbolGraph, model_fqns: set[str]
    ) -> int:
        applied = 0
        for edge in graph.edges:
            if edge.kind != EdgeKind.CONTAINS:
                continue
            if edge.source_fqn not in model_fqns:
                continue
            field_node = graph.get_node(edge.target_fqn)
            if field_node is None or field_node.kind != NodeKind.FIELD:
                continue
            raw = field_node.properties.get("value", "")
            constraints = _parse_field_constraints(raw)
            if constraints:
                field_node.properties["constraints"] = constraints
                applied += 1
        return applied

    def get_layer_classification(self) -> LayerRules:
        return LayerRules.empty()
