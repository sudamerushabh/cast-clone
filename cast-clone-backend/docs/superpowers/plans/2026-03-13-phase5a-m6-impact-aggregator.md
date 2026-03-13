# Phase 5a M6 — Impact Aggregator

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute per-node impact (reusing Phase 3 Cypher queries), detect cross-tech impacts, find affected transactions, and aggregate results across all changed nodes in a PR.

**Architecture:** A single `impact_aggregator.py` module that takes a list of `ChangedNode` objects, runs upstream/downstream impact queries per node, then deduplicates and aggregates into an `AggregatedImpact`. Reuses the same Cypher patterns from `analysis_views.py` but runs them programmatically rather than via API endpoints. Also queries for fan-in and hub status to enrich `ChangedNode` objects for risk scoring.

**Tech Stack:** Neo4j async queries via `GraphStore`.

**Depends On:** M1 (data models), M4 (diff mapper provides `ChangedNode` list).

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── pr_analysis/
│       └── impact_aggregator.py     # CREATE
└── tests/
    └── unit/
        └── test_impact_aggregator.py # CREATE
```

---

### Task 1: Impact Aggregator

**Files:**
- Create: `app/pr_analysis/impact_aggregator.py`
- Test: `tests/unit/test_impact_aggregator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_impact_aggregator.py
"""Tests for PR impact aggregation."""
import pytest
from unittest.mock import AsyncMock

from app.pr_analysis.impact_aggregator import ImpactAggregator
from app.pr_analysis.models import AffectedNode, ChangedNode, CrossTechImpact


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.query = AsyncMock(return_value=[])
    return store


def _make_node(fqn: str = "com.app.Svc.method") -> ChangedNode:
    return ChangedNode(
        fqn=fqn, name="method", type="Function",
        path="Svc.java", line=1, end_line=10,
        language="java", change_type="modified",
    )


class TestImpactAggregatorEmpty:
    @pytest.mark.asyncio
    async def test_empty_nodes_returns_empty_impact(self, mock_store):
        agg = ImpactAggregator(mock_store, app_name="test")
        impact = await agg.compute_aggregated_impact([])
        assert impact.total_blast_radius == 0
        assert impact.changed_nodes == []


class TestImpactAggregatorDownstream:
    @pytest.mark.asyncio
    async def test_single_node_downstream(self, mock_store):
        """Single changed node with 2 downstream affected nodes."""
        mock_store.query.side_effect = [
            # fan-in query
            [{"fqn": "com.app.Svc.method", "fan_in": 5, "pagerank": 0.02}],
            # downstream query
            [
                {"fqn": "com.app.Controller.handle", "name": "handle", "type": "Function", "file": "Controller.java", "depth": 1},
                {"fqn": "com.app.Repo.save", "name": "save", "type": "Function", "file": "Repo.java", "depth": 2},
            ],
            # upstream query
            [],
            # cross-tech: API endpoints
            [{"method": "POST", "path": "/api/orders", "handler_fqn": "com.app.Controller.handle"}],
            # cross-tech: message topics
            [],
            # cross-tech: database tables
            [{"table_name": "orders", "access_type": "WRITES"}],
            # transactions
            [{"transaction_name": "POST /api/orders", "method": "POST", "url": "/api/orders", "size": 5}],
        ]

        agg = ImpactAggregator(mock_store, app_name="test")
        node = _make_node()
        impact = await agg.compute_aggregated_impact([node])

        assert impact.total_blast_radius == 2
        assert len(impact.downstream_affected) == 2
        assert impact.changed_nodes[0].fan_in == 5
        assert len(impact.cross_tech_impacts) == 2  # API + DB
        assert len(impact.transactions_affected) == 1


class TestImpactAggregatorDedup:
    @pytest.mark.asyncio
    async def test_deduplicates_across_nodes(self, mock_store):
        """Two changed nodes that share a downstream node — dedup."""
        mock_store.query.side_effect = [
            # fan-in for node1
            [{"fqn": "a.method1", "fan_in": 2, "pagerank": 0.01}],
            # downstream for node1
            [{"fqn": "shared.dep", "name": "dep", "type": "Function", "file": "Dep.java", "depth": 1}],
            # upstream for node1
            [],
            # cross-tech for node1 (3 queries)
            [], [], [],
            # transactions for node1
            [],
            # fan-in for node2
            [{"fqn": "a.method2", "fan_in": 3, "pagerank": 0.01}],
            # downstream for node2
            [
                {"fqn": "shared.dep", "name": "dep", "type": "Function", "file": "Dep.java", "depth": 1},
                {"fqn": "unique.dep", "name": "dep2", "type": "Function", "file": "Dep2.java", "depth": 2},
            ],
            # upstream for node2
            [],
            # cross-tech for node2 (3 queries)
            [], [], [],
            # transactions for node2
            [],
        ]

        agg = ImpactAggregator(mock_store, app_name="test")
        node1 = _make_node("a.method1")
        node2 = _make_node("a.method2")
        impact = await agg.compute_aggregated_impact([node1, node2])

        # shared.dep appears only once, with min depth
        assert impact.total_blast_radius == 2
        fqns = {n.fqn for n in impact.downstream_affected}
        assert fqns == {"shared.dep", "unique.dep"}


