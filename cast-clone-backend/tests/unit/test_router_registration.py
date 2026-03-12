# tests/unit/test_router_registration.py
import pytest


class TestRouterRegistration:
    def test_all_routes_registered(self):
        """All API routes from M2 should be registered in the app."""
        from app.main import create_app

        app = create_app()
        routes = [route.path for route in app.routes]

        # Project CRUD
        assert "/api/v1/projects" in routes
        assert "/api/v1/projects/{project_id}" in routes

        # Analysis
        assert "/api/v1/projects/{project_id}/analyze" in routes
        assert "/api/v1/projects/{project_id}/status" in routes

        # Graph queries
        assert "/api/v1/graphs/{project_id}/nodes" in routes
        assert "/api/v1/graphs/{project_id}/edges" in routes
        assert "/api/v1/graphs/{project_id}/node/{fqn:path}" in routes
        assert "/api/v1/graphs/{project_id}/neighbors/{fqn:path}" in routes
        assert "/api/v1/graphs/{project_id}/search" in routes

        # WebSocket
        assert "/api/v1/projects/{project_id}/progress" in routes

        # Health (existing)
        assert "/health" in routes

    def test_health_endpoint_still_works(self):
        """Existing health endpoint must not break."""
        from app.main import create_app

        app = create_app()
        routes = [route.path for route in app.routes]
        assert "/health" in routes
