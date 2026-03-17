"""gRPC Service plugin — gRPC endpoint discovery.

Finds gRPC service implementations (classes extending *.{Name}Base),
extracts RPC methods, and MapGrpcService<T> endpoint registrations.

Produces:
- Nodes: (:API_ENDPOINT {method: "GRPC", path, framework: "grpc"})
- Edges: (:Class)-[:EXPOSES]->(:API_ENDPOINT)
         (:Function)-[:HANDLES]->(:API_ENDPOINT)
- Entry points: RPC methods as kind="grpc_endpoint"
- Layer: gRPC service classes -> Presentation
"""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

_GRPC_BASE_RE = re.compile(r"^(\w+)\.\1Base$")


class GRPCPlugin(FrameworkPlugin):
    name = "aspnet-grpc"
    version = "1.0.0"
    supported_languages = {"csharp"}
    depends_on: list[str] = ["aspnet-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "grpc" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected",
                    )

        for node in context.graph.nodes.values():
            base = node.properties.get("base_class", "")
            if _GRPC_BASE_RE.match(base):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason=f"gRPC base class '{base}' found",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("grpc_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        # Collect gRPC mappings: service_type_name -> True (registered)
        grpc_registered: set[str] = set()
        for node in graph.nodes.values():
            grpc_mappings = node.properties.get("grpc_mappings", [])
            for mapping in grpc_mappings:
                service_type = mapping.get("service_type", "")
                if service_type:
                    grpc_registered.add(service_type)

        # Find gRPC service classes
        for node in graph.nodes.values():
            if node.kind != NodeKind.CLASS:
                continue
            base = node.properties.get("base_class", "")
            match = _GRPC_BASE_RE.match(base)
            if not match:
                continue

            service_name = match.group(1)  # e.g., "Greeter" from "Greeter.GreeterBase"

            # Only process if registered via MapGrpcService
            if node.name not in grpc_registered:
                continue

            # Layer assignment
            layer_assignments[node.fqn] = "Presentation"

            # Find override methods (RPC implementations)
            for edge in graph.get_edges_from(node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                child = graph.get_node(edge.target_fqn)
                if child is None or child.kind != NodeKind.FUNCTION:
                    continue
                if not child.properties.get("is_override"):
                    continue

                method_name = child.name
                grpc_path = f"/{service_name}/{method_name}"

                # Create API_ENDPOINT node per RPC method
                endpoint_fqn = f"endpoint:GRPC:{grpc_path}"
                endpoint_node = GraphNode(
                    fqn=endpoint_fqn,
                    name=f"GRPC {grpc_path}",
                    kind=NodeKind.API_ENDPOINT,
                    language="csharp",
                    properties={
                        "method": "GRPC",
                        "path": grpc_path,
                        "framework": "grpc",
                    },
                )
                nodes.append(endpoint_node)

                # HANDLES edge: method -> endpoint
                edges.append(
                    GraphEdge(
                        source_fqn=child.fqn,
                        target_fqn=endpoint_fqn,
                        kind=EdgeKind.HANDLES,
                        confidence=Confidence.HIGH,
                        evidence="aspnet-grpc",
                    )
                )

                # EXPOSES edge: service class -> endpoint
                edges.append(
                    GraphEdge(
                        source_fqn=node.fqn,
                        target_fqn=endpoint_fqn,
                        kind=EdgeKind.EXPOSES,
                        confidence=Confidence.HIGH,
                        evidence="aspnet-grpc",
                    )
                )

                # Entry point
                entry_points.append(
                    EntryPoint(
                        fqn=child.fqn,
                        kind="grpc_endpoint",
                        metadata={"method": "GRPC", "path": grpc_path},
                    )
                )

        log.info("grpc_extract_done", endpoints=len(nodes))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules.empty()
