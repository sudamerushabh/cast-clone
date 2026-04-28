"""Unit tests for FastAPIPydanticPlugin (M3)."""

from __future__ import annotations

from app.models.context import AnalysisContext
from app.models.enums import (
    Confidence,
    EdgeKind,
    NodeKind,
)
from app.models.graph import (  # noqa: F401  -- SymbolGraph used in forthcoming M3 tasks
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


def test_detect_high_when_basemodel_inherits_edge_present():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoCreate",
        name="TodoCreate",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn="BaseModel",
            kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW,
            evidence="tree-sitter",
        )
    )

    result = FastAPIPydanticPlugin().detect(ctx)

    assert result.confidence == Confidence.HIGH
    assert "Pydantic" in result.reason


def test_detect_recognises_qualified_basemodel():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="pkg.schemas.User",
        name="User",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn="pydantic.BaseModel",
            kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW,
        )
    )

    result = FastAPIPydanticPlugin().detect(ctx)

    assert result.confidence == Confidence.HIGH


def test_detect_ignores_non_pydantic_basemodel_inherits():
    """A class inheriting from app.base.BaseModel must not trigger detection.

    Common SQLAlchemy declarative bases or custom base classes share the
    BaseModel name but are not pydantic.BaseModel.
    """
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.models.User",
        name="User",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn="app.base.BaseModel",
            kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW,
        )
    )

    result = FastAPIPydanticPlugin().detect(ctx)
    assert result.confidence is None


def test_detect_recognises_pydantic_root_model():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.IDList",
        name="IDList",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn="pydantic.RootModel",
            kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW,
        )
    )

    result = FastAPIPydanticPlugin().detect(ctx)
    assert result.confidence == Confidence.HIGH
