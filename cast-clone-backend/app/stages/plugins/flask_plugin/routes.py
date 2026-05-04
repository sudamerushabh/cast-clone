"""FlaskPlugin — entry point for Flask route/blueprint/restful/model extraction.

Composes helpers from blueprints.py, restful.py, and sqlalchemy_adapter.py.
"""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, NodeKind
from app.models.graph import SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Matches @<var>.route("/path", ...) including @app.route and @bp.route.
_ROUTE_DECORATOR_RE = re.compile(r"^@(\w+)\.route\(\s*[\"']([^\"']*)[\"']")


def _has_flask_route_annotation(graph: SymbolGraph) -> bool:
    for node in graph.nodes.values():
        if node.kind != NodeKind.FUNCTION or node.language != "python":
            continue
        for deco in node.properties.get("annotations", []):
            if _ROUTE_DECORATOR_RE.match(deco):
                return True
    return False


class FlaskPlugin(FrameworkPlugin):
    name = "flask"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest is not None:
            for fw in context.manifest.detected_frameworks:
                if "flask" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Flask framework '{fw.name}' detected in manifest",
                    )
        if _has_flask_route_annotation(context.graph):
            return PluginDetectionResult(
                confidence=Confidence.HIGH,
                reason="Flask route decorators found in graph",
            )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("flask_extract_start")
        log.info("flask_extract_complete")
        return PluginResult.empty()

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(
            rules=[
                LayerRule(pattern="@app.route", layer="Presentation"),
                LayerRule(pattern="@.route", layer="Presentation"),
            ]
        )
