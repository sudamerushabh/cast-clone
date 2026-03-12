"""Django URLs plugin -- path(), re_path(), include() resolution.

Scans urlpatterns fields in url modules, parses path/re_path/include calls
from the value string, and creates API_ENDPOINT nodes with HANDLES edges
to their view functions or class-based views.

Produces:
- API_ENDPOINT nodes: one per URL pattern with path info
- HANDLES edges: (:API_ENDPOINT)-[:HANDLES]->(:FUNCTION|:CLASS)
- Entry points for transaction discovery
- Layer assignments: view functions/classes -> Presentation
"""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Regex patterns for URL pattern parsing
# ---------------------------------------------------------------------------

_PATH_RE = re.compile(r'path\(\s*["\']([^"\']*)["\'],\s*([^,\)]+)')
_INCLUDE_RE = re.compile(r'include\(\s*["\']([^"\']+)["\']')
_AS_VIEW_RE = re.compile(r'(\w+)\.as_view\(\)')


class DjangoURLsPlugin(FrameworkPlugin):
    """Resolves Django URL patterns into API_ENDPOINT nodes."""

    name = "django-urls"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = ["django-settings"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "django" in fw.name.lower() and "rest" not in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: look for urlpatterns fields in graph
        for node in context.graph.nodes.values():
            if (
                node.kind == NodeKind.FIELD
                and node.language == "python"
                and node.name == "urlpatterns"
            ):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="urlpatterns field found in graph",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("django_urls_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        # Collect all urlpatterns modules and their raw values
        url_modules = self._find_urlpattern_modules(graph)
        log.info("django_url_modules_found", count=len(url_modules))

        # Build include map: module_fqn -> prefix from parent includes
        # First pass: find all include() references to build prefix chains
        include_prefixes = self._resolve_include_prefixes(graph, url_modules)

        # Second pass: extract path() calls from each module
        for module_fqn, urlpatterns_value in url_modules.items():
            prefix = include_prefixes.get(module_fqn, "")
            self._extract_paths_from_module(
                graph=graph,
                module_fqn=module_fqn,
                urlpatterns_value=urlpatterns_value,
                prefix=prefix,
                nodes=nodes,
                edges=edges,
                entry_points=entry_points,
                layer_assignments=layer_assignments,
                warnings=warnings,
            )

        log.info(
            "django_urls_extract_complete",
            endpoints=len(nodes),
            handles_edges=len([e for e in edges if e.kind == EdgeKind.HANDLES]),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_urlpattern_modules(
        self, graph: SymbolGraph
    ) -> dict[str, str]:
        """Find modules with urlpatterns fields; return {module_fqn: value}."""
        result: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind != NodeKind.FIELD or node.name != "urlpatterns":
                continue
            value = node.properties.get("value", "")
            # Find parent module via CONTAINS edge
            for edge in graph.edges:
                if edge.target_fqn == node.fqn and edge.kind == EdgeKind.CONTAINS:
                    parent = graph.nodes.get(edge.source_fqn)
                    if parent and parent.kind == NodeKind.MODULE:
                        result[edge.source_fqn] = value
                    break
        return result

    def _resolve_include_prefixes(
        self,
        graph: SymbolGraph,
        url_modules: dict[str, str],
    ) -> dict[str, str]:
        """Build a map of module_fqn -> URL prefix from include() chains.

        Scans all urlpatterns for include() calls and tracks the prefix
        that each included module should inherit.
        """
        prefixes: dict[str, str] = {}

        for module_fqn, value in url_modules.items():
            # Find path("prefix/", include("other.urls")) patterns
            for match in _PATH_RE.finditer(value):
                url_pattern = match.group(1)
                view_ref = match.group(2).strip()

                include_match = _INCLUDE_RE.search(view_ref)
                if include_match:
                    included_module = include_match.group(1)
                    # The prefix for the included module is the current
                    # module's own prefix plus this path segment
                    parent_prefix = prefixes.get(module_fqn, "")
                    prefixes[included_module] = parent_prefix + "/" + url_pattern

        return prefixes

    def _extract_paths_from_module(
        self,
        *,
        graph: SymbolGraph,
        module_fqn: str,
        urlpatterns_value: str,
        prefix: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        entry_points: list[EntryPoint],
        layer_assignments: dict[str, str],
        warnings: list[str],
    ) -> None:
        """Extract path() calls from a single module's urlpatterns value."""
        # Derive the app module prefix (e.g., "myapp.urls" -> "myapp")
        parts = module_fqn.rsplit(".", 1)
        app_prefix = parts[0] if len(parts) > 1 else module_fqn

        for match in _PATH_RE.finditer(urlpatterns_value):
            url_pattern = match.group(1)
            view_ref = match.group(2).strip()

            # Skip include() calls -- they're handled by prefix resolution
            if _INCLUDE_RE.search(view_ref):
                continue

            # Build full path
            full_path = self._normalize_path(prefix + "/" + url_pattern)

            # Resolve view reference to a graph node
            view_fqn = self._resolve_view_ref(graph, app_prefix, view_ref)

            # Create endpoint FQN
            endpoint_fqn = f"endpoint:{module_fqn}:{url_pattern or '/'}"

            endpoint_node = GraphNode(
                fqn=endpoint_fqn,
                name=full_path,
                kind=NodeKind.API_ENDPOINT,
                language="python",
                properties={
                    "path": full_path,
                    "method": "ANY",
                    "framework": "django",
                    "module": module_fqn,
                },
            )
            nodes.append(endpoint_node)

            # Create HANDLES edge if we resolved the view
            if view_fqn:
                edges.append(GraphEdge(
                    source_fqn=endpoint_fqn,
                    target_fqn=view_fqn,
                    kind=EdgeKind.HANDLES,
                    confidence=Confidence.HIGH,
                    evidence="django-urls",
                ))
                # Assign Presentation layer to the view
                layer_assignments[view_fqn] = "Presentation"

            # Create entry point
            entry_points.append(EntryPoint(
                fqn=endpoint_fqn,
                kind="http_endpoint",
                metadata={"path": full_path, "method": "ANY"},
            ))

    def _resolve_view_ref(
        self, graph: SymbolGraph, app_prefix: str, view_ref: str
    ) -> str | None:
        """Resolve a view reference string to a graph node FQN.

        Handles:
        - views.user_list -> {app_prefix}.views.user_list
        - UserListView.as_view() -> search by class name
        - Direct dotted references
        """
        # Check for class-based view: ClassName.as_view()
        as_view_match = _AS_VIEW_RE.match(view_ref)
        if as_view_match:
            class_name = as_view_match.group(1)
            # Try fully qualified lookup first
            candidate = f"{app_prefix}.views.{class_name}"
            if graph.get_node(candidate):
                return candidate
            # Search all nodes by name
            for node in graph.nodes.values():
                if node.name == class_name and node.kind == NodeKind.CLASS:
                    return node.fqn
            return None

        # Function-based view: views.func_name or module.func_name
        # Strip whitespace and trailing parens if any
        view_ref = view_ref.strip().rstrip(")")
        if "." in view_ref:
            # e.g., "views.user_list" -> try "{app_prefix}.views.user_list"
            ref_parts = view_ref.split(".", 1)
            candidate = f"{app_prefix}.{ref_parts[0]}.{ref_parts[1]}"
            if graph.get_node(candidate):
                return candidate

        # Try direct FQN lookup
        if graph.get_node(view_ref):
            return view_ref

        # Search by function name (last part)
        func_name = view_ref.rsplit(".", 1)[-1]
        for node in graph.nodes.values():
            if node.name == func_name and node.kind == NodeKind.FUNCTION:
                return node.fqn

        return None

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize a URL path: collapse slashes, ensure leading slash."""
        # Replace multiple slashes with single
        while "//" in path:
            path = path.replace("//", "/")
        # Ensure leading slash
        if not path.startswith("/"):
            path = "/" + path
        return path
