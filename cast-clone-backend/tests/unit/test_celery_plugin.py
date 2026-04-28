"""Unit tests for CeleryPlugin (M3)."""

from __future__ import annotations

import pytest

from app.models.context import AnalysisContext
from app.models.enums import (
    Confidence,
    EdgeKind,  # noqa: F401  -- used in forthcoming M3 tasks
    NodeKind,
)
from app.models.graph import (
    GraphEdge,  # noqa: F401  -- used in forthcoming M3 tasks
    GraphNode,
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


def test_detect_high_when_shared_task_decorator_present():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    task = GraphNode(
        fqn="posts.tasks.notify",
        name="notify",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@shared_task(queue="notifications")']},
    )
    ctx.graph.add_node(task)

    result = CeleryPlugin().detect(ctx)

    assert result.confidence == Confidence.HIGH


def test_detect_high_for_app_task_and_celery_task_variants():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="a.b",
            name="b",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ["@app.task"]},
        )
    )

    assert CeleryPlugin().detect(ctx).confidence == Confidence.HIGH

    ctx2 = _ctx()
    ctx2.graph.add_node(
        GraphNode(
            fqn="c.d",
            name="d",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ["@celery.task(bind=True)"]},
        )
    )

    assert CeleryPlugin().detect(ctx2).confidence == Confidence.HIGH


@pytest.mark.asyncio
async def test_extract_tags_task_functions_and_emits_entry_points():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    task = GraphNode(
        fqn="posts.tasks.notify_post_published",
        name="notify_post_published",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@shared_task(queue="notifications")']},
    )
    non_task = GraphNode(
        fqn="posts.tasks.helper",
        name="helper",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": []},
    )
    ctx.graph.add_node(task)
    ctx.graph.add_node(non_task)

    result = await CeleryPlugin().extract(ctx)

    updated = ctx.graph.get_node(task.fqn)
    assert updated.properties.get("framework") == "celery"
    assert updated.properties.get("is_message_consumer") is True
    assert updated.properties.get("task_name") == "notify_post_published"

    other = ctx.graph.get_node(non_task.fqn)
    assert other.properties.get("framework") != "celery"

    assert any(
        ep.fqn == task.fqn and ep.kind == "message_consumer"
        for ep in result.entry_points
    )
    assert result.layer_assignments.get(task.fqn) == "Business Logic"
