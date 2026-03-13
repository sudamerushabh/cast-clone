# Phase 5b-M1: Shared Tool Layer + Agentic Chat Backend

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shared AI tool layer over Neo4j and an agentic chat backend with SSE streaming, extended thinking, tool call visibility, and page-context awareness.

**Architecture:** A set of async tool functions in `app/ai/tools.py` wrap Cypher queries against the existing `GraphStore`. A chat service in `app/ai/chat.py` runs a Claude Sonnet agent loop with these tools, streaming thinking/tool_use/text events via SSE. A FastAPI endpoint at `POST /api/v1/projects/{project_id}/chat` accepts messages with optional page context and returns an SSE stream. JWT auth required.

**Tech Stack:** Python 3.12, FastAPI (SSE via `StreamingResponse`), Anthropic SDK (`AsyncAnthropicBedrock`), Neo4j (async driver), Pydantic v2, structlog, pytest + pytest-asyncio.

---

## File Structure

```
app/ai/                           # NEW package
├── __init__.py                   # Package marker
├── tools.py                      # Shared tool functions (async, Cypher-backed)
├── tool_definitions.py           # Claude API tool schemas (Anthropic format)
└── chat.py                       # Agentic chat service (agent loop + SSE streaming)

app/api/
└── chat.py                       # NEW — FastAPI SSE endpoint

app/schemas/
└── chat.py                       # NEW — ChatRequest, PageContext, ChatEvent models

app/config.py                     # MODIFY — add chat_* settings

app/api/__init__.py               # MODIFY — register chat_router
app/main.py                       # MODIFY — include chat_router

tests/unit/
├── test_chat_tools.py            # NEW — unit tests for shared tool functions
├── test_chat_schemas.py          # NEW — schema validation tests
└── test_chat_service.py          # NEW — agent loop + SSE tests (mocked Anthropic)
```

---

## Task 1: Config Additions

**Files:**
- Modify: `app/config.py:6-41`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_config.py (append to existing file or create)
from app.config import Settings

def test_chat_settings_defaults():
    s = Settings(database_url="postgresql+asyncpg://x", neo4j_uri="bolt://x")
    assert s.chat_model == "us.anthropic.claude-sonnet-4-6"
    assert s.chat_max_tool_calls == 15
    assert s.chat_timeout_seconds == 120
    assert s.chat_max_response_tokens == 4096
    assert s.chat_thinking_budget_tokens == 2048
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_config.py::test_chat_settings_defaults -v`
Expected: FAIL — `Settings` has no `chat_model` attribute.

- [ ] **Step 3: Add chat settings to config**

In `app/config.py`, add after line 41 (after `pr_analysis_max_total_tokens`):

```python
    # Phase 5b: AI chat
    chat_model: str = "us.anthropic.claude-sonnet-4-6"
    chat_max_tool_calls: int = 15
    chat_timeout_seconds: int = 120
    chat_max_response_tokens: int = 4096
    chat_thinking_budget_tokens: int = 2048
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_config.py::test_chat_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/config.py tests/unit/test_config.py
git commit -m "feat(5b-m1): add chat configuration settings"
```

---

## Task 2: Chat Schemas (Pydantic v2)

**Files:**
- Create: `app/schemas/chat.py`
- Test: `tests/unit/test_chat_schemas.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_chat_schemas.py
import pytest
from app.schemas.chat import ChatRequest, PageContext


class TestPageContext:
    def test_minimal(self):
        ctx = PageContext(page="dashboard")
        assert ctx.page == "dashboard"
        assert ctx.selected_node_fqn is None

    def test_full(self):
        ctx = PageContext(
            page="graph_explorer",
            selected_node_fqn="com.app.OrderService",
            view="architecture",
            level="class",
        )
        assert ctx.selected_node_fqn == "com.app.OrderService"


class TestChatRequest:
    def test_minimal(self):
        req = ChatRequest(message="What does OrderService do?")
        assert req.message == "What does OrderService do?"
        assert req.history == []
        assert req.include_page_context is True
        assert req.page_context is None

    def test_with_context(self):
        req = ChatRequest(
            message="Explain this",
            page_context=PageContext(page="graph_explorer", selected_node_fqn="com.app.X"),
            include_page_context=True,
            history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        )
        assert req.page_context.selected_node_fqn == "com.app.X"
        assert len(req.history) == 2

    def test_history_max_10(self):
        history = [{"role": "user", "content": f"msg {i}"} for i in range(12)]
        req = ChatRequest(message="latest", history=history)
        assert len(req.history) == 10  # Truncated to last 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_schemas.py -v`
Expected: FAIL — `app.schemas.chat` not found.

- [ ] **Step 3: Create the schemas**

```python
# app/schemas/chat.py
"""Request/response models for the AI chat endpoint."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class PageContext(BaseModel):
    """Describes what page/view the user is currently on."""
    page: str                                    # "graph_explorer", "pr_detail", "dashboard"
    selected_node_fqn: str | None = None
    view: str | None = None                      # "architecture", "dependency", "transaction"
    level: str | None = None                     # "module", "class", "method"
    pr_analysis_id: str | None = None


class ChatRequest(BaseModel):
    """Incoming chat message from the frontend."""
    message: str = Field(..., min_length=1, max_length=5000)
    history: list[dict] = Field(default_factory=list)
    page_context: PageContext | None = None
    include_page_context: bool = True

    @model_validator(mode="after")
    def trim_history(self) -> "ChatRequest":
        """Keep only the last 10 conversation turns."""
        if len(self.history) > 10:
            self.history = self.history[-10:]
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/schemas/chat.py tests/unit/test_chat_schemas.py
git commit -m "feat(5b-m1): add chat request/response Pydantic schemas"
```

---

## Task 3: Shared Tool Layer — Tool Context + Tool Functions

