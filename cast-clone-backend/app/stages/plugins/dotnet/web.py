"""ASP.NET Core Web plugin — HTTP endpoint extraction.

Finds controllers (classes with [ApiController] or extending ControllerBase/Controller),
extracts [HttpGet]/[HttpPost]/etc. method annotations, combines class-level [Route]
prefix with method paths (including [controller] and [action] token replacement),
and produces API_ENDPOINT nodes + HANDLES/EXPOSES edges.

Produces:
- Nodes: (:API_ENDPOINT {method, path, framework, response_type})
- Edges: (:Function)-[:HANDLES]->(:API_ENDPOINT)
         (:Class)-[:EXPOSES]->(:API_ENDPOINT)
- Entry points: each endpoint handler method (kind="http_endpoint")
- Layer assignments: controller classes -> Presentation
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

# HTTP method attribute -> HTTP verb
_HTTP_METHODS: dict[str, str] = {
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpDelete": "DELETE",
    "HttpPatch": "PATCH",
    "HttpOptions": "OPTIONS",
    "HttpHead": "HEAD",
}

# Minimal API MapXxx -> HTTP verb
_MAP_METHODS: dict[str, str] = {
    "MapGet": "GET",
    "MapPost": "POST",
    "MapPut": "PUT",
    "MapDelete": "DELETE",
    "MapPatch": "PATCH",
    "MapOptions": "OPTIONS",
    "MapHead": "HEAD",
}

# Parameter binding attributes -> binding type
_BINDING_ATTRS: dict[str, str] = {
    "FromBody": "body",
    "FromQuery": "query",
    "FromRoute": "route",
}

# Base classes that indicate a controller
_CONTROLLER_BASES: frozenset[str] = frozenset(
    {"ControllerBase", "Controller", "ODataController"}
)

# Regex to normalize route parameters: {id:int}, {id?}, {id} -> :id
_ROUTE_PARAM_RE = re.compile(r"\{(\w+)(?:[?:][^}]*)?\}")


class ASPNetWebPlugin(FrameworkPlugin):
    name = "aspnet-web"
    version = "1.0.0"
    supported_languages = {"csharp"}
    depends_on: list[str] = ["aspnet-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        """Detect ASP.NET Core by checking manifest for aspnet framework."""
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "aspnet" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        """Extract HTTP endpoints from ASP.NET controllers."""
        log = logger.bind(plugin=self.name)
        log.info("aspnet_web_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}

        # Build name -> fqn index for DTO linking
        name_to_fqn: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind in (NodeKind.CLASS, NodeKind.INTERFACE):
                name_to_fqn[node.name] = node.fqn

        for class_node in graph.nodes.values():
            if class_node.kind != NodeKind.CLASS:
                continue

            if not self._is_controller(class_node):
                continue

            # Resolve class-level route prefix
            class_prefix = self._resolve_class_route(class_node)

            # Classify controller as Presentation layer
            layer_assignments[class_node.fqn] = "Presentation"

            # Scan methods for HTTP method attributes
            for edge in graph.get_edges_from(class_node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                method_node = graph.get_node(edge.target_fqn)
                if method_node is None or method_node.kind != NodeKind.FUNCTION:
                    continue

                method_annotations = set(method_node.properties.get("annotations", []))
                method_annotation_args = method_node.properties.get(
                    "annotation_args", {}
                )

                # Find the HTTP method attribute
                http_method: str | None = None
                method_path = ""
                for attr_name, verb in _HTTP_METHODS.items():
                    if attr_name in method_annotations:
                        http_method = verb
                        # Path can be in unnamed arg ("") or keyed by attr name
                        method_path = method_annotation_args.get(
                            "", method_annotation_args.get(attr_name, "")
                        )
                        break

                if http_method is None:
                    continue

                # Check for [Route] override on method
                route_override = None
                if "Route" in method_annotations:
                    route_path = method_annotation_args.get("Route", "")
                    if route_path:
                        if route_path.startswith("/") or route_path.startswith("~/"):
                            # Absolute route — bypass class prefix
                            route_override = route_path.lstrip("~")
                            route_override = _ROUTE_PARAM_RE.sub(r":\1", route_override)
                        else:
                            # Relative route — replaces method-level path segment
                            method_path = route_path

                if route_override is not None:
                    full_path = route_override
                else:
                    # Build full path: prefix + method path
                    full_path = self._combine_paths(
                        class_prefix, method_path, class_node.name, method_node.name
                    )

                # Create API_ENDPOINT node
                endpoint_fqn = f"endpoint:{http_method}:{full_path}"
                response_type = method_node.properties.get("return_type")
                endpoint_node = GraphNode(
                    fqn=endpoint_fqn,
                    name=f"{http_method} {full_path}",
                    kind=NodeKind.API_ENDPOINT,
                    language="csharp",
                    properties={
                        "method": http_method,
                        "path": full_path,
                        "framework": "aspnet",
                        "response_type": response_type,
                    },
                )
                nodes.append(endpoint_node)

                # HANDLES edge: method -> endpoint
                edges.append(
                    GraphEdge(
                        source_fqn=method_node.fqn,
                        target_fqn=endpoint_fqn,
                        kind=EdgeKind.HANDLES,
                        confidence=Confidence.HIGH,
                        evidence="aspnet-web",
                    )
                )

                # EXPOSES edge: class -> endpoint
                edges.append(
                    GraphEdge(
                        source_fqn=class_node.fqn,
                        target_fqn=endpoint_fqn,
                        kind=EdgeKind.EXPOSES,
                        confidence=Confidence.HIGH,
                        evidence="aspnet-web",
                    )
                )

                # Entry point for transaction discovery
                entry_points.append(
                    EntryPoint(
                        fqn=method_node.fqn,
                        kind="http_endpoint",
                        metadata={"method": http_method, "path": full_path},
                    )
                )

                # DTO linking: [FromBody], [FromQuery], [FromRoute]
                params = method_node.properties.get("parameters", [])
                for param in params:
                    if not isinstance(param, dict):
                        continue
                    param_annotations = param.get("annotations", [])
                    for attr_name, binding_type in _BINDING_ATTRS.items():
                        if attr_name in param_annotations:
                            param_type = param.get("type", "")
                            dto_fqn = name_to_fqn.get(param_type)
                            if dto_fqn:
                                edges.append(
                                    GraphEdge(
                                        source_fqn=endpoint_fqn,
                                        target_fqn=dto_fqn,
                                        kind=EdgeKind.DEPENDS_ON,
                                        confidence=Confidence.HIGH,
                                        evidence="aspnet-web",
                                        properties={"binding": binding_type},
                                    )
                                )

        # Extract Minimal API endpoints (app.MapGet, MapPost, etc.)
        self._extract_minimal_apis(
            graph, nodes, edges, entry_points, layer_assignments
        )

        log.info("aspnet_web_extract_done", endpoints=len(nodes))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=[],
        )

    def get_layer_classification(self) -> LayerRules:
        """Controllers are Presentation layer."""
        return LayerRules(
            rules=[
                LayerRule(pattern="Controller", layer="Presentation"),
            ]
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_minimal_apis(
        self,
        graph: SymbolGraph,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        entry_points: list[EntryPoint],
        layer_assignments: dict[str, str],
    ) -> None:
        """Extract Minimal API endpoints (app.MapGet/MapPost/etc.) from class nodes."""
        for class_node in graph.nodes.values():
            if class_node.kind != NodeKind.CLASS:
                continue

            # Process direct minimal API endpoints
            minimal_endpoints = class_node.properties.get("minimal_api_endpoints", [])
            for ep_data in minimal_endpoints:
                self._create_minimal_endpoint(
                    graph, ep_data, "", nodes, edges, entry_points
                )

            # Process map groups (prefixed endpoint groups)
            minimal_groups = class_node.properties.get("minimal_api_groups", [])
            for group in minimal_groups:
                prefix = group.get("prefix", "")
                for ep_data in group.get("endpoints", []):
                    self._create_minimal_endpoint(
                        graph, ep_data, prefix, nodes, edges, entry_points
                    )

            # Extension method endpoints (1-hop)
            extension_eps = class_node.properties.get("extension_endpoints", [])
            for ep_data in extension_eps:
                self._create_minimal_endpoint(
                    graph, ep_data, "", nodes, edges, entry_points
                )

    def _create_minimal_endpoint(
        self,
        graph: SymbolGraph,
        ep_data: dict,
        prefix: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        entry_points: list[EntryPoint],
    ) -> None:
        """Create an API_ENDPOINT node from a minimal API registration dict."""
        map_method = ep_data.get("method", "")
        http_method = _MAP_METHODS.get(map_method)
        if http_method is None:
            return

        path = ep_data.get("path", "")
        handler_fqn = ep_data.get("handler_fqn", "")

        # Combine group prefix with endpoint path
        full_path = prefix + path if prefix else path

        # Ensure leading slash
        if full_path and not full_path.startswith("/"):
            full_path = "/" + full_path
        if not full_path:
            full_path = "/"

        # Normalize route parameters
        full_path = _ROUTE_PARAM_RE.sub(r":\1", full_path)

        endpoint_fqn = f"endpoint:{http_method}:{full_path}"
        endpoint_node = GraphNode(
            fqn=endpoint_fqn,
            name=f"{http_method} {full_path}",
            kind=NodeKind.API_ENDPOINT,
            language="csharp",
            properties={
                "method": http_method,
                "path": full_path,
                "framework": "aspnet-minimal",
                "handler_fqn": handler_fqn,
            },
        )
        nodes.append(endpoint_node)

        # HANDLES edge: handler -> endpoint (if handler exists in graph)
        if handler_fqn:
            edges.append(
                GraphEdge(
                    source_fqn=handler_fqn,
                    target_fqn=endpoint_fqn,
                    kind=EdgeKind.HANDLES,
                    confidence=Confidence.HIGH,
                    evidence="aspnet-web",
                )
            )

        # Entry point for transaction discovery
        entry_point_fqn = handler_fqn if handler_fqn else endpoint_fqn
        entry_points.append(
            EntryPoint(
                fqn=entry_point_fqn,
                kind="http_endpoint",
                metadata={"method": http_method, "path": full_path},
            )
        )

    def _is_controller(self, node: GraphNode) -> bool:
        """Check if a class node is an ASP.NET controller."""
        annotations = set(node.properties.get("annotations", []))

        # Check for [ApiController] attribute
        if "ApiController" in annotations:
            return True

        # Check for controller base classes
        base_class = node.properties.get("base_class", "")
        if base_class in _CONTROLLER_BASES:
            return True

        return False

    def _resolve_class_route(self, class_node: GraphNode) -> str:
        """Extract and resolve the class-level [Route] template."""
        annotation_args = class_node.properties.get("annotation_args", {})

        # Route template is stored in unnamed arg ("")
        route_template = annotation_args.get("", "")
        if not route_template:
            return ""

        # Replace [controller] token with class name minus "Controller" suffix
        controller_name = class_node.name
        if controller_name.endswith("Controller"):
            controller_name = controller_name[: -len("Controller")]
        controller_name = controller_name.lower()

        route_template = route_template.replace("[controller]", controller_name)

        return route_template

    def _combine_paths(
        self,
        class_prefix: str,
        method_path: str,
        class_name: str,
        method_name: str,
    ) -> str:
        """Combine class prefix and method path with token replacement."""
        # Replace [action] token with lowercased method name
        if "[action]" in class_prefix:
            class_prefix = class_prefix.replace("[action]", method_name.lower())
        if "[action]" in method_path:
            method_path = method_path.replace("[action]", method_name.lower())

        # Combine paths
        if method_path and not method_path.startswith("/"):
            method_path = "/" + method_path

        full_path = class_prefix + method_path if method_path else class_prefix

        # Ensure leading slash
        if full_path and not full_path.startswith("/"):
            full_path = "/" + full_path

        if not full_path:
            full_path = "/"

        # Normalize route parameters: {id:int}, {id?}, {id} -> :id
        full_path = _ROUTE_PARAM_RE.sub(r":\1", full_path)

        return full_path