class TestImpactAggregatorByType:
    @pytest.mark.asyncio
    async def test_by_type_counts(self, mock_store):
        mock_store.query.side_effect = [
            [{"fqn": "a.m", "fan_in": 0, "pagerank": 0.0}],
            [
                {"fqn": "b.Class1", "name": "Class1", "type": "Class", "file": "C.java", "depth": 1},
                {"fqn": "b.func1", "name": "func1", "type": "Function", "file": "F.java", "depth": 1},
                {"fqn": "b.func2", "name": "func2", "type": "Function", "file": "F.java", "depth": 2},
            ],
            [], [], [], [], [],
        ]

        agg = ImpactAggregator(mock_store, app_name="test")
        impact = await agg.compute_aggregated_impact([_make_node()])
        assert impact.by_type == {"Class": 1, "Function": 2}
        assert impact.by_depth == {1: 2, 2: 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_impact_aggregator.py -v`
Expected: FAIL

- [ ] **Step 3: Implement impact aggregator**

```python
# app/pr_analysis/impact_aggregator.py
"""Aggregate per-node impact across all changed nodes in a PR."""
from __future__ import annotations

from collections import Counter

import structlog

from app.pr_analysis.models import (
    AffectedNode,
    AggregatedImpact,
    ChangedNode,
    CrossTechImpact,
)
from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)

# Max traversal depth for impact queries
_MAX_DEPTH = 5