**Files:**
- Create: `app/ai/__init__.py`
- Create: `app/ai/tools.py`
- Test: `tests/unit/test_chat_tools.py`

This is the core shared tool layer. Each function is an async wrapper around a Cypher query, using the same `GraphStore.query()` / `GraphStore.query_single()` interface as Phase 5a.

- [ ] **Step 1: Create `app/ai/__init__.py`**

```python
# app/ai/__init__.py
"""Shared AI layer — tools, chat service, and summaries."""
```

- [ ] **Step 2: Write tests for shared tool functions**

```python
# tests/unit/test_chat_tools.py
"""Unit tests for the shared AI tool layer.

All tests mock GraphStore — no Neo4j needed.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.ai.tools import (
    ChatToolContext,
    list_applications,
    application_stats,
    search_objects,
    object_details,
    impact_analysis,
    find_path,
    list_transactions,
    get_source_code,
    get_architecture,
)


@pytest.fixture
def mock_graph_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def ctx(mock_graph_store: AsyncMock) -> ChatToolContext:
    return ChatToolContext(
        graph_store=mock_graph_store,
        app_name="test-app",
        project_id="proj-123",
    )


class TestListApplications:
    @pytest.mark.asyncio
    async def test_returns_apps(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"name": "app1", "languages": ["Java"], "total_loc": 5000},
            {"name": "app2", "languages": ["Python"], "total_loc": 3000},
        ]
        result = await list_applications(ctx)
        assert len(result) == 2
        assert result[0]["name"] == "app1"

    @pytest.mark.asyncio
    async def test_empty(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = []
        result = await list_applications(ctx)
        assert result == []


class TestSearchObjects:
    @pytest.mark.asyncio
    async def test_search_by_name(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"fqn": "com.app.OrderService", "name": "OrderService", "type": "Class"},
        ]
        result = await search_objects(ctx, query="Order")
        assert len(result) == 1
        assert result[0]["fqn"] == "com.app.OrderService"

    @pytest.mark.asyncio
    async def test_search_with_type_filter(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = []
        result = await search_objects(ctx, query="Order", type_filter="Function")
        # Verify the Cypher query included the type filter
        call_args = ctx.graph_store.query.call_args
        assert "type_filter" in call_args[1] or "Function" in str(call_args)


class TestObjectDetails:
    @pytest.mark.asyncio
    async def test_found(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = {
            "fqn": "com.app.OrderService", "name": "OrderService",
            "type": "Class", "language": "Java", "path": "src/OrderService.java",
            "line": 10, "end_line": 100, "loc": 90,
        }
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.Caller", "name": "Caller", "type": "Class"}],  # callers
            [{"fqn": "com.app.Callee", "name": "Callee", "type": "Class"}],  # callees
        ]
        result = await object_details(ctx, node_fqn="com.app.OrderService")
        assert result["node"]["fqn"] == "com.app.OrderService"
        assert len(result["callers"]) == 1
        assert len(result["callees"]) == 1
        assert result["node"]["fan_in"] == 1
        assert result["node"]["fan_out"] == 1

    @pytest.mark.asyncio
    async def test_not_found(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = None
        result = await object_details(ctx, node_fqn="does.not.exist")
        assert result["node"] is None


class TestImpactAnalysis:
    @pytest.mark.asyncio
    async def test_downstream(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"fqn": "com.app.A", "name": "A", "type": "Class", "file": "A.java", "depth": 1},
            {"fqn": "com.app.B", "name": "B", "type": "Function", "file": "B.java", "depth": 2},
        ]
        result = await impact_analysis(ctx, node_fqn="com.app.X", direction="downstream", depth=5)
        assert result["total"] == 2
        assert result["by_type"] == {"Class": 1, "Function": 1}

    @pytest.mark.asyncio
    async def test_depth_capped_at_10(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = []
        await impact_analysis(ctx, node_fqn="com.app.X", direction="downstream", depth=20)
        cypher = ctx.graph_store.query.call_args[0][0]
        assert "*1..10]" in cypher  # Depth capped


class TestFindPath:
    @pytest.mark.asyncio
    async def test_path_found(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [{
            "nodes": [{"fqn": "A", "name": "A", "type": "Class"}, {"fqn": "B", "name": "B", "type": "Class"}],
            "edges": [{"type": "CALLS", "source": "A", "target": "B"}],
            "path_length": 1,
        }]
        result = await find_path(ctx, from_fqn="A", to_fqn="B")
        assert result["path_length"] == 1

    @pytest.mark.asyncio
    async def test_no_path(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = []
        result = await find_path(ctx, from_fqn="A", to_fqn="Z")
        assert result["path_length"] == 0


class TestGetSourceCode:
    @pytest.mark.asyncio
    async def test_node_found_with_repo(self, ctx: ChatToolContext, tmp_path):
        # Create a fake source file
        src = tmp_path / "src" / "OrderService.java"
        src.parent.mkdir(parents=True)
        src.write_text("line1\nline2\nline3\nline4\nline5\n")

        ctx.repo_path = str(tmp_path)
        ctx.graph_store.query_single.return_value = {
            "path": "src/OrderService.java", "line": 2, "end_line": 4,
        }
        result = await get_source_code(ctx, node_fqn="com.app.OrderService")
        assert result["fqn"] == "com.app.OrderService"
        assert "line2" in result["code"]
        assert "line4" in result["code"]

    @pytest.mark.asyncio
    async def test_node_not_found(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = None
        result = await get_source_code(ctx, node_fqn="does.not.exist")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_repo_path(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = {
            "path": "src/OrderService.java", "line": 2, "end_line": 4,
        }
        result = await get_source_code(ctx, node_fqn="com.app.OrderService")
        # No repo_path → return metadata only
        assert result["fqn"] == "com.app.OrderService"
        assert result.get("code") is None


class TestApplicationStats:
    @pytest.mark.asyncio
    async def test_returns_stats(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"type": "Class", "count": 10, "total_loc": 5000},
            {"type": "Function", "count": 50, "total_loc": 3000},
        ]
        result = await application_stats(ctx)
        assert result["app_name"] == "test-app"
        assert result["by_type"]["Class"] == 10
        assert result["total_loc"] == 8000


class TestGetArchitecture:
    @pytest.mark.asyncio
    async def test_module_level(self, ctx: ChatToolContext):
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.orders", "name": "orders", "type": "Module", "loc": 1000}],
            [{"source": "com.app.orders", "target": "com.app.billing", "kind": "IMPORTS", "weight": 3}],
        ]
        result = await get_architecture(ctx, level="module")
        assert len(result["nodes"]) == 1
        assert len(result["edges"]) == 1


class TestTransactionGraph:
    @pytest.mark.asyncio
    async def test_returns_graph(self, ctx: ChatToolContext):
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.A", "name": "A", "type": "Function", "path": "A.java"}],
            [{"source": "com.app.A", "target": "com.app.B", "kind": "CALLS"}],
        ]
        from app.ai.tools import transaction_graph
        result = await transaction_graph(ctx, transaction_name="POST /orders")
        assert len(result["nodes"]) == 1
        assert len(result["edges"]) == 1


class TestListTransactions:
    @pytest.mark.asyncio
    async def test_returns_transactions(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"name": "POST /orders", "http_method": "POST", "url_path": "/orders", "node_count": 12, "depth": 5},
        ]
        result = await list_transactions(ctx)
        assert len(result) == 1
        assert result[0]["name"] == "POST /orders"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_tools.py -v`
