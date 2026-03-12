# M7c: Neo4j Batch Writer (Stage 8) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Stage 8 of the analysis pipeline — the Neo4j batch writer that takes the in-memory `SymbolGraph` from `AnalysisContext` and persists it to Neo4j. This is a **CRITICAL** stage: failure is fatal and must propagate to the orchestrator.

**Architecture:** A single async function `write_to_neo4j()` that accepts an `AnalysisContext` and a `GraphStore` (dependency-injected for testability). It clears stale data, ensures indexes, writes the Application root node, writes all graph nodes, writes all graph edges, and creates the full-text search index. All batching logic lives inside `Neo4jGraphStore` (batch size 5000) — the writer just calls the store methods.

**Tech Stack:** Python 3.12, FastAPI, neo4j async driver, structlog, pytest + pytest-asyncio

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       └── writer.py                # CREATE — write_to_neo4j() stage function
└── tests/
    └── unit/
        └── test_writer.py           # CREATE — 8 tests with mocked GraphStore
```

---

## Task 1: Writer Tests

**Files:**
- Create: `tests/unit/test_writer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_writer.py
"""Tests for Stage 8: Neo4j Batch Writer.

Neo4j is an external service, so all tests mock the GraphStore interface.
The writer is a CRITICAL stage — errors must propagate, not be swallowed.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.writer import write_to_neo4j, FULLTEXT_INDEX_CYPHER


def _make_store() -> AsyncMock:
    """Create a mock GraphStore with all async methods."""
    store = AsyncMock()
    store.clear_project = AsyncMock(return_value=None)
    store.ensure_indexes = AsyncMock(return_value=None)
    store.write_nodes_batch = AsyncMock(return_value=0)
    store.write_edges_batch = AsyncMock(return_value=0)
    store.query = AsyncMock(return_value=[])
    return store


def _make_context(
    project_id: str = "test-project",
    nodes: list[GraphNode] | None = None,
    edges: list[GraphEdge] | None = None,
) -> AnalysisContext:
    """Create an AnalysisContext with optional nodes and edges."""
    ctx = AnalysisContext(project_id=project_id)
    if nodes:
        for node in nodes:
            ctx.graph.add_node(node)
    if edges:
        for edge in edges:
            ctx.graph.add_edge(edge)
    return ctx


class TestWriteToNeo4j:
    """Tests for the write_to_neo4j stage function."""

    @pytest.mark.asyncio
    async def test_basic_write_nodes_and_edges(self):
        """Graph with 3 nodes + 2 edges: verify store methods called with correct data."""
        nodes = [
            GraphNode(fqn="com.app.A", name="A", kind=NodeKind.CLASS, language="java"),
            GraphNode(fqn="com.app.B", name="B", kind=NodeKind.CLASS, language="java"),
            GraphNode(fqn="com.app.A.foo", name="foo", kind=NodeKind.FUNCTION, language="java"),
        ]
        edges = [
            GraphEdge(source_fqn="com.app.A.foo", target_fqn="com.app.B", kind=EdgeKind.CALLS),
            GraphEdge(source_fqn="com.app.A", target_fqn="com.app.B", kind=EdgeKind.DEPENDS_ON),
        ]
        ctx = _make_context(nodes=nodes, edges=edges)
        store = _make_store()
        store.write_nodes_batch.return_value = 4  # 3 nodes + 1 Application node
        store.write_edges_batch.return_value = 2

        await write_to_neo4j(ctx, store)

        # Application node is written first, then all graph nodes
        assert store.write_nodes_batch.call_count == 2
        # First call: Application node
        app_call_nodes = store.write_nodes_batch.call_args_list[0][0][0]
        assert len(app_call_nodes) == 1
        assert app_call_nodes[0].kind == NodeKind.APPLICATION
        # Second call: graph nodes
        graph_call_nodes = store.write_nodes_batch.call_args_list[1][0][0]
        assert len(graph_call_nodes) == 3

        # Edges written once
        store.write_edges_batch.assert_called_once()
        written_edges = store.write_edges_batch.call_args[0][0]
        assert len(written_edges) == 2

    @pytest.mark.asyncio
    async def test_clear_before_write(self):
        """Verify clear_project is called before any write operations."""
        ctx = _make_context()
        store = _make_store()
        call_order: list[str] = []

        async def track_clear(*args, **kwargs):
            call_order.append("clear")

        async def track_ensure(*args, **kwargs):
            call_order.append("ensure_indexes")

        async def track_write_nodes(*args, **kwargs):
            call_order.append("write_nodes")
            return 0

        async def track_write_edges(*args, **kwargs):
            call_order.append("write_edges")
            return 0

        async def track_query(*args, **kwargs):
            call_order.append("query")
            return []

        store.clear_project.side_effect = track_clear
        store.ensure_indexes.side_effect = track_ensure
        store.write_nodes_batch.side_effect = track_write_nodes
        store.write_edges_batch.side_effect = track_write_edges
        store.query.side_effect = track_query

        await write_to_neo4j(ctx, store)

        # clear must come before ensure_indexes, which comes before writes
        assert call_order.index("clear") < call_order.index("ensure_indexes")
        assert call_order.index("ensure_indexes") < call_order.index("write_nodes")

    @pytest.mark.asyncio
    async def test_ensure_indexes_called(self):
        """Verify ensure_indexes is called during write."""
        ctx = _make_context()
        store = _make_store()

        await write_to_neo4j(ctx, store)

        store.ensure_indexes.assert_called_once()

    @pytest.mark.asyncio
    async def test_application_node_created(self):
        """Verify Application node is created with project metadata."""
        ctx = _make_context(project_id="my-cool-project")
        store = _make_store()
        store.write_nodes_batch.return_value = 1

        await write_to_neo4j(ctx, store)

        # First write_nodes_batch call should be the Application node
        first_call_nodes = store.write_nodes_batch.call_args_list[0][0][0]
        assert len(first_call_nodes) == 1
        app_node = first_call_nodes[0]
        assert app_node.kind == NodeKind.APPLICATION
        assert app_node.name == "my-cool-project"
        assert app_node.fqn == "my-cool-project"
        # app_name passed as second arg
        app_name_arg = store.write_nodes_batch.call_args_list[0][0][1]
        assert app_name_arg == "my-cool-project"

    @pytest.mark.asyncio
    async def test_empty_graph_still_clears_and_indexes(self):
        """0 nodes/edges: still clears, creates indexes, writes Application node, no errors."""
        ctx = _make_context()
        store = _make_store()
        store.write_nodes_batch.return_value = 1

        await write_to_neo4j(ctx, store)

        store.clear_project.assert_called_once_with("test-project")
        store.ensure_indexes.assert_called_once()
        # Application node is still written
        assert store.write_nodes_batch.call_count >= 1
        # Edges batch should be called with empty list
        store.write_edges_batch.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_fulltext_index_created(self):
        """Verify the full-text search index creation query is executed."""
        ctx = _make_context()
        store = _make_store()

        await write_to_neo4j(ctx, store)

        # store.query should be called with the fulltext index cypher
        store.query.assert_called_once()
        cypher_arg = store.query.call_args[0][0]
        assert "FULLTEXT INDEX" in cypher_arg
        assert "idx_node_search" in cypher_arg
        assert "Class" in cypher_arg
        assert "Function" in cypher_arg

    @pytest.mark.asyncio
    async def test_error_propagation_on_write_nodes(self):
        """If store.write_nodes_batch raises, exception propagates (critical stage)."""
        ctx = _make_context(
            nodes=[GraphNode(fqn="a", name="a", kind=NodeKind.CLASS)],
        )
        store = _make_store()
        store.write_nodes_batch.side_effect = RuntimeError("Neo4j connection lost")

        with pytest.raises(RuntimeError, match="Neo4j connection lost"):
            await write_to_neo4j(ctx, store)

    @pytest.mark.asyncio
    async def test_error_propagation_on_write_edges(self):
        """If store.write_edges_batch raises, exception propagates (critical stage)."""
        ctx = _make_context(
            edges=[GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS)],
        )
        store = _make_store()
        store.write_nodes_batch.return_value = 1
        store.write_edges_batch.side_effect = RuntimeError("Neo4j disk full")

        with pytest.raises(RuntimeError, match="Neo4j disk full"):
            await write_to_neo4j(ctx, store)

    @pytest.mark.asyncio
    async def test_error_propagation_on_clear(self):
        """If store.clear_project raises, exception propagates (critical stage)."""
        ctx = _make_context()
        store = _make_store()
        store.clear_project.side_effect = RuntimeError("Neo4j unavailable")

        with pytest.raises(RuntimeError, match="Neo4j unavailable"):
            await write_to_neo4j(ctx, store)

    @pytest.mark.asyncio
    async def test_nodes_written_before_edges(self):
        """Edges reference nodes by FQN, so nodes must be written first."""
        ctx = _make_context(
            nodes=[
                GraphNode(fqn="a", name="a", kind=NodeKind.CLASS),
                GraphNode(fqn="b", name="b", kind=NodeKind.CLASS),
            ],
            edges=[
                GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS),
            ],
        )
        store = _make_store()
        call_order: list[str] = []

        async def track_write_nodes(*args, **kwargs):
            call_order.append("write_nodes")
            return 0

        async def track_write_edges(*args, **kwargs):
            call_order.append("write_edges")
            return 0

        store.write_nodes_batch.side_effect = track_write_nodes
        store.write_edges_batch.side_effect = track_write_edges

        await write_to_neo4j(ctx, store)

        # All write_nodes calls come before write_edges
        node_indices = [i for i, x in enumerate(call_order) if x == "write_nodes"]
        edge_indices = [i for i, x in enumerate(call_order) if x == "write_edges"]
        assert max(node_indices) < min(edge_indices)

    @pytest.mark.asyncio
    async def test_application_node_includes_graph_metadata(self):
        """Application node properties include node_count and edge_count from the graph."""
        nodes = [
            GraphNode(fqn="com.app.A", name="A", kind=NodeKind.CLASS, language="java"),
            GraphNode(fqn="com.app.B", name="B", kind=NodeKind.CLASS, language="java"),
        ]
        edges = [
            GraphEdge(source_fqn="com.app.A", target_fqn="com.app.B", kind=EdgeKind.DEPENDS_ON),
        ]
        ctx = _make_context(nodes=nodes, edges=edges)
        store = _make_store()
        store.write_nodes_batch.return_value = 1

        await write_to_neo4j(ctx, store)

        app_node = store.write_nodes_batch.call_args_list[0][0][0][0]
        assert app_node.properties.get("total_nodes") == 2
        assert app_node.properties.get("total_edges") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_writer.py -v`
Expected: FAIL (ImportError — `app.stages.writer` does not exist)

---

## Task 2: Writer Implementation

**Files:**
- Create: `app/stages/writer.py`

- [ ] **Step 1: Implement the writer stage**

```python
# app/stages/writer.py
"""Stage 8: Neo4j Batch Writer.

