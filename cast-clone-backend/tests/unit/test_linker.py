"""Tests for Stage 6: Cross-Technology Linker."""

import pytest

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.manifest import ProjectManifest
from app.stages.linker import (
    HTTPEndpointMatcher,
    MessageQueueMatcher,
    SharedDBMatcher,
    normalize_url_path,
    run_cross_tech_linker,
)

# ── Helpers ───────────────────────────────────────────────


def _make_context_with_graph(graph: SymbolGraph) -> AnalysisContext:
    """Helper to create a minimal AnalysisContext wrapping a graph."""
    manifest = ProjectManifest(
        root_path="/fake/project",
        detected_languages=[],
        detected_frameworks=[],
        source_files=[],
        total_files=0,
        total_loc=0,
    )
    ctx = AnalysisContext(project_id="test-project", manifest=manifest)
    ctx.graph = graph
    return ctx


# ── Test 1: URL Normalization — basic param styles ────────


class TestNormalizeUrlPath:
    def test_spring_path_param(self):
        """Spring-style {id} -> :param."""
        assert normalize_url_path("/api/v1/users/{id}") == "/api/v1/users/:param"

    def test_express_path_param(self):
        """:id -> :param."""
        assert normalize_url_path("/api/users/:id") == "/api/users/:param"

    def test_template_literal_param(self):
        """${userId} -> :param."""
        assert normalize_url_path("/api/users/${userId}") == "/api/users/:param"

    def test_multiple_params(self):
        """Multiple params all normalized."""
        result = normalize_url_path("/api/{orgId}/users/{id}")
        assert result == "/api/:param/users/:param"

    # ── Test 2: URL Normalization — edge cases ────────────

    def test_trailing_slash_stripped(self):
        assert normalize_url_path("/api/users/") == "/api/users"

    def test_query_params_stripped(self):
        assert normalize_url_path("/api/users?page=1&size=10") == "/api/users"

    def test_base_url_stripped(self):
        assert normalize_url_path("https://example.com/api/users") == "/api/users"

    def test_base_url_with_port_stripped(self):
        assert normalize_url_path("http://localhost:3000/api/users") == "/api/users"

    def test_lowercase(self):
        assert normalize_url_path("/API/Users") == "/api/users"

    def test_root_path(self):
        assert normalize_url_path("/") == "/"

    def test_empty_string(self):
        assert normalize_url_path("") == "/"

    def test_no_leading_slash_added(self):
        assert normalize_url_path("api/users") == "/api/users"

    def test_combined_edge_cases(self):
        """Base URL + params + query string + trailing slash — all normalized."""
        result = normalize_url_path(
            "https://api.example.com/API/v1/Users/{userId}/?fields=name"
        )
        assert result == "/api/v1/users/:param"


# ── Test 3-5: HTTP Endpoint Matcher ──────────────────────


