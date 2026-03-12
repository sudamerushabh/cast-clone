"""Plugin registry: discovery, detection, topological sort, and execution.

The registry manages the full plugin lifecycle:
1. Registration -- plugins register via decorator or explicit call
2. Detection -- each plugin's detect() determines relevance (HIGH/MEDIUM activate)
3. Ordering -- topological sort on depends_on; independent plugins concurrent
4. Execution -- plugins run in dependency order; concurrent within each layer
5. Merging -- results are merged into AnalysisContext
6. Error handling -- failed plugins skip themselves AND all dependents

Usage:
    # Option 1: Module-level global registry (for production)
    from app.stages.plugins.registry import global_registry, run_framework_plugins

    @global_registry.register
    class MyPlugin(FrameworkPlugin): ...

    await run_framework_plugins(context)  # uses global_registry by default

    # Option 2: Explicit registry (for testing)
    registry = PluginRegistry()
    registry.register(MyPlugin)
    await run_framework_plugins(context, registry=registry)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any

import structlog

from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Plugin Registry
# ---------------------------------------------------------------------------


class PluginRegistry:
    """Stores registered plugin classes and instantiates them on demand."""

    def __init__(self) -> None:
        self._plugin_classes: list[type[FrameworkPlugin]] = []
        self._by_name: dict[str, type[FrameworkPlugin]] = {}

    @property
    def plugin_classes(self) -> list[type[FrameworkPlugin]]:
        return list(self._plugin_classes)

    def register(self, plugin_class: type[FrameworkPlugin]) -> type[FrameworkPlugin]:
        """Register a plugin class. Works as a decorator or called directly.

        If a plugin with the same name is already registered, the old one
        is replaced.

        Returns:
            The plugin class (unchanged), so this works as a decorator.
        """
        name = plugin_class.name
        if name in self._by_name:
            # Replace existing registration
            self._plugin_classes = [
                cls for cls in self._plugin_classes if cls.name != name
            ]
            logger.warning("plugin_replaced", plugin_name=name)
        self._plugin_classes.append(plugin_class)
        self._by_name[name] = plugin_class
        logger.debug(
            "plugin_registered",
            plugin_name=name,
            version=plugin_class.version,
        )
        return plugin_class

    def instantiate(self) -> list[FrameworkPlugin]:
        """Create instances of all registered plugin classes."""
        return [cls() for cls in self._plugin_classes]


# Module-level global registry for production use
global_registry = PluginRegistry()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _detect_plugins(
    context: Any,
    plugins: list[FrameworkPlugin],
) -> list[FrameworkPlugin]:
    """Run detect() on each plugin, return those that are active.

    If a plugin's detect() raises, it is skipped with a warning.
    LOW confidence and not-detected plugins are excluded.
    """
    active: list[FrameworkPlugin] = []
    for plugin in plugins:
        try:
            result: PluginDetectionResult = plugin.detect(context)
            if result.is_active:
                logger.info(
                    "plugin_detected",
                    plugin_name=plugin.name,
                    confidence=(
                        result.confidence.name if result.confidence else "NONE"
                    ),
                    reason=result.reason,
                )
                active.append(plugin)
            else:
                logger.debug(
                    "plugin_skipped",
                    plugin_name=plugin.name,
                    confidence=(
                        result.confidence.name if result.confidence else "NONE"
                    ),
                    reason=result.reason,
                )
        except Exception:
            logger.exception("plugin_detect_failed", plugin_name=plugin.name)
    return active


# ---------------------------------------------------------------------------
# Topological Sort
# ---------------------------------------------------------------------------


def _topological_sort(
    plugins: list[FrameworkPlugin],
) -> list[list[FrameworkPlugin]]:
    """Sort plugins into layers by dependency order (Kahn's algorithm).

    Returns a list of layers. Each layer contains plugins that can run
    concurrently (all their dependencies are in earlier layers).

    Plugins with missing dependencies are excluded with a warning.
    Raises ValueError if a circular dependency is detected.
    """
    if not plugins:
        return []

    # Build lookup
    by_name: dict[str, FrameworkPlugin] = {p.name: p for p in plugins}
    available_names = set(by_name.keys())

    # Exclude plugins with missing dependencies
    excluded: set[str] = set()

    def _find_excluded() -> bool:
        """One pass: find plugins whose deps are missing or excluded."""
        found = False
        for p in plugins:
            if p.name in excluded:
                continue
            for dep in p.depends_on:
                if dep not in available_names or dep in excluded:
                    logger.warning(
                        "plugin_excluded_missing_dep",
                        plugin_name=p.name,
                        missing_dependency=dep,
                    )
                    excluded.add(p.name)
                    found = True
                    break
        return found

    # Iterate until stable (cascading exclusions)
    while _find_excluded():
        pass

    remaining = [p for p in plugins if p.name not in excluded]
    if not remaining:
        return []

    # Kahn's algorithm with layering
    in_degree: dict[str, int] = {p.name: 0 for p in remaining}
    dependents: dict[str, list[str]] = defaultdict(list)

    for p in remaining:
        for dep in p.depends_on:
            if dep not in excluded:
                in_degree[p.name] += 1
                dependents[dep].append(p.name)

    # Initial layer: all plugins with in_degree 0
    current_layer_names = deque(name for name, deg in in_degree.items() if deg == 0)
    layers: list[list[FrameworkPlugin]] = []
    processed = 0

    while current_layer_names:
        layer: list[FrameworkPlugin] = []
        next_layer_names: list[str] = []

        while current_layer_names:
            name = current_layer_names.popleft()
            layer.append(by_name[name])
            processed += 1

            for dependent_name in dependents[name]:
                in_degree[dependent_name] -= 1
                if in_degree[dependent_name] == 0:
                    next_layer_names.append(dependent_name)

        layers.append(layer)
        current_layer_names = deque(next_layer_names)

    if processed < len(remaining):
        cycle_members = [p.name for p in remaining if in_degree.get(p.name, 0) > 0]
        raise ValueError(f"Circular dependency detected among plugins: {cycle_members}")

    return layers


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


async def _execute_plugin(
    plugin: FrameworkPlugin,
    context: Any,
) -> tuple[str, PluginResult | None, Exception | None]:
    """Execute a single plugin's extract() with error handling.

    Returns:
        (plugin_name, result_or_none, exception_or_none)
    """
    try:
        logger.info("plugin_extract_start", plugin_name=plugin.name)
        result = await plugin.extract(context)
        logger.info(
            "plugin_extract_complete",
            plugin_name=plugin.name,
            nodes=result.node_count,
            edges=result.edge_count,
            warnings=len(result.warnings),
        )
        return (plugin.name, result, None)
    except Exception as exc:
        logger.exception("plugin_extract_failed", plugin_name=plugin.name)
        return (plugin.name, None, exc)


def _merge_result(context: Any, result: PluginResult) -> None:
    """Merge a single PluginResult into the AnalysisContext.

    Adds nodes and edges to context.graph, updates counters, collects
    entry points, layer assignments, and warnings.
    """
    for node in result.nodes:
        context.graph.add_node(node)
    for edge in result.edges:
        context.graph.add_edge(edge)

    context.plugin_new_nodes += result.node_count
    context.plugin_new_edges += result.edge_count
    context.entry_points.extend(result.entry_points)
    context.warnings.extend(result.warnings)

    # Layer assignments: stored on context if the attribute exists
    if hasattr(context, "layer_assignments"):
        context.layer_assignments.update(result.layer_assignments)


async def run_framework_plugins(
    context: Any,
    *,
    registry: PluginRegistry | None = None,
) -> None:
    """Main entry point: discover, detect, order, execute, and merge plugins.

    This is Stage 5 of the analysis pipeline.

    Args:
        context: AnalysisContext for the current project.
        registry: Optional explicit registry. Defaults to global_registry.
    """
    reg = registry or global_registry
    logger.info("plugin_stage_start", registered_count=len(reg.plugin_classes))

    # 1. Instantiate all registered plugins
    all_plugins = reg.instantiate()
    if not all_plugins:
        logger.info("plugin_stage_complete", message="no plugins registered")
        return

    # 2. Detection: filter to active plugins
    active_plugins = _detect_plugins(context, all_plugins)
    if not active_plugins:
        logger.info(
            "plugin_stage_complete",
            message="no plugins detected for this project",
        )
        return

    logger.info(
        "plugins_detected",
        active=[p.name for p in active_plugins],
        skipped=[p.name for p in all_plugins if p not in active_plugins],
    )

    # 3. Topological sort into dependency layers
    try:
        layers = _topological_sort(active_plugins)
    except ValueError as exc:
        context.warnings.append(f"Plugin ordering failed: {exc}")
        logger.error("plugin_topological_sort_failed", error=str(exc))
        return

    # 4. Execute layer by layer
    failed_plugins: set[str] = set()

    for layer_idx, layer in enumerate(layers):
        # Filter out plugins whose dependencies failed
        runnable = [
            p for p in layer if not any(dep in failed_plugins for dep in p.depends_on)
        ]
        skipped = [p for p in layer if p not in runnable]

        for p in skipped:
            failed_plugins.add(p.name)
            msg = f"Plugin {p.name!r} skipped: dependency failed"
            context.warnings.append(msg)
            logger.warning("plugin_skipped_dep_failed", plugin_name=p.name)

        if not runnable:
            continue

        logger.info(
            "plugin_layer_start",
            layer=layer_idx,
            plugins=[p.name for p in runnable],
        )

        # Run all plugins in this layer concurrently
        tasks = [_execute_plugin(p, context) for p in runnable]
        results = await asyncio.gather(*tasks)

        # Process results
        for plugin_name, result, exc in results:
            if exc is not None:
                failed_plugins.add(plugin_name)
                msg = f"Plugin {plugin_name!r} failed: {exc}"
                context.warnings.append(msg)
            elif result is not None:
                _merge_result(context, result)

    logger.info(
        "plugin_stage_complete",
        total_new_nodes=context.plugin_new_nodes,
        total_new_edges=context.plugin_new_edges,
        failed_plugins=list(failed_plugins),
    )
