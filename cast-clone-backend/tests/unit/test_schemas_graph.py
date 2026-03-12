# tests/unit/test_schemas_graph.py
from app.schemas.graph import (
    GraphNodeResponse,
    GraphEdgeResponse,
    GraphNodeListResponse,
    GraphEdgeListResponse,
    NodeWithNeighborsResponse,
    GraphSearchResponse,
    GraphSearchHit,
)


class TestGraphNodeResponse:
    def test_create(self):
        node = GraphNodeResponse(
            fqn="com.example.UserService",
            name="UserService",
            kind="CLASS",
            language="java",
            path="src/main/java/com/example/UserService.java",
            line=10,
            end_line=50,
            properties={"annotations": ["Service"]},
        )
        assert node.fqn == "com.example.UserService"
        assert node.kind == "CLASS"

    def test_optional_fields(self):
        node = GraphNodeResponse(
            fqn="x",
            name="x",
            kind="CLASS",
        )
        assert node.language is None
        assert node.path is None
        assert node.properties == {}


class TestGraphEdgeResponse:
    def test_create(self):
        edge = GraphEdgeResponse(
            source_fqn="a.B.method1",
            target_fqn="a.C.method2",
            kind="CALLS",
            confidence="HIGH",
            evidence="tree-sitter",
        )
        assert edge.kind == "CALLS"


class TestGraphNodeListResponse:
    def test_pagination(self):
        resp = GraphNodeListResponse(
            nodes=[],
            total=100,
            offset=0,
            limit=50,
        )
        assert resp.total == 100
        assert resp.limit == 50


class TestGraphEdgeListResponse:
    def test_pagination(self):
        resp = GraphEdgeListResponse(
            edges=[],
            total=200,
            offset=0,
            limit=50,
        )
        assert resp.total == 200


class TestNodeWithNeighborsResponse:
    def test_create(self):
        node = GraphNodeResponse(fqn="a", name="a", kind="CLASS")
        resp = NodeWithNeighborsResponse(
            node=node,
            incoming_edges=[],
            outgoing_edges=[],
            neighbors=[],
        )
        assert resp.node.fqn == "a"


class TestGraphSearchResponse:
    def test_create(self):
        hit = GraphSearchHit(
            fqn="com.example.UserService",
            name="UserService",
            kind="CLASS",
            language="java",
            score=0.95,
        )
        resp = GraphSearchResponse(
            query="UserService",
            hits=[hit],
            total=1,
        )
        assert resp.hits[0].score == 0.95
