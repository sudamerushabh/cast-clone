# M7a: Cross-Technology Linker (Stage 6) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Stage 6 of the analysis pipeline — the Cross-Technology Linker. This stage runs after all framework plugins (Stage 5) and stitches connections across language/service boundaries via three matchers: HTTP Endpoint Matcher, Message Queue Matcher, and Shared Database Matcher.

**Architecture:** Three matcher classes operate on the shared `AnalysisContext.graph` (a `SymbolGraph`). Each matcher reads existing nodes/edges and produces new edges (and optionally new nodes). The top-level `run_cross_tech_linker()` async function orchestrates all three matchers, catches individual failures gracefully, and updates `context.cross_tech_edge_count`. All matchers are pure in-memory graph transformations — no I/O.

**Tech Stack:** Python 3.12, dataclasses, structlog, re, urllib.parse, fnmatch, pytest + pytest-asyncio

**Dependencies from M1:** `GraphNode`, `GraphEdge`, `SymbolGraph`, `AnalysisContext`, `ProjectManifest`, `NodeKind`, `EdgeKind`, `Confidence`

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       ├── __init__.py              # MODIFY — add linker import
│       └── linker.py                # CREATE — Stage 6: Cross-Tech Linker
├── tests/
│   └── unit/
│       └── test_linker.py           # CREATE — 14 tests
```

---

## Task 1: URL Normalization + HTTP Endpoint Matcher

**Files:**
- Create: `app/stages/linker.py` (partial — URL normalization + HTTPEndpointMatcher)
- Create: `tests/unit/test_linker.py` (partial — URL normalization + HTTP matcher tests)

### Overview

The HTTP Endpoint Matcher links frontend HTTP client calls to backend API endpoints. Framework plugins (Spring Web, Express, ASP.NET, NestJS) produce `APIEndpoint` nodes with `properties["method"]` and `properties["path"]`. Frontend extractors tag `FUNCTION` nodes with `properties["http_calls"]` — a list of `{"method": "GET", "url": "/api/users"}` dicts.

The core algorithm is **path normalization**: convert all parameter styles (`{id}`, `:id`, `${id}`) to a canonical `:param` form, strip base URLs, lowercase, strip trailing slashes and query strings. Then match by (HTTP method, normalized path) — exact match yields HIGH confidence, parameterized segment match yields MEDIUM.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_linker.py
"""Tests for Stage 6: Cross-Technology Linker."""

import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest
from app.stages.linker import (
    normalize_url_path,
    run_cross_tech_linker,
    HTTPEndpointMatcher,
    MessageQueueMatcher,
    SharedDBMatcher,
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
        assert normalize_url_path("/api/{orgId}/users/{id}") == "/api/:param/users/:param"

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
        """frontend fetch('/api/users') matches backend GET /api/users -> CALLS_API HIGH."""
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
        g.add_edge(GraphEdge(
            source_fqn="com.app.UserController.getUsers",
            target_fqn="GET:/api/users",
            kind=EdgeKind.HANDLES,
        ))

        # Frontend caller
        caller = GraphNode(
            fqn="src/api/userApi.fetchUsers",
            name="fetchUsers",
            kind=NodeKind.FUNCTION,
            language="typescript",
            properties={
                "http_calls": [
                    {"method": "GET", "url": "/api/users"}
                ]
            },
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
            properties={
                "http_calls": [
                    {"method": "GET", "url": "/api/users/${userId}"}
                ]
            },
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
            properties={
                "http_calls": [
                    {"method": "POST", "url": "/api/users"}
                ]
            },
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
            properties={
                "http_calls": [
                    {"method": "GET", "url": "/api/users"}
                ]
            },
        )
        g.add_node(caller)

        ctx = _make_context_with_graph(g)
        matcher = HTTPEndpointMatcher()
        new_edges = matcher.match(ctx)

        assert len(new_edges) == 0

    def test_multiple_endpoints_matched(self):
        """Caller with multiple HTTP calls produces multiple CALLS_API edges."""
        g = SymbolGraph()

        g.add_node(GraphNode(
            fqn="GET:/api/users",
            name="GET /api/users",
            kind=NodeKind.API_ENDPOINT,
            properties={"method": "GET", "path": "/api/users"},
        ))
        g.add_node(GraphNode(
            fqn="POST:/api/users",
            name="POST /api/users",
            kind=NodeKind.API_ENDPOINT,
            properties={"method": "POST", "path": "/api/users"},
        ))

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
        g.add_node(GraphNode(
            fqn="src/app.main",
            name="main",
            kind=NodeKind.FUNCTION,
            language="typescript",
            properties={"http_calls": [{"method": "GET", "url": "/api/users"}]},
        ))

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
            properties={
                "mq_produces": [{"topic": "order-events", "broker": "kafka"}]
            },
        )
        g.add_node(producer)

        consumer = GraphNode(
            fqn="com.app.NotificationService.onOrderEvent",
            name="onOrderEvent",
            kind=NodeKind.FUNCTION,
            language="java",
            properties={
                "mq_consumes": [{"topic": "order-events", "broker": "kafka"}]
            },
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
            properties={
                "mq_consumes": [{"topic": "order.*", "broker": "rabbitmq"}]
            },
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
        """Two entities from different modules mapping to same table -> DEPENDS_ON edge."""
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

        g.add_edge(GraphEdge(
            source_fqn="com.app.orders.OrderEntity",
            target_fqn="table:orders",
            kind=EdgeKind.MAPS_TO,
            properties={"orm": "hibernate"},
        ))

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

        g.add_edge(GraphEdge(
            source_fqn="com.app.reporting.OrderReadModel",
            target_fqn="table:orders",
            kind=EdgeKind.MAPS_TO,
            properties={"orm": "hibernate"},
        ))

        ctx = _make_context_with_graph(g)
        matcher = SharedDBMatcher()
        result = matcher.match(ctx)

        # Should produce a DEPENDS_ON edge between the two entities
        assert len(result.new_edges) >= 1
        dep_edges = [e for e in result.new_edges if e.kind == EdgeKind.DEPENDS_ON]
        assert len(dep_edges) >= 1
        # Should have a warning about shared DB coupling
        assert len(result.warnings) >= 1
        assert "orders" in result.warnings[0].lower() or "shared" in result.warnings[0].lower()

    def test_same_module_no_dependency_created(self):
        """Two entities from the SAME module mapping to same table -> no cross-module edge."""
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

        g.add_edge(GraphEdge(
            source_fqn="com.app.orders.OrderEntity",
            target_fqn="table:orders",
            kind=EdgeKind.MAPS_TO,
        ))
        g.add_edge(GraphEdge(
            source_fqn="com.app.orders.OrderSummary",
            target_fqn="table:orders",
            kind=EdgeKind.MAPS_TO,
        ))

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

        g.add_node(GraphNode(
            fqn="GET:/api/users",
            name="GET /api/users",
            kind=NodeKind.API_ENDPOINT,
            properties={"method": "GET", "path": "/api/users"},
        ))
        g.add_node(GraphNode(
            fqn="src/api.fetchUsers",
            name="fetchUsers",
            kind=NodeKind.FUNCTION,
            language="typescript",
            properties={"http_calls": [{"method": "GET", "url": "/api/users"}]},
        ))

        ctx = _make_context_with_graph(g)
        await run_cross_tech_linker(ctx)

        assert ctx.cross_tech_edge_count >= 1
        api_edges = [e for e in ctx.graph.edges if e.kind == EdgeKind.CALLS_API]
        assert len(api_edges) == 1

    @pytest.mark.asyncio
    async def test_full_integration_all_matchers(self):
        """Graph with HTTP endpoints, MQ topics, and shared DB -> all matchers produce edges."""
        g = SymbolGraph()

        # HTTP: backend endpoint + frontend caller
        g.add_node(GraphNode(
            fqn="GET:/api/orders",
            name="GET /api/orders",
            kind=NodeKind.API_ENDPOINT,
            properties={"method": "GET", "path": "/api/orders"},
        ))
        g.add_node(GraphNode(
            fqn="src/OrderPage.loadOrders",
            name="loadOrders",
            kind=NodeKind.FUNCTION,
            language="typescript",
            properties={"http_calls": [{"method": "GET", "url": "/api/orders"}]},
        ))

        # MQ: producer + consumer
        g.add_node(GraphNode(
            fqn="com.app.OrderService.placeOrder",
            name="placeOrder",
            kind=NodeKind.FUNCTION,
            language="java",
            properties={"mq_produces": [{"topic": "order-events", "broker": "kafka"}]},
        ))
        g.add_node(GraphNode(
            fqn="com.app.NotificationService.onOrder",
            name="onOrder",
            kind=NodeKind.FUNCTION,
            language="java",
            properties={"mq_consumes": [{"topic": "order-events", "broker": "kafka"}]},
        ))

        # Shared DB: two entities from different modules -> same table
        g.add_node(GraphNode(
            fqn="com.app.orders.Order",
            name="Order",
            kind=NodeKind.CLASS,
            language="java",
            properties={"module": "orders"},
        ))
        g.add_node(GraphNode(
            fqn="com.app.shipping.OrderRef",
            name="OrderRef",
            kind=NodeKind.CLASS,
            language="java",
            properties={"module": "shipping"},
        ))
        g.add_node(GraphNode(
            fqn="table:orders",
            name="orders",
            kind=NodeKind.TABLE,
        ))
        g.add_edge(GraphEdge(
            source_fqn="com.app.orders.Order",
            target_fqn="table:orders",
            kind=EdgeKind.MAPS_TO,
        ))
        g.add_edge(GraphEdge(
            source_fqn="com.app.shipping.OrderRef",
            target_fqn="table:orders",
            kind=EdgeKind.MAPS_TO,
        ))

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_linker.py -v`
Expected: FAIL (ImportError — module doesn't exist)

- [ ] **Step 3: Implement the linker**

```python
# app/stages/linker.py
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
_SPRING_PARAM = re.compile(r"\{[^}]+\}")          # {id}, {userId}
_EXPRESS_PARAM = re.compile(r":([a-zA-Z_]\w*)")    # :id, :userId
_TEMPLATE_PARAM = re.compile(r"\$\{[^}]+\}")       # ${id}, ${userId}
_URL_SCHEME = re.compile(r"^https?://[^/]+")        # https://example.com


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
                    new_edges.append(GraphEdge(
                        source_fqn=node.fqn,
                        target_fqn=endpoint_fqn,
                        kind=EdgeKind.CALLS_API,
                        confidence=confidence,
                        evidence="cross-tech-linker",
                        properties={
                            "url_pattern": url,
                            "method": method,
                        },
                    ))

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
                producers.append((node.fqn, prod["topic"], prod.get("broker", "unknown")))

            for cons in node.properties.get("mq_consumes", []):
                consumers.append((node.fqn, cons["topic"], cons.get("broker", "unknown")))

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
            result.new_edges.append(GraphEdge(
                source_fqn=fn_fqn,
                target_fqn=topic_fqns[topic],
                kind=EdgeKind.PRODUCES,
                confidence=Confidence.HIGH,
                evidence="cross-tech-linker",
            ))

        # Create CONSUMES edges
        for fn_fqn, topic_or_pattern, _ in consumers:
            if "*" in topic_or_pattern or "?" in topic_or_pattern:
                # Wildcard consumer — match against all concrete topics
                for concrete_topic, fqn in topic_fqns.items():
                    if fnmatch(concrete_topic, topic_or_pattern):
                        result.new_edges.append(GraphEdge(
                            source_fqn=fn_fqn,
                            target_fqn=fqn,
                            kind=EdgeKind.CONSUMES,
                            confidence=Confidence.MEDIUM,
                            evidence="cross-tech-linker-wildcard",
                            properties={"pattern": topic_or_pattern},
                        ))
            else:
                # Exact consumer topic
                fqn = topic_fqns.get(topic_or_pattern)
                if fqn is not None:
                    result.new_edges.append(GraphEdge(
                        source_fqn=fn_fqn,
                        target_fqn=fqn,
                        kind=EdgeKind.CONSUMES,
                        confidence=Confidence.HIGH,
                        evidence="cross-tech-linker",
                    ))

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
        table_to_entities: dict[str, list[str]] = defaultdict(list)  # table_fqn -> [entity_fqn]

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
            module_entities: dict[str, list[str]] = defaultdict(list)  # module -> [entity_fqn]
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
                            result.new_edges.append(GraphEdge(
                                source_fqn=ea,
                                target_fqn=eb,
                                kind=EdgeKind.DEPENDS_ON,
                                confidence=Confidence.MEDIUM,
                                evidence="shared-db-coupling",
                                properties={
                                    "shared_table": table_name,
                                    "coupling_type": "shared_database",
                                },
                            ))

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_linker.py -v`
Expected: PASS (all 14 tests across 5 test classes)

Expected output:
```
tests/unit/test_linker.py::TestNormalizeUrlPath::test_spring_path_param PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_express_path_param PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_template_literal_param PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_multiple_params PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_trailing_slash_stripped PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_query_params_stripped PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_base_url_stripped PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_base_url_with_port_stripped PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_lowercase PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_root_path PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_empty_string PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_no_leading_slash_added PASSED
tests/unit/test_linker.py::TestNormalizeUrlPath::test_combined_edge_cases PASSED
tests/unit/test_linker.py::TestHTTPEndpointMatcher::test_exact_match_get_endpoint PASSED
tests/unit/test_linker.py::TestHTTPEndpointMatcher::test_parameterized_match_medium_confidence PASSED
tests/unit/test_linker.py::TestHTTPEndpointMatcher::test_no_match_different_method PASSED
tests/unit/test_linker.py::TestHTTPEndpointMatcher::test_no_match_unmatched_url PASSED
tests/unit/test_linker.py::TestHTTPEndpointMatcher::test_multiple_endpoints_matched PASSED
tests/unit/test_linker.py::TestHTTPEndpointMatcher::test_no_endpoints_returns_empty PASSED
tests/unit/test_linker.py::TestMessageQueueMatcher::test_exact_topic_match PASSED
tests/unit/test_linker.py::TestMessageQueueMatcher::test_wildcard_topic_match PASSED
tests/unit/test_linker.py::TestMessageQueueMatcher::test_no_match_different_topics PASSED
tests/unit/test_linker.py::TestMessageQueueMatcher::test_existing_topic_node_reused PASSED
tests/unit/test_linker.py::TestSharedDBMatcher::test_shared_table_cross_module_dependency PASSED
tests/unit/test_linker.py::TestSharedDBMatcher::test_same_module_no_dependency_created PASSED
tests/unit/test_linker.py::TestSharedDBMatcher::test_no_maps_to_edges PASSED
tests/unit/test_linker.py::TestRunCrossTechLinker::test_empty_graph_no_errors PASSED
tests/unit/test_linker.py::TestRunCrossTechLinker::test_updates_context_edge_count PASSED
tests/unit/test_linker.py::TestRunCrossTechLinker::test_full_integration_all_matchers PASSED
```

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/linker.py tests/unit/test_linker.py && git commit -m "feat(stages): add Stage 6 cross-tech linker with HTTP, MQ, and shared DB matchers"
```

---

## Summary

| Artifact | Description |
|----------|-------------|
| `app/stages/linker.py` | ~280 lines. Three matcher classes + `normalize_url_path()` + `run_cross_tech_linker()` orchestrator |
| `tests/unit/test_linker.py` | ~420 lines. 29 tests across 5 classes |

### Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| URL normalization as standalone function | `normalize_url_path()` | Testable in isolation, reusable by other stages |
| Query string stripping | Split on `?` before param normalization | Real frontend calls often include query params that backends never route on |
| Param normalization order | `${...}` first, then `{...}`, then `:name` | Avoids `${id}` being partially matched by the `{...}` regex |
| MQ wildcard matching | `fnmatch` from stdlib | Supports `*` and `?` patterns already, no new deps needed |
| Wildcard consumers link to concrete topics | CONSUMES edge from consumer -> producer's topic node | Avoids creating phantom topic nodes for patterns like `order.*` |
| Shared DB module inference | `properties["module"]` with FQN-based fallback | Plugins set module explicitly; fallback covers cases where they don't |
| Matcher isolation | Each matcher is its own class with a `match()` method | Easy to test independently, easy to add new matchers later |
| Non-critical error handling | Each matcher wrapped in try/except in orchestrator | One matcher failing doesn't block the others |

### Edge Schema Produced

| Edge | Source | Target | Properties |
|------|--------|--------|------------|
| `CALLS_API` | `Function` (frontend caller) | `APIEndpoint` | `url_pattern`, `method` |
| `PRODUCES` | `Function` (publisher) | `MessageTopic` | — |
| `CONSUMES` | `Function` (subscriber) | `MessageTopic` | `pattern` (if wildcard) |
| `DEPENDS_ON` | `Class` (entity A) | `Class` (entity B) | `shared_table`, `coupling_type` |

### Test Commands

```bash
# Run all linker tests
cd cast-clone-backend && uv run pytest tests/unit/test_linker.py -v

# Run only URL normalization tests
cd cast-clone-backend && uv run pytest tests/unit/test_linker.py::TestNormalizeUrlPath -v

# Run only HTTP matcher tests
cd cast-clone-backend && uv run pytest tests/unit/test_linker.py::TestHTTPEndpointMatcher -v

# Run only MQ matcher tests
cd cast-clone-backend && uv run pytest tests/unit/test_linker.py::TestMessageQueueMatcher -v

# Run only shared DB matcher tests
cd cast-clone-backend && uv run pytest tests/unit/test_linker.py::TestSharedDBMatcher -v

# Run only integration tests
cd cast-clone-backend && uv run pytest tests/unit/test_linker.py::TestRunCrossTechLinker -v
```