class TestHTTPEndpointMatcher:
    def test_exact_match_get_endpoint(self):
        """frontend fetch('/api/users') matches GET /api/users."""
        g = SymbolGraph()

        # Backend endpoint node (created by Spring Web plugin)
        endpoint = GraphNode(
            fqn="GET:/api/users",
            name="GET /api/users",
            kind=NodeKind.API_ENDPOINT,
            properties={"method": "GET", "path": "/api/users"},
        )
        g.add_node(endpoint)

        # Backend handler
        handler = GraphNode(
            fqn="com.app.UserController.getUsers",
            name="getUsers",
            kind=NodeKind.FUNCTION,
            language="java",
        )
        g.add_node(handler)
        g.add_edge(
            GraphEdge(
                source_fqn="com.app.UserController.getUsers",
                target_fqn="GET:/api/users",
                kind=EdgeKind.HANDLES,
            )
        )

        # Frontend caller
        caller = GraphNode(
            fqn="src/api/userApi.fetchUsers",
            name="fetchUsers",
            kind=NodeKind.FUNCTION,
            language="typescript",
            properties={"http_calls": [{"method": "GET", "url": "/api/users"}]},
        )
        g.add_node(caller)

        ctx = _make_context_with_graph(g)
        matcher = HTTPEndpointMatcher()
        new_edges = matcher.match(ctx)

        assert len(new_edges) == 1
        edge = new_edges[0]
        assert edge.source_fqn == "src/api/userApi.fetchUsers"
        assert edge.target_fqn == "GET:/api/users"
        assert edge.kind == EdgeKind.CALLS_API
        assert edge.confidence == Confidence.HIGH

    def test_parameterized_match_medium_confidence(self):
        """fetch('/api/users/123') matches GET /api/users/{id} -> CALLS_API MEDIUM."""
        g = SymbolGraph()

        endpoint = GraphNode(
            fqn="GET:/api/users/:param",
            name="GET /api/users/{id}",
            kind=NodeKind.API_ENDPOINT,
            properties={"method": "GET", "path": "/api/users/{id}"},
        )
        g.add_node(endpoint)

        caller = GraphNode(
            fqn="src/UserPage.loadUser",
            name="loadUser",
            kind=NodeKind.FUNCTION,
            language="typescript",
            properties={"http_calls": [{"method": "GET", "url": "/api/users/123"}]},
        )
        g.add_node(caller)

        ctx = _make_context_with_graph(g)
        matcher = HTTPEndpointMatcher()
        new_edges = matcher.match(ctx)

        assert len(new_edges) == 1
        assert new_edges[0].confidence == Confidence.MEDIUM

    def test_no_match_different_method(self):
        """POST call does not match GET endpoint."""
        g = SymbolGraph()

        endpoint = GraphNode(
            fqn="GET:/api/users",
            name="GET /api/users",
            kind=NodeKind.API_ENDPOINT,
            properties={"method": "GET", "path": "/api/users"},
        )
        g.add_node(endpoint)

        caller = GraphNode(
            fqn="src/UserPage.createUser",
            name="createUser",
            kind=NodeKind.FUNCTION,
            language="typescript",
            properties={"http_calls": [{"method": "POST", "url": "/api/users"}]},
        )
        g.add_node(caller)

        ctx = _make_context_with_graph(g)
        matcher = HTTPEndpointMatcher()
        new_edges = matcher.match(ctx)

        assert len(new_edges) == 0

    def test_no_match_unmatched_url(self):
        """URL with no corresponding endpoint produces no edges."""
        g = SymbolGraph()

        endpoint = GraphNode(
            fqn="GET:/api/orders",
            name="GET /api/orders",
            kind=NodeKind.API_ENDPOINT,
            properties={"method": "GET", "path": "/api/orders"},
        )
        g.add_node(endpoint)

        caller = GraphNode(
            fqn="src/UserPage.loadUsers",
            name="loadUsers",
            kind=NodeKind.FUNCTION,
            language="typescript",
            properties={"http_calls": [{"method": "GET", "url": "/api/users"}]},
        )
        g.add_node(caller)

        ctx = _make_context_with_graph(g)
        matcher = HTTPEndpointMatcher()
        new_edges = matcher.match(ctx)

        assert len(new_edges) == 0

    def test_multiple_endpoints_matched(self):
        """Caller with multiple HTTP calls produces multiple CALLS_API edges."""
        g = SymbolGraph()

        g.add_node(
            GraphNode(
                fqn="GET:/api/users",
                name="GET /api/users",
                kind=NodeKind.API_ENDPOINT,
                properties={"method": "GET", "path": "/api/users"},
            )
        )
        g.add_node(
            GraphNode(
                fqn="POST:/api/users",
                name="POST /api/users",
                kind=NodeKind.API_ENDPOINT,
                properties={"method": "POST", "path": "/api/users"},
            )
        )

        caller = GraphNode(
            fqn="src/UserPage.init",
            name="init",
            kind=NodeKind.FUNCTION,
            language="typescript",
            properties={
                "http_calls": [
                    {"method": "GET", "url": "/api/users"},
                    {"method": "POST", "url": "/api/users"},
                ]
            },
        )
        g.add_node(caller)

        ctx = _make_context_with_graph(g)
        matcher = HTTPEndpointMatcher()
        new_edges = matcher.match(ctx)

        assert len(new_edges) == 2
        assert all(e.kind == EdgeKind.CALLS_API for e in new_edges)

    def test_no_endpoints_returns_empty(self):
        """Graph with no APIEndpoint nodes -> no edges, no crash."""
        g = SymbolGraph()
        g.add_node(
            GraphNode(
                fqn="src/app.main",
                name="main",
                kind=NodeKind.FUNCTION,
                language="typescript",
                properties={"http_calls": [{"method": "GET", "url": "/api/users"}]},
            )
        )

        ctx = _make_context_with_graph(g)
        matcher = HTTPEndpointMatcher()
        new_edges = matcher.match(ctx)

        assert len(new_edges) == 0


