"""ASP.NET Core Dependency Injection plugin.

Extracts DI registrations from Program.cs / Startup.cs patterns and resolves
constructor injection to create INJECTS edges.

Scans for:
- builder.Services.AddScoped<IService, ServiceImpl>()
- builder.Services.AddTransient<IService, ServiceImpl>()
- builder.Services.AddSingleton<IService, ServiceImpl>()
- builder.Services.AddDbContext<AppDbContext>(...)
- Self-registration: builder.Services.AddScoped<Service>()

Then resolves constructor injection: for each class whose constructor has
interface-typed parameters, looks up the DI registration to find the concrete
implementation, and creates INJECTS edges.

Produces:
- INJECTS edges: (:Interface)-[:INJECTS {framework, lifetime}]->(:Class) for registrations
- INJECTS edges: (:Class)-[:INJECTS {framework, injection_type}]->(:Class) for constructor injection
- Layer assignments: services->Business Logic, repositories->Data Access, DbContext->Data Access
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Method name -> DI lifetime
_LIFETIME_MAP: dict[str, str] = {
    "AddScoped": "scoped",
    "AddTransient": "transient",
    "AddSingleton": "singleton",
    "AddDbContext": "scoped",
}


@dataclass
class _DIRegistration:
    """Internal tracking for a DI service registration."""

    interface_name: str  # Simple name of the service type (e.g., "IUserService")
    implementation_name: str  # Simple name of the implementation (e.g., "UserService")
    interface_fqn: str | None = None  # Resolved FQN
    implementation_fqn: str | None = None  # Resolved FQN
    lifetime: str = "scoped"
    method: str = "AddScoped"


class ASPNetDIPlugin(FrameworkPlugin):
    name = "aspnet-di"
    version = "1.0.0"
    supported_languages = {"csharp"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        """Detect ASP.NET Core by checking manifest for aspnet framework."""
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "aspnet" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: check graph for DI registration patterns
        for node in context.graph.nodes.values():
            if node.properties.get("di_registrations"):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="DI registrations found in graph nodes",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("aspnet_di_extract_start")

        graph = context.graph
        edges: list[GraphEdge] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        # Phase 1: Collect DI registrations from Program/Startup class nodes
        registrations = self._collect_registrations(graph)
        log.info("aspnet_di_registrations_found", count=len(registrations))

        # Phase 2: Create INJECTS edges for each registration (interface -> implementation)
        for reg in registrations:
            if reg.interface_fqn and reg.implementation_fqn:
                edges.append(GraphEdge(
                    source_fqn=reg.interface_fqn,
                    target_fqn=reg.implementation_fqn,
                    kind=EdgeKind.INJECTS,
                    confidence=Confidence.HIGH,
                    evidence="aspnet-di",
                    properties={
                        "framework": "aspnet",
                        "lifetime": reg.lifetime,
                    },
                ))

        # Phase 3: Classify layers
        layer_assignments.update(self._classify_layers(graph, registrations))

        # Phase 4: Resolve constructor injection
        ctor_edges = self._resolve_constructor_injection(graph, registrations)
        edges.extend(ctor_edges)
        log.info("aspnet_di_constructor_injections", count=len(ctor_edges))

        log.info("aspnet_di_extract_done", edges=len(edges), layers=len(layer_assignments))

        return PluginResult(
            nodes=[],
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[
            LayerRule(pattern="Repository", layer="Data Access"),
            LayerRule(pattern="DbContext", layer="Data Access"),
            LayerRule(pattern="Service", layer="Business Logic"),
        ])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_registrations(self, graph: SymbolGraph) -> list[_DIRegistration]:
        """Scan all nodes for di_registrations property and resolve FQNs."""
        registrations: list[_DIRegistration] = []

        for node in graph.nodes.values():
            di_regs = node.properties.get("di_registrations", [])
            if not di_regs:
                continue

            for reg_dict in di_regs:
                method = reg_dict.get("method", "")
                interface_name = reg_dict.get("interface", "")
                impl_name = reg_dict.get("implementation", "")

                lifetime = _LIFETIME_MAP.get(method, "scoped")

                # If no implementation specified, it's a self-registration
                if not impl_name:
                    impl_name = interface_name

                reg = _DIRegistration(
                    interface_name=interface_name,
                    implementation_name=impl_name,
                    lifetime=lifetime,
                    method=method,
                )

                # Resolve FQNs by matching simple names against graph nodes
                reg.interface_fqn = self._resolve_fqn(graph, interface_name)
                reg.implementation_fqn = self._resolve_fqn(graph, impl_name)

                registrations.append(reg)

        return registrations

    def _resolve_fqn(self, graph: SymbolGraph, simple_name: str) -> str | None:
        """Find the FQN for a simple class/interface name in the graph."""
        if not simple_name:
            return None
        for node in graph.nodes.values():
            if node.name == simple_name and node.kind in (NodeKind.CLASS, NodeKind.INTERFACE):
                return node.fqn
        return None

    def _classify_layers(
        self, graph: SymbolGraph, registrations: list[_DIRegistration]
    ) -> dict[str, str]:
        """Assign architectural layers based on naming conventions and DI registrations."""
        assignments: dict[str, str] = {}

        for reg in registrations:
            impl_fqn = reg.implementation_fqn
            if not impl_fqn:
                continue

            impl_node = graph.get_node(impl_fqn)
            if impl_node is None:
                continue

            # DbContext subclasses -> Data Access
            base_class = impl_node.properties.get("base_class", "")
            if "DbContext" in base_class or impl_node.name.endswith("DbContext"):
                assignments[impl_fqn] = "Data Access"
                continue

            # Repository naming -> Data Access
            if "Repository" in impl_node.name or "Repository" in reg.interface_name:
                assignments[impl_fqn] = "Data Access"
                continue

            # Everything else registered as a service -> Business Logic
            assignments[impl_fqn] = "Business Logic"

        return assignments

    def _resolve_constructor_injection(
        self, graph: SymbolGraph, registrations: list[_DIRegistration]
    ) -> list[GraphEdge]:
        """For each constructor with interface-typed params, resolve via DI registrations."""
        edges: list[GraphEdge] = []

        # Build lookup: interface_name -> implementation_fqn
        di_lookup: dict[str, str] = {}
        for reg in registrations:
            if reg.interface_fqn and reg.implementation_fqn:
                di_lookup[reg.interface_name] = reg.implementation_fqn

        # Scan all classes for constructors
        for node in graph.nodes.values():
            if node.kind != NodeKind.CLASS:
                continue

            # Find constructor methods
            for edge in graph.get_edges_from(node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                child = graph.get_node(edge.target_fqn)
                if child is None or child.kind != NodeKind.FUNCTION:
                    continue
                if not child.properties.get("is_constructor"):
                    continue

                # Resolve each parameter
                params = child.properties.get("parameters", [])
                for param in params:
                    param_type = param.get("type", "") if isinstance(param, dict) else ""
                    if not param_type:
                        continue

                    # Look up in DI registrations
                    impl_fqn = di_lookup.get(param_type)
                    if impl_fqn:
                        edges.append(GraphEdge(
                            source_fqn=node.fqn,
                            target_fqn=impl_fqn,
                            kind=EdgeKind.INJECTS,
                            confidence=Confidence.HIGH,
                            evidence="aspnet-di",
                            properties={
                                "framework": "aspnet",
                                "injection_type": "constructor",
                            },
                        ))

        return edges
