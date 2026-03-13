# tests/unit/test_pipeline.py
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestrator.pipeline import (
    _STAGE_FUNCS,
    PIPELINE_STAGES,
    PipelineServices,
    run_analysis_pipeline,
)


class TestPipelineStages:
    def test_stage_order(self):
        """Pipeline stages must run in the documented order."""
        expected = [
            "discovery",
            "dependencies",
            "parsing",
            "scip",
            "lsp_fallback",
            "plugins",
            "linking",
            "enrichment",
            "transactions",
            "writing",
            "gds_enrichment",
        ]
        assert [s.name for s in PIPELINE_STAGES] == expected

    def test_critical_stages(self):
        """Only discovery and writing are critical (fatal on failure)."""
        critical = [s.name for s in PIPELINE_STAGES if s.critical]
        assert critical == ["discovery", "writing"]


def _make_mock_session_factory():
    """Create a mock session factory that returns an async context manager."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()  # add() is sync in SQLAlchemy

    # Create an async context manager that yields mock_session
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    # session_factory() returns the context manager (sync call)
    mock_session_factory = MagicMock(return_value=mock_ctx)

    return mock_session_factory, mock_session


def _make_noop_stage_funcs():
    """Create no-op stage functions matching the (context, services) signature."""
    noop = AsyncMock()
    return {name: noop for name in _STAGE_FUNCS}


def _make_mock_services():
    """Create mock PipelineServices."""
    return PipelineServices(
        graph_store=MagicMock(),
        source_path=Path("/tmp/test"),
    )


class TestRunAnalysisPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_runs_all_stages(self):
        """Pipeline should call each stage and emit progress."""
        mock_session_factory, mock_session = _make_mock_session_factory()

        # Mock the Project query result
        mock_project = MagicMock()
        mock_project.id = "proj-1"
        mock_project.name = "test-project"
        mock_project.source_path = "/tmp/test"
        mock_project.status = "created"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute = AsyncMock(return_value=mock_result)

        services = _make_mock_services()

        with patch("app.orchestrator.pipeline.get_session_factory") as mock_get_sf:
            mock_get_sf.return_value = mock_session_factory
            with patch(
                "app.orchestrator.pipeline.WebSocketProgressReporter"
            ) as mock_ws:
                mock_reporter = AsyncMock()
                mock_ws.return_value = mock_reporter
                with patch.dict(
                    "app.orchestrator.pipeline._STAGE_FUNCS", _make_noop_stage_funcs()
                ):
                    await run_analysis_pipeline("proj-1", services=services)

                # Pipeline should emit progress for each stage
                assert mock_reporter.emit.call_count >= len(PIPELINE_STAGES)
                # Pipeline should mark complete
                mock_reporter.emit_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_updates_status_to_analyzing(self):
        """Pipeline should set project status to 'analyzed' at completion."""
        mock_session_factory, mock_session = _make_mock_session_factory()

        mock_project = MagicMock()
        mock_project.id = "proj-1"
        mock_project.name = "test-project"
        mock_project.source_path = "/tmp/test"
        mock_project.status = "created"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute = AsyncMock(return_value=mock_result)

        services = _make_mock_services()

        with patch("app.orchestrator.pipeline.get_session_factory") as mock_get_sf:
            mock_get_sf.return_value = mock_session_factory
            with patch(
                "app.orchestrator.pipeline.WebSocketProgressReporter"
            ) as mock_ws:
                mock_reporter = AsyncMock()
                mock_ws.return_value = mock_reporter
                with patch.dict(
                    "app.orchestrator.pipeline._STAGE_FUNCS", _make_noop_stage_funcs()
                ):
                    await run_analysis_pipeline("proj-1", services=services)

        # Project status should be set to "analyzed"
        assert mock_project.status == "analyzed"

    @pytest.mark.asyncio
    async def test_pipeline_handles_project_not_found(self):
        """Pipeline should raise if project not found."""
        mock_session_factory, mock_session = _make_mock_session_factory()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.orchestrator.pipeline.get_session_factory") as mock_get_sf:
            mock_get_sf.return_value = mock_session_factory
            with pytest.raises(ValueError, match="not found"):
                await run_analysis_pipeline("nonexistent")
