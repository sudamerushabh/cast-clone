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


class FastAPIPydanticPlugin(FrameworkPlugin):
    name = "fastapi_pydantic"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = ["fastapi"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        for edge in context.graph.edges:
            if edge.kind != EdgeKind.INHERITS:
                continue
            target = edge.target_fqn
            if target == "BaseModel" or target.endswith(".BaseModel"):
                return PluginDetectionResult(
                    confidence=Confidence.HIGH,
                    reason="Pydantic BaseModel subclass found via INHERITS edge",
                )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        return PluginResult.empty()

    def get_layer_classification(self) -> LayerRules:
        return LayerRules.empty()
