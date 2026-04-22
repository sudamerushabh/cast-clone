"""Unit tests for Task 13 / CHAN-67: Cypher traversal depth validation.

Cypher does NOT permit parameterizing variable-length path hop counts (the
``[:REL*..$depth]`` form is a syntax error), so every hop count that appears
in a Cypher string MUST be interpolated from a validated int. These tests
assert that:

* The ``_validate_depth`` helper rejects out-of-range / non-int values.
* ``impact_analysis`` and ``find_path`` (shared AI tools) propagate that
  validation before building the Cypher string.
* The interpolated depth that actually reaches Cypher matches the caller's
  validated value (spy on ``graph_store.query``).
* The ``CONTAINS`` hierarchy walk uses the bounded module constant rather
  than a hardcoded literal.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.ai.tools import (
    CONTAINS_HIERARCHY_MAX_DEPTH,
    FIND_PATH_MAX_DEPTH,
    IMPACT_MAX_DEPTH,
    ChatToolContext,
    _validate_depth,
    find_path,
    impact_analysis,
)

# ── _validate_depth ──────────────────────────────────────────────────


class TestValidateDepth:
    def test_accepts_in_range(self) -> None:
        assert _validate_depth(1, 10) == 1
        assert _validate_depth(5, 10) == 5
        assert _validate_depth(10, 10) == 10

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="between 1 and"):
            _validate_depth(0, 10)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="between 1 and"):
            _validate_depth(-3, 10)

    def test_rejects_above_max(self) -> None:
        with pytest.raises(ValueError, match="between 1 and 5"):
            _validate_depth(6, 5)

    def test_rejects_non_int(self) -> None:
        with pytest.raises(ValueError, match="must be an int"):
            _validate_depth("5", 10)  # type: ignore[arg-type]

    def test_rejects_bool(self) -> None:
        # bool is a subclass of int in Python; reject explicitly so a
        # ``True`` value cannot slip past length validation.
        with pytest.raises(ValueError, match="must be an int"):
            _validate_depth(True, 10)  # type: ignore[arg-type]


# ── impact_analysis depth validation ─────────────────────────────────


@pytest.fixture
def mock_graph_store() -> AsyncMock:
    store = AsyncMock()
    store.query.return_value = []
    return store


@pytest.fixture
def ctx(mock_graph_store: AsyncMock) -> ChatToolContext:
    return ChatToolContext(
        graph_store=mock_graph_store,
        app_name="test-app",
        project_id="proj-1",
    )


class TestImpactAnalysisDepth:
    @pytest.mark.asyncio
    async def test_impact_analysis_rejects_depth_above_max(
        self, ctx: ChatToolContext
    ) -> None:
        with pytest.raises(ValueError, match=f"between 1 and {IMPACT_MAX_DEPTH}"):
            await impact_analysis(ctx, "com.app.Foo", depth=IMPACT_MAX_DEPTH + 1)

    @pytest.mark.asyncio
    async def test_impact_analysis_rejects_depth_zero_or_negative(
        self, ctx: ChatToolContext
    ) -> None:
        with pytest.raises(ValueError, match="between 1 and"):
            await impact_analysis(ctx, "com.app.Foo", depth=0)
        with pytest.raises(ValueError, match="between 1 and"):
            await impact_analysis(ctx, "com.app.Foo", depth=-1)

    @pytest.mark.asyncio
    async def test_cypher_uses_validated_depth_downstream(
        self, ctx: ChatToolContext, mock_graph_store: AsyncMock
    ) -> None:
        await impact_analysis(ctx, "com.app.Foo", depth=3, direction="downstream")
        cypher = mock_graph_store.query.call_args.args[0]
        # Depth literal is interpolated.
        assert "*1..3]" in cypher
        # No hardcoded 10 hop count sneaks in.
        assert "*1..10]" not in cypher

    @pytest.mark.asyncio
    async def test_cypher_uses_validated_depth_upstream(
        self, ctx: ChatToolContext, mock_graph_store: AsyncMock
    ) -> None:
        await impact_analysis(ctx, "com.app.Foo", depth=2, direction="upstream")
        cypher = mock_graph_store.query.call_args.args[0]
        assert "*1..2]" in cypher
        # Hierarchy walk uses the module constant, not the old hardcoded 10.
        assert f"CONTAINS*0..{CONTAINS_HIERARCHY_MAX_DEPTH}]" in cypher
        assert "CONTAINS*0..10]" not in cypher

    @pytest.mark.asyncio
    async def test_cypher_containment_depth_is_bounded_constant(
        self, ctx: ChatToolContext, mock_graph_store: AsyncMock
    ) -> None:
        # The CONTAINS hierarchy cap should be a finite, known-safe number
        # (Task 13 raised 10 → 12 for deeper monorepos).
        assert CONTAINS_HIERARCHY_MAX_DEPTH == 12
        await impact_analysis(ctx, "com.app.Foo", depth=1, direction="upstream")
        cypher = mock_graph_store.query.call_args.args[0]
        assert f"*0..{CONTAINS_HIERARCHY_MAX_DEPTH}]" in cypher


# ── find_path depth validation ───────────────────────────────────────


class TestFindPathDepth:
    @pytest.mark.asyncio
    async def test_find_path_rejects_depth_above_max(
        self, ctx: ChatToolContext
    ) -> None:
        with pytest.raises(ValueError, match=f"between 1 and {FIND_PATH_MAX_DEPTH}"):
            await find_path(ctx, "a", "b", max_depth=FIND_PATH_MAX_DEPTH + 1)

    @pytest.mark.asyncio
    async def test_find_path_rejects_zero(self, ctx: ChatToolContext) -> None:
        with pytest.raises(ValueError, match="between 1 and"):
            await find_path(ctx, "a", "b", max_depth=0)

    @pytest.mark.asyncio
    async def test_find_path_uses_validated_depth(
        self, ctx: ChatToolContext, mock_graph_store: AsyncMock
    ) -> None:
        await find_path(ctx, "a", "b", max_depth=7)
        cypher = mock_graph_store.query.call_args.args[0]
        assert "*..7]" in cypher
        # No leftover hardcoded 10 hop count.
        assert "*..10]" not in cypher

    @pytest.mark.asyncio
    async def test_find_path_default_is_max(
        self, ctx: ChatToolContext, mock_graph_store: AsyncMock
    ) -> None:
        await find_path(ctx, "a", "b")
        cypher = mock_graph_store.query.call_args.args[0]
        assert f"*..{FIND_PATH_MAX_DEPTH}]" in cypher


# ── analysis_views Cypher bounding ───────────────────────────────────


class TestAnalysisViewsHierarchyDepth:
    """Regression test: the legacy hardcoded ``CONTAINS*0..10`` literal must
    no longer appear anywhere in the shipped Cypher for analysis_views or
    pr_analysis — Task 13 replaced all of them with the module constant.
    """

    def test_analysis_views_uses_constant(self) -> None:
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "app" / "api" / "analysis_views.py"
        src = path.read_text()
        assert "CONTAINS*0..10]" not in src
        # Interpolation uses the module constant directly.
        assert "CONTAINS*0..{CONTAINS_HIERARCHY_MAX_DEPTH}]" in src

    def test_pr_impact_aggregator_uses_constant(self) -> None:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "pr_analysis"
            / "impact_aggregator.py"
        )
        src = path.read_text()
        assert "CONTAINS*0..10]" not in src
        # Module constant re-exported locally as _HIERARCHY_MAX_DEPTH.
        assert "CONTAINS*0..{_HIERARCHY_MAX_DEPTH}]" in src

    def test_pr_ai_tools_uses_constant(self) -> None:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "pr_analysis"
            / "ai"
            / "tools.py"
        )
        src = path.read_text()
        assert "CONTAINS*0..10]" not in src
        # Uses a local ``hierarchy`` variable bound to CONTAINS_HIERARCHY_MAX_DEPTH.
        assert "CONTAINS*0..{hierarchy}]" in src
