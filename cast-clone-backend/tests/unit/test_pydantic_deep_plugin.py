"""Unit tests for FastAPIPydanticPlugin (M3)."""

from __future__ import annotations

import pytest  # noqa: F401  -- used in forthcoming M3 tasks

from app.models.context import AnalysisContext
from app.models.enums import (  # noqa: F401  -- used in forthcoming M3 tasks
    Confidence,
    EdgeKind,
    NodeKind,
)
from app.models.graph import (  # noqa: F401  -- used in forthcoming M3 tasks
    GraphEdge,
    GraphNode,
    SymbolGraph,
)


def _ctx() -> AnalysisContext:
    return AnalysisContext(project_id="test-project")


def test_plugin_class_is_importable():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    plugin = FastAPIPydanticPlugin()
    assert plugin.name == "fastapi_pydantic"
    assert "python" in plugin.supported_languages
    assert "fastapi" in plugin.depends_on


def test_detect_returns_not_detected_when_no_basemodel_inherits():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    plugin = FastAPIPydanticPlugin()
    result = plugin.detect(ctx)
    assert result.confidence is None