# ── Test 6-7: Message Queue Matcher ──────────────────────


class TestMessageQueueMatcher:
    def test_exact_topic_match(self):
        """Producer and consumer on same topic get linked via MessageTopic node."""
        g = SymbolGraph()

        producer = GraphNode(
            fqn="com.app.OrderService.placeOrder",
            name="placeOrder",
            kind=NodeKind.FUNCTION,
            language="java",
            properties={"mq_produces": [{"topic": "order-events", "broker": "kafka"}]},
        )
        g.add_node(producer)

        consumer = GraphNode(
            fqn="com.app.NotificationService.onOrderEvent",
            name="onOrderEvent",
            kind=NodeKind.FUNCTION,
            language="java",
            properties={"mq_consumes": [{"topic": "order-events", "broker": "kafka"}]},
        )
        g.add_node(consumer)

        ctx = _make_context_with_graph(g)
        matcher = MessageQueueMatcher()
        result = matcher.match(ctx)

        # Should create a MessageTopic node + PRODUCES edge + CONSUMES edge
        assert len(result.new_nodes) == 1
        topic_node = result.new_nodes[0]
        assert topic_node.kind == NodeKind.MESSAGE_TOPIC
        assert topic_node.name == "order-events"
        assert topic_node.properties["broker_type"] == "kafka"

        assert len(result.new_edges) == 2
        produces = [e for e in result.new_edges if e.kind == EdgeKind.PRODUCES]
        consumes = [e for e in result.new_edges if e.kind == EdgeKind.CONSUMES]
        assert len(produces) == 1
        assert len(consumes) == 1
        assert produces[0].source_fqn == producer.fqn
        assert consumes[0].source_fqn == consumer.fqn

    def test_wildcard_topic_match(self):
        """Consumer with 'order.*' wildcard matches producer with 'order.created'."""
        g = SymbolGraph()

        producer = GraphNode(
            fqn="com.app.OrderService.placeOrder",
            name="placeOrder",
            kind=NodeKind.FUNCTION,
            language="java",
            properties={
                "mq_produces": [{"topic": "order.created", "broker": "rabbitmq"}]
            },
        )
        g.add_node(producer)

        consumer = GraphNode(
            fqn="com.app.AuditService.onOrderEvent",
            name="onOrderEvent",
            kind=NodeKind.FUNCTION,
            language="java",
            properties={"mq_consumes": [{"topic": "order.*", "broker": "rabbitmq"}]},
        )
        g.add_node(consumer)

        ctx = _make_context_with_graph(g)
        matcher = MessageQueueMatcher()
        result = matcher.match(ctx)

        # The wildcard consumer should still get a CONSUMES edge.
        # Producer topic node: "order.created"
        # Consumer pattern "order.*" matches "order.created" -> linked to same topic
        consumes = [e for e in result.new_edges if e.kind == EdgeKind.CONSUMES]
        assert len(consumes) == 1
        # The consumer should be linked to the concrete topic node
        assert consumes[0].target_fqn == "topic:order.created"

    def test_no_match_different_topics(self):
        """Producer and consumer on different topics produce separate MessageTopics."""
        g = SymbolGraph()

        producer = GraphNode(
            fqn="com.app.A.publish",
            name="publish",
            kind=NodeKind.FUNCTION,
            properties={"mq_produces": [{"topic": "topic-a", "broker": "kafka"}]},
        )
        g.add_node(producer)

        consumer = GraphNode(
            fqn="com.app.B.consume",
            name="consume",
            kind=NodeKind.FUNCTION,
            properties={"mq_consumes": [{"topic": "topic-b", "broker": "kafka"}]},
        )
        g.add_node(consumer)

        ctx = _make_context_with_graph(g)
        matcher = MessageQueueMatcher()
        result = matcher.match(ctx)

        # Two separate topic nodes, one PRODUCES edge + one CONSUMES edge
        assert len(result.new_nodes) == 2
        assert len(result.new_edges) == 2

    def test_existing_topic_node_reused(self):
        """If a MessageTopic node already exists in the graph, reuse it."""
        g = SymbolGraph()

        existing_topic = GraphNode(
            fqn="topic:order-events",
            name="order-events",
            kind=NodeKind.MESSAGE_TOPIC,
            properties={"broker_type": "kafka"},
        )
        g.add_node(existing_topic)

        producer = GraphNode(
            fqn="com.app.A.publish",
            name="publish",
            kind=NodeKind.FUNCTION,
            properties={"mq_produces": [{"topic": "order-events", "broker": "kafka"}]},
        )
        g.add_node(producer)

        ctx = _make_context_with_graph(g)
        matcher = MessageQueueMatcher()
        result = matcher.match(ctx)

        # No new topic node — reuse existing
        assert len(result.new_nodes) == 0
        assert len(result.new_edges) == 1


