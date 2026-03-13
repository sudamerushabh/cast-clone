"""Tests for annotations API endpoints."""
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


class TestAnnotationEndpointsExist:
    @pytest.mark.asyncio
    async def test_create_annotation_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/projects/proj-1/annotations",
            json={"node_fqn": "com.Foo", "content": "test"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_annotations_requires_auth(self, client):
        resp = await client.get(
            "/api/v1/projects/proj-1/annotations",
            params={"node_fqn": "com.Foo"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_update_annotation_requires_auth(self, client):
        resp = await client.put(
            "/api/v1/annotations/ann-1",
            json={"content": "updated"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_annotation_requires_auth(self, client):
        resp = await client.delete("/api/v1/annotations/ann-1")
        assert resp.status_code == 401
