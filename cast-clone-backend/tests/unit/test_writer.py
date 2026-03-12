"""Tests for Stage 8: Neo4j Batch Writer.

Neo4j is an external service, so all tests mock the GraphStore interface.
The writer is a CRITICAL stage — errors must propagate, not be swallowed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.context import AnalysisContext
from app.models.enums import EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.writer import write_to_neo4j


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
        """Graph with nodes + edges: verify store methods called correctly."""
        nodes = [
            GraphNode(fqn="com.app.A", name="A", kind=NodeKind.CLASS, language="java"),
            GraphNode(fqn="com.app.B", name="B", kind=NodeKind.CLASS, language="java"),
            GraphNode(
                fqn="com.app.A.foo",
                name="foo",
                kind=NodeKind.FUNCTION,
                language="java",
            ),
        ]
        edges = [
            GraphEdge(
                source_fqn="com.app.A.foo",
                target_fqn="com.app.B",
                kind=EdgeKind.CALLS,
            ),
            GraphEdge(
                source_fqn="com.app.A",
                target_fqn="com.app.B",
                kind=EdgeKind.DEPENDS_ON,
            ),
        ]
        ctx = _make_context(nodes=nodes, edges=edges)
        store = _make_store()
        store.write_nodes_batch.return_value = 4  # 3 nodes + 1 Application node

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
        """0 nodes/edges: still clears, indexes, writes App node."""
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
        """Application node properties include node/edge counts."""
        nodes = [
            GraphNode(fqn="com.app.A", name="A", kind=NodeKind.CLASS, language="java"),
            GraphNode(fqn="com.app.B", name="B", kind=NodeKind.CLASS, language="java"),
        ]
        edges = [
            GraphEdge(
                source_fqn="com.app.A",
                target_fqn="com.app.B",
                kind=EdgeKind.DEPENDS_ON,
            ),
        ]
        ctx = _make_context(nodes=nodes, edges=edges)
        store = _make_store()
        store.write_nodes_batch.return_value = 1

        await write_to_neo4j(ctx, store)

        app_node = store.write_nodes_batch.call_args_list[0][0][0][0]
        assert app_node.properties.get("total_nodes") == 2
        assert app_node.properties.get("total_edges") == 1