# ── Test 8: Shared Database Matcher ──────────────────────


class TestSharedDBMatcher:
    def test_shared_table_cross_module_dependency(self):
        """Cross-module entities on same table -> DEPENDS_ON."""
        g = SymbolGraph()

        # Module A: OrderEntity -> orders table
        entity_a = GraphNode(
            fqn="com.app.orders.OrderEntity",
            name="OrderEntity",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/app/orders/OrderEntity.java",
            properties={"module": "orders"},
        )
        g.add_node(entity_a)

        table = GraphNode(
            fqn="table:orders",
            name="orders",
            kind=NodeKind.TABLE,
        )
        g.add_node(table)

        g.add_edge(
            GraphEdge(
                source_fqn="com.app.orders.OrderEntity",
                target_fqn="table:orders",
                kind=EdgeKind.MAPS_TO,
                properties={"orm": "hibernate"},
            )
        )

        # Module B: OrderReadModel -> orders table (same table, different module!)
        entity_b = GraphNode(
            fqn="com.app.reporting.OrderReadModel",
            name="OrderReadModel",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/app/reporting/OrderReadModel.java",
            properties={"module": "reporting"},
        )
        g.add_node(entity_b)

        g.add_edge(
            GraphEdge(
                source_fqn="com.app.reporting.OrderReadModel",
                target_fqn="table:orders",
                kind=EdgeKind.MAPS_TO,
                properties={"orm": "hibernate"},
            )
        )

        ctx = _make_context_with_graph(g)
        matcher = SharedDBMatcher()
        result = matcher.match(ctx)

        # Should produce a DEPENDS_ON edge between the two entities
        assert len(result.new_edges) >= 1
        dep_edges = [e for e in result.new_edges if e.kind == EdgeKind.DEPENDS_ON]
        assert len(dep_edges) >= 1
        # Should have a warning about shared DB coupling
        assert len(result.warnings) >= 1
        warning = result.warnings[0].lower()
        assert "orders" in warning or "shared" in warning

    def test_same_module_no_dependency_created(self):
        """Same module entities on same table -> no edge."""
        g = SymbolGraph()

        entity_a = GraphNode(
            fqn="com.app.orders.OrderEntity",
            name="OrderEntity",
            kind=NodeKind.CLASS,
            language="java",
            properties={"module": "orders"},
        )
        g.add_node(entity_a)

        entity_b = GraphNode(
            fqn="com.app.orders.OrderSummary",
            name="OrderSummary",
            kind=NodeKind.CLASS,
            language="java",
            properties={"module": "orders"},
        )
        g.add_node(entity_b)

        table = GraphNode(
            fqn="table:orders",
            name="orders",
            kind=NodeKind.TABLE,
        )
        g.add_node(table)

        g.add_edge(
            GraphEdge(
                source_fqn="com.app.orders.OrderEntity",
                target_fqn="table:orders",
                kind=EdgeKind.MAPS_TO,
            )
        )
        g.add_edge(
            GraphEdge(
                source_fqn="com.app.orders.OrderSummary",
                target_fqn="table:orders",
                kind=EdgeKind.MAPS_TO,
            )
        )

        ctx = _make_context_with_graph(g)
        matcher = SharedDBMatcher()
        result = matcher.match(ctx)

        # Same module — no cross-module dependency
        assert len(result.new_edges) == 0
        assert len(result.warnings) == 0

    def test_no_maps_to_edges(self):
        """Graph with no MAPS_TO edges -> no crash, no edges."""
        g = SymbolGraph()
        g.add_node(GraphNode(fqn="A", name="A", kind=NodeKind.CLASS))

        ctx = _make_context_with_graph(g)
        matcher = SharedDBMatcher()
        result = matcher.match(ctx)

        assert len(result.new_edges) == 0


# ── Test 9-10: Integration — run_cross_tech_linker ───────


