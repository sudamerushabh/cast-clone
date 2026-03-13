# tests/unit/test_gds_enricher.py
"""Tests for Stage 10: GDS Louvain Community Detection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.context import AnalysisContext
from app.stages.gds_enricher import run_gds_community_detection


def _make_context() -> AnalysisContext:
    return AnalysisContext(project_id="test-project")


class TestGdsCommunityDetection:
    @pytest.mark.asyncio
    async def test_runs_louvain_and_returns_community_count(self):
        mock_driver = AsyncMock()
        mock_gds = MagicMock()
        mock_graph = MagicMock()
        mock_graph.name.return_value = "test-project_communities"
        mock_gds.graph.project.return_value = (mock_graph, {"nodeCount": 10})
        mock_gds.louvain.write.return_value = {
            "communityCount": 3,
            "modularity": 0.65,
            "nodePropertiesWritten": 10,
        }
        mock_graph.drop = MagicMock()
        ctx = _make_context()

        with patch("app.stages.gds_enricher._create_gds_client", return_value=mock_gds):
            result = await run_gds_community_detection(ctx, mock_driver)

        assert result["communityCount"] == 3
        assert result["modularity"] == 0.65
        assert ctx.community_count == 3
        mock_gds.graph.project.assert_called_once()
        mock_gds.louvain.write.assert_called_once()
        mock_graph.drop.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_gds_failure_gracefully(self):
        mock_driver = AsyncMock()
        ctx = _make_context()

        with patch("app.stages.gds_enricher._create_gds_client", side_effect=Exception("GDS not available")):
            result = await run_gds_community_detection(ctx, mock_driver)

        assert result["communityCount"] == 0
        assert ctx.community_count == 0
        assert len(ctx.warnings) == 1
        assert "GDS" in ctx.warnings[0]

    @pytest.mark.asyncio
    async def test_cleans_up_projection_on_louvain_failure(self):
        mock_driver = AsyncMock()
        mock_gds = MagicMock()
        mock_graph = MagicMock()
        mock_gds.graph.project.return_value = (mock_graph, {"nodeCount": 5})
        mock_gds.louvain.write.side_effect = RuntimeError("Louvain failed")
        mock_graph.drop = MagicMock()
        ctx = _make_context()

        with patch("app.stages.gds_enricher._create_gds_client", return_value=mock_gds):
            result = await run_gds_community_detection(ctx, mock_driver)

        assert result["communityCount"] == 0
        assert len(ctx.warnings) == 1
        mock_graph.drop.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_if_no_class_nodes_in_neo4j(self):
        mock_driver = AsyncMock()
        mock_gds = MagicMock()
        mock_gds.graph.project.side_effect = Exception("No nodes found with the specified labels")
        ctx = _make_context()

        with patch("app.stages.gds_enricher._create_gds_client", return_value=mock_gds):
            result = await run_gds_community_detection(ctx, mock_driver)

        assert result["communityCount"] == 0
