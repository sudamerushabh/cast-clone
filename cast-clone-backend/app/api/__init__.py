"""API router registry."""

from app.api.activity import router as activity_router
from app.api.analysis import router as analysis_router
from app.api.analysis_views import router as analysis_views_router
from app.api.annotations import annotation_router as annotations_router
from app.api.annotations import project_router as annotations_project_router
from app.api.auth import router as auth_router
from app.api.connectors import router as connectors_router
from app.api.export import router as export_router
from app.api.git_config import router as git_config_router
from app.api.graph import router as graph_router
from app.api.graph_views import router as graph_views_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.pull_requests import router as pull_requests_router
from app.api.repositories import router as repositories_router
from app.api.saved_views import project_router as views_project_router
from app.api.saved_views import view_router as views_router
from app.api.tags import project_router as tags_project_router
from app.api.tags import tag_router as tags_router
from app.api.users import router as users_router
from app.api.webhooks import router as webhooks_router
from app.api.websocket import router as websocket_router

__all__ = [
    "activity_router",
    "annotations_project_router",
    "annotations_router",
    "auth_router",
    "analysis_router",
    "analysis_views_router",
    "connectors_router",
    "export_router",
    "git_config_router",
    "graph_router",
    "graph_views_router",
    "health_router",
    "projects_router",
    "pull_requests_router",
    "repositories_router",
    "tags_project_router",
    "tags_router",
    "users_router",
    "views_project_router",
    "views_router",
    "webhooks_router",
    "websocket_router",
]
