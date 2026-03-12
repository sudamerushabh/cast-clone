# tests/unit/test_analysis_api.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.conftest import make_project


class TestTriggerAnalysis:
    @pytest.mark.asyncio
    async def test_trigger_202(self, app_client, mock_session):
        project = make_project(id="proj-1", status="created")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def mock_refresh(obj):
            obj.id = "run-1"
            obj.status = "running"

        mock_session.refresh = mock_refresh

        with patch("app.api.analysis.run_analysis_pipeline", new_callable=AsyncMock):
            response = await app_client.post("/api/v1/projects/proj-1/analyze")
        assert response.status_code == 202
        data = response.json()
        assert data["project_id"] == "proj-1"
        assert data["status"] == "analyzing"

    @pytest.mark.asyncio
    async def test_trigger_404_project_not_found(self, app_client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.post("/api/v1/projects/nonexistent/analyze")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_trigger_409_already_analyzing(self, app_client, mock_session):
        project = make_project(id="proj-1", status="analyzing")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.post("/api/v1/projects/proj-1/analyze")
        assert response.status_code == 409


class TestAnalysisStatus:
    @pytest.mark.asyncio
    async def test_status_200(self, app_client, mock_session):
        project = make_project(id="proj-1", status="analyzed")

        # First call returns project, second returns latest run
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_run = MagicMock()
        mock_run.id = "run-1"
        mock_run.status = "completed"
        mock_run.stage = None
        mock_run.started_at = datetime.now(timezone.utc)
        mock_run.completed_at = datetime.now(timezone.utc)

        mock_run_result = MagicMock()
        mock_run_result.scalar_one_or_none.return_value = mock_run

        mock_session.execute = AsyncMock(
            side_effect=[mock_project_result, mock_run_result]
        )

        response = await app_client.get("/api/v1/projects/proj-1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == "proj-1"
        assert data["status"] == "analyzed"

    @pytest.mark.asyncio
    async def test_status_404(self, app_client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.get("/api/v1/projects/nonexistent/status")
        assert response.status_code == 404
