"""Framework plugin system for extracting invisible connections from code.

Plugins detect framework usage, extract hidden relationships (DI wiring,
ORM mappings, endpoint routes), and produce new graph nodes and edges.
"""

from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)
from app.stages.plugins.registry import (
    PluginRegistry,
    global_registry,
    run_framework_plugins,
)

__all__ = [
    "FrameworkPlugin",
    "LayerRule",
    "LayerRules",
    "PluginDetectionResult",
    "PluginRegistry",
    "PluginResult",
    "global_registry",
    "run_framework_plugins",
]
