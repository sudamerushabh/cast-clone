"""Stage 6: Cross-Technology Linker.

Stitches connections across language/service boundaries:
- HTTP Endpoint Matcher: frontend HTTP calls -> backend API endpoints
- Message Queue Matcher: producers -> MessageTopic <- consumers
- Shared Database Matcher: entities from different modules mapping to same table

This stage is non-critical. Failures degrade gracefully with warnings.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from fnmatch import fnmatch

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode

logger = structlog.get_logger(__name__)

# ── URL Normalization ──────────────────────────────────────

# Patterns for path parameters across frameworks
_SPRING_PARAM = re.compile(r"\{[^}]+\}")  # {id}, {userId}
_EXPRESS_PARAM = re.compile(r":([a-zA-Z_]\w*)")  # :id, :userId
_TEMPLATE_PARAM = re.compile(r"\$\{[^}]+\}")  # ${id}, ${userId}
_URL_SCHEME = re.compile(r"^https?://[^/]+")  # https://example.com


def normalize_url_path(path: str) -> str:
    """Normalize a URL path for matching.

    Transformations applied in order:
    1. Strip scheme + host (``https://example.com/api`` -> ``/api``)
    2. Strip query string (``/api?x=1`` -> ``/api``)
    3. Ensure leading slash
    4. Convert param styles ({id}, :id, ${id}) -> ``:param``
    5. Lowercase
    6. Strip trailing slash (except root ``/``)
    """
    if not path:
        return "/"

    # Strip scheme + host if present
    path = _URL_SCHEME.sub("", path)

    # Strip query string
    if "?" in path:
        path = path.split("?", 1)[0]

    # Ensure leading slash
    if not path.startswith("/"):
        path = "/" + path

    # Normalize path params to :param
    # Order matters: template literals first (contains ${ which might conflict)
    path = _TEMPLATE_PARAM.sub(":param", path)
    path = _SPRING_PARAM.sub(":param", path)
    path = _EXPRESS_PARAM.sub(":param", path)

    # Lowercase
    path = path.lower()

    # Strip trailing slash (but keep root "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return path


# ── HTTP Endpoint Matcher ──────────────────────────────────


class HTTPEndpointMatcher:
    """Matches frontend HTTP client calls to backend API endpoints.

    Algorithm:
    1. Collect all APIEndpoint nodes from the graph (from Spring Web, Express, etc.)
    2. Build a lookup: (method, normalized_path) -> endpoint FQN
    3. Scan all Function nodes for ``http_calls`` properties
    4. For each HTTP call, normalize the URL and match against the lookup
    5. Exact match -> HIGH confidence, parameterized match -> MEDIUM confidence
    6. Create CALLS_API edges for matches
    """

    def match(self, ctx: AnalysisContext) -> list[GraphEdge]:
        """Find HTTP endpoint matches and return new CALLS_API edges."""
        # Build endpoint lookup: (METHOD, normalized_path) -> endpoint_fqn
        endpoint_index: dict[tuple[str, str], str] = {}
        for node in ctx.graph.nodes.values():
            if node.kind != NodeKind.API_ENDPOINT:
                continue
            method = node.properties.get("method", "").upper()
            path = node.properties.get("path", "")
            normalized = normalize_url_path(path)
            endpoint_index[(method, normalized)] = node.fqn

        if not endpoint_index:
            return []

        new_edges: list[GraphEdge] = []

        # Scan functions for HTTP calls
        for node in ctx.graph.nodes.values():
            if node.kind != NodeKind.FUNCTION:
                continue
            http_calls = node.properties.get("http_calls", [])
            if not http_calls:
                continue

            for call in http_calls:
                method = call.get("method", "").upper()
                url = call.get("url", "")
                normalized = normalize_url_path(url)

                # Try exact match first
                endpoint_fqn = endpoint_index.get((method, normalized))
                confidence = Confidence.HIGH

                # If no exact match, try parameterized match
                if endpoint_fqn is None:
                    endpoint_fqn = self._parameterized_match(
                        method, normalized, endpoint_index
                    )
                    confidence = Confidence.MEDIUM

                if endpoint_fqn is not None:
                    new_edges.append(
                        GraphEdge(
                            source_fqn=node.fqn,
                            target_fqn=endpoint_fqn,
                            kind=EdgeKind.CALLS_API,
                            confidence=confidence,
                            evidence="cross-tech-linker",
                            properties={
                                "url_pattern": url,
                                "method": method,
                            },
                        )
                    )

        logger.info(
            "http_endpoint_matcher.complete",
            endpoints_indexed=len(endpoint_index),
            matches=len(new_edges),
        )
        return new_edges

    def _parameterized_match(
        self,
        method: str,
        normalized_call_path: str,
        endpoint_index: dict[tuple[str, str], str],
    ) -> str | None:
        """Try to match a call path against parameterized endpoint paths.

        Splits both paths into segments. A ``:param`` segment in the endpoint
        matches any segment in the call path, and vice versa.
        """
        call_segments = normalized_call_path.strip("/").split("/")

        for (ep_method, ep_path), ep_fqn in endpoint_index.items():
            if ep_method != method:
                continue
            ep_segments = ep_path.strip("/").split("/")
            if len(ep_segments) != len(call_segments):
                continue

            match = True
            for ep_seg, call_seg in zip(ep_segments, call_segments):
                if ep_seg == ":param" or call_seg == ":param":
                    continue  # Param segment matches anything
                if ep_seg != call_seg:
                    match = False
                    break

            if match:
                return ep_fqn

        return None


# ── Message Queue Matcher ──────────────────────────────────


@dataclass
class MQMatchResult:
    """Result of message queue matching."""

    new_nodes: list[GraphNode] = field(default_factory=list)
    new_edges: list[GraphEdge] = field(default_factory=list)


class MessageQueueMatcher:
    """Matches message queue producers to consumers via topic names.

    Algorithm:
    1. Scan all Function nodes for ``mq_produces`` and ``mq_consumes`` properties
    2. Collect concrete topics from producers, and patterns from consumers
    3. For each unique concrete topic, find or create a MessageTopic node
    4. Create PRODUCES edges from producer functions to topic nodes
    5. Create CONSUMES edges from consumer functions to topic nodes
       - Consumers with wildcard patterns (e.g. ``order.*``) are matched against
         concrete producer topics using ``fnmatch``
    """

    def match(self, ctx: AnalysisContext) -> MQMatchResult:
        """Find MQ matches and return new nodes and edges."""
        result = MQMatchResult()

        # Collect producers and consumers
        producers: list[tuple[str, str, str]] = []  # (fn_fqn, topic, broker)
        consumers: list[tuple[str, str, str]] = []  # (fn_fqn, topic_or_pattern, broker)

        for node in ctx.graph.nodes.values():
            if node.kind != NodeKind.FUNCTION:
                continue

            for prod in node.properties.get("mq_produces", []):
                broker = prod.get("broker", "unknown")
                producers.append((node.fqn, prod["topic"], broker))

            for cons in node.properties.get("mq_consumes", []):
                broker = cons.get("broker", "unknown")
                consumers.append((node.fqn, cons["topic"], broker))

        if not producers and not consumers:
            return result

        # Gather all concrete topics from producers
        concrete_topics: dict[str, str] = {}  # topic_name -> broker_type
        for _, topic, broker in producers:
            if topic not in concrete_topics:
                concrete_topics[topic] = broker

        # Also add non-wildcard consumer topics as concrete
        for _, topic, broker in consumers:
            if "*" not in topic and "?" not in topic:
                if topic not in concrete_topics:
                    concrete_topics[topic] = broker

        # Find or create MessageTopic nodes for all concrete topics
        topic_fqns: dict[str, str] = {}  # topic_name -> fqn
        for topic_name, broker in concrete_topics.items():
            topic_fqn = f"topic:{topic_name}"
            topic_fqns[topic_name] = topic_fqn

            # Check if node already exists in the graph
            existing = ctx.graph.get_node(topic_fqn)
            if existing is None:
                topic_node = GraphNode(
                    fqn=topic_fqn,
                    name=topic_name,
                    kind=NodeKind.MESSAGE_TOPIC,
                    properties={"broker_type": broker},
                )
                result.new_nodes.append(topic_node)

        # Create PRODUCES edges
        for fn_fqn, topic, _ in producers:
            result.new_edges.append(
                GraphEdge(
                    source_fqn=fn_fqn,
                    target_fqn=topic_fqns[topic],
                    kind=EdgeKind.PRODUCES,
                    confidence=Confidence.HIGH,
                    evidence="cross-tech-linker",
                )
            )

        # Create CONSUMES edges
        for fn_fqn, topic_or_pattern, _ in consumers:
            if "*" in topic_or_pattern or "?" in topic_or_pattern:
                # Wildcard consumer — match against all concrete topics
                for concrete_topic, fqn in topic_fqns.items():
                    if fnmatch(concrete_topic, topic_or_pattern):
                        result.new_edges.append(
                            GraphEdge(
                                source_fqn=fn_fqn,
                                target_fqn=fqn,
                                kind=EdgeKind.CONSUMES,
                                confidence=Confidence.MEDIUM,
                                evidence="cross-tech-linker-wildcard",
                                properties={"pattern": topic_or_pattern},
                            )
                        )
            else:
                # Exact consumer topic
                fqn = topic_fqns.get(topic_or_pattern)
                if fqn is not None:
                    result.new_edges.append(
                        GraphEdge(
                            source_fqn=fn_fqn,
                            target_fqn=fqn,
                            kind=EdgeKind.CONSUMES,
                            confidence=Confidence.HIGH,
                            evidence="cross-tech-linker",
                        )
                    )

        logger.info(
            "mq_matcher.complete",
            topics=len(concrete_topics),
            producers=len(producers),
            consumers=len(consumers),
        )
        return result


# ── Shared Database Matcher ────────────────────────────────


@dataclass
class SharedDBMatchResult:
    """Result of shared database matching."""

    new_edges: list[GraphEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SharedDBMatcher:
    """Detects shared database coupling across modules/services.

    Algorithm:
    1. Collect all MAPS_TO edges (entity -> table) from the graph
    2. Group entities by target table name
    3. For each table with entities from DIFFERENT modules, create
       cross-module DEPENDS_ON edges and log an architectural warning
    """

    def match(self, ctx: AnalysisContext) -> SharedDBMatchResult:
        """Find shared DB coupling and return new edges + warnings."""
        result = SharedDBMatchResult()

        # Collect MAPS_TO edges and group by target table
        # table_fqn -> [entity_fqn]
        table_to_entities: dict[str, list[str]] = defaultdict(list)

        for edge in ctx.graph.edges:
            if edge.kind != EdgeKind.MAPS_TO:
                continue
            table_to_entities[edge.target_fqn].append(edge.source_fqn)

        if not table_to_entities:
            return result

        # For each table, check if entities come from different modules
        for table_fqn, entity_fqns in table_to_entities.items():
            if len(entity_fqns) < 2:
                continue

            # Resolve entity nodes and extract their module
            # module -> [entity_fqn]
            module_entities: dict[str, list[str]] = defaultdict(list)
            for entity_fqn in entity_fqns:
                entity_node = ctx.graph.get_node(entity_fqn)
                if entity_node is None:
                    continue
                module = entity_node.properties.get("module", "")
                if not module:
                    # Try to infer module from FQN (second segment of Java package)
                    # e.g. "com.app.orders.OrderEntity" -> "orders"
                    module = self._infer_module(entity_fqn)
                module_entities[module].append(entity_fqn)

            # If entities span multiple modules -> shared DB coupling
            modules = [m for m in module_entities if m]  # filter empty
            if len(modules) < 2:
                continue

            # Get table name for the warning message
            table_node = ctx.graph.get_node(table_fqn)
            table_name = table_node.name if table_node else table_fqn

            # Create DEPENDS_ON edges between all cross-module entity pairs
            module_list = list(module_entities.items())
            for i in range(len(module_list)):
                for j in range(i + 1, len(module_list)):
                    mod_a, entities_a = module_list[i]
                    mod_b, entities_b = module_list[j]
                    if mod_a == mod_b:
                        continue
                    # Create one edge per cross-module entity pair
                    for ea in entities_a:
                        for eb in entities_b:
                            result.new_edges.append(
                                GraphEdge(
                                    source_fqn=ea,
                                    target_fqn=eb,
                                    kind=EdgeKind.DEPENDS_ON,
                                    confidence=Confidence.MEDIUM,
                                    evidence="shared-db-coupling",
                                    properties={
                                        "shared_table": table_name,
                                        "coupling_type": "shared_database",
                                    },
                                )
                            )

            result.warnings.append(
                f"Shared database coupling: table '{table_name}' is mapped by entities "
                f"from modules: {', '.join(sorted(modules))}"
            )

        logger.info(
            "shared_db_matcher.complete",
            shared_tables=len(result.warnings),
            cross_module_edges=len(result.new_edges),
        )
        return result

    @staticmethod
    def _infer_module(fqn: str) -> str:
        """Infer module name from FQN by extracting the 3rd package segment.

        For ``com.app.orders.OrderEntity`` returns ``orders``.
        For short FQNs or non-package FQNs, returns empty string.
        """
        parts = fqn.split(".")
        if len(parts) >= 3:
            return parts[2]
        return ""


# ── Main Entry Point ───────────────────────────────────────


async def run_cross_tech_linker(context: AnalysisContext) -> None:
    """Stage 6: Run all cross-technology linkers.

    Modifies ``context.graph`` in place. Sets ``context.cross_tech_edge_count``.
    Non-critical — individual matcher failures are logged as warnings and do not
    abort the pipeline.
    """
    logger.info("cross_tech_linker.start", project_id=context.project_id)
    total_new_edges = 0

    # 1. HTTP Endpoint Matcher
    try:
        http_matcher = HTTPEndpointMatcher()
        http_edges = http_matcher.match(context)
        for edge in http_edges:
            context.graph.add_edge(edge)
        total_new_edges += len(http_edges)
    except Exception as e:
        context.warnings.append(f"HTTP endpoint matcher failed: {e}")
        logger.warning("http_matcher.failed", error=str(e))

    # 2. Message Queue Matcher
    try:
        mq_matcher = MessageQueueMatcher()
        mq_result = mq_matcher.match(context)
        for node in mq_result.new_nodes:
            context.graph.add_node(node)
        for edge in mq_result.new_edges:
            context.graph.add_edge(edge)
        total_new_edges += len(mq_result.new_edges)
    except Exception as e:
        context.warnings.append(f"Message queue matcher failed: {e}")
        logger.warning("mq_matcher.failed", error=str(e))

    # 3. Shared Database Matcher
    try:
        db_matcher = SharedDBMatcher()
        db_result = db_matcher.match(context)
        for edge in db_result.new_edges:
            context.graph.add_edge(edge)
        total_new_edges += len(db_result.new_edges)
        # Propagate shared DB warnings to the context
        context.warnings.extend(db_result.warnings)
    except Exception as e:
        context.warnings.append(f"Shared database matcher failed: {e}")
        logger.warning("shared_db_matcher.failed", error=str(e))

    context.cross_tech_edge_count = total_new_edges
    logger.info(
        "cross_tech_linker.complete",
        project_id=context.project_id,
        cross_tech_edges=total_new_edges,
    )
