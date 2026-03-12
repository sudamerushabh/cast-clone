# tests/unit/test_graph_models.py
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph


class TestGraphNode:
    def test_create_class_node(self):
        node = GraphNode(
            fqn="com.example.UserService",
            name="UserService",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/example/UserService.java",
            line=10,
            end_line=50,
        )
        assert node.fqn == "com.example.UserService"
        assert node.kind == NodeKind.CLASS
        assert node.properties == {}

    def test_node_with_properties(self):
        node = GraphNode(
            fqn="com.example.UserService",
            name="UserService",
            kind=NodeKind.CLASS,
            properties={"is_abstract": True, "annotations": ["Service"]},
        )
        assert node.properties["is_abstract"] is True

    def test_node_label_returns_kind_value(self):
        node = GraphNode(fqn="x", name="x", kind=NodeKind.CLASS)
        assert node.label == "Class"

    def test_node_label_api_endpoint(self):
        node = GraphNode(fqn="x", name="x", kind=NodeKind.API_ENDPOINT)
        assert node.label == "APIEndpoint"


class TestGraphEdge:
    def test_create_calls_edge(self):
        edge = GraphEdge(
            source_fqn="com.example.A.method1",
            target_fqn="com.example.B.method2",
            kind=EdgeKind.CALLS,
        )
        assert edge.confidence == Confidence.HIGH
        assert edge.evidence == "tree-sitter"

    def test_edge_with_low_confidence(self):
        edge = GraphEdge(
            source_fqn="a",
            target_fqn="b",
            kind=EdgeKind.CALLS,
            confidence=Confidence.LOW,
            evidence="heuristic",
        )
        assert edge.confidence == Confidence.LOW


class TestSymbolGraph:
    def test_empty_graph(self):
        g = SymbolGraph()
        assert len(g.nodes) == 0
        assert len(g.edges) == 0

    def test_add_and_get_node(self):
        g = SymbolGraph()
        node = GraphNode(fqn="a.B", name="B", kind=NodeKind.CLASS)
        g.add_node(node)
        assert g.get_node("a.B") is node
        assert g.get_node("nonexistent") is None

    def test_add_duplicate_node_overwrites(self):
        g = SymbolGraph()
        n1 = GraphNode(fqn="a.B", name="B", kind=NodeKind.CLASS, line=1)
        n2 = GraphNode(fqn="a.B", name="B", kind=NodeKind.CLASS, line=99)
        g.add_node(n1)
        g.add_node(n2)
        assert g.get_node("a.B").line == 99
        assert len(g.nodes) == 1

    def test_add_edge(self):
        g = SymbolGraph()
        edge = GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS)
        g.add_edge(edge)
        assert len(g.edges) == 1

    def test_get_edges_from(self):
        g = SymbolGraph()
        g.add_edge(GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="a", target_fqn="c", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="x", target_fqn="y", kind=EdgeKind.CALLS))
        assert len(g.get_edges_from("a")) == 2
        assert len(g.get_edges_from("x")) == 1
        assert len(g.get_edges_from("z")) == 0

    def test_get_edges_to(self):
        g = SymbolGraph()
        g.add_edge(GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="c", target_fqn="b", kind=EdgeKind.CALLS))
        assert len(g.get_edges_to("b")) == 2

    def test_merge_graphs(self):
        g1 = SymbolGraph()
        g1.add_node(GraphNode(fqn="a", name="a", kind=NodeKind.CLASS))
        g1.add_edge(GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS))

        g2 = SymbolGraph()
        g2.add_node(GraphNode(fqn="b", name="b", kind=NodeKind.CLASS))
        g2.add_edge(GraphEdge(source_fqn="b", target_fqn="c", kind=EdgeKind.CALLS))

        g1.merge(g2)
        assert len(g1.nodes) == 2
        assert len(g1.edges) == 2

    def test_node_count_and_edge_count(self):
        g = SymbolGraph()
        g.add_node(GraphNode(fqn="a", name="a", kind=NodeKind.CLASS))
        g.add_node(GraphNode(fqn="b", name="b", kind=NodeKind.CLASS))
        g.add_edge(GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS))
        assert g.node_count == 2
        assert g.edge_count == 1
