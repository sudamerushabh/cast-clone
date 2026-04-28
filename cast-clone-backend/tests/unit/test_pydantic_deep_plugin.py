"""Unit tests for FastAPIPydanticPlugin (M3)."""

from __future__ import annotations

import pytest

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


@pytest.mark.asyncio
async def test_extract_tags_pydantic_model_classes():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoCreate",
        name="TodoCreate",
        kind=NodeKind.CLASS,
        language="python",
    )
    non_model = GraphNode(
        fqn="app.services.TodoService",
        name="TodoService",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(non_model)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn="BaseModel",
            kind=EdgeKind.INHERITS,
        )
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    # Plugin does not duplicate the class node — it mutates the existing one.
    updated = ctx.graph.get_node(model.fqn)
    assert updated is not None
    assert updated.properties.get("is_pydantic_model") is True
    other = ctx.graph.get_node(non_model.fqn)
    assert other is not None
    assert other.properties.get("is_pydantic_model") is not True
    assert result.warnings == []


@pytest.mark.asyncio
async def test_extract_parses_class_body_field_constraints():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoCreate",
        name="TodoCreate",
        kind=NodeKind.CLASS,
        language="python",
    )
    field_node = GraphNode(
        fqn="app.schemas.todo.TodoCreate.title",
        name="title",
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "type": "str",
            "value": "Field(min_length=1, max_length=200)",
        },
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(field_node)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn=field_node.fqn,
            kind=EdgeKind.CONTAINS,
        )
    )
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn="BaseModel",
            kind=EdgeKind.INHERITS,
        )
    )

    await FastAPIPydanticPlugin().extract(ctx)

    updated = ctx.graph.get_node(field_node.fqn)
    assert updated is not None
    constraints = updated.properties.get("constraints")
    assert constraints == {"min_length": "1", "max_length": "200"}


@pytest.mark.asyncio
async def test_extract_parses_ge_and_le_numeric_constraints():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoCreate",
        name="TodoCreate",
        kind=NodeKind.CLASS,
        language="python",
    )
    owner_id = GraphNode(
        fqn="app.schemas.todo.TodoCreate.owner_id",
        name="owner_id",
        kind=NodeKind.FIELD,
        language="python",
        properties={"type": "int", "value": "Field(ge=1, le=1000)"},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(owner_id)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn=owner_id.fqn, kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    constraints = ctx.graph.get_node(owner_id.fqn).properties.get("constraints")
    assert constraints == {"ge": "1", "le": "1000"}


@pytest.mark.asyncio
async def test_extract_ignores_non_field_value():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="M",
        name="M",
        kind=NodeKind.CLASS,
        language="python",
    )
    plain = GraphNode(
        fqn="M.x",
        name="x",
        kind=NodeKind.FIELD,
        language="python",
        properties={"type": "int", "value": "42"},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(plain)
    ctx.graph.add_edge(GraphEdge(source_fqn="M", target_fqn="M.x", kind=EdgeKind.CONTAINS))
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    assert "constraints" not in ctx.graph.get_node(plain.fqn).properties


@pytest.mark.asyncio
async def test_extract_field_constraints_merges_with_existing():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    field = GraphNode(
        fqn="M.title",
        name="title",
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "value": "Field(min_length=1)",
            "constraints": {"description": "preset"},
        },
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(field)
    ctx.graph.add_edge(GraphEdge(source_fqn="M", target_fqn="M.title", kind=EdgeKind.CONTAINS))
    ctx.graph.add_edge(GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS))

    await FastAPIPydanticPlugin().extract(ctx)

    constraints = ctx.graph.get_node("M.title").properties["constraints"]
    assert constraints == {"description": "preset", "min_length": "1"}
