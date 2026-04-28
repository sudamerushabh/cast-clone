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
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="M.x", kind=EdgeKind.CONTAINS)
    )
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
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="M.title", kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    constraints = ctx.graph.get_node("M.title").properties["constraints"]
    assert constraints == {"description": "preset", "min_length": "1"}


@pytest.mark.asyncio
async def test_extract_parses_annotated_field_constraints():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.User",
        name="User",
        kind=NodeKind.CLASS,
        language="python",
    )
    email_field = GraphNode(
        fqn="app.schemas.User.email",
        name="email",
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "type": "Annotated[str, Field(min_length=3, max_length=254)]",
            "value": "",
        },
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(email_field)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn=email_field.fqn,
            kind=EdgeKind.CONTAINS,
        )
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    constraints = ctx.graph.get_node(email_field.fqn).properties.get("constraints")
    assert constraints == {"min_length": "3", "max_length": "254"}


@pytest.mark.asyncio
async def test_extract_merges_constraints_from_type_and_value():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    # Defensive case: both type and value carry Field() — should merge,
    # with value taking precedence on key collision.
    f = GraphNode(
        fqn="M.x",
        name="x",
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "type": "Annotated[int, Field(ge=0)]",
            "value": "Field(le=100)",
        },
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(f)
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="M.x", kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    constraints = ctx.graph.get_node("M.x").properties.get("constraints")
    assert constraints == {"ge": "0", "le": "100"}


@pytest.mark.asyncio
async def test_extract_tags_field_validator_function():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.User",
        name="User",
        kind=NodeKind.CLASS,
        language="python",
    )
    validator = GraphNode(
        fqn="app.schemas.User.normalise_email",
        name="normalise_email",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@field_validator("email")']},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(validator)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn=validator.fqn,
            kind=EdgeKind.CONTAINS,
        )
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    updated = ctx.graph.get_node(validator.fqn)
    assert updated.properties.get("is_validator") is True
    assert updated.properties.get("validator_kind") == "field_validator"
    assert updated.properties.get("target_field") == "email"


@pytest.mark.asyncio
async def test_extract_tags_model_validator_without_target_field():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    mv = GraphNode(
        fqn="M.check",
        name="check",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@model_validator(mode="after")']},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(mv)
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="M.check", kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    props = ctx.graph.get_node("M.check").properties
    assert props.get("is_validator") is True
    assert props.get("validator_kind") == "model_validator"
    assert "target_field" not in props


@pytest.mark.asyncio
async def test_extract_tags_v1_validator_and_root_validator():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    v1 = GraphNode(
        fqn="M.v1",
        name="v1",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@validator("x", pre=True)']},
    )
    root = GraphNode(
        fqn="M.root",
        name="root",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ["@root_validator"]},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(v1)
    ctx.graph.add_node(root)
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="M.v1", kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="M.root", kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    v1_props = ctx.graph.get_node("M.v1").properties
    assert v1_props.get("validator_kind") == "validator"
    assert v1_props.get("target_field") == "x"
    root_props = ctx.graph.get_node("M.root").properties
    assert root_props.get("validator_kind") == "root_validator"
    assert "target_field" not in root_props


@pytest.mark.asyncio
async def test_extract_emits_accepts_edge_for_body_param():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    # Pydantic model
    model = GraphNode(
        fqn="app.schemas.todo.TodoCreate",
        name="TodoCreate",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )
    # FastAPI endpoint handler
    handler = GraphNode(
        fqn="app.routes.todos.create_todo",
        name="create_todo",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={
            "params": [
                {"name": "data", "type": "TodoCreate", "default": ""},
                {
                    "name": "session",
                    "type": "AsyncSession",
                    "default": "Depends(get_session)",
                },
            ],
            "return_type": "TodoRead",
        },
    )
    endpoint = GraphNode(
        fqn="POST:/todos",
        name="POST /todos",
        kind=NodeKind.API_ENDPOINT,
        language="python",
        properties={"method": "POST", "path": "/todos"},
    )
    ctx.graph.add_node(handler)
    ctx.graph.add_node(endpoint)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=handler.fqn,
            target_fqn=endpoint.fqn,
            kind=EdgeKind.HANDLES,
            confidence=Confidence.HIGH,
        )
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    accepts = [e for e in result.edges if e.kind == EdgeKind.ACCEPTS]
    assert len(accepts) == 1
    assert accepts[0].source_fqn == endpoint.fqn
    assert accepts[0].target_fqn == model.fqn
    assert accepts[0].confidence == Confidence.HIGH


