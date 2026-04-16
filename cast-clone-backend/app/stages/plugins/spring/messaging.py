"""Spring Messaging plugin.

Detects message queue integration patterns:
- @KafkaListener(topics="...") — Kafka consumers
- @RabbitListener(queues="...") — RabbitMQ consumers
- @JmsListener(destination="...") — JMS consumers
- KafkaTemplate.send("topic", ...) — Kafka producers
- RabbitTemplate.convertAndSend("exchange", ...) — RabbitMQ producers
- JmsTemplate.convertAndSend("queue", ...) — JMS producers

Produces:
- MESSAGE_TOPIC nodes: Shared topic/queue entities
- PRODUCES edges: (:Function)-[:PRODUCES]->(:MESSAGE_TOPIC)
- CONSUMES edges: (:Function)-[:CONSUMES]->(:MESSAGE_TOPIC)
- Entry points for listener methods

This captures the invisible coupling between microservices communicating
via message queues — the most common source of "dark dependencies" in
enterprise architectures.
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

# Listener annotation -> (topic parameter name, broker type)
_LISTENER_ANNOTATIONS: dict[str, tuple[str, str]] = {
    "KafkaListener": ("topics", "kafka"),
    "RabbitListener": ("queues", "rabbitmq"),
    "JmsListener": ("destination", "jms"),
}

# Template types that produce messages
_PRODUCER_TYPES: dict[str, str] = {
    "KafkaTemplate": "kafka",
    "RabbitTemplate": "rabbitmq",
    "JmsTemplate": "jms",
    "StreamBridge": "kafka",
}

# Methods on templates that send messages
_SEND_METHODS = frozenset({
    "send", "sendDefault", "convertAndSend",
    "convertSendAndReceive", "sendAndReceive",
})


class SpringMessagingPlugin(FrameworkPlugin):
    name = "spring-messaging"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = ["spring-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        # Check for listener annotations
        for node in context.graph.nodes.values():
            annotations = node.properties.get("annotations", [])
            if any(a in _LISTENER_ANNOTATIONS for a in annotations):
                matched = [
                    a for a in annotations
                    if a in _LISTENER_ANNOTATIONS
                ]
                return PluginDetectionResult(
                    confidence=Confidence.HIGH,
                    reason=f"Message listener annotation: {matched}",
                )

        # Check for template field types
        for node in context.graph.nodes.values():
            if node.kind == NodeKind.FIELD:
                field_type = node.properties.get("type", "")
                stripped = field_type.split("<")[0]  # Strip generics
                if stripped in _PRODUCER_TYPES:
                    return PluginDetectionResult(
                        confidence=Confidence.MEDIUM,
                        reason=f"Message template field found: {field_type}",
                    )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("spring_messaging_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        warnings: list[str] = []

        # Track created topics to avoid duplicates
        topic_nodes: dict[str, GraphNode] = {}

        # Phase 1: Find all listener methods and their topics
        consumers = self._find_consumers(graph)
        log.info("spring_messaging_consumers_found", count=len(consumers))

        # Phase 2: Find all producer calls and their topics
        producers = self._find_producers(graph)
        log.info("spring_messaging_producers_found", count=len(producers))

        # Phase 3: Create MESSAGE_TOPIC nodes and edges
        for method_fqn, topic_name, broker in consumers:
            topic_node = self._get_or_create_topic(
                topic_nodes, topic_name, broker
            )
            edges.append(GraphEdge(
                source_fqn=method_fqn,
                target_fqn=topic_node.fqn,
                kind=EdgeKind.CONSUMES,
                confidence=Confidence.HIGH,
                evidence="spring-messaging",
                properties={"framework": "spring", "broker": broker},
            ))
            entry_points.append(EntryPoint(
                fqn=method_fqn,
                kind="message_consumer",
                metadata={
                    "topic": topic_name,
                    "broker": broker,
                    "framework": "spring",
                },
            ))

        for method_fqn, topic_name, broker in producers:
            topic_node = self._get_or_create_topic(
                topic_nodes, topic_name, broker
            )
            edges.append(GraphEdge(
                source_fqn=method_fqn,
                target_fqn=topic_node.fqn,
                kind=EdgeKind.PRODUCES,
                confidence=Confidence.HIGH,
                evidence="spring-messaging",
                properties={"framework": "spring", "broker": broker},
            ))

        nodes.extend(topic_nodes.values())
        log.info(
            "spring_messaging_extract_complete",
            topics=len(topic_nodes),
            edges=len(edges),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=entry_points,
            warnings=warnings,
        )

    def _find_consumers(
        self, graph: SymbolGraph
    ) -> list[tuple[str, str, str]]:
        """Find message listener methods and their topics.

        Returns list of (method_fqn, topic_name, broker_type).
        """
        consumers: list[tuple[str, str, str]] = []

        for node in graph.nodes.values():
            if node.kind != NodeKind.FUNCTION:
                continue
            annotations = node.properties.get("annotations", [])
            ann_args = node.properties.get("annotation_params", {})

            for ann_name, (param_key, broker) in _LISTENER_ANNOTATIONS.items():
                if ann_name not in annotations:
                    continue

                topics = self._extract_topics(ann_args, ann_name, param_key)
                for topic in topics:
                    consumers.append((node.fqn, topic, broker))

        return consumers

    def _extract_topics(
        self,
        ann_args: dict,
        ann_name: str,
        param_key: str,
    ) -> list[str]:
        """Extract topic/queue names from annotation arguments.

        Handles:
        - @KafkaListener(topics = "orders")
        - @KafkaListener(topics = {"orders", "payments"})
        - @RabbitListener(queues = "checkout-queue")
        - @JmsListener(destination = "my-queue")
        - @KafkaListener("orders")  (bare value)
        """
        topics: list[str] = []
        arg_val = ann_args.get(ann_name)

        if arg_val is None:
            return topics

        if isinstance(arg_val, str):
            # Bare value: @KafkaListener("orders")
            topics.append(arg_val)
        elif isinstance(arg_val, dict):
            # Named parameters
            val = arg_val.get(param_key) or arg_val.get("value")
            if isinstance(val, str):
                topics.append(val)
            elif isinstance(val, list):
                topics.extend(v for v in val if isinstance(v, str))

        return topics

    def _find_producers(
        self, graph: SymbolGraph
    ) -> list[tuple[str, str, str]]:
        """Find message producer calls and their topics.

        Returns list of (caller_method_fqn, topic_name, broker_type).

        Detection strategy:
        1. Find fields of template types (KafkaTemplate, RabbitTemplate, etc.)
        2. Find CALLS edges where the target matches template.send*()
        3. Extract topic from the call's annotation_args or call context
        """
        producers: list[tuple[str, str, str]] = []

        # Build a map of class_fqn -> (field_name, broker_type) for template fields
        template_fields: dict[str, list[tuple[str, str]]] = {}
        for node in graph.nodes.values():
            if node.kind != NodeKind.FIELD:
                continue
            field_type = node.properties.get("type", "")
            stripped = field_type.split("<")[0]
            if stripped not in _PRODUCER_TYPES:
                continue
            broker = _PRODUCER_TYPES[stripped]
            class_fqn = node.fqn.rsplit(".", 1)[0]
            template_fields.setdefault(class_fqn, []).append(
                (node.name, broker)
            )

        # Scan CALLS edges for send() method invocations on template types
        for edge in graph.edges:
            if edge.kind != EdgeKind.CALLS:
                continue

            target = edge.target_fqn
            method_name = target.rsplit(".", 1)[-1] if "." in target else target
            if method_name not in _SEND_METHODS:
                continue

            # Check if the receiver type is a known template
            receiver_class = target.rsplit(".", 1)[0] if "." in target else ""
            receiver_short = (
                receiver_class.rsplit(".", 1)[-1]
                if "." in receiver_class
                else receiver_class
            )

            broker: str | None = None
            if receiver_short in _PRODUCER_TYPES:
                broker = _PRODUCER_TYPES[receiver_short]
            else:
                # Check if the caller's class has a template field
                caller_fqn = edge.source_fqn
                caller_class = caller_fqn.rsplit(".", 1)[0] if "." in caller_fqn else ""
                fields = template_fields.get(caller_class, [])
                for _field_name, field_broker in fields:
                    broker = field_broker
                    break

            if broker is None:
                continue

            # Extract topic from call context
            # Strategy: look at the edge properties for line number,
            # then check if there are tagged_strings or other hints
            topic = self._extract_topic_from_call(
                graph, edge.source_fqn, edge.properties.get("line")
            )
            if topic:
                producers.append((edge.source_fqn, topic, broker))

        return producers

    def _extract_topic_from_call(
        self,
        graph: SymbolGraph,
        method_fqn: str,
        _line: int | None,
    ) -> str | None:
        """Extract topic name from a send() call context.

        Looks for string constants in the method that look like topic names.
        This is a heuristic — the actual argument isn't available in the graph.
        """
        node = graph.get_node(method_fqn)
        if node is None:
            return None

        # Check tagged_strings for topic-like patterns
        tagged = node.properties.get("tagged_strings", [])
        for s in tagged:
            # Skip SQL strings
            if any(kw in s.upper() for kw in ("SELECT", "INSERT", "UPDATE", "DELETE")):
                continue
            return s

        return None

    def _get_or_create_topic(
        self,
        topic_nodes: dict[str, GraphNode],
        topic_name: str,
        broker: str,
    ) -> GraphNode:
        """Get existing or create new MESSAGE_TOPIC node."""
        fqn = f"topic:{broker}:{topic_name}"
        if fqn not in topic_nodes:
            topic_nodes[fqn] = GraphNode(
                fqn=fqn,
                name=f"{broker}://{topic_name}",
                kind=NodeKind.MESSAGE_TOPIC,
                language="config",
                properties={
                    "broker": broker,
                    "topic_name": topic_name,
                    "framework": "spring",
                },
            )
        return topic_nodes[fqn]
