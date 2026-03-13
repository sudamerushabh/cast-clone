# Phase 5a M5 — Risk Scorer + Drift Detector

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement risk classification (High/Medium/Low) and architecture drift detection (new cross-module deps, circular dep involvement).

**Architecture:** Two pure-logic modules: `risk_scorer.py` computes a numeric score from impact data and classifies it; `drift_detector.py` queries Neo4j for module membership and cycle involvement of changed nodes. Both take structured data in and return structured data out — no side effects.

**Tech Stack:** Python dataclasses, Neo4j Cypher (drift detector only).

**Depends On:** M1 (data models — `AggregatedImpact`, `DriftReport`, `ChangedNode`). Can run in parallel with M4.

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── pr_analysis/
│       ├── risk_scorer.py           # CREATE
│       └── drift_detector.py        # CREATE
└── tests/
    └── unit/
        ├── test_risk_scorer.py      # CREATE
        └── test_drift_detector.py   # CREATE
```

---

### Task 1: Risk Scorer

**Files:**
- Create: `app/pr_analysis/risk_scorer.py`
- Test: `tests/unit/test_risk_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_risk_scorer.py
"""Tests for PR risk classification."""
import pytest

from app.pr_analysis.models import (
    AggregatedImpact,
    ChangedNode,
    CrossTechImpact,
)
from app.pr_analysis.risk_scorer import classify_risk


def _make_impact(
    blast_radius: int = 0,
    changed_nodes: list[ChangedNode] | None = None,
    cross_tech_count: int = 0,
    layer_count: int = 1,
) -> AggregatedImpact:
    nodes = changed_nodes or []
    return AggregatedImpact(
        changed_nodes=nodes,
        downstream_affected=[],
        upstream_dependents=[],
        total_blast_radius=blast_radius,
        by_type={},
        by_depth={},
        by_layer={f"Layer{i}": 1 for i in range(layer_count)},
        by_module={},
        cross_tech_impacts=[
            CrossTechImpact(kind="api", name=f"ep{i}", detail="GET /x")
            for i in range(cross_tech_count)
        ],
        transactions_affected=[],
    )


def _make_node(fan_in: int = 0, is_hub: bool = False) -> ChangedNode:
    return ChangedNode(
        fqn="com.app.Svc.method",
        name="method",
        type="Function",
        path="Svc.java",
        line=1,
        end_line=10,
        language="java",
        change_type="modified",
        fan_in=fan_in,
        is_hub=is_hub,
    )


class TestClassifyRisk:
    def test_low_risk_minimal_changes(self):
        impact = _make_impact(blast_radius=2)
        assert classify_risk(impact) == "Low"

    def test_low_risk_small_blast_radius(self):
        impact = _make_impact(blast_radius=4)
        assert classify_risk(impact) == "Low"

    def test_medium_risk_moderate_blast_radius(self):
        impact = _make_impact(blast_radius=10)
        assert classify_risk(impact) == "Medium"

    def test_medium_risk_cross_tech(self):
        impact = _make_impact(blast_radius=6, cross_tech_count=2)
        assert classify_risk(impact) == "Medium"

    def test_high_risk_hub_node(self):
        node = _make_node(is_hub=True)
        impact = _make_impact(blast_radius=10, changed_nodes=[node])
        assert classify_risk(impact) == "High"

    def test_high_risk_large_blast_radius_plus_cross_tech(self):
        impact = _make_impact(blast_radius=55, cross_tech_count=4)
        assert classify_risk(impact) == "High"

    def test_high_risk_many_factors(self):
        node = _make_node(fan_in=20, is_hub=True)
        impact = _make_impact(
            blast_radius=60,
            changed_nodes=[node],
            cross_tech_count=5,
            layer_count=4,
        )
        assert classify_risk(impact) == "High"

    def test_medium_risk_high_fan_in(self):
        node = _make_node(fan_in=10)
        impact = _make_impact(blast_radius=6, changed_nodes=[node])
        assert classify_risk(impact) == "Medium"

    def test_boundary_low_medium(self):
        """Score of exactly 3 should be Medium."""
        # blast_radius 6 = +1, cross_tech 1 = +1, fan_in 6 = +1 → score=3 → Medium
        node = _make_node(fan_in=6)
        impact = _make_impact(blast_radius=6, changed_nodes=[node], cross_tech_count=1)
        assert classify_risk(impact) == "Medium"

    def test_boundary_medium_high(self):
        """Score of exactly 7 should be High."""
        # hub=+3, blast>50=+3, layer>=3=+1 → score=7 → High
        node = _make_node(is_hub=True)
        impact = _make_impact(blast_radius=55, changed_nodes=[node], layer_count=3)
        assert classify_risk(impact) == "High"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_risk_scorer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement risk scorer**