class TestRunCrossTechLinker:
    @pytest.mark.asyncio
    async def test_empty_graph_no_errors(self):
        """Running linker on an empty graph produces no errors, 0 edges."""
        g = SymbolGraph()
        ctx = _make_context_with_graph(g)
        await run_cross_tech_linker(ctx)
        assert ctx.cross_tech_edge_count == 0
        assert len(ctx.warnings) == 0

    @pytest.mark.asyncio
    async def test_updates_context_edge_count(self):
        """run_cross_tech_linker sets context.cross_tech_edge_count."""
        g = SymbolGraph()

        g.add_node(
            GraphNode(
                fqn="GET:/api/users",
                name="GET /api/users",
                kind=NodeKind.API_ENDPOINT,
                properties={"method": "GET", "path": "/api/users"},
            )
        )
        g.add_node(
            GraphNode(
                fqn="src/api.fetchUsers",
                name="fetchUsers",
                kind=NodeKind.FUNCTION,
                language="typescript",
                properties={"http_calls": [{"method": "GET", "url": "/api/users"}]},
            )
        )

        ctx = _make_context_with_graph(g)
        await run_cross_tech_linker(ctx)

        assert ctx.cross_tech_edge_count >= 1
        api_edges = [e for e in ctx.graph.edges if e.kind == EdgeKind.CALLS_API]
        assert len(api_edges) == 1

    @pytest.mark.asyncio
    async def test_full_integration_all_matchers(self):
        """All matchers produce edges from a combined graph."""
        g = SymbolGraph()

        # HTTP: backend endpoint + frontend caller
        g.add_node(
            GraphNode(
                fqn="GET:/api/orders",
                name="GET /api/orders",
                kind=NodeKind.API_ENDPOINT,
                properties={"method": "GET", "path": "/api/orders"},
            )
        )
        g.add_node(
            GraphNode(
                fqn="src/OrderPage.loadOrders",
                name="loadOrders",
                kind=NodeKind.FUNCTION,
                language="typescript",
                properties={"http_calls": [{"method": "GET", "url": "/api/orders"}]},
            )
        )

        # MQ: producer + consumer
        g.add_node(
            GraphNode(
                fqn="com.app.OrderService.placeOrder",
                name="placeOrder",
                kind=NodeKind.FUNCTION,
                language="java",
                properties={
                    "mq_produces": [{"topic": "order-events", "broker": "kafka"}]
                },
            )
        )
        g.add_node(
            GraphNode(
                fqn="com.app.NotificationService.onOrder",
                name="onOrder",
                kind=NodeKind.FUNCTION,
                language="java",
                properties={
                    "mq_consumes": [{"topic": "order-events", "broker": "kafka"}]
                },
            )
        )

        # Shared DB: two entities from different modules -> same table
        g.add_node(
            GraphNode(
                fqn="com.app.orders.Order",
                name="Order",
                kind=NodeKind.CLASS,
                language="java",
                properties={"module": "orders"},
            )
        )
        g.add_node(
            GraphNode(
                fqn="com.app.shipping.OrderRef",
                name="OrderRef",
                kind=NodeKind.CLASS,
                language="java",
                properties={"module": "shipping"},
            )
        )
        g.add_node(
            GraphNode(
                fqn="table:orders",
                name="orders",
                kind=NodeKind.TABLE,
            )
        )
        g.add_edge(
            GraphEdge(
                source_fqn="com.app.orders.Order",
                target_fqn="table:orders",
                kind=EdgeKind.MAPS_TO,
            )
        )
        g.add_edge(
            GraphEdge(
                source_fqn="com.app.shipping.OrderRef",
                target_fqn="table:orders",
                kind=EdgeKind.MAPS_TO,
            )
        )

        ctx = _make_context_with_graph(g)
        await run_cross_tech_linker(ctx)

        # HTTP: 1 CALLS_API edge
        api_edges = [e for e in ctx.graph.edges if e.kind == EdgeKind.CALLS_API]
        assert len(api_edges) == 1

        # MQ: 1 PRODUCES + 1 CONSUMES edge
        produces = [e for e in ctx.graph.edges if e.kind == EdgeKind.PRODUCES]
        consumes = [e for e in ctx.graph.edges if e.kind == EdgeKind.CONSUMES]
        assert len(produces) == 1
        assert len(consumes) == 1

        # Shared DB: at least 1 DEPENDS_ON edge
        depends = [e for e in ctx.graph.edges if e.kind == EdgeKind.DEPENDS_ON]
        assert len(depends) >= 1

        # Total cross_tech_edge_count should be >= 4
        assert ctx.cross_tech_edge_count >= 4
