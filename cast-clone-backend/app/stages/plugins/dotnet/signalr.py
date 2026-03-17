"""SignalR Hub plugin — WebSocket endpoint discovery.

Finds Hub/Hub<T> subclasses, extracts hub methods, client events,
and MapHub<T> endpoint registrations.

Produces:
- Nodes: (:API_ENDPOINT {method: "WS", path, framework: "signalr", protocol: "websocket"})
- Edges: (:Class)-[:EXPOSES]->(:API_ENDPOINT)
         (:Function)-[:HANDLES]->(:API_ENDPOINT)
         (:Class)-[:PRODUCES {event}]->(:API_ENDPOINT)
- Entry points: hub methods as kind="websocket_endpoint"
- Layer: Hub classes -> Presentation
"""

from __future__ import annotations

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

_HUB_LIFECYCLE_METHODS = frozenset({"OnConnectedAsync", "OnDisconnectedAsync"})


class SignalRPlugin(FrameworkPlugin):
    name = "aspnet-signalr"
    version = "1.0.0"
    supported_languages = {"csharp"}
    depends_on: list[str] = ["aspnet-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "signalr" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected",
                    )

        for node in context.graph.nodes.values():
            base = node.properties.get("base_class", "")
            if base == "Hub" or base.startswith("Hub<"):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="Hub subclass found",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        """Extract SignalR hub endpoints, methods, and client events."""
        log = logger.bind(plugin=self.name)
        log.info("signalr_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        # Build name -> FQN index
        name_to_fqn: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind in (NodeKind.CLASS, NodeKind.INTERFACE):
                name_to_fqn[node.name] = node.fqn

        # Collect hub mappings: hub_type_name -> path
        hub_path_map: dict[str, str] = {}
        for node in graph.nodes.values():
            hub_mappings = node.properties.get("hub_mappings", [])
            for mapping in hub_mappings:
                hub_type = mapping.get("hub_type", "")
                path = mapping.get("path", "")
                if hub_type and path:
                    hub_path_map[hub_type] = path

        # Find Hub subclasses
        for node in graph.nodes.values():
            if node.kind != NodeKind.CLASS:
                continue
            base = node.properties.get("base_class", "")
            if base != "Hub" and not base.startswith("Hub<"):
                continue

            hub_name = node.name
            hub_path = hub_path_map.get(hub_name)
            if not hub_path:
                continue

            # Create WS API_ENDPOINT node
            endpoint_fqn = f"endpoint:WS:{hub_path}"
            endpoint_node = GraphNode(
                fqn=endpoint_fqn,
                name=f"WS {hub_path}",
                kind=NodeKind.API_ENDPOINT,
                language="csharp",
                properties={
                    "method": "WS",
                    "path": hub_path,
                    "framework": "signalr",
                    "protocol": "websocket",
                },
            )
            nodes.append(endpoint_node)

            # EXPOSES edge: hub class -> endpoint
            edges.append(
                GraphEdge(
                    source_fqn=node.fqn,
                    target_fqn=endpoint_fqn,
                    kind=EdgeKind.EXPOSES,
                    confidence=Confidence.HIGH,
                    evidence="aspnet-signalr",
                )
            )

            # Layer assignment
            layer_assignments[node.fqn] = "Presentation"

            # Find hub methods (excluding lifecycle methods)
            for edge in graph.get_edges_from(node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                child = graph.get_node(edge.target_fqn)
                if child is None or child.kind != NodeKind.FUNCTION:
                    continue
                if child.name in _HUB_LIFECYCLE_METHODS:
                    continue
                if child.properties.get("is_constructor"):
                    continue

                # HANDLES edge: method -> endpoint
                edges.append(
                    GraphEdge(
                        source_fqn=child.fqn,
                        target_fqn=endpoint_fqn,
                        kind=EdgeKind.HANDLES,
                        confidence=Confidence.HIGH,
                        evidence="aspnet-signalr",
                    )
                )

                # Entry point
                entry_points.append(
                    EntryPoint(
                        fqn=child.fqn,
                        kind="websocket_endpoint",
                        metadata={"method": "WS", "path": hub_path},
                    )
                )

                # Client events from method properties
                client_events = child.properties.get("client_events", [])
                for event_name in client_events:
                    edges.append(
                        GraphEdge(
                            source_fqn=node.fqn,
                            target_fqn=endpoint_fqn,
                            kind=EdgeKind.PRODUCES,
                            confidence=Confidence.HIGH,
                            evidence="aspnet-signalr",
                            properties={"event": event_name},
                        )
                    )

            # Strongly-typed hub: Hub<IClientInterface>
            # Resolve client interface methods as client events
            if base.startswith("Hub<") and base.endswith(">"):
                client_interface_name = base[4:-1]
                client_fqn = name_to_fqn.get(client_interface_name)
                if client_fqn:
                    for edge in graph.get_edges_from(client_fqn):
                        if edge.kind != EdgeKind.CONTAINS:
                            continue
                        interface_method = graph.get_node(edge.target_fqn)
                        if (
                            interface_method is None
                            or interface_method.kind != NodeKind.FUNCTION
                        ):
                            continue
                        edges.append(
                            GraphEdge(
                                source_fqn=node.fqn,
                                target_fqn=endpoint_fqn,
                                kind=EdgeKind.PRODUCES,
                                confidence=Confidence.HIGH,
                                evidence="aspnet-signalr",
                                properties={"event": interface_method.name},
                            )
                        )

        log.info("signalr_extract_done", endpoints=len(nodes))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[LayerRule(pattern="Hub", layer="Presentation")])
