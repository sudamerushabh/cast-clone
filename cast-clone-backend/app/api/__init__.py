"""API router registry."""

from app.api.analysis import router as analysis_router
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.websocket import router as websocket_router

__all__ = [
    "analysis_router",
    "graph_router",
    "health_router",
    "projects_router",
    "websocket_router",
]
