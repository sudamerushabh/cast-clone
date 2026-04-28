"""Unit tests for CeleryPlugin (M3)."""

from __future__ import annotations

from app.models.context import AnalysisContext
from app.models.enums import (
    Confidence,  # noqa: F401  -- used in forthcoming M3 tasks
    EdgeKind,  # noqa: F401  -- used in forthcoming M3 tasks
    NodeKind,  # noqa: F401  -- used in forthcoming M3 tasks
)
from app.models.graph import (
    GraphEdge,  # noqa: F401  -- used in forthcoming M3 tasks
    GraphNode,  # noqa: F401  -- used in forthcoming M3 tasks
)


def _ctx() -> AnalysisContext:
    return AnalysisContext(project_id="test-project")


def test_plugin_class_is_importable():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    plugin = CeleryPlugin()
    assert plugin.name == "celery"
    assert "python" in plugin.supported_languages
    assert plugin.depends_on == []


def test_detect_returns_not_detected_when_no_celery_decorator_present():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    plugin = CeleryPlugin()
    result = plugin.detect(ctx)
    assert result.confidence is None
