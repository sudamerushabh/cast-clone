"""FlaskPlugin — entry point for Flask route/blueprint/restful/model extraction.

Composes helpers from blueprints.py, restful.py, and sqlalchemy_adapter.py.
"""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext, EntryPoint
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

# @<var>.route("/path", methods=["GET", "POST"])
_ROUTE_DECORATOR_RE = re.compile(r"^@(\w+)\.route\(\s*[\"']([^\"']*)[\"']")
_METHODS_KWARG_RE = re.compile(r"methods\s*=\s*\[([^\]]*)\]")
_METHOD_STRING_RE = re.compile(r"[\"']([A-Z]+)[\"']")

APP_ROUTE_VARS: frozenset[str] = frozenset({"app"})


def _parse_methods(decorator: str) -> list[str]:
    match = _METHODS_KWARG_RE.search(decorator)
    if not match:
        return ["GET"]
    inner = match.group(1)
    methods = [m.group(1).upper() for m in _METHOD_STRING_RE.finditer(inner)]
    return methods or ["GET"]


def _has_flask_route_annotation(graph: SymbolGraph) -> bool:
    for node in graph.nodes.values():
        if node.kind != NodeKind.FUNCTION or node.language != "python":
            continue
        for deco in node.properties.get("annotations", []):
            if _ROUTE_DECORATOR_RE.match(deco):
                return True
    return False


def _make_endpoint(
    path: str,
    method: str,
    handler_fqn: str,
    framework_tag: str = "flask",
    blueprint: str | None = None,
) -> tuple[GraphNode, GraphEdge, EntryPoint]:
    endpoint_fqn = f"{method}:{path}"
    props: dict[str, object] = {
        "method": method,
        "path": path,
        "framework": framework_tag,
    }
    if blueprint is not None:
        props["blueprint"] = blueprint
    endpoint = GraphNode(
        fqn=endpoint_fqn,
        name=f"{method} {path}",
        kind=NodeKind.API_ENDPOINT,
        language="python",
        properties=props,
    )
    edge = GraphEdge(
        source_fqn=handler_fqn,
        target_fqn=endpoint_fqn,
        kind=EdgeKind.HANDLES,
        confidence=Confidence.HIGH,
        evidence="flask-decorator",
    )
    entry = EntryPoint(
        fqn=endpoint_fqn,
        kind="http_endpoint",
        metadata={"method": method, "path": path},
    )
    return endpoint, edge, entry


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

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        for func in graph.nodes.values():
            if func.kind != NodeKind.FUNCTION or func.language != "python":
                continue
            for deco in func.properties.get("annotations", []):
                match = _ROUTE_DECORATOR_RE.match(deco)
                if not match:
                    continue
                var_name, path = match.group(1), match.group(2)
                if var_name not in APP_ROUTE_VARS:
                    continue
                for method in _parse_methods(deco):
                    endpoint, edge, entry = _make_endpoint(
                        path=path,
                        method=method,
                        handler_fqn=func.fqn,
                    )
                    nodes.append(endpoint)
                    edges.append(edge)
                    entry_points.append(entry)
                    layer_assignments[func.fqn] = "Presentation"

        log.info(
            "flask_extract_complete",
            endpoints=len([n for n in nodes if n.kind == NodeKind.API_ENDPOINT]),
        )
        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(
            rules=[
                LayerRule(pattern="@app.route", layer="Presentation"),
                LayerRule(pattern="@.route", layer="Presentation"),
            ]
        )
