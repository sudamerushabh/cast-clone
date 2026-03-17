"""ASP.NET Core Middleware Pipeline plugin.

Extracts middleware ordering from Program.cs / Startup.cs and validates
the pipeline configuration. Scans for app.Use*() calls stored as the
``middleware_calls`` property on Program/Startup class nodes.

Produces:
- MIDDLEWARE_CHAIN edges between consecutive middleware entries
- HANDLES edges from custom middleware classes to their pipeline position
- Technology COMPONENT nodes for well-known middleware
- Terminal middleware detection (MapControllers, MapHub<T>, etc.)
- Warnings when middleware ordering violates best practices:
  - UseAuthorization before UseAuthentication
  - UseCors after UseAuthentication
"""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

_USE_MIDDLEWARE_RE = re.compile(r"^UseMiddleware<(\w+)>$")

_TECHNOLOGY_MAP: dict[str, str] = {
    "UseAuthentication": "Authentication",
    "UseAuthorization": "Authorization",
    "UseCors": "CORS",
    "UseRateLimiter": "Rate Limiting",
    "UseResponseCaching": "Response Caching",
    "UseHttpsRedirection": "HTTPS Redirection",
    "UseStaticFiles": "Static Files",
    "UseHsts": "HSTS",
}

_TERMINAL_MIDDLEWARE = frozenset({"MapControllers", "MapRazorPages"})
_TERMINAL_GENERIC_RE = re.compile(r"^(MapHub|MapGrpcService)<(\w+)>$")


class ASPNetMiddlewarePlugin(FrameworkPlugin):
    name = "aspnet-middleware"
    version = "1.0.0"
    supported_languages = {"csharp"}
    depends_on: list[str] = ["aspnet-di"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        """Detect ASP.NET Core by checking manifest for aspnet framework."""
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "aspnet" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: check graph for middleware_calls property
        for node in context.graph.nodes.values():
            if node.properties.get("middleware_calls"):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="Middleware calls found in graph nodes",
                )

        return PluginDetectionResult.not_detected()

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[
            LayerRule(pattern="Middleware", layer="Cross-Cutting"),
        ])

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("aspnet_middleware_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []
        layer_assignments: dict[str, str] = {}

        for node in graph.nodes.values():
            middleware_calls = node.properties.get("middleware_calls")
            if not middleware_calls:
                continue

            log.info(
                "aspnet_middleware_found",
                class_fqn=node.fqn,
                count=len(middleware_calls),
            )

            # Create middleware component nodes
            mw_fqns: list[str] = []
            for i, mw_name in enumerate(middleware_calls):
                mw_fqn = f"{node.fqn}::middleware::{mw_name}"
                mw_fqns.append(mw_fqn)

                is_terminal = mw_name in _TERMINAL_MIDDLEWARE
                generic_match = _TERMINAL_GENERIC_RE.match(mw_name)

                mw_node = GraphNode(
                    fqn=mw_fqn,
                    name=mw_name,
                    kind=NodeKind.COMPONENT,
                    language="csharp",
                    properties={
                        "middleware_name": mw_name,
                        "order": i,
                        "framework": "aspnet",
                    },
                )

                if generic_match:
                    is_terminal = True
                    mw_node.properties["generic_type"] = generic_match.group(2)
                if is_terminal:
                    mw_node.properties["terminal"] = True

                nodes.append(mw_node)

            # Create MIDDLEWARE_CHAIN edges between consecutive entries
            for i in range(len(mw_fqns) - 1):
                edges.append(
                    GraphEdge(
                        source_fqn=mw_fqns[i],
                        target_fqn=mw_fqns[i + 1],
                        kind=EdgeKind.MIDDLEWARE_CHAIN,
                        confidence=Confidence.HIGH,
                        evidence="aspnet-middleware",
                        properties={
                            "framework": "aspnet",
                            "order": i,
                        },
                    )
                )

            # Resolve UseMiddleware<T> to actual middleware classes
            for i, mw_name in enumerate(middleware_calls):
                match = _USE_MIDDLEWARE_RE.match(mw_name)
                if not match:
                    continue
                type_name = match.group(1)

                # Find the class node in the graph
                for graph_node in graph.nodes.values():
                    if graph_node.name == type_name and graph_node.kind == NodeKind.CLASS:
                        # Verify it has Invoke or InvokeAsync method
                        has_invoke = False
                        for edge_item in graph.get_edges_from(graph_node.fqn):
                            if edge_item.kind != EdgeKind.CONTAINS:
                                continue
                            child = graph.get_node(edge_item.target_fqn)
                            if child and child.kind == NodeKind.FUNCTION and child.name in ("Invoke", "InvokeAsync"):
                                has_invoke = True
                                break

                        if has_invoke:
                            edges.append(GraphEdge(
                                source_fqn=graph_node.fqn,
                                target_fqn=mw_fqns[i],
                                kind=EdgeKind.HANDLES,
                                confidence=Confidence.HIGH,
                                evidence="aspnet-middleware",
                            ))
                            layer_assignments[graph_node.fqn] = "Cross-Cutting"
                        break

            # Create technology nodes for well-known middleware
            for mw_name in middleware_calls:
                tech_name = _TECHNOLOGY_MAP.get(mw_name)
                if tech_name:
                    tech_fqn = f"technology:aspnet:{tech_name.lower().replace(' ', '-')}"
                    nodes.append(GraphNode(
                        fqn=tech_fqn,
                        name=tech_name,
                        kind=NodeKind.COMPONENT,
                        language="csharp",
                        properties={"technology": True, "name": tech_name, "framework": "aspnet"},
                    ))

            # Validate ordering
            warnings.extend(self._validate_ordering(middleware_calls))

        log.info(
            "aspnet_middleware_extract_done",
            nodes=len(nodes),
            edges=len(edges),
            warnings=len(warnings),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_ordering(self, middleware_calls: list[str]) -> list[str]:
        """Check middleware ordering for common misconfigurations."""
        warnings: list[str] = []

        # Build index lookup
        index_of: dict[str, int] = {}
        for i, name in enumerate(middleware_calls):
            index_of[name] = i

        auth_idx = index_of.get("UseAuthentication")
        authz_idx = index_of.get("UseAuthorization")
        cors_idx = index_of.get("UseCors")

        # UseAuthorization should not come before UseAuthentication
        if authz_idx is not None and auth_idx is not None and authz_idx < auth_idx:
            warnings.append(
                "Middleware ordering issue: UseAuthorization (index "
                f"{authz_idx}) is registered before UseAuthentication "
                f"(index {auth_idx}). UseAuthentication should come first."
            )

        # UseCors should not come after UseAuthentication
        if cors_idx is not None and auth_idx is not None and cors_idx > auth_idx:
            warnings.append(
                "Middleware ordering issue: UseCors (index "
                f"{cors_idx}) is registered after UseAuthentication "
                f"(index {auth_idx}). UseCors should come before "
                "UseAuthentication for proper CORS handling."
            )

        return warnings
