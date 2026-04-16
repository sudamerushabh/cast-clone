"""Spring Scheduling and Async plugin.

Detects Spring scheduling and async execution patterns:
- @Scheduled methods (cron, fixedRate, fixedDelay)
- @Async methods (called via proxy, executed in thread pool)

These methods are invoked by the Spring framework itself at runtime —
they have no explicit caller in the source code, making them invisible
entry points for transaction flow analysis.

Produces:
- Entry points with kind="scheduled" or kind="async"
- Layer assignments for classes containing scheduled/async methods
"""

from __future__ import annotations

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

_SCHEDULING_ANNOTATIONS = frozenset({
    "Scheduled",
    "Schedules",  # Container for repeatable @Scheduled
})

_ASYNC_ANNOTATIONS = frozenset({
    "Async",
})

_ALL_ANNOTATIONS = _SCHEDULING_ANNOTATIONS | _ASYNC_ANNOTATIONS


class SpringSchedulingPlugin(FrameworkPlugin):
    name = "spring-scheduling"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = ["spring-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        for node in context.graph.nodes.values():
            annotations = node.properties.get("annotations", [])
            if any(a in _ALL_ANNOTATIONS for a in annotations):
                matched = [
                    a for a in annotations
                    if a in _ALL_ANNOTATIONS
                ]
                return PluginDetectionResult(
                    confidence=Confidence.HIGH,
                    reason=f"Scheduling annotations: {matched}",
                )

        # Check for @EnableScheduling or @EnableAsync on config classes
        for node in context.graph.nodes.values():
            if node.kind != NodeKind.CLASS:
                continue
            annotations = node.properties.get("annotations", [])
            if "EnableScheduling" in annotations or "EnableAsync" in annotations:
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="@EnableScheduling or @EnableAsync found",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("spring_scheduling_extract_start")

        graph = context.graph
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        scheduled_count = 0
        async_count = 0

        for node in graph.nodes.values():
            if node.kind != NodeKind.FUNCTION:
                continue
            annotations = node.properties.get("annotations", [])
            ann_args = node.properties.get("annotation_params", {})

            # Handle @Scheduled methods
            if any(a in _SCHEDULING_ANNOTATIONS for a in annotations):
                metadata = self._extract_schedule_metadata(ann_args)
                metadata["framework"] = "spring"

                entry_points.append(EntryPoint(
                    fqn=node.fqn,
                    kind="scheduled",
                    metadata=metadata,
                ))
                scheduled_count += 1

                # Assign containing class to "Background Processing" layer
                class_fqn = node.fqn.rsplit(".", 1)[0]
                if class_fqn not in layer_assignments:
                    layer_assignments[class_fqn] = "Background Processing"

            # Handle @Async methods
            if any(a in _ASYNC_ANNOTATIONS for a in annotations):
                metadata = {"framework": "spring"}

                # Check for custom executor name
                async_arg = ann_args.get("Async")
                if isinstance(async_arg, str) and async_arg:
                    metadata["executor"] = async_arg
                elif isinstance(async_arg, dict):
                    executor = async_arg.get("value")
                    if isinstance(executor, str) and executor:
                        metadata["executor"] = executor

                entry_points.append(EntryPoint(
                    fqn=node.fqn,
                    kind="async",
                    metadata=metadata,
                ))
                async_count += 1

                # Mark callers: any CALLS edge targeting this @Async method
                # goes through Spring's proxy — flag it for awareness
                for edge in graph.get_edges_to(node.fqn):
                    if edge.kind == EdgeKind.CALLS:
                        # Add a property to indicate this call is async
                        edge.properties["is_async_call"] = True

        log.info(
            "spring_scheduling_extract_complete",
            scheduled=scheduled_count,
            async_methods=async_count,
        )

        return PluginResult(
            nodes=[],
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=warnings,
        )

    def _extract_schedule_metadata(
        self, ann_args: dict
    ) -> dict[str, str]:
        """Extract scheduling configuration from @Scheduled annotation args.

        Handles:
        - @Scheduled(fixedRate = 5000)
        - @Scheduled(fixedDelay = 1000)
        - @Scheduled(cron = "0 0 * * * *")
        - @Scheduled(initialDelay = 1000, fixedRate = 5000)
        """
        metadata: dict[str, str] = {}
        sched_arg = ann_args.get("Scheduled")

        if sched_arg is None:
            return metadata

        if isinstance(sched_arg, str):
            # Bare value — likely cron expression
            metadata["cron"] = sched_arg
        elif isinstance(sched_arg, dict):
            for key in ("cron", "fixedRate", "fixedDelay", "initialDelay", "zone"):
                val = sched_arg.get(key)
                if val is not None:
                    metadata[key] = str(val)

        return metadata
