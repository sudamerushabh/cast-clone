"""Unit tests for FlaskPlugin (M4)."""

from __future__ import annotations

import pytest

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphNode


def _ctx() -> AnalysisContext:
    return AnalysisContext(project_id="test-project")


def test_plugin_class_is_importable():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    plugin = FlaskPlugin()
    assert plugin.name == "flask"
    assert "python" in plugin.supported_languages
    assert plugin.depends_on == []


def test_detect_not_detected_on_empty_graph():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    result = FlaskPlugin().detect(_ctx())
    assert result.confidence is None


def test_detect_high_when_flask_route_decorator_present():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="app.blueprints.items.list_items",
            name="list_items",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ['@items_bp.route("", methods=["GET"])']},
        )
    )
    result = FlaskPlugin().detect(ctx)
    assert result.confidence == Confidence.HIGH
    assert "Flask" in result.reason


def test_detect_high_from_manifest_framework():
    from pathlib import Path

    from app.models.manifest import DetectedFramework, ProjectManifest
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    ctx.manifest = ProjectManifest(
        root_path=Path("/fake"),
        detected_frameworks=[
            DetectedFramework(
                name="Flask", language="python", confidence=Confidence.HIGH
            )
        ],
    )
    result = FlaskPlugin().detect(ctx)
    assert result.confidence == Confidence.HIGH


@pytest.mark.asyncio
async def test_extract_emits_endpoint_from_app_route():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    handler = GraphNode(
        fqn="app.wsgi.login",
        name="login",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@app.route("/login", methods=["GET", "POST"])']},
    )
    ctx.graph.add_node(handler)

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert len(endpoints) == 2
    methods = sorted(ep.properties["method"] for ep in endpoints)
    assert methods == ["GET", "POST"]
    paths = {ep.properties["path"] for ep in endpoints}
    assert paths == {"/login"}

    handles = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
    assert len(handles) == 2
    assert all(e.source_fqn == handler.fqn for e in handles)


@pytest.mark.asyncio
async def test_extract_defaults_app_route_method_to_get():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="app.wsgi.home",
            name="home",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ['@app.route("/")']},
        )
    )

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert len(endpoints) == 1
    assert endpoints[0].properties["method"] == "GET"
    assert endpoints[0].properties["path"] == "/"


@pytest.mark.asyncio
async def test_extract_normalizes_lowercase_methods():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="app.wsgi.search",
            name="search",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={
                "annotations": ['@app.route("/search", methods=["get", "post"])']
            },
        )
    )

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    methods = sorted(ep.properties["method"] for ep in endpoints)
    assert methods == ["GET", "POST"], (
        "lowercase methods=['get','post'] must produce two upper-cased endpoints"
    )


@pytest.mark.asyncio
async def test_extract_emits_endpoint_from_blueprint_route():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    handler = GraphNode(
        fqn="app.blueprints.items.list_items",
        name="list_items",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@items_bp.route("", methods=["GET"])']},
    )
    ctx.graph.add_node(handler)

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert len(endpoints) == 1
    ep = endpoints[0]
    assert ep.properties["method"] == "GET"
    assert ep.properties["path"] == ""
    assert ep.properties["blueprint"] == "items_bp"


@pytest.mark.asyncio
async def test_extract_blueprint_route_with_path_converter():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="app.blueprints.items.adjust_quantity",
            name="adjust_quantity",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={
                "annotations": [
                    '@items_bp.route("/<int:item_id>/adjust", methods=["POST"])'
                ],
            },
        )
    )

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert len(endpoints) == 1
    assert endpoints[0].properties["path"] == "/<int:item_id>/adjust"
    assert endpoints[0].properties["method"] == "POST"
    assert endpoints[0].properties["blueprint"] == "items_bp"


def test_resolve_blueprint_prefixes_from_registration(tmp_path):
    from app.stages.plugins.flask_plugin.blueprints import resolve_blueprint_prefixes

    app_init = tmp_path / "app" / "__init__.py"
    app_init.parent.mkdir(parents=True)
    app_init.write_text(
        "from flask import Flask\n"
        "from app.blueprints.items import items_bp\n"
        "from app.blueprints.warehouses import warehouses_bp\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        '    app.register_blueprint(items_bp, url_prefix="/items")\n'
        '    app.register_blueprint(warehouses_bp, url_prefix="/warehouses")\n'
        "    return app\n"
    )

    items_file = tmp_path / "app" / "blueprints" / "items.py"
    items_file.parent.mkdir(parents=True)
    items_file.write_text('items_bp = Blueprint("items", __name__)\n')

    warehouses_file = tmp_path / "app" / "blueprints" / "warehouses.py"
    warehouses_file.write_text('warehouses_bp = Blueprint("warehouses", __name__)\n')

    from app.models.graph import SymbolGraph

    graph = SymbolGraph()
    graph.add_node(
        GraphNode(
            fqn="app.blueprints.items.items_bp",
            name="items_bp",
            kind=NodeKind.FIELD,
            language="python",
            path=str(items_file),
            properties={"value": 'Blueprint("items", __name__)'},
        )
    )
    graph.add_node(
        GraphNode(
            fqn="app.blueprints.warehouses.warehouses_bp",
            name="warehouses_bp",
            kind=NodeKind.FIELD,
            language="python",
            path=str(warehouses_file),
            properties={"value": 'Blueprint("warehouses", __name__)'},
        )
    )

    result = resolve_blueprint_prefixes(graph, project_root=str(tmp_path))

    assert result == {"items_bp": "/items", "warehouses_bp": "/warehouses"}


def test_resolve_blueprint_prefixes_prefers_registration_over_constructor(tmp_path):
    from app.stages.plugins.flask_plugin.blueprints import resolve_blueprint_prefixes

    app_init = tmp_path / "app" / "__init__.py"
    app_init.parent.mkdir(parents=True)
    app_init.write_text('app.register_blueprint(items_bp, url_prefix="/v2/items")\n')
    items_file = tmp_path / "app" / "items.py"
    items_file.write_text('items_bp = Blueprint("items", __name__, url_prefix="/v1")\n')

    from app.models.graph import SymbolGraph

    graph = SymbolGraph()
    graph.add_node(
        GraphNode(
            fqn="app.items.items_bp",
            name="items_bp",
            kind=NodeKind.FIELD,
            language="python",
            path=str(items_file),
            properties={"value": 'Blueprint("items", __name__, url_prefix="/v1")'},
        )
    )

    result = resolve_blueprint_prefixes(graph, project_root=str(tmp_path))

    assert result["items_bp"] == "/v2/items"


def test_resolve_blueprint_prefixes_falls_back_to_constructor(tmp_path):
    from app.stages.plugins.flask_plugin.blueprints import resolve_blueprint_prefixes

    items_file = tmp_path / "app" / "items.py"
    items_file.parent.mkdir(parents=True)
    items_file.write_text('bp = Blueprint("x", __name__, url_prefix="/only")\n')

    from app.models.graph import SymbolGraph

    graph = SymbolGraph()
    graph.add_node(
        GraphNode(
            fqn="app.items.bp",
            name="bp",
            kind=NodeKind.FIELD,
            language="python",
            path=str(items_file),
            properties={"value": 'Blueprint("x", __name__, url_prefix="/only")'},
        )
    )

    result = resolve_blueprint_prefixes(graph, project_root=str(tmp_path))

    assert result == {"bp": "/only"}
