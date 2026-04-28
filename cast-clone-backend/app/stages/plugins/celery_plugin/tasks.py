"""Celery task discovery and queue extraction (M3).

Discovers Celery tasks via @celery.task, @shared_task, and @app.task
decorators; extracts the ``queue=`` kwarg; emits MESSAGE_TOPIC nodes and
CONSUMES edges from each task to its queue; registers each task as a
message-consumer EntryPoint.

Producer linking lives in producers.py.
"""

from __future__ import annotations

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence  # noqa: F401  -- used in forthcoming M3 tasks
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,  # noqa: F401  -- used in forthcoming M3 tasks
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()


class CeleryPlugin(FrameworkPlugin):
    name = "celery"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        return PluginResult.empty()

    def get_layer_classification(self) -> LayerRules:
        return LayerRules.empty()