Expected: FAIL — `app.ai.tools` not found.

- [ ] **Step 4: Implement the shared tool functions**

```python
# app/ai/tools.py
"""Shared AI tool functions — used by both the chat backend and the MCP server.

Each function wraps a Cypher query against GraphStore. All functions are async
and return plain dicts/lists (JSON-serializable).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from app.services.neo4j import GraphStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


@dataclass
class ChatToolContext:
    """Shared context passed to all tool functions."""
    graph_store: GraphStore
    app_name: str
    project_id: str
    repo_path: str | None = None         # Cloned repo path (for get_source_code)
    db_session: AsyncSession | None = None  # For PostgreSQL writes (M2: summaries)


# ── Portfolio Tools ──────────────────────────────────────────


async def list_applications(ctx: ChatToolContext) -> list[dict]:
    """List all analyzed applications in CodeLens."""
    return await ctx.graph_store.query(
        "MATCH (n) WHERE n.app_name IS NOT NULL "
        "WITH DISTINCT n.app_name AS name "
        "OPTIONAL MATCH (m {app_name: name, kind: 'Module'}) "
        "RETURN name, count(m) AS module_count"
    )


async def application_stats(ctx: ChatToolContext, app_name: str | None = None) -> dict:
    """Get size, complexity, and technology metrics for an application."""
    name = app_name or ctx.app_name
    records = await ctx.graph_store.query(
        "MATCH (n) WHERE n.app_name = $name "
        "RETURN labels(n)[0] AS type, count(n) AS count, sum(n.loc) AS total_loc",
        {"name": name},
    )
    by_type = {r["type"]: r["count"] for r in records if r["type"]}
    total_loc = sum(r["total_loc"] or 0 for r in records)
    return {"app_name": name, "by_type": by_type, "total_loc": total_loc}


# ── Architecture Tools ───────────────────────────────────────


async def get_architecture(
    ctx: ChatToolContext, level: str = "module",
) -> dict:
    """Get application architecture at module or class level."""
    if level == "module":
        nodes = await ctx.graph_store.query(
            "MATCH (m) WHERE m.app_name = $name AND m.kind = 'Module' "
            "RETURN m.fqn AS fqn, m.name AS name, 'Module' AS type, m.loc AS loc",
            {"name": ctx.app_name},
        )
        edges = await ctx.graph_store.query(
            "MATCH (a)-[r:IMPORTS]->(b) "
            "WHERE a.app_name = $name AND b.app_name = $name "
            "AND a.kind = 'Module' AND b.kind = 'Module' "
            "RETURN a.fqn AS source, b.fqn AS target, type(r) AS kind, r.weight AS weight",
            {"name": ctx.app_name},
        )
    else:
        nodes = await ctx.graph_store.query(
            "MATCH (c) WHERE c.app_name = $name AND c.kind = 'Class' "
            "RETURN c.fqn AS fqn, c.name AS name, 'Class' AS type, c.loc AS loc "
            "LIMIT 500",
            {"name": ctx.app_name},
        )
        edges = await ctx.graph_store.query(
            "MATCH (a)-[r:DEPENDS_ON]->(b) "
            "WHERE a.app_name = $name AND b.app_name = $name "
            "AND a.kind = 'Class' AND b.kind = 'Class' "
            "RETURN a.fqn AS source, b.fqn AS target, type(r) AS kind, r.weight AS weight "
            "LIMIT 2000",
            {"name": ctx.app_name},
        )
    return {"nodes": nodes, "edges": edges}


async def search_objects(
    ctx: ChatToolContext,
    query: str,
    type_filter: str | None = None,
) -> list[dict]:
    """Search for code objects by name. Optionally filter by type."""
    where_parts = [
        "n.app_name = $app_name",
        "(toLower(n.name) CONTAINS toLower($query) OR toLower(n.fqn) CONTAINS toLower($query))",
    ]
    params: dict = {"app_name": ctx.app_name, "query": query}

    if type_filter:
        where_parts.append("labels(n)[0] = $type_filter")
        params["type_filter"] = type_filter

    cypher = (
        f"MATCH (n) WHERE {' AND '.join(where_parts)} "
        "RETURN n.fqn AS fqn, n.name AS name, labels(n)[0] AS type, "
        "n.language AS language, n.path AS path "
        "LIMIT 50"
    )
    return await ctx.graph_store.query(cypher, params)


# ── Node Details Tools ───────────────────────────────────────


async def object_details(ctx: ChatToolContext, node_fqn: str) -> dict:
    """Get detailed info about a specific code object including callers and callees."""
    node = await ctx.graph_store.query_single(
        "MATCH (n {fqn: $fqn, app_name: $app_name}) "
        "RETURN n.fqn AS fqn, n.name AS name, labels(n)[0] AS type, "
        "  n.language AS language, n.path AS path, n.line AS line, "
        "  n.end_line AS end_line, n.loc AS loc, n.complexity AS complexity, "
        "  n.communityId AS community_id",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )
    if not node:
        return {"node": None, "callers": [], "callees": []}

    callers = await ctx.graph_store.query(
        "MATCH (caller)-[:CALLS]->(n {fqn: $fqn, app_name: $app_name}) "
        "RETURN caller.fqn AS fqn, caller.name AS name, labels(caller)[0] AS type "
        "LIMIT 50",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )
    callees = await ctx.graph_store.query(
        "MATCH (n {fqn: $fqn, app_name: $app_name})-[:CALLS]->(callee) "
        "RETURN callee.fqn AS fqn, callee.name AS name, labels(callee)[0] AS type "
        "LIMIT 50",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )

    node["fan_in"] = len(callers)
    node["fan_out"] = len(callees)
    return {"node": node, "callers": callers, "callees": callees}


# ── Analysis Tools ───────────────────────────────────────────


async def impact_analysis(
    ctx: ChatToolContext,
    node_fqn: str,
    depth: int = 5,
    direction: str = "both",
) -> dict:
    """Compute the blast radius of changing a specific code object."""
    depth = min(depth, 10)

    if direction == "upstream":
        cypher = (
            "MATCH (start {fqn: $fqn, app_name: $app_name})-[:CONTAINS*0..10]->(seed) "
            "WITH collect(DISTINCT seed.fqn) AS seed_fqns "
            f"MATCH (dep {{app_name: $app_name}})"
            f"-[:CALLS|IMPLEMENTS|DEPENDS_ON|INHERITS|INJECTS|CONSUMES|READS*1..{depth}]->(target) "
            "WHERE target.fqn IN seed_fqns AND dep.fqn <> $fqn "
            "WITH DISTINCT dep, 1 AS depth "
            "RETURN dep.fqn AS fqn, dep.name AS name, "
            "  labels(dep)[0] AS type, dep.path AS file, depth "
            "ORDER BY name LIMIT 100"
        )
    else:  # downstream or both
        cypher = (
            f"MATCH path = (start {{fqn: $fqn, app_name: $app_name}})"
            f"-[:CALLS|INJECTS|IMPLEMENTS|PRODUCES|WRITES|READS|CONTAINS|DEPENDS_ON*1..{depth}]->(affected) "
            "WHERE affected.app_name = $app_name AND affected.fqn <> $fqn "
            "WITH affected, min(length(path)) AS depth "
            "RETURN affected.fqn AS fqn, affected.name AS name, "
            "  labels(affected)[0] AS type, affected.path AS file, depth "
            "ORDER BY depth, name LIMIT 100"
        )

    records = await ctx.graph_store.query(
        cypher, {"fqn": node_fqn, "app_name": ctx.app_name}
    )
    by_type = dict(Counter(r["type"] for r in records))
    return {"affected": records, "total": len(records), "by_type": by_type}


async def find_path(ctx: ChatToolContext, from_fqn: str, to_fqn: str) -> dict:
    """Find the shortest connection path between two code objects."""
    records = await ctx.graph_store.query(
        "MATCH path = shortestPath("
        "(a {fqn: $source, app_name: $app_name})"
        "-[:CALLS|IMPLEMENTS|DEPENDS_ON|INJECTS|INHERITS|READS|WRITES|PRODUCES|CONSUMES*..10]-"
        "(b {fqn: $target, app_name: $app_name})) "
        "RETURN [n IN nodes(path) | {fqn: n.fqn, name: n.name, type: labels(n)[0]}] AS nodes, "
        "[r IN relationships(path) | {type: type(r), source: startNode(r).fqn, target: endNode(r).fqn}] AS edges, "
        "length(path) AS path_length",
        {"source": from_fqn, "target": to_fqn, "app_name": ctx.app_name},
    )
    if not records:
        return {"nodes": [], "edges": [], "path_length": 0}
    return records[0]


async def list_transactions(ctx: ChatToolContext) -> list[dict]:
    """List all end-to-end transaction flows in an application."""
    return await ctx.graph_store.query(
        "MATCH (t:Transaction {app_name: $app_name}) "
        "RETURN t.name AS name, t.http_method AS http_method, "
        "t.url_path AS url_path, t.node_count AS node_count, t.depth AS depth",
        {"app_name": ctx.app_name},
    )


async def transaction_graph(ctx: ChatToolContext, transaction_name: str) -> dict:
    """Get the full call graph for a specific transaction."""
    nodes = await ctx.graph_store.query(
        "MATCH (t:Transaction {name: $name, app_name: $app_name})-[:INCLUDES]->(n) "
        "RETURN n.fqn AS fqn, n.name AS name, labels(n)[0] AS type, n.path AS path",
        {"name": transaction_name, "app_name": ctx.app_name},
    )
    edges = await ctx.graph_store.query(
        "MATCH (t:Transaction {name: $name, app_name: $app_name})-[:INCLUDES]->(a) "
        "MATCH (t)-[:INCLUDES]->(b) "
        "MATCH (a)-[r:CALLS]->(b) "
        "RETURN a.fqn AS source, b.fqn AS target, type(r) AS kind",
        {"name": transaction_name, "app_name": ctx.app_name},
    )
    return {"nodes": nodes, "edges": edges}


async def get_source_code(ctx: ChatToolContext, node_fqn: str) -> dict:
    """Get the source code for a specific code object."""
    node = await ctx.graph_store.query_single(
        "MATCH (n {fqn: $fqn, app_name: $app_name}) RETURN n.path AS path, n.line AS line, n.end_line AS end_line",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )
    if not node:
        return {"error": "Node not found"}

    result: dict = {"fqn": node_fqn, "file": node.get("path"), "line": node.get("line")}

    if not ctx.repo_path or not node.get("path"):
        return result  # Metadata only — no repo access

    resolved = Path(ctx.repo_path, node["path"]).resolve()
    repo_resolved = Path(ctx.repo_path).resolve()
    if not str(resolved).startswith(str(repo_resolved)):
        return {**result, "error": "Path traversal not allowed"}

    if not resolved.is_file():
        return {**result, "error": f"File not found: {node['path']}"}

    try:
        text = resolved.read_text(errors="replace")
        lines = text.split("\n")
        start = max((node.get("line") or 1) - 1, 0)
        end = min(node.get("end_line") or len(lines), len(lines))
        # Cap at 200 lines
        if end - start > 200:
            end = start + 200
        selected = lines[start:end]
        numbered = "\n".join(f"{start + i + 1}: {l}" for i, l in enumerate(selected))
        result["code"] = numbered
    except Exception as exc:
        result["error"] = f"Cannot read file: {exc}"

    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_tools.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/ai/__init__.py app/ai/tools.py tests/unit/test_chat_tools.py
git commit -m "feat(5b-m1): add shared AI tool layer with Cypher-backed functions"
```

