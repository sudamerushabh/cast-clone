"""ASP.NET Core Dependency Injection plugin.

Extracts DI registrations from Program.cs / Startup.cs patterns and resolves
constructor injection to create INJECTS edges.

Scans for:
- builder.Services.AddScoped<IService, ServiceImpl>()
- builder.Services.AddTransient<IService, ServiceImpl>()
- builder.Services.AddSingleton<IService, ServiceImpl>()
- builder.Services.AddDbContext<AppDbContext>(...)
- Self-registration: builder.Services.AddScoped<Service>()
- Keyed services: builder.Services.AddKeyedScoped<I, T>('key')
- Open generics: builder.Services.AddScoped(typeof(IRepo<>), typeof(Repo<>))

Then resolves constructor injection: for each class whose constructor has
interface-typed parameters, looks up the DI registration to find the concrete
implementation, and creates INJECTS edges.

Produces:
- INJECTS edges: (:Interface)-[:INJECTS]->(:Class) for registrations
- INJECTS edges: (:Class)-[:INJECTS]->(:Class) for constructor injection
- Layer assignments: services->Business Logic, repos->Data Access
- Shared DI map: context.dotnet_di_map for downstream plugins
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, SymbolGraph
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
    "AddKeyedScoped": "scoped",
    "AddKeyedTransient": "transient",
    "AddKeyedSingleton": "singleton",
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
    key: str | None = None  # Keyed service key (e.g., "redis")
    is_open_generic: bool = False  # Open generic registration (e.g., IRepo<> -> Repo<>)


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

        # Build name -> FQN index for O(1) lookups
        name_to_fqn: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind in (NodeKind.CLASS, NodeKind.INTERFACE):
                name_to_fqn[node.name] = node.fqn

        # Phase 1: Collect DI registrations from Program/Startup class nodes
        registrations = self._collect_registrations(graph, name_to_fqn)
        log.info("aspnet_di_registrations_found", count=len(registrations))

        # Separate open generics from normal registrations
        open_generics = [r for r in registrations if r.is_open_generic]
        normal_registrations = [r for r in registrations if not r.is_open_generic]

        # Phase 2: Create INJECTS edges for each registration
        for reg in normal_registrations:
            if reg.interface_fqn and reg.implementation_fqn:
                props: dict[str, str] = {
                    "framework": "aspnet",
                    "lifetime": reg.lifetime,
                }
                if reg.key is not None:
                    props["key"] = reg.key
                edges.append(
                    GraphEdge(
                        source_fqn=reg.interface_fqn,
                        target_fqn=reg.implementation_fqn,
                        kind=EdgeKind.INJECTS,
                        confidence=Confidence.HIGH,
                        evidence="aspnet-di",
                        properties=props,
                    )
                )

        # Phase 3: Classify layers
        layer_assignments.update(self._classify_layers(graph, registrations))

        # Phase 4: Resolve constructor injection and build DI lookup
        ctor_edges, di_lookup = self._resolve_constructor_injection(
            graph, registrations, open_generics
        )
        edges.extend(ctor_edges)
        log.info("aspnet_di_constructor_injections", count=len(ctor_edges))

        # Phase 5: Store shared DI map on context for downstream plugins
        context.dotnet_di_map = di_lookup

        log.info(
            "aspnet_di_extract_done",
            edges=len(edges),
            layers=len(layer_assignments),
        )

        return PluginResult(
            nodes=[],
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(
            rules=[
                LayerRule(pattern="Repository", layer="Data Access"),
                LayerRule(pattern="DbContext", layer="Data Access"),
                LayerRule(pattern="Service", layer="Business Logic"),
            ]
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_registrations(
        self, graph: SymbolGraph, name_to_fqn: dict[str, str]
    ) -> list[_DIRegistration]:
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
                key = reg_dict.get("key")

                lifetime = _LIFETIME_MAP.get(method, "scoped")

                # Detect open generic registrations
                is_open_generic = bool(
                    reg_dict.get("is_open_generic")
                    or (interface_name.endswith("<>"))
                )

                # If no implementation specified, it's a self-registration
                if not impl_name:
                    impl_name = interface_name

                reg = _DIRegistration(
                    interface_name=interface_name,
                    implementation_name=impl_name,
                    lifetime=lifetime,
                    method=method,
                    key=key,
                    is_open_generic=is_open_generic,
                )

                # Resolve FQNs via pre-built index (O(1) per lookup)
                # For open generics, strip <> before lookup
                if is_open_generic:
                    base_iface = interface_name.rstrip("<>")
                    base_impl = impl_name.rstrip("<>")
                    reg.interface_fqn = name_to_fqn.get(base_iface)
                    reg.implementation_fqn = name_to_fqn.get(base_impl)
                else:
                    reg.interface_fqn = name_to_fqn.get(interface_name)
                    reg.implementation_fqn = name_to_fqn.get(impl_name)

                registrations.append(reg)

        return registrations

    def _classify_layers(
        self, graph: SymbolGraph, registrations: list[_DIRegistration]
    ) -> dict[str, str]:
        """Assign architectural layers based on naming conventions."""
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
        self,
        graph: SymbolGraph,
        registrations: list[_DIRegistration],
        open_generics: list[_DIRegistration],
    ) -> tuple[list[GraphEdge], dict[str, str]]:
        """Resolve constructor params via DI registrations.

        Returns:
            Tuple of (constructor injection edges, di_lookup map).
        """
        edges: list[GraphEdge] = []

        # Build lookup: interface_name -> implementation_fqn
        di_lookup: dict[str, str] = {}
        # Build keyed lookup: (interface_name, key) -> implementation_fqn
        keyed_lookup: dict[tuple[str, str], str] = {}

        for reg in registrations:
            if reg.interface_fqn and reg.implementation_fqn:
                if reg.key is not None:
                    keyed_lookup[(reg.interface_name, reg.key)] = reg.implementation_fqn
                else:
                    di_lookup[reg.interface_name] = reg.implementation_fqn

        # Build open generic lookup: base_interface_name -> (impl_fqn, registration)
        open_generic_lookup: dict[str, _DIRegistration] = {}
        for reg in open_generics:
            base_name = reg.interface_name.rstrip("<>")
            open_generic_lookup[base_name] = reg

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
                    param_type = (
                        param.get("type", "") if isinstance(param, dict) else ""
                    )
                    if not param_type:
                        continue

                    impl_fqn: str | None = None
                    confidence = Confidence.HIGH

                    # Check for keyed service resolution via [FromKeyedServices]
                    annotations = (
                        param.get("annotations", [])
                        if isinstance(param, dict)
                        else []
                    )
                    if "FromKeyedServices" in annotations:
                        key = (
                            param.get("annotation_args", {}).get("FromKeyedServices")
                            if isinstance(param, dict)
                            else None
                        )
                        if key:
                            impl_fqn = keyed_lookup.get((param_type, key))

                    # Normal DI lookup
                    if impl_fqn is None:
                        impl_fqn = di_lookup.get(param_type)

                    # Open generic fallback: IRepo<User> -> Repo
                    if impl_fqn is None and "<" in param_type:
                        base_name = param_type.split("<")[0]
                        og_reg = open_generic_lookup.get(base_name)
                        if og_reg and og_reg.implementation_fqn:
                            impl_fqn = og_reg.implementation_fqn
                            confidence = Confidence.MEDIUM

                    if impl_fqn:
                        edges.append(
                            GraphEdge(
                                source_fqn=node.fqn,
                                target_fqn=impl_fqn,
                                kind=EdgeKind.INJECTS,
                                confidence=confidence,
                                evidence="aspnet-di",
                                properties={
                                    "framework": "aspnet",
                                    "injection_type": "constructor",
                                },
                            )
                        )

        return edges, di_lookup
