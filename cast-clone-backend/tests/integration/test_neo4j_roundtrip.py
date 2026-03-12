"""Integration test: write a SymbolGraph to Neo4j and query it back.

Uses testcontainers for a real Neo4j instance.
"""

from __future__ import annotations

import pytest

from app.models.context import AnalysisContext
from app.models.enums import EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.writer import write_to_neo4j


@pytest.mark.integration
class TestNeo4jRoundtrip:
    """Write a graph and verify it's queryable."""

    @pytest.fixture
    def sample_graph(self) -> SymbolGraph:
        """Build a small but realistic graph."""
        graph = SymbolGraph()

        # Module
        graph.add_node(
            GraphNode(
                fqn="org.petclinic",
                name="petclinic",
                kind=NodeKind.MODULE,
                language="java",
            )
        )

        # Class
        graph.add_node(
            GraphNode(
                fqn="org.petclinic.Owner",
                name="Owner",
                kind=NodeKind.CLASS,
                language="java",
                path="src/main/java/org/petclinic/Owner.java",
                line=10,
                end_line=50,
                loc=40,
            )
        )

        # Function
        graph.add_node(
            GraphNode(
                fqn="org.petclinic.Owner.getName",
                name="getName",
                kind=NodeKind.FUNCTION,
                language="java",
                path="src/main/java/org/petclinic/Owner.java",
                line=30,
                end_line=32,
                loc=3,
            )
        )

        # Edges
        graph.add_edge(
            GraphEdge(
                source_fqn="org.petclinic",
                target_fqn="org.petclinic.Owner",
                kind=EdgeKind.CONTAINS,
            )
        )
        graph.add_edge(
            GraphEdge(
                source_fqn="org.petclinic.Owner",
                target_fqn="org.petclinic.Owner.getName",
                kind=EdgeKind.CONTAINS,
            )
        )

        return graph

    @pytest.mark.asyncio
    async def test_write_and_query_nodes(self, graph_store, sample_graph):
        """Write nodes and verify count matches."""
        context = AnalysisContext(project_id="test-roundtrip")
        context.graph = sample_graph

        await write_to_neo4j(context, graph_store)

        # Query back
        result = await graph_store.query(
            "MATCH (n) WHERE n.fqn IS NOT NULL RETURN count(n) AS cnt",
            {},
        )
        assert result[0]["cnt"] == 3  # module + class + function

    @pytest.mark.asyncio
    async def test_write_and_query_edges(self, graph_store, sample_graph):
        """Write edges and verify relationships exist."""
        context = AnalysisContext(project_id="test-roundtrip")
        context.graph = sample_graph

        await write_to_neo4j(context, graph_store)

        result = await graph_store.query(
            "MATCH ()-[r:CONTAINS]->() RETURN count(r) AS cnt",
            {},
        )
        assert result[0]["cnt"] == 2

    @pytest.mark.asyncio
    async def test_write_and_query_by_label(self, graph_store, sample_graph):
        """Verify nodes have correct labels."""
        context = AnalysisContext(project_id="test-roundtrip")
        context.graph = sample_graph

        await write_to_neo4j(context, graph_store)

        classes = await graph_store.query(
            "MATCH (c:Class) RETURN c.fqn AS fqn",
            {},
        )
        assert len(classes) == 1
        assert classes[0]["fqn"] == "org.petclinic.Owner"

    @pytest.mark.asyncio
    async def test_application_node_created(self, graph_store, sample_graph):
        """Verify the Application root node is created."""
        context = AnalysisContext(project_id="test-roundtrip")
        context.graph = sample_graph

        await write_to_neo4j(context, graph_store)

        result = await graph_store.query(
            "MATCH (a:Application) RETURN a.name AS name",
            {},
        )
        assert len(result) == 1
