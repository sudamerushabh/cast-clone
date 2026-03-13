# Phase 3 M1: GDS Integration + Enricher Upgrade — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Neo4j GDS Louvain community detection as a post-write pipeline stage, replacing the in-memory BFS connected-components approach from Phase 1.

**Architecture:** The current Stage 7 enricher runs community detection in-memory via BFS *before* Neo4j write. GDS Louvain requires data in Neo4j, so we add a new Stage 10 ("GDS Enrichment") that runs *after* Stage 8 (write) and Stage 9 (transactions). The existing BFS community detection in `enricher.py` is removed. The new stage projects an in-memory GDS graph, runs Louvain, writes `communityId` back to Neo4j nodes, then drops the projection.

**Tech Stack:** Python 3.12, `graphdatascience` (GDS Python client), Neo4j 5 + GDS plugin, pytest + pytest-asyncio

**Dependencies:** Phase 1 M7b (enricher), Phase 1 M7c (writer), Phase 1 M9 (pipeline wiring)

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── stages/
│   │   ├── enricher.py              # MODIFY — remove BFS community detection (Step 5)
│   │   └── gds_enricher.py          # CREATE — Stage 10: GDS Louvain community detection
│   ├── orchestrator/
│   │   └── pipeline.py              # MODIFY — add Stage 10
│   └── services/
│       └── neo4j.py                 # READ ONLY — uses existing get_driver()
├── tests/
│   └── unit/
│       ├── test_enricher.py         # MODIFY — remove BFS community tests
│       └── test_gds_enricher.py     # CREATE — tests for GDS enricher
├── pyproject.toml                   # MODIFY — add graphdatascience dependency
└── docker-compose.yml               # READ ONLY — GDS plugin already configured
```

---

## Task 1: Add `graphdatascience` Dependency

**Files:**
- Modify: `cast-clone-backend/pyproject.toml`

- [ ] **Step 1: Add the dependency**

```bash
cd cast-clone-backend && uv add graphdatascience
```

- [ ] **Step 2: Verify installation**

Run: `cd cast-clone-backend && uv run python -c "from graphdatascience import GraphDataScience; print('GDS client OK')"`
Expected: `GDS client OK`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add pyproject.toml uv.lock
git commit -m "feat(phase3): add graphdatascience Python client dependency"
```

---

## Task 2: Remove BFS Community Detection from Enricher

**Files:**
- Modify: `cast-clone-backend/app/stages/enricher.py`
- Modify: `cast-clone-backend/tests/unit/test_enricher.py`

- [ ] **Step 1: Remove the `detect_communities` function and Step 5 call from enricher.py**

In `app/stages/enricher.py`, remove the entire `detect_communities` function (lines ~355-442) and the Step 5 block in `enrich_graph()` (lines ~88-97). Also remove the `deque` import if no longer used.

The `enrich_graph` function should end after Step 4 (architectural layers):

```python
async def enrich_graph(context: AnalysisContext) -> None:
    """Run all enrichment steps on the analysis context's graph.

    Steps (in order):
    1. Compute fan-in/fan-out metrics on CLASS nodes
    2. Aggregate class-level DEPENDS_ON edges from method CALLS
    3. Aggregate module-level IMPORTS edges from class DEPENDS_ON
    4. Assign architectural layers (create Layer nodes + CONTAINS edges)

    Community detection moved to Stage 10 (GDS Louvain, post Neo4j write).
    Non-critical: catches exceptions per step, logs warnings, continues.
    """
    graph = context.graph
    app_name = context.project_id

    logger.info(
        "enricher.start",
        node_count=graph.node_count,
        edge_count=graph.edge_count,
    )

    # Step 1: Fan metrics
    try:
        compute_fan_metrics(graph)
        logger.info("enricher.fan_metrics.done")
    except Exception as exc:
        msg = f"Fan metrics computation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.fan_metrics.failed", error=str(exc))

    # Step 2: Class-level DEPENDS_ON
    try:
        depends_on_count = aggregate_class_depends_on(graph)
        logger.info("enricher.depends_on.done", edges_created=depends_on_count)
    except Exception as exc:
        msg = f"Class DEPENDS_ON aggregation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.depends_on.failed", error=str(exc))

    # Step 3: Module-level IMPORTS
    try:
        imports_count = aggregate_module_imports(graph)
        logger.info("enricher.imports.done", edges_created=imports_count)
    except Exception as exc:
        msg = f"Module IMPORTS aggregation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.imports.failed", error=str(exc))

    # Step 4: Architectural layers
    try:
        layer_count = assign_architectural_layers(graph, app_name=app_name)
        logger.info("enricher.layers.done", layers_created=layer_count)
    except Exception as exc:
        msg = f"Layer assignment failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.layers.failed", error=str(exc))

    logger.info(
        "enricher.done",
        node_count=graph.node_count,
        edge_count=graph.edge_count,
    )
```

- [ ] **Step 2: Remove BFS community detection tests from test_enricher.py**

