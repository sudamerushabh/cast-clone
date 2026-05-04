"""Unit tests for FlaskPlugin (M4)."""

from __future__ import annotations

from app.models.context import AnalysisContext
from app.models.enums import Confidence, NodeKind
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