---

## Task 4: Tool Definitions (Claude API Format)

**Files:**
- Create: `app/ai/tool_definitions.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_chat_tools.py (append to file)

from app.ai.tool_definitions import get_chat_tool_definitions


class TestToolDefinitions:
    def test_all_tools_present(self):
        defs = get_chat_tool_definitions()
        names = {d["name"] for d in defs}
        expected = {
            "list_applications", "application_stats", "get_architecture",
            "search_objects", "object_details", "impact_analysis",
            "find_path", "list_transactions", "transaction_graph",
            "get_source_code",
        }
        assert expected.issubset(names)

    def test_each_has_input_schema(self):
        for tool in get_chat_tool_definitions():
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_each_has_description(self):
        for tool in get_chat_tool_definitions():
            assert "description" in tool
            assert len(tool["description"]) > 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_tools.py::TestToolDefinitions -v`
Expected: FAIL

- [ ] **Step 3: Create tool definitions**

```python
# app/ai/tool_definitions.py
"""Claude API tool schemas for the shared AI tool layer.

These definitions are used by both the chat backend and the MCP server.
They match the Anthropic Messages API format.
"""
from __future__ import annotations


def get_chat_tool_definitions() -> list[dict]:
    """Return tool definitions in Anthropic Messages API format."""
    return [
        {
            "name": "list_applications",
            "description": "List all analyzed applications in CodeLens with their languages and size.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "application_stats",
            "description": "Get size, complexity, and technology metrics for an application. Omit app_name to use the current project.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Application name (optional — defaults to current project)"},
                },
            },
        },
        {
            "name": "get_architecture",
            "description": "Get application architecture showing modules/classes and their dependencies.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["module", "class"],
                        "description": "Level of detail (default: module)",
                    },
                },
            },
        },
        {
            "name": "search_objects",
            "description": "Search for code objects (classes, functions, tables, endpoints) by name.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (matches name or FQN)"},
                    "type_filter": {"type": "string", "description": "Optional filter: Class, Function, Interface, Table, APIEndpoint"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "object_details",
            "description": "Get detailed info about a specific code object including its callers, callees, and metrics.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_fqn": {"type": "string", "description": "Fully qualified name of the node"},
                },
                "required": ["node_fqn"],
            },
        },
        {
            "name": "impact_analysis",
            "description": "Compute the blast radius of changing a specific code object. Returns all affected nodes grouped by type and depth.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_fqn": {"type": "string", "description": "Fully qualified name of the node to analyze"},
                    "depth": {"type": "integer", "description": "Max traversal depth (default 5, max 10)"},
                    "direction": {
                        "type": "string",
                        "enum": ["downstream", "upstream", "both"],
                        "description": "Direction of impact (default: both)",
                    },
                },
                "required": ["node_fqn"],
            },
        },
        {
            "name": "find_path",
            "description": "Find the shortest connection path between two code objects in the architecture graph.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "from_fqn": {"type": "string", "description": "FQN of the source node"},
                    "to_fqn": {"type": "string", "description": "FQN of the target node"},
                },
                "required": ["from_fqn", "to_fqn"],
            },
        },
        {
            "name": "list_transactions",
            "description": "List all end-to-end transaction flows (API requests) in the application.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "transaction_graph",
            "description": "Get the full call graph for a specific transaction flow.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "transaction_name": {"type": "string", "description": "Name of the transaction"},
                },
                "required": ["transaction_name"],
            },
        },
        {
            "name": "get_source_code",
            "description": "Get the source code for a specific code object. Returns line-numbered source.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_fqn": {"type": "string", "description": "Fully qualified name of the node"},
                },
                "required": ["node_fqn"],
            },
        },
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_tools.py::TestToolDefinitions -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/ai/tool_definitions.py tests/unit/test_chat_tools.py
git commit -m "feat(5b-m1): add Claude API tool definitions for chat/MCP"
```