This is a CRITICAL stage — failure here is fatal and must propagate
to the orchestrator. Unlike non-critical stages, this function does NOT
catch exceptions internally.

Writes the in-memory SymbolGraph from AnalysisContext to Neo4j via the
GraphStore abstraction. Steps:
  1. Clear existing data for this project
  2. Ensure indexes exist
  3. Write Application root node
  4. Write all graph nodes in batches
  5. Write all graph edges in batches
  6. Create full-text search index
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.models.enums import NodeKind
from app.models.graph import GraphNode

if TYPE_CHECKING:
    from app.models.context import AnalysisContext
    from app.services.neo4j import GraphStore

logger = logging.getLogger(__name__)

FULLTEXT_INDEX_CYPHER = """
CREATE FULLTEXT INDEX idx_node_search IF NOT EXISTS
FOR (n:Class|Function|Interface|Table|APIEndpoint|Module)
ON EACH [n.name, n.fqn]
""".strip()


def _build_application_node(context: AnalysisContext) -> GraphNode:
    """Build the Application root node from pipeline context.

    The Application node is the top of the containment hierarchy:
      Application -> Module -> Class -> Function
    """
    # Collect language names from manifest if available
    languages: list[str] = []
    frameworks: list[str] = []
    total_files = 0
    total_loc = 0

    if context.manifest is not None:
        languages = context.manifest.language_names
        frameworks = [fw.name for fw in context.manifest.detected_frameworks]
        total_files = context.manifest.total_files
        total_loc = context.manifest.total_loc

    return GraphNode(
        fqn=context.project_id,
        name=context.project_id,
        kind=NodeKind.APPLICATION,
        properties={
            "languages": languages,
            "frameworks": frameworks,
            "total_files": total_files,
            "total_loc": total_loc,
            "total_nodes": context.graph.node_count,
            "total_edges": context.graph.edge_count,
        },
    )


