# tests/unit/test_analysis_views_api.py
"""Tests for Phase 3 analysis API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.analysis_views import get_graph_store
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_graph_store():
    mock_store = AsyncMock()
    mock_store.query = AsyncMock(return_value=[])
    mock_store.query_single = AsyncMock(return_value=None)

    async def override_get_graph_store():
        return mock_store

    app.dependency_overrides[get_graph_store] = override_get_graph_store
    yield mock_store
    app.dependency_overrides.clear()


class TestImpactAnalysis:
    def test_downstream_impact_returns_affected_nodes(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {
                "fqn": "com.app.Repo.save", "name": "save",
                "type": "Function", "file": "Repo.java", "depth": 1,
            },
            {
                "fqn": "com.app.users", "name": "users",
                "type": "Table", "file": None, "depth": 2,
            },
        ]
        resp = client.get(
            "/api/v1/analysis/test-project/impact/com.app.Service.create",
            params={"direction": "downstream", "max_depth": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["node"] == "com.app.Service.create"
        assert data["direction"] == "downstream"
        assert data["summary"]["total"] == 2
        assert data["summary"]["by_type"]["Function"] == 1
        assert data["summary"]["by_type"]["Table"] == 1
        assert len(data["affected"]) == 2

    def test_upstream_impact(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {
                "fqn": "com.app.Controller.handle", "name": "handle",
                "type": "Function", "file": "Controller.java", "depth": 1,
            },
        ]
        resp = client.get(
            "/api/v1/analysis/test-project/impact/com.app.Service.create",
            params={"direction": "upstream"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["direction"] == "upstream"
        assert data["summary"]["total"] == 1

    def test_impact_default_direction_is_downstream(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []
        resp = client.get("/api/v1/analysis/test-project/impact/com.app.X")
        assert resp.status_code == 200
        assert resp.json()["direction"] == "downstream"

    def test_impact_max_depth_default_is_5(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []
        resp = client.get("/api/v1/analysis/test-project/impact/com.app.X")
        assert resp.status_code == 200
        assert resp.json()["max_depth"] == 5

    def test_impact_direction_both_deduplicates_by_minimum_depth(
        self, client, mock_graph_store
    ):
        """direction=both runs two queries and deduplicates by minimum depth."""
        # First call (downstream): node A at depth 2, node B at depth 1
        # Second call (upstream): node A at depth 1 (closer upstream), node C at depth 3
        # Expected: A kept at depth 1 (minimum), B at depth 1, C at depth 3
        mock_graph_store.query.side_effect = [
            [
                {
                    "fqn": "com.app.A", "name": "A", "type": "Class",
                    "file": "A.java", "depth": 2,
                },
                {
                    "fqn": "com.app.B", "name": "B", "type": "Function",
                    "file": "B.java", "depth": 1,
                },
            ],
            [
                {
                    "fqn": "com.app.A", "name": "A", "type": "Class",
                    "file": "A.java", "depth": 1,
                },
                {
                    "fqn": "com.app.C", "name": "C", "type": "Class",
                    "file": "C.java", "depth": 3,
                },
            ],
        ]
        resp = client.get(
            "/api/v1/analysis/test-project/impact/com.app.Service.create",
            params={"direction": "both", "max_depth": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["direction"] == "both"
        assert data["max_depth"] == 3
        # 3 unique nodes: A, B, C (A deduplicated, depth kept at 1)
        assert data["summary"]["total"] == 3
        affected_by_fqn = {n["fqn"]: n for n in data["affected"]}
        assert "com.app.A" in affected_by_fqn
        assert "com.app.B" in affected_by_fqn
        assert "com.app.C" in affected_by_fqn
        # A's depth should be 1 (minimum of 2 and 1)
        assert affected_by_fqn["com.app.A"]["depth"] == 1
        # Both store.query calls are made (one for downstream, one for upstream)
        assert mock_graph_store.query.call_count == 2


class TestPathFinder:
    def test_shortest_path_between_nodes(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {
                "nodes": [
                    {"fqn": "com.A", "name": "A", "type": "Class"},
                    {"fqn": "com.B", "name": "B", "type": "Class"},
                    {"fqn": "com.C", "name": "C", "type": "Class"},
                ],
                "edges": [
                    {"type": "CALLS", "source": "com.A", "target": "com.B"},
                    {"type": "DEPENDS_ON", "source": "com.B", "target": "com.C"},
                ],
                "pathLength": 2,
            }
        ]
        resp = client.get(
            "/api/v1/analysis/test-project/path",
            params={"from_fqn": "com.A", "to_fqn": "com.C"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["path_length"] == 2
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2

    def test_path_no_connection(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []
        resp = client.get(
            "/api/v1/analysis/test-project/path",
            params={"from_fqn": "com.A", "to_fqn": "com.Z"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["path_length"] == 0
        assert data["nodes"] == []

    def test_path_requires_both_fqns(self, client, mock_graph_store):
        resp = client.get(
            "/api/v1/analysis/test-project/path",
            params={"from_fqn": "com.A"},
        )
        assert resp.status_code == 422


class TestCommunities:
    def test_list_communities(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {"communityId": 0, "size": 5, "members": ["A", "B", "C", "D", "E"]},
            {"communityId": 1, "size": 3, "members": ["X", "Y", "Z"]},
        ]
        resp = client.get("/api/v1/analysis/test-project/communities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["communities"]) == 2
        assert data["communities"][0]["size"] == 5

    def test_communities_empty(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []
        resp = client.get("/api/v1/analysis/test-project/communities")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestCircularDependencies:
    def test_module_level_cycles(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {"cycle": ["mod.A", "mod.B", "mod.A"], "cycleLength": 2},
        ]
        resp = client.get(
            "/api/v1/analysis/test-project/circular-dependencies",
            params={"level": "module"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["level"] == "module"
        assert data["cycles"][0]["cycle_length"] == 2

    def test_class_level_cycles(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []
        resp = client.get(
            "/api/v1/analysis/test-project/circular-dependencies",
            params={"level": "class"},
        )
        assert resp.status_code == 200
        assert resp.json()["level"] == "class"

    def test_default_level_is_module(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []
        resp = client.get("/api/v1/analysis/test-project/circular-dependencies")
        assert resp.json()["level"] == "module"


class TestDeadCode:
    def test_dead_functions(self, client, mock_graph_store):
        mock_graph_store.query.return_value = [
            {
                "fqn": "com.app.Util.unused", "name": "unused",
                "path": "Util.java", "line": 42, "loc": 15,
            },
        ]
        resp = client.get(
            "/api/v1/analysis/test-project/dead-code",
            params={"type": "function"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["candidates"][0]["fqn"] == "com.app.Util.unused"

    def test_dead_code_default_type_is_function(self, client, mock_graph_store):
        mock_graph_store.query.return_value = []
        resp = client.get("/api/v1/analysis/test-project/dead-code")
        assert resp.json()["type_filter"] == "function"


class TestMetrics:
    def test_metrics_overview(self, client, mock_graph_store):
        mock_graph_store.query_single.return_value = {
            "modules": 5, "classes": 30, "functions": 120, "totalLoc": 5000,
        }
        mock_graph_store.query.side_effect = [
            [{"fqn": "com.Complex", "name": "Complex", "value": 50}],
            [{"fqn": "com.Popular", "name": "Popular", "value": 20}],
            [{"fqn": "com.God", "name": "God", "value": 30}],
            [{"count": 4}],
            [{"count": 2}],
            [{"count": 8}],
        ]
        resp = client.get("/api/v1/analysis/test-project/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overview"]["modules"] == 5
        assert data["overview"]["classes"] == 30
        assert len(data["most_complex"]) == 1
        assert data["community_count"] == 4


class TestNodeDetails:
    def test_node_details_with_callers_callees(self, client, mock_graph_store):
        mock_graph_store.query_single.return_value = {
            "fqn": "com.app.Service", "name": "Service", "type": "Class",
            "language": "java", "path": "Service.java", "line": 10,
            "loc": 100, "complexity": 15, "fan_in": 5, "fan_out": 8,
            "communityId": 2,
        }
        mock_graph_store.query.side_effect = [
            [{"fqn": "com.app.Controller", "name": "Controller", "type": "Class"}],
            [{"fqn": "com.app.Repository", "name": "Repository", "type": "Class"}],
        ]
        resp = client.get("/api/v1/analysis/test-project/node/com.app.Service/details")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fqn"] == "com.app.Service"
        assert data["fan_in"] == 5
        assert data["community_id"] == 2
        assert len(data["callers"]) == 1
        assert len(data["callees"]) == 1

    def test_node_not_found(self, client, mock_graph_store):
        mock_graph_store.query_single.return_value = None
        resp = client.get("/api/v1/analysis/test-project/node/nonexistent/details")
        assert resp.status_code == 404
