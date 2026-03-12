# tests/unit/test_projects_api.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.unit.conftest import make_project


class TestCreateProject:
    @pytest.mark.asyncio
    async def test_create_project_201(self, app_client, mock_session):
        # Mock session.refresh to populate the project with an ID
        async def mock_refresh(obj):
            obj.id = str(uuid4())
            obj.status = "created"
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)

        mock_session.refresh = mock_refresh

        response = await app_client.post(
            "/api/v1/projects",
            json={"name": "my-project", "source_path": "/opt/code/my-project"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "my-project"
        assert data["source_path"] == "/opt/code/my-project"
        assert data["status"] == "created"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_project_missing_name_422(self, app_client):
        response = await app_client.post(
            "/api/v1/projects",
            json={"source_path": "/opt/code"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_project_empty_name_422(self, app_client):
        response = await app_client.post(
            "/api/v1/projects",
            json={"name": "", "source_path": "/opt/code"},
        )
        assert response.status_code == 422


class TestListProjects:
    @pytest.mark.asyncio
    async def test_list_projects_200(self, app_client, mock_session):
        project = make_project()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [project]

        # Count query
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_result]
        )

        response = await app_client.get("/api/v1/projects")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["projects"]) == 1

    @pytest.mark.asyncio
    async def test_list_projects_empty(self, app_client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_result]
        )

        response = await app_client.get("/api/v1/projects")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["projects"] == []


class TestGetProject:
    @pytest.mark.asyncio
    async def test_get_project_200(self, app_client, mock_session):
        project = make_project(id="proj-123")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.get("/api/v1/projects/proj-123")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "proj-123"

    @pytest.mark.asyncio
    async def test_get_project_404(self, app_client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.get("/api/v1/projects/nonexistent")
        assert response.status_code == 404


class TestDeleteProject:
    @pytest.mark.asyncio
    async def test_delete_project_204(self, app_client, mock_session):
        project = make_project(id="proj-123")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.delete("/api/v1/projects/proj-123")
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_project_404(self, app_client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.delete("/api/v1/projects/nonexistent")
        assert response.status_code == 404
