"""API router registry."""

from app.api.auth import router as auth_router
from app.api.analysis import router as analysis_router
from app.api.analysis_views import router as analysis_views_router
from app.api.connectors import router as connectors_router
from app.api.graph import router as graph_router
from app.api.graph_views import router as graph_views_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.repositories import router as repositories_router
from app.api.websocket import router as websocket_router

__all__ = [
    "auth_router",
    "analysis_router",
    "analysis_views_router",
    "connectors_router",
    "graph_router",
    "graph_views_router",
    "health_router",
    "projects_router",
    "repositories_router",
    "websocket_router",
]
