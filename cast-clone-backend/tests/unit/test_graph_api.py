# tests/unit/test_graph_api.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestListNodes:
    @pytest.mark.asyncio
    async def test_list_nodes_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "n": {
                    "fqn": "com.example.UserService",
                    "name": "UserService",
                    "kind": "CLASS",
                    "language": "java",
                    "path": "src/UserService.java",
                    "line": 10,
                    "end_line": 50,
                }
            }
        ]
        mock_store.query_single.return_value = {"count": 1}

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get("/api/v1/graphs/proj-1/nodes")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["nodes"][0]["fqn"] == "com.example.UserService"

    @pytest.mark.asyncio
    async def test_list_nodes_filter_by_kind(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []
        mock_store.query_single.return_value = {"count": 0}

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get(
                "/api/v1/graphs/proj-1/nodes?kind=CLASS"
            )

        assert response.status_code == 200
        # Verify the query was called with kind filter
        call_args = mock_store.query.call_args
        assert "CLASS" in str(call_args)

    @pytest.mark.asyncio
    async def test_list_nodes_pagination(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []
        mock_store.query_single.return_value = {"count": 0}

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get(
                "/api/v1/graphs/proj-1/nodes?offset=10&limit=20"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["offset"] == 10
        assert data["limit"] == 20


class TestListEdges:
    @pytest.mark.asyncio
    async def test_list_edges_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "source_fqn": "a.B",
                "target_fqn": "a.C",
                "kind": "CALLS",
                "confidence": "HIGH",
                "evidence": "tree-sitter",
            }
        ]
        mock_store.query_single.return_value = {"count": 1}

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get("/api/v1/graphs/proj-1/edges")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1


class TestGetNode:
    @pytest.mark.asyncio
    async def test_get_node_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query_single.return_value = {
            "n": {
                "fqn": "com.example.UserService",
                "name": "UserService",
                "kind": "CLASS",
                "language": "java",
            }
        }
        mock_store.query.side_effect = [
            # incoming edges
            [{"source_fqn": "a.A", "target_fqn": "com.example.UserService", "kind": "CALLS", "confidence": "HIGH", "evidence": "tree-sitter"}],
            # outgoing edges
            [],
            # neighbors
            [{"n": {"fqn": "a.A", "name": "A", "kind": "CLASS"}}],
        ]

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get(
                "/api/v1/graphs/proj-1/node/com.example.UserService"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["node"]["fqn"] == "com.example.UserService"

    @pytest.mark.asyncio
    async def test_get_node_404(self, app_client):
        mock_store = AsyncMock()
        mock_store.query_single.return_value = None

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get(
                "/api/v1/graphs/proj-1/node/nonexistent"
            )

        assert response.status_code == 404


class TestSearchNodes:
    @pytest.mark.asyncio
    async def test_search_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "fqn": "com.example.UserService",
                "name": "UserService",
                "kind": "CLASS",
                "language": "java",
                "score": 0.95,
            }
        ]

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get(
                "/api/v1/graphs/proj-1/search?q=UserService"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "UserService"
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_search_empty_query_422(self, app_client):
        response = await app_client.get("/api/v1/graphs/proj-1/search?q=")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_search_missing_query_422(self, app_client):
        response = await app_client.get("/api/v1/graphs/proj-1/search")
        assert response.status_code == 422