```python
# app/pr_analysis/risk_scorer.py
"""Risk classification for PR impact analysis."""
from __future__ import annotations

from app.pr_analysis.models import AggregatedImpact


def classify_risk(impact: AggregatedImpact) -> str:
    """Classify PR risk as High, Medium, or Low based on impact factors."""
    score = 0

    # Blast radius size
    if impact.total_blast_radius > 50:
        score += 3
    elif impact.total_blast_radius > 20:
        score += 2
    elif impact.total_blast_radius > 5:
        score += 1

    # Hub node changed (top 10% by PageRank)
    if any(n.is_hub for n in impact.changed_nodes):
        score += 3

    # Cross-tech impact
    cross_tech_count = len(impact.cross_tech_impacts)
    if cross_tech_count > 3:
        score += 2
    elif cross_tech_count > 0:
        score += 1

    # Fan-in of changed nodes
    max_fan_in = max((n.fan_in for n in impact.changed_nodes), default=0)
    if max_fan_in > 15:
        score += 2
    elif max_fan_in > 5:
        score += 1

    # Layer span
    if len(impact.by_layer) >= 3:
        score += 1

    # Classify
    if score >= 7:
        return "High"
    elif score >= 3:
        return "Medium"
    else:
        return "Low"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_risk_scorer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/risk_scorer.py tests/unit/test_risk_scorer.py
git commit -m "feat(phase5a): implement PR risk classification scorer"
```

---

### Task 2: Drift Detector

**Files:**
- Create: `app/pr_analysis/drift_detector.py`
- Test: `tests/unit/test_drift_detector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_drift_detector.py
"""Tests for architecture drift detection."""
import pytest
from unittest.mock import AsyncMock

from app.pr_analysis.drift_detector import DriftDetector
from app.pr_analysis.models import ChangedNode


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


class TestDriftDetectorNoModules:
    @pytest.mark.asyncio
    async def test_no_changed_nodes_returns_no_drift(self, mock_store):
        detector = DriftDetector(mock_store, app_name="test")
        report = await detector.detect_drift([])
        assert report.has_drift is False
        assert report.potential_new_module_deps == []
        assert report.circular_deps_affected == []

    @pytest.mark.asyncio
    async def test_no_drift_when_no_modules_found(self, mock_store):
        """If changed nodes don't belong to any module, no drift."""
        mock_store.query.return_value = []
        detector = DriftDetector(mock_store, app_name="test")
        report = await detector.detect_drift([_make_node()])
        assert report.has_drift is False


class TestDriftDetectorNewModuleDeps:
    @pytest.mark.asyncio
    async def test_detects_new_cross_module_dep(self, mock_store):
        """If a changed node now calls into a different module, report it."""
        mock_store.query.side_effect = [
            # module membership query
            [{"module_fqn": "com.app.orders", "module_name": "orders", "changed_nodes_in_module": ["com.app.Svc.method"]}],
            # new cross-module deps query
            [{"from_module": "orders", "to_module": "billing"}],
            # circular deps query
            [],
        ]
        detector = DriftDetector(mock_store, app_name="test")
        report = await detector.detect_drift([_make_node()])
        assert report.has_drift is True
        assert len(report.potential_new_module_deps) == 1
        assert report.potential_new_module_deps[0].from_module == "orders"
        assert report.potential_new_module_deps[0].to_module == "billing"


class TestDriftDetectorCircularDeps:
    @pytest.mark.asyncio
    async def test_detects_circular_deps(self, mock_store):
        """If changed nodes participate in a cycle, report it."""
        mock_store.query.side_effect = [
            # module membership
            [{"module_fqn": "com.app.orders", "module_name": "orders", "changed_nodes_in_module": ["com.app.Svc.method"]}],
            # new cross-module deps
            [],
            # circular deps
            [{"cycle": ["orders", "billing", "orders"]}],
        ]
        detector = DriftDetector(mock_store, app_name="test")
        report = await detector.detect_drift([_make_node()])
        assert report.has_drift is True
        assert len(report.circular_deps_affected) == 1
        assert "orders" in report.circular_deps_affected[0]


class TestDriftDetectorNewFiles:
    @pytest.mark.asyncio
    async def test_new_files_outside_modules(self, mock_store):
        detector = DriftDetector(mock_store, app_name="test")
        report = await detector.detect_drift(
            [],
            new_files=["src/main/java/com/app/random/Orphan.java"],
        )
        assert "src/main/java/com/app/random/Orphan.java" in report.new_files_outside_modules
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_drift_detector.py -v`
Expected: FAIL

