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

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind
from app.models.graph import SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

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
        model_fqns = _find_pydantic_model_fqns(context.graph)
        logger.info(
            "fastapi_pydantic_extract_start",
            pydantic_models=len(model_fqns),
        )
        for fqn in model_fqns:
            node = context.graph.get_node(fqn)
            if node is None:
                continue
            node.properties["is_pydantic_model"] = True
        logger.info(
            "fastapi_pydantic_extract_end",
            pydantic_models=len(model_fqns),
        )
        return PluginResult.empty()

    def get_layer_classification(self) -> LayerRules:
        return LayerRules.empty()