async def write_to_neo4j(
    context: AnalysisContext,
    store: GraphStore,
) -> None:
    """Write the entire SymbolGraph to Neo4j.

    This is a CRITICAL pipeline stage. Any exception raised here will
    propagate to the orchestrator and abort the analysis run.

    Args:
        context: The shared pipeline state containing the graph to persist.
        store: The GraphStore implementation (injected for testability).

    Raises:
        Any exception from the store — this stage does not swallow errors.
    """
    start = time.monotonic()
    project_id = context.project_id

    logger.info(
        "writer.start",
        extra={
            "project_id": project_id,
            "node_count": context.graph.node_count,
            "edge_count": context.graph.edge_count,
        },
    )

    # Step 1: Clear existing data for this project
    logger.info("writer.clear_project", extra={"project_id": project_id})
    await store.clear_project(project_id)

    # Step 2: Ensure indexes exist
    logger.info("writer.ensure_indexes")
    await store.ensure_indexes()

    # Step 3: Write Application root node first
    app_node = _build_application_node(context)
    logger.info("writer.write_application_node", extra={"fqn": app_node.fqn})
    nodes_written = await store.write_nodes_batch([app_node], project_id)

    # Step 4: Write all graph nodes
    all_nodes = list(context.graph.nodes.values())
    if all_nodes:
        logger.info(
            "writer.write_nodes",
            extra={"count": len(all_nodes)},
        )
        nodes_written += await store.write_nodes_batch(all_nodes, project_id)
    else:
        logger.info("writer.write_nodes", extra={"count": 0})

    # Step 5: Write all graph edges (nodes must exist first — edges reference by FQN)
    all_edges = context.graph.edges
    logger.info(
        "writer.write_edges",
        extra={"count": len(all_edges)},
    )
    edges_written = await store.write_edges_batch(all_edges)

    # Step 6: Create full-text search index
    logger.info("writer.create_fulltext_index")
    await store.query(FULLTEXT_INDEX_CYPHER)

    duration = time.monotonic() - start
    logger.info(
        "writer.complete",
        extra={
            "project_id": project_id,
            "nodes_written": nodes_written,
            "edges_written": edges_written,
            "duration_seconds": round(duration, 2),
        },
    )