---

## Task 5: Chat Service — Agentic Loop with SSE Streaming

**Files:**
- Create: `app/ai/chat.py`
- Test: `tests/unit/test_chat_service.py`

This is the core agentic loop. It calls Claude with tools, streams thinking/tool_use/text events, executes tools, and loops until done.

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_chat_service.py
"""Tests for the agentic chat service.

Mocks the Anthropic client to test the agent loop, SSE event generation,
page context injection, and tool dispatch.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.chat import build_system_prompt, execute_tool_call
from app.ai.tools import ChatToolContext
from app.schemas.chat import PageContext


@pytest.fixture
def ctx() -> ChatToolContext:
    return ChatToolContext(
        graph_store=AsyncMock(),
        app_name="test-app",
        project_id="proj-123",
    )


class TestBuildSystemPrompt:
    def test_without_page_context(self):
        prompt = build_system_prompt(
            app_name="MyApp",
            frameworks=["Spring Boot"],
            languages=["Java"],
            page_context=None,
        )
        assert "MyApp" in prompt
        assert "Spring Boot" in prompt
        assert "Java" in prompt
        assert "currently viewing" not in prompt

    def test_with_page_context(self):
        page_ctx = PageContext(
            page="graph_explorer",
            selected_node_fqn="com.app.OrderService",
            view="architecture",
            level="class",
        )
        prompt = build_system_prompt(
            app_name="MyApp",
            frameworks=["Spring Boot"],
            languages=["Java"],
            page_context=page_ctx,
        )
        assert "OrderService" in prompt
        assert "architecture" in prompt
        assert "class" in prompt

    def test_context_aware_off(self):
        """When include_page_context=False, no page context in prompt."""
        prompt = build_system_prompt(
            app_name="MyApp",
            frameworks=[],
            languages=[],
            page_context=None,
        )
        assert "currently viewing" not in prompt


class TestExecuteToolCall:
    @pytest.mark.asyncio
    async def test_search_objects(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"fqn": "com.app.Order", "name": "Order", "type": "Class", "language": "Java", "path": "Order.java"}
        ]
        result = await execute_tool_call(ctx, "search_objects", {"query": "Order"})
        parsed = json.loads(result)
        assert len(parsed) == 1

    @pytest.mark.asyncio
    async def test_unknown_tool(self, ctx: ChatToolContext):
        result = await execute_tool_call(ctx, "nonexistent_tool", {})
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_impact_analysis(self, ctx: ChatToolContext):
        ctx.graph_store.query.return_value = [
            {"fqn": "com.app.A", "name": "A", "type": "Class", "file": "A.java", "depth": 1},
        ]
        result = await execute_tool_call(ctx, "impact_analysis", {"node_fqn": "com.app.X"})
        parsed = json.loads(result)
        assert parsed["total"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_service.py -v`
Expected: FAIL — `app.ai.chat` not found.

- [ ] **Step 3: Implement the chat service**

```python
# app/ai/chat.py
"""Agentic chat service — runs a Claude Sonnet agent loop with SSE streaming.

