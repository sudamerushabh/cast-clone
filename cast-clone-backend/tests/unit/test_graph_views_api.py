"""Tests for Phase 2 graph view API endpoints."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestListModules:
    @pytest.mark.asyncio
    async def test_list_modules_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "n": {
                    "fqn": "com.example.user",
                    "name": "user",
                    "kind": "MODULE",
                    "language": "java",
                    "loc": 500,
                    "file_count": 10,
                },
                "class_count": 5,
            }
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/modules"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["modules"][0]["fqn"] == "com.example.user"
        assert data["modules"][0]["name"] == "user"
        assert data["modules"][0]["class_count"] == 5

    @pytest.mark.asyncio
    async def test_list_modules_empty(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/modules"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["modules"] == []


class TestListClasses:
    @pytest.mark.asyncio
    async def test_list_classes_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "n": {
                    "fqn": "com.example.user.UserService",
                    "name": "UserService",
                    "kind": "CLASS",
                    "language": "java",
                    "loc": 120,
                    "complexity": 15,
                }
            }
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/modules/com.example.user/classes"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["parent_fqn"] == "com.example.user"
        assert data["classes"][0]["fqn"] == "com.example.user.UserService"
        assert data["classes"][0]["kind"] == "CLASS"

    @pytest.mark.asyncio
    async def test_list_classes_empty(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/modules/com.example.user/classes"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["classes"] == []
        assert data["parent_fqn"] == "com.example.user"


class TestListMethods:
    @pytest.mark.asyncio
    async def test_list_methods_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "n": {
                    "fqn": "com.example.user.UserService.findById",
                    "name": "findById",
                    "kind": "FUNCTION",
                    "language": "java",
                    "loc": 15,
                    "complexity": 3,
                    "visibility": "public",
                }
            }
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/classes/com.example.user.UserService/methods"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["parent_fqn"] == "com.example.user.UserService"
        assert data["methods"][0]["name"] == "findById"
        assert data["methods"][0]["kind"] == "FUNCTION"

    @pytest.mark.asyncio
    async def test_list_methods_empty(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/classes/com.example.user.UserService/methods"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["methods"] == []


class TestAggregatedEdges:
    @pytest.mark.asyncio
    async def test_module_level_edges(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "source": "com.example.user",
                "target": "com.example.db",
                "weight": 12,
            },
            {
                "source": "com.example.web",
                "target": "com.example.user",
                "weight": 8,
            },
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/edges/aggregated?level=module"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["level"] == "module"
        assert data["edges"][0]["source"] == "com.example.user"
        assert data["edges"][0]["weight"] == 12

    @pytest.mark.asyncio
    async def test_class_level_edges(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "source": "com.example.user.UserService",
                "target": "com.example.user.UserRepo",
                "weight": 5,
            },
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/edges/aggregated?level=class&parent=com.example.user"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["level"] == "class"

    @pytest.mark.asyncio
    async def test_invalid_level_422(self, app_client):
        response = await app_client.get(
            "/api/v1/graph-views/proj-1/edges/aggregated?level=invalid"
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_class_level_without_parent_400(self, app_client):
        with patch(
            "app.api.graph_views.get_graph_store", return_value=AsyncMock()
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/edges/aggregated?level=class"
            )
        assert response.status_code == 400


class TestListTransactions:
    @pytest.mark.asyncio
    async def test_list_transactions_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "n": {
                    "fqn": "txn::GET /api/users",
                    "name": "GET /api/users",
                    "kind": "TRANSACTION",
                    "http_method": "GET",
                    "entry_point": "com.example.UserController.listUsers",
                }
            },
            {
                "n": {
                    "fqn": "txn::POST /api/users",
                    "name": "POST /api/users",
                    "kind": "TRANSACTION",
                    "http_method": "POST",
                    "entry_point": "com.example.UserController.createUser",
                }
            },
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/transactions"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["transactions"][0]["fqn"] == "txn::GET /api/users"
        assert data["transactions"][0]["name"] == "GET /api/users"

    @pytest.mark.asyncio
    async def test_list_transactions_empty(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/transactions"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["transactions"] == []


class TestTransactionDetail:
    @pytest.mark.asyncio
    async def test_transaction_detail_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query_single.return_value = {
            "n": {
                "fqn": "txn::GET /api/users",
                "name": "GET /api/users",
                "kind": "TRANSACTION",
            }
        }
        mock_store.query.side_effect = [
            # Nodes in the transaction
            [
                {
                    "n": {
                        "fqn": "com.example.UserController.listUsers",
                        "name": "listUsers",
                        "kind": "FUNCTION",
                        "language": "java",
                    }
                },
                {
                    "n": {
                        "fqn": "com.example.UserService.findAll",
                        "name": "findAll",
                        "kind": "FUNCTION",
                        "language": "java",
                    }
                },
            ],
            # Edges between the nodes
            [
                {
                    "source_fqn": "com.example.UserController.listUsers",
                    "target_fqn": "com.example.UserService.findAll",
                    "kind": "CALLS",
                    "confidence": "HIGH",
                    "evidence": "tree-sitter",
                }
            ],
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/transactions/txn::GET /api/users"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["fqn"] == "txn::GET /api/users"
        assert data["name"] == "GET /api/users"
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert (
            data["edges"][0]["source_fqn"]
            == "com.example.UserController.listUsers"
        )

    @pytest.mark.asyncio
    async def test_transaction_detail_404(self, app_client):
        mock_store = AsyncMock()
        mock_store.query_single.return_value = None

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/transactions/txn::nonexistent"
            )

        assert response.status_code == 404


class TestCodeViewer:
    @pytest.mark.asyncio
    async def test_code_viewer_200(self, app_client, mock_session):
        """Read a file that exists on disk."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".java", delete=False, dir="/tmp"
        ) as f:
            f.write(
                "package com.example;\n"
                "\n"
                "public class Foo {\n"
                "    public void bar() {\n"
                "        // hello\n"
                "    }\n"
                "}\n"
            )
            temp_path = f.name

        try:
            temp_dir = "/tmp"
            relative_file = os.path.basename(temp_path)

            mock_result = MagicMock()
            mock_project = MagicMock()
            mock_project.source_path = temp_dir
            mock_result.scalar_one_or_none.return_value = mock_project
            mock_session.execute.return_value = mock_result

            response = await app_client.get(
                f"/api/v1/graph-views/proj-1/code?file={relative_file}&line=4&context=2"
            )

            assert response.status_code == 200
            data = response.json()
            assert data["language"] == "java"
            assert "public class Foo" in data["content"]
            assert data["highlight_line"] == 4
            assert data["total_lines"] == 7
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_code_viewer_missing_file_param_422(self, app_client):
        response = await app_client.get("/api/v1/graph-views/proj-1/code")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_code_viewer_project_not_found_404(
        self, app_client, mock_session
    ):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = await app_client.get(
            "/api/v1/graph-views/proj-1/code?file=Foo.java"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_code_viewer_path_traversal_400(
        self, app_client, mock_session
    ):
        """Reject paths that try to escape the source directory."""
        mock_result = MagicMock()
        mock_project = MagicMock()
        mock_project.source_path = "/opt/code/myproject"
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_result

        response = await app_client.get(
            "/api/v1/graph-views/proj-1/code?file=../../etc/passwd"
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_code_viewer_file_not_found_404(
        self, app_client, mock_session
    ):
        mock_result = MagicMock()
        mock_project = MagicMock()
        mock_project.source_path = "/opt/code/myproject"
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_result

        response = await app_client.get(
            "/api/v1/graph-views/proj-1/code?file=nonexistent.java"
        )
        assert response.status_code == 404