- [ ] **Step 3: Implement drift detector**

```python
# app/pr_analysis/drift_detector.py
"""Architecture drift detection for PR analysis."""
from __future__ import annotations

import structlog

from app.pr_analysis.models import ChangedNode, DriftReport, ModuleDependency
from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)


class DriftDetector:
    """Detect architectural drift introduced by a PR."""

    def __init__(self, store: GraphStore, app_name: str) -> None:
        self._store = store
        self._app_name = app_name

    async def detect_drift(
        self,
        changed_nodes: list[ChangedNode],
        new_files: list[str] | None = None,
    ) -> DriftReport:
        """Run drift detection queries and return a report."""
        new_module_deps: list[ModuleDependency] = []
        circular_deps: list[list[str]] = []
        new_files_outside = list(new_files) if new_files else []

        if not changed_nodes:
            return DriftReport(
                potential_new_module_deps=new_module_deps,
                circular_deps_affected=circular_deps,
                new_files_outside_modules=new_files_outside,
            )

        changed_fqns = [n.fqn for n in changed_nodes]

        # 1. Find modules of changed nodes
        module_records = await self._store.query(
            "UNWIND $changedFqns AS fqn "
            "MATCH (m:Module)-[:CONTAINS*1..3]->(n {fqn: fqn, app_name: $appName}) "
            "RETURN DISTINCT m.fqn AS module_fqn, m.name AS module_name, "
            "  collect(fqn) AS changed_nodes_in_module",
            {"changedFqns": changed_fqns, "appName": self._app_name},
        )

        if not module_records:
            return DriftReport(
                potential_new_module_deps=new_module_deps,
                circular_deps_affected=circular_deps,
                new_files_outside_modules=new_files_outside,
            )

        changed_module_fqns = [r["module_fqn"] for r in module_records]

        # 2. Detect new cross-module dependencies from changed nodes
        dep_records = await self._store.query(
            "UNWIND $changedFqns AS fqn "
            "MATCH (n {fqn: fqn, app_name: $appName}) "
            "MATCH (srcMod:Module)-[:CONTAINS*1..3]->(n) "
            "MATCH (n)-[:CALLS|DEPENDS_ON|INJECTS]->(target) "
            "MATCH (tgtMod:Module)-[:CONTAINS*1..3]->(target) "
            "WHERE srcMod.fqn <> tgtMod.fqn "
            "  AND NOT (srcMod)-[:IMPORTS]->(tgtMod) "
            "RETURN DISTINCT srcMod.name AS from_module, tgtMod.name AS to_module",
            {"changedFqns": changed_fqns, "appName": self._app_name},
        )
        for r in dep_records:
            new_module_deps.append(
                ModuleDependency(from_module=r["from_module"], to_module=r["to_module"])
            )

        # 3. Check for circular dependencies involving changed modules
        cycle_records = await self._store.query(
            "UNWIND $moduleFqns AS mFqn "
            "MATCH (m {fqn: mFqn, app_name: $appName}) "
            "MATCH cyclePath = (m)-[:IMPORTS|DEPENDS_ON*2..6]->(m) "
            "RETURN DISTINCT [node IN nodes(cyclePath) | node.name] AS cycle",
            {"moduleFqns": changed_module_fqns, "appName": self._app_name},
        )

        for r in cycle_records:
            circular_deps.append(r["cycle"])

        return DriftReport(
            potential_new_module_deps=new_module_deps,
            circular_deps_affected=circular_deps,
            new_files_outside_modules=new_files_outside,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_drift_detector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/drift_detector.py tests/unit/test_drift_detector.py
git commit -m "feat(phase5a): implement architecture drift detector"
```

---

## Success Criteria

- [ ] `classify_risk()` returns "Low" for small changes, "Medium" for moderate, "High" for large/hub/cross-tech
- [ ] Boundary conditions tested: score=3 → Medium, score=7 → High
- [ ] `DriftDetector` detects circular deps involving changed nodes
- [ ] New files flagged as `new_files_outside_modules`
- [ ] No drift reported when changed nodes don't belong to modules
- [ ] All tests pass: `uv run pytest tests/unit/test_risk_scorer.py tests/unit/test_drift_detector.py -v`