@pytest.mark.asyncio
async def test_extract_accepts_skips_non_pydantic_types():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    handler = GraphNode(
        fqn="m.h",
        name="h",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"params": [{"name": "q", "type": "str", "default": ""}]},
    )
    endpoint = GraphNode(
        fqn="GET:/q", name="GET /q", kind=NodeKind.API_ENDPOINT, language="python"
    )
    ctx.graph.add_node(handler)
    ctx.graph.add_node(endpoint)
    ctx.graph.add_edge(
        GraphEdge(source_fqn="m.h", target_fqn="GET:/q", kind=EdgeKind.HANDLES)
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    assert [e for e in result.edges if e.kind == EdgeKind.ACCEPTS] == []


@pytest.mark.asyncio
async def test_extract_emits_returns_edge_from_response_model():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoRead",
        name="TodoRead",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )
    handler = GraphNode(
        fqn="app.routes.todos.create_todo",
        name="create_todo",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={
            "annotations": [
                '@router.post("", response_model=TodoRead, status_code=201)'
            ],
            "return_type": "TodoRead",
            "params": [],
        },
    )
    endpoint = GraphNode(
        fqn="POST:/todos",
        name="POST /todos",
        kind=NodeKind.API_ENDPOINT,
        language="python",
    )
    ctx.graph.add_node(handler)
    ctx.graph.add_node(endpoint)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=handler.fqn,
            target_fqn=endpoint.fqn,
            kind=EdgeKind.HANDLES,
        )
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    returns = [e for e in result.edges if e.kind == EdgeKind.RETURNS]
    assert len(returns) == 1
    assert returns[0].source_fqn == endpoint.fqn
    assert returns[0].target_fqn == model.fqn
    assert returns[0].evidence == "fastapi-response-model"


@pytest.mark.asyncio
async def test_extract_falls_back_to_return_type_when_no_response_model():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoRead",
        name="TodoRead",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )
    handler = GraphNode(
        fqn="app.routes.todos.list_todos",
        name="list_todos",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={
            "annotations": ['@router.get("/owner/{owner_id}")'],
            "return_type": "list[TodoRead]",
            "params": [],
        },
    )
    endpoint = GraphNode(
        fqn="GET:/owner/{owner_id}",
        name="GET /owner/{owner_id}",
        kind=NodeKind.API_ENDPOINT,
        language="python",
    )
    ctx.graph.add_node(handler)
    ctx.graph.add_node(endpoint)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=handler.fqn,
            target_fqn=endpoint.fqn,
            kind=EdgeKind.HANDLES,
        )
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    returns = [e for e in result.edges if e.kind == EdgeKind.RETURNS]
    assert len(returns) == 1
    assert returns[0].target_fqn == model.fqn
    assert returns[0].evidence == "fastapi-return-annotation"


@pytest.mark.asyncio
async def test_extract_emits_maps_to_for_unique_column_match():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.User",
        name="User",
        kind=NodeKind.CLASS,
        language="python",
    )
    email_field = GraphNode(
        fqn="app.schemas.User.email",
        name="email",
        kind=NodeKind.FIELD,
        language="python",
        properties={"type": "str", "value": ""},
    )
    users_table = GraphNode(
        fqn="app.db.users",
        name="users",
        kind=NodeKind.TABLE,
        language="python",
    )
    email_column = GraphNode(
        fqn="app.db.users.email",
        name="email",
        kind=NodeKind.COLUMN,
        language="python",
        properties={"type": "VARCHAR"},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(email_field)
    ctx.graph.add_node(users_table)
    ctx.graph.add_node(email_column)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn, target_fqn=email_field.fqn, kind=EdgeKind.CONTAINS
        )
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=users_table.fqn,
            target_fqn=email_column.fqn,
            kind=EdgeKind.HAS_COLUMN,
        )
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    maps = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
    assert len(maps) == 1
    assert maps[0].source_fqn == email_field.fqn
    assert maps[0].target_fqn == email_column.fqn
    assert maps[0].confidence == Confidence.MEDIUM
    assert maps[0].properties.get("source") == "pydantic"
    assert maps[0].properties.get("confidence_reason") == "name_and_type_match"


@pytest.mark.asyncio
async def test_extract_uses_low_confidence_on_ambiguous_matches():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    field = GraphNode(
        fqn="M.email",
        name="email",
        kind=NodeKind.FIELD,
        language="python",
        properties={"type": "str"},
    )
    col1 = GraphNode(
        fqn="t1.email",
        name="email",
        kind=NodeKind.COLUMN,
        language="python",
        properties={"type": "VARCHAR"},
    )
    col2 = GraphNode(
        fqn="t2.email",
        name="email",
        kind=NodeKind.COLUMN,
        language="python",
        properties={"type": "TEXT"},
    )
    for n in (model, field, col1, col2):
        ctx.graph.add_node(n)
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="M.email", kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    maps = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
    assert len(maps) == 2
    assert all(e.confidence == Confidence.LOW for e in maps)


@pytest.mark.asyncio
async def test_extract_skips_maps_to_when_flag_disabled(monkeypatch):
    import app.stages.plugins.fastapi_plugin.pydantic as mod

    monkeypatch.setattr(mod, "ENABLE_PYDANTIC_ORM_LINKING", False)

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    field = GraphNode(
        fqn="M.email",
        name="email",
        kind=NodeKind.FIELD,
        language="python",
        properties={"type": "str"},
    )
    col = GraphNode(
        fqn="t.email",
        name="email",
        kind=NodeKind.COLUMN,
        language="python",
        properties={"type": "VARCHAR"},
    )
    for n in (model, field, col):
        ctx.graph.add_node(n)
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="M.email", kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    result = await mod.FastAPIPydanticPlugin().extract(ctx)

    assert [e for e in result.edges if e.kind == EdgeKind.MAPS_TO] == []