```

- [ ] **Step 2: Ensure `app/stages/__init__.py` exists**

If the file does not exist, create it as an empty file:

```python
# app/stages/__init__.py
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_writer.py -v`
Expected: PASS (11 tests)

- [ ] **Step 4: Run linting**

Run: `cd cast-clone-backend && uv run ruff check app/stages/writer.py tests/unit/test_writer.py`
Run: `cd cast-clone-backend && uv run ruff format app/stages/writer.py tests/unit/test_writer.py`

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/__init__.py app/stages/writer.py tests/unit/test_writer.py && git commit -m "feat(stages): add Neo4j batch writer (Stage 8) with tests"
```

---

## Design Decisions

### Why inject GraphStore as a parameter?

The writer accepts `store: GraphStore` as a parameter rather than importing a global singleton. This makes tests fast (mock the store, no Neo4j needed) and follows the project convention of explicit dependency passing (`Depends()`).

In the orchestrator (`pipeline.py`), the store is created from the driver:

```python
from app.services.neo4j import get_driver, Neo4jGraphStore

store = Neo4jGraphStore(get_driver())
await write_to_neo4j(context, store)
```

### Why is this a CRITICAL stage?

From `07-ANALYSIS-ORCHESTRATOR.md`: only Stage 1 (discovery) and Stage 8 (writer) are fatal. If Neo4j write fails, the graph cannot be queried — the entire analysis is useless. The writer intentionally does NOT wrap calls in try/except. Exceptions propagate to the orchestrator's top-level handler, which marks the run as `failed`.

### Why write Application node separately?

The Application node is the root of the containment hierarchy (`Application -> Module -> Class -> Function`). It carries project-level metadata (languages, frameworks, LOC totals) and must exist before CONTAINS edges from Application to Module can be created in Stage 9 or later queries. Writing it first (before graph nodes) ensures it is always present.

### Why write nodes before edges?

Edges in Neo4j use `MATCH (from {fqn: e.from_fqn})` to find endpoints. If the target node does not exist yet, the edge is silently dropped. Writing all nodes first guarantees edge endpoints are resolvable.

### Why create full-text index via store.query()?

The full-text index (`CREATE FULLTEXT INDEX ... IF NOT EXISTS`) is a one-time DDL operation that does not fit `ensure_indexes()` (which handles property indexes). Using `store.query()` keeps it explicit and testable. The `IF NOT EXISTS` clause makes it idempotent across re-analyses.

---

## Verification Checklist

After implementation, verify:

1. `cd cast-clone-backend && uv run pytest tests/unit/test_writer.py -v` — all 11 tests pass
2. `cd cast-clone-backend && uv run ruff check app/stages/writer.py` — no lint errors
3. `cd cast-clone-backend && uv run ruff format --check app/stages/writer.py` — already formatted
4. The writer function signature matches what `07-ANALYSIS-ORCHESTRATOR.md` expects: `await write_to_neo4j(context)` — note: the orchestrator will need to also pass the store, which is a minor wiring change in `pipeline.py`
5. No try/except in the writer — errors propagate as required for a CRITICAL stage