Remove `TestCommunityDetection` class and any imports of `detect_communities` from `tests/unit/test_enricher.py`.

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_enricher.py -v`
Expected: All remaining tests PASS (fan metrics, DEPENDS_ON, IMPORTS, layers)

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend
git add app/stages/enricher.py tests/unit/test_enricher.py
git commit -m "refactor: remove BFS community detection from enricher (moved to GDS Stage 10)"
```

---

## Task 3: Write Failing Tests for GDS Enricher

**Files:**
- Create: `cast-clone-backend/tests/unit/test_gds_enricher.py`

- [ ] **Step 1: Write the test file**

```python
# tests/unit/test_gds_enricher.py
"""Tests for Stage 10: GDS Louvain Community Detection.

These tests mock the GDS client since unit tests don't have Neo4j.
Integration tests with real Neo4j + GDS are in tests/integration/.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.context import AnalysisContext
from app.stages.gds_enricher import run_gds_community_detection


def _make_context() -> AnalysisContext:
    return AnalysisContext(project_id="test-project")


class TestGdsCommunityDetection:
    """Tests for run_gds_community_detection."""

    @pytest.mark.asyncio
    async def test_runs_louvain_and_returns_community_count(self):
        """Happy path: GDS projects graph, runs Louvain, drops projection."""
        mock_driver = AsyncMock()

        # Mock GDS client
        mock_gds = MagicMock()
        mock_graph = MagicMock()
        mock_graph.name.return_value = "test-project_communities"

        # gds.graph.project returns (Graph, stats)
        mock_gds.graph.project.return_value = (mock_graph, {"nodeCount": 10})

        # gds.louvain.write returns result dict
        mock_gds.louvain.write.return_value = {
            "communityCount": 3,
            "modularity": 0.65,
            "nodePropertiesWritten": 10,
        }

        mock_graph.drop = MagicMock()

        ctx = _make_context()

        with patch(
            "app.stages.gds_enricher._create_gds_client", return_value=mock_gds
        ):
            result = await run_gds_community_detection(ctx, mock_driver)

        assert result["communityCount"] == 3
        assert result["modularity"] == 0.65
        assert ctx.community_count == 3

        # Verify projection was created and dropped
        mock_gds.graph.project.assert_called_once()
        mock_gds.louvain.write.assert_called_once()
        mock_graph.drop.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_gds_failure_gracefully(self):
        """If GDS fails, warns but does not raise."""
        mock_driver = AsyncMock()
        ctx = _make_context()

        with patch(
            "app.stages.gds_enricher._create_gds_client",
            side_effect=Exception("GDS not available"),
        ):
            result = await run_gds_community_detection(ctx, mock_driver)

        assert result["communityCount"] == 0
        assert ctx.community_count == 0
        assert len(ctx.warnings) == 1
        assert "GDS" in ctx.warnings[0]

    @pytest.mark.asyncio
    async def test_cleans_up_projection_on_louvain_failure(self):
        """If Louvain fails after projection, still drops the projection."""
        mock_driver = AsyncMock()
        mock_gds = MagicMock()
        mock_graph = MagicMock()
        mock_gds.graph.project.return_value = (mock_graph, {"nodeCount": 5})
        mock_gds.louvain.write.side_effect = RuntimeError("Louvain failed")
        mock_graph.drop = MagicMock()

        ctx = _make_context()

        with patch(
            "app.stages.gds_enricher._create_gds_client", return_value=mock_gds
        ):
            result = await run_gds_community_detection(ctx, mock_driver)

        assert result["communityCount"] == 0
        assert len(ctx.warnings) == 1
        mock_graph.drop.assert_called_once()  # Cleanup happened

    @pytest.mark.asyncio
    async def test_skips_if_no_class_nodes_in_neo4j(self):
        """If graph has no Class nodes, skip gracefully."""
        mock_driver = AsyncMock()
        mock_gds = MagicMock()
        mock_gds.graph.project.side_effect = Exception(
            "No nodes found with the specified labels"
        )

        ctx = _make_context()

        with patch(
            "app.stages.gds_enricher._create_gds_client", return_value=mock_gds
        ):
            result = await run_gds_community_detection(ctx, mock_driver)

        assert result["communityCount"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_gds_enricher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.stages.gds_enricher'`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add tests/unit/test_gds_enricher.py
