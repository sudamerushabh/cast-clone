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
from app.stages.plugins.flask_plugin.blueprints import resolve_blueprint_prefixes
from app.stages.plugins.flask_plugin.restful import (
    enumerate_resource_methods,
    resolve_restful_bindings,
)
from app.stages.plugins.flask_plugin.sqlalchemy_adapter import (
    extract_flask_sqlalchemy_tables,
)

logger = structlog.get_logger()

# @<var>.route("/path", methods=["GET", "POST"])
_ROUTE_DECORATOR_RE = re.compile(r"^@(\w+)\.route\(\s*[\"']([^\"']*)[\"']")
_METHODS_KWARG_RE = re.compile(r"methods\s*=\s*\[([^\]]*)\]")
_METHOD_STRING_RE = re.compile(r"[\"']([A-Za-z]+)[\"']")
_ADD_URL_RULE_RE = re.compile(
    r"^add_url_rule\(\s*[\"']([^\"']+)[\"'].*?view_func\s*=\s*(\w+)",
    re.DOTALL,
)

APP_ROUTE_VARS: frozenset[str] = frozenset({"app"})
_RESTFUL_BASE_CLASSES: frozenset[str] = frozenset({"Resource", "MethodView"})


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


def _join_prefix_and_path(prefix: str, path: str) -> str:
    """Join a Flask url_prefix with a route path using exactly one slash."""
    if not prefix:
        return path
    if not path:
        return prefix
    if prefix.endswith("/") and path.startswith("/"):
        return prefix + path[1:]
    if not prefix.endswith("/") and not path.startswith("/"):
        return f"{prefix}/{path}"
    return prefix + path


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

        project_root = (
            str(context.manifest.root_path) if context.manifest is not None else ""
        )
        bp_prefixes = (
            resolve_blueprint_prefixes(graph, project_root) if project_root else {}
        )

        for func in graph.nodes.values():
            if func.kind != NodeKind.FUNCTION or func.language != "python":
                continue
            for deco in func.properties.get("annotations", []):
                match = _ROUTE_DECORATOR_RE.match(deco)
                if not match:
                    continue
                var_name, raw_path = match.group(1), match.group(2)
                blueprint = None if var_name in APP_ROUTE_VARS else var_name
                prefix = bp_prefixes.get(var_name, "") if blueprint else ""
                full_path = _join_prefix_and_path(prefix, raw_path)
                for method in _parse_methods(deco):
                    endpoint, edge, entry = _make_endpoint(
                        path=full_path,
                        method=method,
                        handler_fqn=func.fqn,
                        blueprint=blueprint,
                    )
                    nodes.append(endpoint)
                    edges.append(edge)
                    entry_points.append(entry)
                    layer_assignments[func.fqn] = "Presentation"

        rule_nodes, rule_edges, rule_entries, rule_warnings = (
            self._extract_add_url_rule_endpoints(graph)
        )
        nodes.extend(rule_nodes)
        edges.extend(rule_edges)
        entry_points.extend(rule_entries)
        warnings.extend(rule_warnings)

        rest_nodes, rest_edges, rest_entries, rest_warnings = (
            self._extract_restful_endpoints(graph, project_root)
        )
        nodes.extend(rest_nodes)
        edges.extend(rest_edges)
        entry_points.extend(rest_entries)
        warnings.extend(rest_warnings)

        for table_node, class_fqn in extract_flask_sqlalchemy_tables(graph):
            nodes.append(table_node)
            layer_assignments[class_fqn] = "Data Access"

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

    def _extract_add_url_rule_endpoints(
        self, graph: SymbolGraph
    ) -> tuple[list[GraphNode], list[GraphEdge], list[EntryPoint], list[str]]:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        warnings: list[str] = []

        for node in graph.nodes.values():
            if node.kind != NodeKind.FIELD or node.language != "python":
                continue
            raw = node.properties.get("value", "")
            if not raw.startswith("add_url_rule("):
                continue
            match = _ADD_URL_RULE_RE.match(raw)
            if not match:
                continue
            path, view_func = match.group(1), match.group(2)
            methods = _parse_methods(raw)

            handler_fqn = None
            parent_module = node.fqn.rsplit(".", 1)[0]
            candidate = f"{parent_module}.{view_func}"
            if candidate in graph.nodes:
                handler_fqn = candidate
            elif view_func in graph.nodes:
                handler_fqn = view_func
            else:
                for fqn in graph.nodes:
                    if fqn.endswith(f".{view_func}"):
                        handler_fqn = fqn
                        break

            if handler_fqn is None:
                warnings.append(
                    f"add_url_rule view_func '{view_func}' at path '{path}' unresolved"
                )
                continue

            for method in methods:
                endpoint, edge, entry = _make_endpoint(
                    path=path,
                    method=method,
                    handler_fqn=handler_fqn,
                )
                nodes.append(endpoint)
                edges.append(edge)
                entry_points.append(entry)
        return nodes, edges, entry_points, warnings

    def _extract_restful_endpoints(
        self, graph: SymbolGraph, project_root: str
    ) -> tuple[list[GraphNode], list[GraphEdge], list[EntryPoint], list[str]]:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        warnings: list[str] = []

        bindings = resolve_restful_bindings(project_root) if project_root else {}
        methods_by_class = enumerate_resource_methods(graph, _RESTFUL_BASE_CLASSES)

        for class_fqn, methods in methods_by_class.items():
            class_node = graph.get_node(class_fqn)
            if class_node is None:
                continue
            path = bindings.get(class_node.name)
            if path is None:
                warnings.append(
                    f"restful resource {class_node.name} has no add_resource binding"
                )
                continue
            for http_method, handler_fqn in methods:
                endpoint, edge, entry = _make_endpoint(
                    path=path,
                    method=http_method,
                    handler_fqn=handler_fqn,
                )
                nodes.append(endpoint)
                edges.append(edge)
                entry_points.append(entry)
        return nodes, edges, entry_points, warnings

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(
            rules=[
                LayerRule(pattern="@app.route", layer="Presentation"),
                LayerRule(pattern="@.route", layer="Presentation"),
            ]
        )
