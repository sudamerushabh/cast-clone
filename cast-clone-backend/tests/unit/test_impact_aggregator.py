"""Tests for ImpactAggregator — Phase 5a M6."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.pr_analysis.impact_aggregator import ImpactAggregator
from app.pr_analysis.models import ChangedNode


def _make_changed_node(fqn: str = "com.example.Foo", name: str = "Foo") -> ChangedNode:
    return ChangedNode(
        fqn=fqn, name=name, type="Class", path="src/Foo.java",
        line=1, end_line=50, language="java", change_type="modified",
    )


@pytest.mark.asyncio
class TestEmptyNodes:
    async def test_empty_changed_nodes_returns_empty_impact(self) -> None:
        mock_store = AsyncMock()
        agg = ImpactAggregator(store=mock_store, app_name="test-app")

        result = await agg.compute_aggregated_impact([])

        assert result.changed_nodes == []
        assert result.downstream_affected == []
        assert result.upstream_dependents == []
        assert result.total_blast_radius == 0
        assert result.by_type == {}
        assert result.by_depth == {}
        assert result.cross_tech_impacts == []
        assert result.transactions_affected == []
        mock_store.query.assert_not_called()


@pytest.mark.asyncio
class TestSingleNodeDownstream:
    async def test_single_node_with_downstream_impact(self) -> None:
        mock_store = AsyncMock()
        node = _make_changed_node()

        # 7 calls per node:
        # 1) enrich
        # 2) downstream
        # 3) upstream
        # 4) cross_tech: API endpoints
        # 5) cross_tech: message topics
        # 6) cross_tech: database tables
        # 7) transactions
        mock_store.query.side_effect = [
            # 1. enrich
            [{"fqn": "com.example.Foo", "fan_in": 5, "pagerank": 0.1}],
            # 2. downstream — 2 affected nodes
            [
                {"fqn": "com.example.Bar", "name": "Bar", "type": "Class", "file": "src/Bar.java", "depth": 1},
                {"fqn": "com.example.Baz", "name": "Baz", "type": "Function", "file": "src/Baz.java", "depth": 2},
            ],
            # 3. upstream — 0
            [],
            # 4. cross_tech: API endpoints — 1
            [{"method": "GET", "path": "/users", "handler_fqn": "com.example.UserController.getUsers"}],
            # 5. cross_tech: message topics — 0
            [],
            # 6. cross_tech: database tables — 1
            [{"table_name": "users", "access_type": "READS"}],
            # 7. transactions — 1
            [{"transaction_name": "user-login-flow"}],
        ]

        agg = ImpactAggregator(store=mock_store, app_name="test-app")
        result = await agg.compute_aggregated_impact([node])

        assert result.total_blast_radius == 2
        assert node.fan_in == 5
        assert node.is_hub is True
        assert len(result.downstream_affected) == 2
        assert len(result.cross_tech_impacts) == 2
        assert result.cross_tech_impacts[0].kind == "api_endpoint"
        assert result.cross_tech_impacts[1].kind == "database_table"
        assert result.transactions_affected == ["user-login-flow"]


@pytest.mark.asyncio
class TestDedupAcrossNodes:
    async def test_shared_downstream_deduped(self) -> None:
        mock_store = AsyncMock()
        node_a = _make_changed_node(fqn="com.example.A", name="A")
        node_b = _make_changed_node(fqn="com.example.B", name="B")

        # 14 calls total (7 per node)
        mock_store.query.side_effect = [
            # --- Node A ---
            # 1. enrich
            [{"fqn": "com.example.A", "fan_in": 2, "pagerank": 0.01}],
            # 2. downstream — shared.dep at depth 2, unique.dep.A at depth 1
            [
                {"fqn": "shared.dep", "name": "SharedDep", "type": "Class", "file": "src/Shared.java", "depth": 2},
                {"fqn": "unique.dep.A", "name": "UniqueA", "type": "Function", "file": "src/A.java", "depth": 1},
            ],
            # 3. upstream
            [],
            # 4. cross_tech: API
            [],
            # 5. cross_tech: MQ
            [],
            # 6. cross_tech: DB
            [],
            # 7. transactions
            [],
            # --- Node B ---
            # 1. enrich
            [{"fqn": "com.example.B", "fan_in": 3, "pagerank": 0.02}],
            # 2. downstream — shared.dep at depth 1 (should replace depth 2)
            [
                {"fqn": "shared.dep", "name": "SharedDep", "type": "Class", "file": "src/Shared.java", "depth": 1},
            ],
            # 3. upstream
            [],
            # 4. cross_tech: API
            [],
            # 5. cross_tech: MQ
            [],
            # 6. cross_tech: DB
            [],
            # 7. transactions
            [],
        ]

        agg = ImpactAggregator(store=mock_store, app_name="test-app")
        result = await agg.compute_aggregated_impact([node_a, node_b])

        # shared.dep appears once with min depth = 1
        downstream_fqns = [d.fqn for d in result.downstream_affected]
        assert downstream_fqns.count("shared.dep") == 1
        shared = next(d for d in result.downstream_affected if d.fqn == "shared.dep")
        assert shared.depth == 1

        # blast_radius = 2 (shared.dep + unique.dep.A)
        assert result.total_blast_radius == 2


@pytest.mark.asyncio
class TestByTypeCounts:
    async def test_by_type_and_by_depth(self) -> None:
        mock_store = AsyncMock()
        node = _make_changed_node()

        # 7 calls
        mock_store.query.side_effect = [
            # 1. enrich
            [{"fqn": "com.example.Foo", "fan_in": 0, "pagerank": 0.0}],
            # 2. downstream — 1 Class + 2 Functions
            [
                {"fqn": "com.example.Bar", "name": "Bar", "type": "Class", "file": "src/Bar.java", "depth": 1},
                {"fqn": "com.example.baz", "name": "baz", "type": "Function", "file": "src/Baz.java", "depth": 1},
                {"fqn": "com.example.qux", "name": "qux", "type": "Function", "file": "src/Qux.java", "depth": 2},
            ],
            # 3. upstream
            [],
            # 4. cross_tech: API
            [],
            # 5. cross_tech: MQ
            [],
            # 6. cross_tech: DB
            [],
            # 7. transactions
            [],
        ]

        agg = ImpactAggregator(store=mock_store, app_name="test-app")
        result = await agg.compute_aggregated_impact([node])

        assert result.by_type == {"Class": 1, "Function": 2}
        assert result.by_depth == {1: 2, 2: 1}