The agent has access to architecture graph tools and streams thinking blocks,
tool calls, and responses as SSE events.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator

import structlog
from anthropic import AsyncAnthropicBedrock

from app.ai.tool_definitions import get_chat_tool_definitions
from app.ai.tools import (
    ChatToolContext,
    application_stats,
    find_path,
    get_architecture,
    get_source_code,
    impact_analysis,
    list_applications,
    list_transactions,
    object_details,
    search_objects,
    transaction_graph,
)
from app.config import get_settings
from app.schemas.chat import PageContext

logger = structlog.get_logger(__name__)

# Map tool names to handler functions
_TOOL_HANDLERS = {
    "list_applications": lambda ctx, inp: list_applications(ctx),
    "application_stats": lambda ctx, inp: application_stats(ctx, app_name=inp.get("app_name")),
    "get_architecture": lambda ctx, inp: get_architecture(ctx, level=inp.get("level", "module")),
    "search_objects": lambda ctx, inp: search_objects(ctx, query=inp["query"], type_filter=inp.get("type_filter")),
    "object_details": lambda ctx, inp: object_details(ctx, node_fqn=inp["node_fqn"]),
    "impact_analysis": lambda ctx, inp: impact_analysis(
        ctx, node_fqn=inp["node_fqn"], depth=inp.get("depth", 5), direction=inp.get("direction", "both"),
    ),
    "find_path": lambda ctx, inp: find_path(ctx, from_fqn=inp["from_fqn"], to_fqn=inp["to_fqn"]),
    "list_transactions": lambda ctx, inp: list_transactions(ctx),
    "transaction_graph": lambda ctx, inp: transaction_graph(ctx, transaction_name=inp["transaction_name"]),
    "get_source_code": lambda ctx, inp: get_source_code(ctx, node_fqn=inp["node_fqn"]),
}


def build_system_prompt(
    app_name: str,
    frameworks: list[str],
    languages: list[str],
    page_context: PageContext | None,
) -> str:
    """Build the system prompt with optional page context."""
    parts = [
        f'You are an expert software architect analyzing the application "{app_name}".',
    ]
    if frameworks:
        parts.append(f"The application is built with {', '.join(frameworks)}.")
    if languages:
        parts.append(f"Languages: {', '.join(languages)}.")
    parts.append("You have access to the application's complete architecture graph via the provided tools.")

    if page_context:
        ctx_parts = []
        if page_context.view:
            ctx_parts.append(f"the {page_context.view} view")
        if page_context.level:
            ctx_parts.append(f"at {page_context.level} level")
        if page_context.page:
            ctx_parts.append(f"on the {page_context.page} page")

        location = " ".join(ctx_parts) if ctx_parts else page_context.page
        parts.append(f"\nThe user is currently viewing {location}.")
        if page_context.selected_node_fqn:
            parts.append(f"They have selected the node: {page_context.selected_node_fqn}")
        parts.append("Use this context to make your answers more relevant to what they're looking at.")

    parts.append(
        "\nWhen answering questions:\n"
        "- Use tools to look up real data. Don't guess about the architecture.\n"
        "- Be specific — reference actual class names, method names, and file paths.\n"
        "- Include FQNs when mentioning code objects so the UI can link to them.\n"
        "- If a question is ambiguous, search first to find relevant nodes, then get details."
    )
    return "\n".join(parts)