git commit -m "test: add failing tests for GDS Louvain community detection (Stage 10)"
```

---

## Task 4: Implement GDS Enricher

**Files:**
- Create: `cast-clone-backend/app/stages/gds_enricher.py`

- [ ] **Step 1: Write the GDS enricher module**

```python
# app/stages/gds_enricher.py
"""Stage 10: GDS Louvain Community Detection.

Runs after Stage 8 (Neo4j write) and Stage 9 (transactions).
Projects an in-memory GDS graph from Neo4j, runs Louvain community
detection, writes communityId back to Class nodes, then drops the
projection.

Non-critical: if GDS fails, pipeline continues with a warning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from app.models.context import AnalysisContext

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _create_gds_client(driver: AsyncDriver) -> Any:
    """Create a GDS client from app settings.

    Separated for testability — tests mock this function.
    The GDS Python client is synchronous and uses its own connection,
    independent of the async Neo4j driver.
    """
    from graphdatascience import GraphDataScience

    from app.config import get_settings

    settings = get_settings()
    return GraphDataScience(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


async def run_gds_community_detection(
    context: AnalysisContext,
    driver: AsyncDriver,
) -> dict[str, Any]:
    """Run Louvain community detection via Neo4j GDS.

    1. Project an in-memory graph (Class nodes, CALLS + DEPENDS_ON edges)
    2. Run Louvain algorithm (writes communityId to nodes)
    3. Drop the projection
    4. Update context.community_count

    Returns dict with communityCount and modularity.
    Non-critical: catches all exceptions and returns zeros on failure.
    """
    result: dict[str, Any] = {"communityCount": 0, "modularity": 0.0}
    projection_name = f"{context.project_id}_communities"
    gds = None
    G = None

    try:
        gds = _create_gds_client(driver)
        logger.info("gds_enricher.start", project_id=context.project_id)

        # NOTE: The graphdatascience client is synchronous. We wrap calls in
        # asyncio.to_thread() to avoid blocking the event loop.
        import asyncio

        G, louvain_result = await asyncio.to_thread(
            _run_louvain_sync, gds, projection_name
        )

        if louvain_result is None:
            # No nodes to cluster
            context.community_count = 0
            return result

        community_count = louvain_result.get("communityCount", 0)
        modularity = louvain_result.get("modularity", 0.0)

        result = {
            "communityCount": community_count,
            "modularity": modularity,
        }
        context.community_count = community_count

        logger.info(
            "gds_enricher.louvain.done",
            community_count=community_count,
            modularity=round(modularity, 4),
        )

    except Exception as exc:
        msg = f"GDS community detection failed: {exc}"
        context.warnings.append(msg)
        context.community_count = 0
        logger.warning("gds_enricher.failed", error=str(exc))

    finally:
        # Always clean up the projection
        if G is not None:
            try:
                G.drop()
                logger.info("gds_enricher.projection_dropped")
            except Exception as drop_exc:
                logger.warning(
                    "gds_enricher.projection_drop_failed", error=str(drop_exc)
                )

    return result


def _run_louvain_sync(gds: Any, projection_name: str) -> tuple[Any, dict[str, Any] | None]:
    """Synchronous helper — runs in a thread via asyncio.to_thread().

    Returns (graph_projection, louvain_result) or (graph_projection, None)
    if no nodes are found.
    """
    G, stats = gds.graph.project(
        projection_name,
        {"Class": {"properties": ["fqn"]}},
        {
            "CALLS": {"orientation": "UNDIRECTED"},
            "DEPENDS_ON": {"orientation": "UNDIRECTED"},
        },
    )

    node_count = stats.get("nodeCount", 0) if isinstance(stats, dict) else 0
    if node_count == 0:
        G.drop()
        return G, None

    louvain_result = gds.louvain.write(G, writeProperty="communityId")
    return G, dict(louvain_result) if not isinstance(louvain_result, dict) else louvain_result
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_gds_enricher.py -v`
Expected: All 4 tests PASS

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/stages/gds_enricher.py
git commit -m "feat(phase3): implement GDS Louvain community detection (Stage 10)"
```

---

## Task 5: Wire Stage 10 into Pipeline

**Files:**
- Modify: `cast-clone-backend/app/orchestrator/pipeline.py`

- [ ] **Step 1: Add Stage 10 wrapper function and register it**

Add after the `_stage_transactions` function:

```python
async def _stage_gds_enrichment(
    context: AnalysisContext, services: PipelineServices
) -> None:
    """Stage 10: Run GDS algorithms (Louvain community detection)."""
    from app.stages.gds_enricher import run_gds_community_detection
    from app.services.neo4j import get_driver

    driver = get_driver()
    await run_gds_community_detection(context, driver)
```

Add to `PIPELINE_STAGES` list (after transactions):

```python
PipelineStage("gds_enrichment", "Running graph algorithms (community detection)..."),
```

Add to `_STAGE_FUNCS` dict:

```python
"gds_enrichment": _stage_gds_enrichment,
```

- [ ] **Step 2: Run existing pipeline tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -k pipeline -v`
Expected: All existing tests PASS (new stage is non-critical)

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend
git add app/orchestrator/pipeline.py
git commit -m "feat(phase3): wire GDS enrichment as Stage 10 in analysis pipeline"
```

---

## Task 6: Run Full Test Suite

- [ ] **Step 1: Run all unit tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run linting**

Run: `cd cast-clone-backend && uv run ruff check app/stages/gds_enricher.py app/orchestrator/pipeline.py`
Expected: No errors

- [ ] **Step 3: Final commit if any fixes needed**

```bash
cd cast-clone-backend
git add -A
git commit -m "fix: address lint issues from Phase 3 M1"
```
