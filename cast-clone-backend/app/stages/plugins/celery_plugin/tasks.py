"""Celery task discovery and queue extraction (M3)."""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, NodeKind
from app.models.graph import GraphNode, SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

_TASK_DECORATOR_RE = re.compile(
    r"^@(?:shared_task|celery\.task|app\.task)\b"
)


def _find_task_functions(graph: SymbolGraph) -> list[GraphNode]:
    """Return FUNCTION nodes whose annotations include a Celery task decorator."""
    results: list[GraphNode] = []
    for node in graph.nodes.values():
        if node.kind != NodeKind.FUNCTION or node.language != "python":
            continue
        for deco in node.properties.get("annotations", []):
            if _TASK_DECORATOR_RE.match(deco):
                results.append(node)
                break
    return results


class CeleryPlugin(FrameworkPlugin):
    name = "celery"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        tasks = _find_task_functions(context.graph)
        if tasks:
            return PluginDetectionResult(
                confidence=Confidence.HIGH,
                reason=f"Celery task decorators found ({len(tasks)} tasks)",
            )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("celery_extract_start")

        graph = context.graph
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}

        tasks = _find_task_functions(graph)
        for task in tasks:
            task.properties["framework"] = "celery"
            task.properties["is_message_consumer"] = True
            task.properties["task_name"] = task.name
            entry_points.append(
                EntryPoint(
                    fqn=task.fqn,
                    kind="message_consumer",
                    metadata={"task_name": task.name},
                )
            )
            layer_assignments[task.fqn] = "Business Logic"

        log.info("celery_extract_complete", tasks=len(tasks))
        return PluginResult(
            nodes=[],
            edges=[],
            entry_points=entry_points,
            layer_assignments=layer_assignments,
            warnings=[],
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(
            rules=[
                LayerRule(pattern="@shared_task", layer="Business Logic"),
                LayerRule(pattern="@celery.task", layer="Business Logic"),
                LayerRule(pattern="@app.task", layer="Business Logic"),
            ]
        )