async def execute_tool_call(ctx: ChatToolContext, tool_name: str, tool_input: dict) -> str:
    """Execute a tool call and return a JSON string result."""
    handler = _TOOL_HANDLERS.get(tool_name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        result = await handler(ctx, tool_input)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("chat_tool_failed", tool=tool_name, error=str(exc))
        return json.dumps({"error": f"Tool {tool_name} failed: {str(exc)}"})


def _serialize_content(content) -> list[dict]:
    """Serialize response content blocks to plain dicts for the API."""
    blocks = []
    for block in content:
        if hasattr(block, "type"):
            block_type = block.type if isinstance(block.type, str) else str(block.type)
        elif isinstance(block, dict):
            block_type = block.get("type", "text")
        else:
            blocks.append({"type": "text", "text": str(block)})
            continue

        if block_type == "text":
            text = block.text if hasattr(block, "text") else block.get("text", "")
            blocks.append({"type": "text", "text": text})
        elif block_type == "tool_use":
            blocks.append({
                "type": "tool_use",
                "id": block.id if hasattr(block, "id") else block["id"],
                "name": block.name if hasattr(block, "name") else block["name"],
                "input": block.input if hasattr(block, "input") else block["input"],
            })
        elif block_type == "thinking":
            blocks.append({
                "type": "thinking",
                "thinking": block.thinking if hasattr(block, "thinking") else block.get("thinking", ""),
            })
    return blocks


def _sse_event(event: str, data: dict) -> str:
    """Format an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def chat_stream(
    ctx: ChatToolContext,
    message: str,
    history: list[dict],
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    """Run the agentic chat loop and yield SSE events.

    Yields events:
        thinking  — extended thinking content
        tool_use  — tool name + input
        tool_result — summarized tool result
        text      — streaming text response
        done      — completion with token usage
        error     — error message
    """
    settings = get_settings()
    client = AsyncAnthropicBedrock(aws_region=settings.aws_region)
    tool_defs = get_chat_tool_definitions()

    messages = list(history) + [{"role": "user", "content": message}]
    tool_calls_made = 0
    total_input_tokens = 0
    total_output_tokens = 0
    start = time.monotonic()

    try:
        while True:
            elapsed = time.monotonic() - start
            if elapsed > settings.chat_timeout_seconds:
                yield _sse_event("error", {"message": "Chat timed out"})
                break

            response = await asyncio.wait_for(
                client.messages.create(
                    model=settings.chat_model,
                    max_tokens=settings.chat_max_response_tokens,
                    system=system_prompt,
                    tools=tool_defs,
                    messages=messages,
                    thinking={
                        "type": "enabled",
                        "budget_tokens": settings.chat_thinking_budget_tokens,
                    },
                ),
                timeout=max(settings.chat_timeout_seconds - elapsed, 10),
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Emit events for each content block
            for block in response.content:
                if hasattr(block, "type"):
                    block_type = block.type if isinstance(block.type, str) else str(block.type)
                else:
                    continue

                if block_type == "thinking":
                    thinking_text = block.thinking if hasattr(block, "thinking") else ""
                    if thinking_text:
                        yield _sse_event("thinking", {"content": thinking_text})

                elif block_type == "text" and hasattr(block, "text") and block.text:
                    yield _sse_event("text", {"content": block.text})

                elif block_type == "tool_use":
                    yield _sse_event("tool_use", {
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            # If no tool calls, we're done
            if response.stop_reason != "tool_use":
                break

            # Process tool calls
            messages.append({"role": "assistant", "content": _serialize_content(response.content)})
            tool_results = []

            for block in response.content:
                block_type = block.type if hasattr(block, "type") and isinstance(block.type, str) else ""
                if block_type != "tool_use":
                    continue

                if tool_calls_made >= settings.chat_max_tool_calls:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"error": "Tool call limit reached. Please provide your answer now."}),
                        "is_error": True,
                    })
                    yield _sse_event("tool_result", {
                        "tool_use_id": block.id,
                        "content_summary": "Tool limit reached",
                    })
                    continue

                result = await execute_tool_call(ctx, block.name, block.input)
                tool_calls_made += 1

                # Truncate large results for the SSE event (frontend display)
                summary = result[:500] + "..." if len(result) > 500 else result
                yield _sse_event("tool_result", {
                    "tool_use_id": block.id,
                    "content_summary": summary,
                })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        yield _sse_event("done", {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "tool_calls": tool_calls_made,
            "duration_ms": int((time.monotonic() - start) * 1000),
        })

    except asyncio.TimeoutError:
        yield _sse_event("error", {"message": "Chat request timed out"})
    except asyncio.CancelledError:
        logger.info("chat_stream_cancelled")
        raise
    except Exception as exc:
        logger.error("chat_stream_error", error=str(exc), exc_info=True)
        yield _sse_event("error", {"message": f"Chat error: {str(exc)}"})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/ai/chat.py tests/unit/test_chat_service.py
git commit -m "feat(5b-m1): add agentic chat service with SSE streaming"
```

---

## Task 6: FastAPI Chat Endpoint

**Files:**
- Create: `app/api/chat.py`
- Modify: `app/api/__init__.py`
- Modify: `app/main.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_chat_endpoint.py
"""Tests for the chat API endpoint.

Tests endpoint routing, auth, and SSE response format.
Uses mocked chat service.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_chat_endpoint_returns_sse():
    """POST /api/v1/projects/{id}/chat returns text/event-stream."""
    async def mock_stream(*args, **kwargs):
        yield 'event: text\ndata: {"content": "Hello"}\n\n'
        yield 'event: done\ndata: {"input_tokens": 100, "output_tokens": 50}\n\n'

    with patch("app.api.chat._resolve_project_context") as mock_resolve, \
         patch("app.ai.chat.chat_stream", return_value=mock_stream()):
        mock_resolve.return_value = ("test-app", ["Java"], ["Spring"], None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/projects/proj-123/chat",
                json={"message": "What is OrderService?"},
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_endpoint.py -v`
Expected: FAIL — `app.api.chat` not found.

- [ ] **Step 3: Create the endpoint**

```python
# app/api/chat.py
"""AI chat endpoint — agentic architecture assistant with SSE streaming."""
from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat import build_system_prompt, chat_stream
from app.ai.tools import ChatToolContext
from app.api.dependencies import get_current_user
from app.config import Settings, get_settings
from app.models.db import Project, User
from app.schemas.chat import ChatRequest
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/projects", tags=["chat"])

# Concurrency guard: max 1 active chat stream per user
_user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def _resolve_project_context(
    project_id: str,
    session: AsyncSession,
) -> tuple[str, list[str], list[str], str | None]:
    """Resolve project_id to (app_name, languages, frameworks, repo_path).

    Queries Neo4j for language/framework metadata since the graph nodes
    store this information (populated during analysis Stage 1/7).
    """
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        return project_id, [], [], None

    app_name = project.neo4j_app_name
    repo_path = project.source_path

    # Query Neo4j for language + framework metadata
    store = Neo4jGraphStore(get_driver())
    lang_records = await store.query(
        "MATCH (n {app_name: $name}) WHERE n.language IS NOT NULL "
        "RETURN DISTINCT n.language AS language",
        {"name": app_name},
    )
    languages = [r["language"] for r in lang_records if r.get("language")]

    fw_records = await store.query(
        "MATCH (n {app_name: $name}) WHERE n.kind = 'Component' AND n.name IS NOT NULL "
        "RETURN DISTINCT n.name AS framework",
        {"name": app_name},
    )
    frameworks = [r["framework"] for r in fw_records if r.get("framework")]

    return app_name, languages, frameworks, repo_path


@router.post("/{project_id}/chat")
async def chat(
    project_id: str,
    request: Request,
    body: ChatRequest,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Chat with the AI architecture assistant.

    Returns an SSE stream with thinking blocks, tool calls, and text responses.
    Limited to 1 active stream per user to prevent abuse.
    """
    # Concurrency guard: reject if user already has an active stream
    user_lock = _user_locks[_user.id]
    if user_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You already have an active chat stream. Please wait for it to complete.",
        )

    app_name, languages, frameworks, repo_path = await _resolve_project_context(
        project_id, session,
    )

    # Build page-aware or generic system prompt
    page_context = body.page_context if body.include_page_context else None
    system_prompt = build_system_prompt(
        app_name=app_name,
        frameworks=frameworks,
        languages=languages,
        page_context=page_context,
    )

    ctx = ChatToolContext(
        graph_store=Neo4jGraphStore(get_driver()),
        app_name=app_name,
        project_id=project_id,
        repo_path=repo_path,
    )

    async def event_generator():
        async with user_lock:
            try:
                async for event in chat_stream(
                    ctx=ctx,
                    message=body.message,
                    history=body.history,
                    system_prompt=system_prompt,
                ):
                    if await request.is_disconnected():
                        break
                    yield event
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Register the router**

In `app/api/__init__.py`, add:

```python
from app.api.chat import router as chat_router
```

And add `"chat_router"` to the `__all__` list.

In `app/main.py`, add to the imports:

```python
from app.api import chat_router
```

And add to the router registration section:

```python
application.include_router(chat_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_endpoint.py -v`
Expected: PASS

- [ ] **Step 6: Run all tests to verify nothing broke**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v --tb=short`
Expected: All existing tests still pass.

- [ ] **Step 7: Commit**

```bash
cd cast-clone-backend && git add app/api/chat.py app/api/__init__.py app/main.py tests/unit/test_chat_endpoint.py
git commit -m "feat(5b-m1): add chat SSE endpoint with JWT auth and page context"
```

---

## Task 7: Integration Smoke Test

**Files:**
- No new files — manual verification

- [ ] **Step 1: Run linting**

Run: `cd cast-clone-backend && uv run ruff check app/ai/ app/api/chat.py app/schemas/chat.py`
Expected: No errors.

- [ ] **Step 2: Run type checking**

Run: `cd cast-clone-backend && uv run mypy app/ai/ app/api/chat.py app/schemas/chat.py --ignore-missing-imports`
Expected: No errors (or only pre-existing ones).

- [ ] **Step 3: Run full unit test suite**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v --tb=short`
Expected: All tests pass.

- [ ] **Step 4: Verify SSE format with curl (requires running services)**

If services are running:

```bash
curl -N -X POST http://localhost:8000/api/v1/projects/test/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What applications are analyzed?"}'
```

Expected: SSE stream with `event: thinking`, `event: tool_use`, `event: text`, `event: done` events.

- [ ] **Step 5: Final commit with all files verified**

```bash
cd cast-clone-backend && git status
# Verify only expected files, then add them:
git add app/ai/ app/api/chat.py app/schemas/chat.py app/config.py app/api/__init__.py app/main.py tests/unit/test_chat_*.py tests/unit/test_config.py
git commit -m "feat(5b-m1): complete shared tool layer + agentic chat backend

Implements Phase 5b Milestone 1:
- Shared AI tool layer (app/ai/tools.py) with 10 Cypher-backed functions
- Tool definitions in Anthropic API format (app/ai/tool_definitions.py)
- Agentic chat service with extended thinking + SSE streaming (app/ai/chat.py)
- FastAPI endpoint POST /api/v1/projects/{id}/chat with JWT auth
- Page context awareness toggle (context-aware vs generic mode)
- Chat request schemas with history trimming (app/schemas/chat.py)
- Full unit test coverage for tools, schemas, service, and endpoint"
```