class ImpactAggregator:
    """Compute and aggregate impact for all changed nodes in a PR."""

    def __init__(self, store: GraphStore, app_name: str) -> None:
        self._store = store
        self._app_name = app_name

    async def compute_aggregated_impact(
        self, changed_nodes: list[ChangedNode]
    ) -> AggregatedImpact:
        """Run impact analysis per node, then merge and deduplicate."""
        if not changed_nodes:
            return AggregatedImpact(
                changed_nodes=[],
                downstream_affected=[],
                upstream_dependents=[],
                total_blast_radius=0,
                by_type={},
                by_depth={},
                by_layer={},
                by_module={},
                cross_tech_impacts=[],
                transactions_affected=[],
            )

        all_downstream: dict[str, AffectedNode] = {}
        all_upstream: dict[str, AffectedNode] = {}
        all_cross_tech: list[CrossTechImpact] = []
        all_transactions: set[str] = set()

        changed_fqns = {n.fqn for n in changed_nodes}

        for node in changed_nodes:
            # Enrich with fan-in and hub status
            await self._enrich_node(node)

            # Downstream impact
            downstream = await self._query_downstream(node.fqn)
            for d in downstream:
                if d.fqn not in changed_fqns:
                    if d.fqn not in all_downstream or d.depth < all_downstream[d.fqn].depth:
                        all_downstream[d.fqn] = d

            # Upstream impact
            upstream = await self._query_upstream(node.fqn)
            for u in upstream:
                if u.fqn not in changed_fqns:
                    if u.fqn not in all_upstream or u.depth < all_upstream[u.fqn].depth:
                        all_upstream[u.fqn] = u

            # Cross-tech impacts
            cross_tech = await self._query_cross_tech(node.fqn)
            all_cross_tech.extend(cross_tech)

            # Transactions
            txns = await self._query_transactions(node.fqn)
            all_transactions.update(txns)

        # Deduplicate cross-tech by (kind, name)
        seen_ct: set[tuple[str, str]] = set()
        deduped_ct: list[CrossTechImpact] = []
        for ct in all_cross_tech:
            key = (ct.kind, ct.name)
            if key not in seen_ct:
                seen_ct.add(key)
                deduped_ct.append(ct)

        # Compute aggregated stats — deduplicate across downstream/upstream
        all_unique: dict[str, AffectedNode] = {}
        for fqn, node in all_downstream.items():
            all_unique[fqn] = node
        for fqn, node in all_upstream.items():
            if fqn not in all_unique:
                all_unique[fqn] = node

        by_type = dict(Counter(a.type for a in all_unique.values()))
        by_depth = dict(Counter(a.depth for a in all_unique.values()))

        return AggregatedImpact(
            changed_nodes=changed_nodes,
            downstream_affected=sorted(all_downstream.values(), key=lambda a: (a.depth, a.name)),
            upstream_dependents=sorted(all_upstream.values(), key=lambda a: (a.depth, a.name)),
            total_blast_radius=len(all_unique),
            by_type=by_type,
            by_depth=by_depth,
            by_layer={},  # Populated if layer info available on nodes
            by_module={},  # Populated if module info available on nodes
            cross_tech_impacts=deduped_ct,
            transactions_affected=sorted(all_transactions),
        )

    async def _enrich_node(self, node: ChangedNode) -> None:
        """Add fan-in and hub status to a changed node."""
        records = await self._store.query(
            "MATCH (n {fqn: $fqn, app_name: $appName}) "
            "OPTIONAL MATCH (caller)-[:CALLS]->(n) "
            "WITH n, count(DISTINCT caller) AS fan_in "
            "RETURN n.fqn AS fqn, fan_in, "
            "  COALESCE(n.pagerank, 0.0) AS pagerank",
            {"fqn": node.fqn, "appName": self._app_name},
        )
        if records:
            node.fan_in = records[0].get("fan_in", 0)
            node.is_hub = records[0].get("pagerank", 0) > 0.05

    async def _query_downstream(self, fqn: str) -> list[AffectedNode]:
        records = await self._store.query(
            f"MATCH path = (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CALLS|INJECTS|IMPLEMENTS|PRODUCES|WRITES|READS|CONTAINS|DEPENDS_ON*1..{_MAX_DEPTH}]->(affected) "
            "WHERE affected.app_name = $appName AND affected.fqn <> $fqn "
            "WITH affected, min(length(path)) AS depth "
            "RETURN affected.fqn AS fqn, affected.name AS name, "
            "  labels(affected)[0] AS type, affected.path AS file, depth "
            "ORDER BY depth, name",
            {"fqn": fqn, "appName": self._app_name},
        )
        return [AffectedNode(**r) for r in records]

    async def _query_upstream(self, fqn: str) -> list[AffectedNode]:
        records = await self._store.query(
            "MATCH (start {fqn: $fqn, app_name: $appName})-[:CONTAINS*0..10]->(seed) "
            "WITH collect(DISTINCT seed.fqn) AS seed_fqns "
            f"MATCH (dep {{app_name: $appName}})"
            f"-[:CALLS|IMPLEMENTS|DEPENDS_ON|INHERITS|INJECTS|CONSUMES|READS|INCLUDES*1..{_MAX_DEPTH}]->(target) "
            "WHERE target.fqn IN seed_fqns "
            "AND dep.fqn <> $fqn "
            "AND NOT dep.fqn STARTS WITH $fqnPrefix "
            "WITH DISTINCT dep, 1 AS depth "
            "RETURN dep.fqn AS fqn, dep.name AS name, "
            "  labels(dep)[0] AS type, dep.path AS file, depth "
            "ORDER BY name",
            {"fqn": fqn, "appName": self._app_name, "fqnPrefix": fqn + "."},
        )
        return [AffectedNode(**r) for r in records]

    async def _query_cross_tech(self, fqn: str) -> list[CrossTechImpact]:
        impacts: list[CrossTechImpact] = []

        # API endpoints
        eps = await self._store.query(
            f"MATCH (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CALLS|INJECTS*0..{_MAX_DEPTH}]->(fn:Function)"
            "-[:HANDLES]->(ep:APIEndpoint) "
            "RETURN ep.method AS method, ep.path AS path, fn.fqn AS handler_fqn",
            {"fqn": fqn, "appName": self._app_name},
        )
        for ep in eps:
            impacts.append(CrossTechImpact(
                kind="api_endpoint",
                name=f"{ep['method']} {ep['path']}",
                detail=f"via {ep['handler_fqn']}",
            ))

        # Message topics
        mts = await self._store.query(
            f"MATCH path = (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CALLS*0..{_MAX_DEPTH}]->(fn:Function)"
            "-[:PRODUCES|CONSUMES]->(mt:MessageTopic) "
            "RETURN mt.name AS topic, type(last(relationships(path))) AS direction",
            {"fqn": fqn, "appName": self._app_name},
        )
        for mt in mts:
            impacts.append(CrossTechImpact(
                kind="message_topic",
                name=mt["topic"],
                detail=mt["direction"],
            ))

        # Database tables
        tables = await self._store.query(
            f"MATCH path = (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CALLS*0..{_MAX_DEPTH}]->(fn:Function)"
            "-[:READS|WRITES]->(t:Table) "
            "RETURN t.name AS table_name, type(last(relationships(path))) AS access_type",
            {"fqn": fqn, "appName": self._app_name},
        )
        for t in tables:
            impacts.append(CrossTechImpact(
                kind="database_table",
                name=t["table_name"],
                detail=t["access_type"],
            ))

        return impacts

    async def _query_transactions(self, fqn: str) -> list[str]:
        records = await self._store.query(
            "MATCH (t:Transaction {app_name: $appName})-[:INCLUDES]->(fn {fqn: $fqn}) "
            "RETURN DISTINCT t.name AS transaction_name",
            {"fqn": fqn, "appName": self._app_name},
        )
        return [r["transaction_name"] for r in records]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_impact_aggregator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/impact_aggregator.py tests/unit/test_impact_aggregator.py
git commit -m "feat(phase5a): implement per-node impact computation and aggregation"
```

---

## Success Criteria

- [ ] Empty changed nodes returns empty `AggregatedImpact`
- [ ] Single node computes downstream, upstream, cross-tech, and transaction impacts
- [ ] Multiple nodes are deduplicated (shared affected nodes counted once, min depth kept)
- [ ] Changed nodes are enriched with fan-in and hub status for risk scoring
- [ ] `by_type` and `by_depth` counts are correct
- [ ] Cross-tech impacts deduplicated by (kind, name)
- [ ] All tests pass: `uv run pytest tests/unit/test_impact_aggregator.py -v`
