"""Django Settings plugin.

Scans for Django settings modules (files containing INSTALLED_APPS,
DATABASES, MIDDLEWARE, ROOT_URLCONF) and extracts configuration entries
as CONFIG_FILE and CONFIG_ENTRY nodes. Downstream plugins (django-urls,
django-orm, django-drf) read these entries to resolve app labels,
URL root, and database configuration.

Produces:
- CONFIG_FILE nodes: one per settings module
- CONFIG_ENTRY nodes: one per key setting (INSTALLED_APPS, ROOT_URLCONF, etc.)
- CONTAINS edges: (:CONFIG_FILE)-[:CONTAINS]->(:CONFIG_ENTRY)
"""

from __future__ import annotations

import ast
from typing import Any

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Settings keys we care about
_DJANGO_SETTINGS_KEYS = frozenset(
    {
        "INSTALLED_APPS",
        "ROOT_URLCONF",
        "DATABASES",
        "MIDDLEWARE",
        "DEFAULT_AUTO_FIELD",
        "AUTH_USER_MODEL",
    }
)


def parse_installed_apps(raw_value: str) -> list[str]:
    """Parse an INSTALLED_APPS RHS into a list of app names.

    Uses ``ast.literal_eval`` (stdlib safe parser that only accepts literal
    Python values and refuses arbitrary code) so the RHS cannot execute.
    Drops non-string entries (e.g. int, dict) to keep the caller's type sane.
    Returns [] on any parse failure.
    """
    if not raw_value.strip():
        return []
    try:
        parsed = ast.literal_eval(raw_value)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(parsed, (list, tuple)):
        return []
    return [item for item in parsed if isinstance(item, str)]


def parse_databases(raw_value: str) -> dict[str, str]:
    """Parse a DATABASES RHS, returning structured keys for the default conn.

    Output keys (all optional, present only if the setting supplied them):
    - default_engine
    - default_name
    - default_host
    - default_port

    Returns {} on malformed input or missing "default" key.
    """
    if not raw_value.strip():
        return {}
    try:
        parsed = ast.literal_eval(raw_value)
    except (ValueError, SyntaxError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    default = parsed.get("default")
    if not isinstance(default, dict):
        return {}

    mapping = {
        "ENGINE": "default_engine",
        "NAME": "default_name",
        "HOST": "default_host",
        "PORT": "default_port",
    }
    out: dict[str, str] = {}
    for django_key, out_key in mapping.items():
        value = default.get(django_key)
        if isinstance(value, str):
            out[out_key] = value
    return out


class DjangoSettingsPlugin(FrameworkPlugin):
    name = "django-settings"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "django" in fw.name.lower() and "rest" not in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: look for INSTALLED_APPS field in graph
        for node in context.graph.nodes.values():
            if (
                node.kind == NodeKind.FIELD
                and node.language == "python"
                and node.name == "INSTALLED_APPS"
            ):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="INSTALLED_APPS field found in graph",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("django_settings_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []

        # Find settings modules: modules containing INSTALLED_APPS field
        settings_modules = self._find_settings_modules(graph)
        log.info("django_settings_modules_found", count=len(settings_modules))

        for module_fqn in settings_modules:
            # Create CONFIG_FILE node
            config_file_fqn = f"config:{module_fqn}"
            config_file = GraphNode(
                fqn=config_file_fqn,
                name=module_fqn.split(".")[-1],
                kind=NodeKind.CONFIG_FILE,
                language="python",
                properties={"module_fqn": module_fqn},
            )
            nodes.append(config_file)

            # Extract settings entries
            for field_fqn, field_node in self._get_settings_fields(graph, module_fqn):
                raw_value = field_node.properties.get("value", "")
                entry_properties: dict[str, Any] = {
                    "value": raw_value,
                    "setting_key": field_node.name,
                }
                if field_node.name == "INSTALLED_APPS":
                    entry_properties["apps"] = parse_installed_apps(raw_value)
                elif field_node.name == "DATABASES":
                    entry_properties.update(parse_databases(raw_value))

                entry_fqn = f"config:{module_fqn}.{field_node.name}"
                entry = GraphNode(
                    fqn=entry_fqn,
                    name=field_node.name,
                    kind=NodeKind.CONFIG_ENTRY,
                    language="python",
                    properties=entry_properties,
                )
                nodes.append(entry)
                edges.append(
                    GraphEdge(
                        source_fqn=config_file_fqn,
                        target_fqn=entry_fqn,
                        kind=EdgeKind.CONTAINS,
                        confidence=Confidence.HIGH,
                        evidence="django-settings",
                    )
                )

        log.info(
            "django_settings_extract_complete",
            entries=len(nodes) - len(settings_modules),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_settings_modules(self, graph: SymbolGraph) -> list[str]:
        """Find module FQNs that contain INSTALLED_APPS."""
        modules: set[str] = set()
        for node in graph.nodes.values():
            if node.kind != NodeKind.FIELD or node.name != "INSTALLED_APPS":
                continue
            # Find parent module via CONTAINS edge (indexed lookup)
            for edge in graph.get_edges_to(node.fqn):
                if edge.kind == EdgeKind.CONTAINS:
                    parent = graph.nodes.get(edge.source_fqn)
                    if parent and parent.kind == NodeKind.MODULE:
                        modules.add(edge.source_fqn)
                    break
        return sorted(modules)

    def _get_settings_fields(
        self, graph: SymbolGraph, module_fqn: str
    ) -> list[tuple[str, GraphNode]]:
        """Get Django settings fields from a module."""
        fields: list[tuple[str, GraphNode]] = []
        for edge in graph.get_edges_from(module_fqn):
            if edge.kind != EdgeKind.CONTAINS:
                continue
            field_node = graph.nodes.get(edge.target_fqn)
            if (
                field_node
                and field_node.kind == NodeKind.FIELD
                and field_node.name in _DJANGO_SETTINGS_KEYS
            ):
                fields.append((edge.target_fqn, field_node))
        return fields
