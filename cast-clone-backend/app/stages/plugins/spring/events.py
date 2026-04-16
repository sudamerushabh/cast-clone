"""Spring Events plugin.

Detects Spring application event patterns:
- @EventListener methods (consumers of events)
- @TransactionalEventListener methods (consumers with transaction phase binding)
- ApplicationEventPublisher.publishEvent() calls (producers of events)

Produces:
- PRODUCES edges: (:Function)-[:PRODUCES {event_type, framework}]->(:Class)
- CONSUMES edges: (:Function)-[:CONSUMES {event_type, framework}]->(:Class)

The link between producer and consumer is the event type (class name).
This captures the invisible coupling where two classes communicate via
Spring's event bus with zero compile-time dependency between them.
"""

from __future__ import annotations

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Annotations that mark a method as an event listener
_LISTENER_ANNOTATIONS = frozenset({
    "EventListener",
    "TransactionalEventListener",
})

# Known publisher method patterns: class.method combinations that publish events
_PUBLISHER_METHODS = frozenset({
    "publishEvent",
    "publish",
})

# Known publisher type short names
_PUBLISHER_TYPES = frozenset({
    "ApplicationEventPublisher",
    "ApplicationContext",
})


class SpringEventsPlugin(FrameworkPlugin):
    name = "spring-events"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = ["spring-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        # Check for @EventListener annotations in the graph
        for node in context.graph.nodes.values():
            annotations = node.properties.get("annotations", [])
            if any(a in _LISTENER_ANNOTATIONS for a in annotations):
                return PluginDetectionResult(
                    confidence=Confidence.HIGH,
                    reason="@EventListener annotations found",
                )

        # Check for ApplicationEventPublisher field types
        for node in context.graph.nodes.values():
            if node.kind == NodeKind.FIELD:
                field_type = node.properties.get("type", "")
                if field_type in _PUBLISHER_TYPES:
                    return PluginDetectionResult(
                        confidence=Confidence.MEDIUM,
                        reason="ApplicationEventPublisher field found",
                    )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("spring_events_extract_start")

        graph = context.graph
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        warnings: list[str] = []

        # Phase 1: Find all @EventListener methods and their event types
        listeners = self._find_listeners(graph)
        log.info("spring_events_listeners_found", count=len(listeners))

        # Phase 2: Find all publishEvent() calls and their event types
        publishers = self._find_publishers(graph)
        log.info("spring_events_publishers_found", count=len(publishers))

        # Phase 3: Create edges linking publishers to listeners via event type
        for pub_fqn, event_type in publishers:
            for listener_fqn, listener_event_type in listeners:
                if self._types_match(event_type, listener_event_type):
                    # Publisher -> Listener (via event type)
                    edges.append(GraphEdge(
                        source_fqn=pub_fqn,
                        target_fqn=listener_fqn,
                        kind=EdgeKind.PRODUCES,
                        confidence=Confidence.HIGH,
                        evidence="spring-events",
                        properties={
                            "framework": "spring",
                            "event_type": event_type,
                        },
                    ))

        # Phase 4: Create CONSUMES edges from listener methods to their event types
        for listener_fqn, event_type in listeners:
            # Find the event class node if it exists
            event_node = self._find_event_class(graph, event_type)
            if event_node is not None:
                edges.append(GraphEdge(
                    source_fqn=listener_fqn,
                    target_fqn=event_node.fqn,
                    kind=EdgeKind.CONSUMES,
                    confidence=Confidence.HIGH,
                    evidence="spring-events",
                    properties={
                        "framework": "spring",
                        "event_type": event_type,
                    },
                ))

            # Listener methods are entry points for transaction discovery
            entry_points.append(EntryPoint(
                fqn=listener_fqn,
                kind="event_listener",
                metadata={"event_type": event_type, "framework": "spring"},
            ))

        log.info("spring_events_extract_complete", edges=len(edges))

        return PluginResult(
            nodes=[],
            edges=edges,
            layer_assignments={},
            entry_points=entry_points,
            warnings=warnings,
        )

    def _find_listeners(
        self, graph: SymbolGraph
    ) -> list[tuple[str, str]]:
        """Find @EventListener methods and extract their event type.

        Returns list of (method_fqn, event_type_short_name).

        Event type is determined by:
        1. First parameter type of the listener method
        2. @EventListener(classes = SomeEvent.class) annotation arg
        """
        listeners: list[tuple[str, str]] = []

        for node in graph.nodes.values():
            if node.kind != NodeKind.FUNCTION:
                continue
            annotations = node.properties.get("annotations", [])
            if not any(a in _LISTENER_ANNOTATIONS for a in annotations):
                continue

            event_type: str | None = None

            # Strategy 1: Check annotation args for explicit class reference
            ann_args = node.properties.get("annotation_params", {})
            for ann_name in _LISTENER_ANNOTATIONS:
                if ann_name in ann_args:
                    arg_val = ann_args[ann_name]
                    if isinstance(arg_val, dict):
                        # @EventListener(classes = SomeEvent.class)
                        classes_val = arg_val.get("classes") or arg_val.get("value")
                        if isinstance(classes_val, str):
                            event_type = classes_val.removesuffix(".class")
                        elif isinstance(classes_val, list) and classes_val:
                            event_type = classes_val[0].removesuffix(".class")
                    elif isinstance(arg_val, str):
                        event_type = arg_val.removesuffix(".class")

            # Strategy 2: First parameter type
            if event_type is None:
                params = node.properties.get("params", [])
                if params:
                    param = params[0]
                    if isinstance(param, str):
                        parts = param.strip().split()
                        if parts:
                            event_type = parts[0]
                            # Strip generics
                            idx = event_type.find("<")
                            if idx != -1:
                                event_type = event_type[:idx]

            if event_type:
                listeners.append((node.fqn, event_type))

        return listeners

    def _find_publishers(
        self, graph: SymbolGraph
    ) -> list[tuple[str, str]]:
        """Find publishEvent() calls and extract the event type.

        Returns list of (caller_method_fqn, event_type_short_name).

        Scans CALLS edges where the target is publishEvent() or similar,
        then infers the event type from the call context.
        """
        publishers: list[tuple[str, str]] = []

        # Find all fields of type ApplicationEventPublisher
        publisher_fields: dict[str, str] = {}  # class_fqn -> field_name
        for node in graph.nodes.values():
            if node.kind != NodeKind.FIELD:
                continue
            field_type = node.properties.get("type", "")
            if field_type in _PUBLISHER_TYPES:
                # Extract class FQN from field FQN (e.g., "com.X.Y.field" -> "com.X.Y")
                class_fqn = node.fqn.rsplit(".", 1)[0]
                publisher_fields[class_fqn] = node.name

        # Scan CALLS edges for publishEvent() invocations
        for edge in graph.edges:
            if edge.kind != EdgeKind.CALLS:
                continue
            target = edge.target_fqn
            # Check if the call target ends with .publishEvent or similar
            method_name = target.rsplit(".", 1)[-1] if "." in target else target
            if method_name not in _PUBLISHER_METHODS:
                continue

            # The caller is the publisher
            caller_fqn = edge.source_fqn

            # Try to infer event type from:
            # 1. The call line context (we don't have argument AST here)
            # 2. The caller method's return type or name heuristic
            # For now, use the receiver type resolution to get a generic "event" marker
            # A more precise approach would need the actual AST argument
            caller_node = graph.get_node(caller_fqn)
            if caller_node is None:
                continue

            # Look for object_creation_expressions in the same method
            # that create event objects (heuristic: class name contains "Event")
            event_type = self._infer_event_type_from_calls(graph, caller_fqn)
            if event_type:
                publishers.append((caller_fqn, event_type))

        return publishers

    def _infer_event_type_from_calls(
        self, graph: SymbolGraph, method_fqn: str
    ) -> str | None:
        """Infer the event type published by a method.

        Looks at CALLS edges from this method to find <init> calls for
        classes whose name contains 'Event'.
        """
        for edge in graph.get_edges_from(method_fqn):
            if edge.kind != EdgeKind.CALLS:
                continue
            target = edge.target_fqn
            # Check for "new SomeEvent()" pattern -> target is SomeEvent.<init>
            if target.endswith(".<init>"):
                class_name = target.rsplit(".", 1)[0]
                short_name = class_name.rsplit(".", 1)[-1]
                if "Event" in short_name or "event" in short_name.lower():
                    return short_name

        return None

    def _types_match(self, pub_type: str, listener_type: str) -> bool:
        """Check if a published event type matches a listener's event type.

        Handles both short names and FQNs: "UserCreatedEvent" matches
        "com.example.UserCreatedEvent" and vice versa.
        """
        if pub_type == listener_type:
            return True
        # Short name match
        pub_short = pub_type.rsplit(".", 1)[-1]
        listener_short = listener_type.rsplit(".", 1)[-1]
        return pub_short == listener_short

    def _find_event_class(
        self, graph: SymbolGraph, event_type: str
    ) -> GraphNode | None:
        """Find the graph node for an event class by short name or FQN."""
        # Direct FQN lookup
        node = graph.get_node(event_type)
        if node is not None:
            return node
        # Short name scan
        short_name = event_type.rsplit(".", 1)[-1]
        for n in graph.nodes.values():
            if n.kind == NodeKind.CLASS and n.name == short_name:
                return n
        return None
