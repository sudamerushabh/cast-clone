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
