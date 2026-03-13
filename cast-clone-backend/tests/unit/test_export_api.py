"""Tests for export API endpoints."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.postgres import get_session


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
async def client(mock_session):
    async def _override_get_session():
        return mock_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


class TestExportEndpointsExist:
    @pytest.mark.asyncio
    async def test_export_nodes_csv_requires_auth(self, client):
        resp = await client.get("/api/v1/export/proj-1/nodes.csv")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_edges_csv_requires_auth(self, client):
        resp = await client.get("/api/v1/export/proj-1/edges.csv")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_graph_json_requires_auth(self, client):
        resp = await client.get("/api/v1/export/proj-1/graph.json")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_impact_csv_requires_auth(self, client):
        resp = await client.get(
            "/api/v1/export/proj-1/impact.csv",
            params={"node": "com.app.Foo"},
        )
        assert resp.status_code == 401
