"""Spring Web plugin — REST endpoint extraction.

Finds @Controller/@RestController classes, extracts @GetMapping/@PostMapping/etc.
method annotations, combines class-level @RequestMapping prefix with method paths,
and produces APIEndpoint nodes + HANDLES/EXPOSES edges.

Produces:
- Nodes: (:APIEndpoint {method, path, framework, response_type})
- Edges: (:Function)-[:HANDLES]->(:APIEndpoint)
         (:Class)-[:EXPOSES]->(:APIEndpoint)
- Entry points: each endpoint handler method
"""

from __future__ import annotations

import structlog

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext, EntryPoint
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Annotation name -> HTTP method
_HTTP_METHOD_ANNOTATIONS: dict[str, str] = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}

_CONTROLLER_ANNOTATIONS = frozenset({"Controller", "RestController"})


class SpringWebPlugin(FrameworkPlugin):
    name = "spring-web"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = ["spring-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "spring" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("spring_web_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []

        for class_node in graph.nodes.values():
            if class_node.kind != NodeKind.CLASS:
                continue
            class_annotations = set(class_node.properties.get("annotations", []))
            if not (class_annotations & _CONTROLLER_ANNOTATIONS):
                continue

            # Get class-level @RequestMapping prefix
            class_annotation_args = class_node.properties.get("annotation_args", {})
            class_prefix = class_annotation_args.get("RequestMapping", "")
            # Normalize: strip trailing slash
            class_prefix = class_prefix.rstrip("/")

            # Scan methods in this controller
            for containment_edge in graph.get_edges_from(class_node.fqn):
                if containment_edge.kind != EdgeKind.CONTAINS:
                    continue
                method_node = graph.get_node(containment_edge.target_fqn)
                if method_node is None or method_node.kind != NodeKind.FUNCTION:
                    continue

                method_annotations = set(method_node.properties.get("annotations", []))
                method_annotation_args = method_node.properties.get("annotation_args", {})

                http_method = None
                method_path = ""

                # Check specific HTTP method annotations
                for ann_name, http_verb in _HTTP_METHOD_ANNOTATIONS.items():
                    if ann_name in method_annotations:
                        http_method = http_verb
                        method_path = method_annotation_args.get(ann_name, "")
                        break

                # Check generic @RequestMapping on method
                if http_method is None and "RequestMapping" in method_annotations:
                    method_path = method_annotation_args.get("RequestMapping", "")
                    http_method = method_annotation_args.get("method", "GET").upper()

                if http_method is None:
                    continue

                # Combine paths
                # Normalize method path
                if method_path and not method_path.startswith("/"):
                    method_path = "/" + method_path
                full_path = class_prefix + method_path if method_path else class_prefix
                if not full_path:
                    full_path = "/"

                # Create APIEndpoint node
                endpoint_fqn = f"endpoint:{http_method}:{full_path}"
                response_type = method_node.properties.get("return_type")
                endpoint_node = GraphNode(
                    fqn=endpoint_fqn,
                    name=f"{http_method} {full_path}",
                    kind=NodeKind.API_ENDPOINT,
                    language="java",
                    properties={
                        "method": http_method,
                        "path": full_path,
                        "framework": "spring",
                        "response_type": response_type,
                    },
                )
                nodes.append(endpoint_node)

                # HANDLES edge: method -> endpoint
                edges.append(GraphEdge(
                    source_fqn=method_node.fqn,
                    target_fqn=endpoint_fqn,
                    kind=EdgeKind.HANDLES,
                    confidence=Confidence.HIGH,
                    evidence="spring-web",
                ))

                # EXPOSES edge: class -> endpoint
                edges.append(GraphEdge(
                    source_fqn=class_node.fqn,
                    target_fqn=endpoint_fqn,
                    kind=EdgeKind.EXPOSES,
                    confidence=Confidence.HIGH,
                    evidence="spring-web",
                ))

                # Entry point
                entry_points.append(EntryPoint(
                    fqn=method_node.fqn,
                    kind="http_endpoint",
                    metadata={"method": http_method, "path": full_path},
                ))

        log.info("spring_web_extract_done", endpoints=len(nodes))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=entry_points,
            warnings=[],
        )
