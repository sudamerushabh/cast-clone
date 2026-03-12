"""Spring Dependency Injection plugin.

Detects Spring beans (@Component, @Service, @Repository, @Controller,
@RestController, @Configuration, @Bean methods) and resolves injection
wiring (@Autowired fields, constructor injection).

Produces:
- INJECTS edges: (:Class)-[:INJECTS {framework, qualifier, confidence}]->(:Class)
- Layer assignments: Controller->Presentation, Service->Business Logic, etc.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext, EntryPoint
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Annotations that mark a class as a Spring bean
STEREOTYPE_ANNOTATIONS = frozenset({
    "Component", "Service", "Repository",
    "Controller", "RestController", "Configuration",
})

# Annotation -> architectural layer
_LAYER_MAP: dict[str, str] = {
    "Controller": "Presentation",
    "RestController": "Presentation",
    "Service": "Business Logic",
    "Repository": "Data Access",
    "Configuration": "Configuration",
}


@dataclass
class _BeanInfo:
    """Internal tracking for a detected Spring bean."""
    fqn: str
    name: str
    bean_type: str  # The type this bean provides (class name or interface name)
    is_primary: bool = False
    source: str = "stereotype"  # "stereotype" or "bean_method"


class SpringDIPlugin(FrameworkPlugin):
    name = "spring-di"
    version = "1.0.0"
    supported_languages = {"java"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        # Check manifest for spring-boot framework detection
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "spring" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: check graph for Spring annotations
        for node in context.graph.nodes.values():
            annotations = node.properties.get("annotations", [])
            if any(a in STEREOTYPE_ANNOTATIONS for a in annotations):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="Spring stereotype annotations found in graph",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("spring_di_extract_start")

        graph = context.graph
        edges: list[GraphEdge] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        # Phase 1: Detect all beans (stereotype + @Bean methods)
        beans = self._detect_beans(graph)
        log.info("spring_di_beans_detected", count=len(beans))

        # Phase 2: Assign layers
        for fqn, layer in self._classify_layers(graph).items():
            layer_assignments[fqn] = layer

        # Phase 3: Resolve injections
        inject_edges = self._resolve_injections(graph, beans)
        edges.extend(inject_edges)
        log.info("spring_di_injections_resolved", count=len(inject_edges))

        return PluginResult(
            nodes=[],
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=[],
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[
            LayerRule(pattern="@RestController", layer="Presentation"),
            LayerRule(pattern="@Controller", layer="Presentation"),
            LayerRule(pattern="@Service", layer="Business Logic"),
            LayerRule(pattern="@Repository", layer="Data Access"),
            LayerRule(pattern="@Configuration", layer="Configuration"),
        ])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_beans(self, graph: SymbolGraph) -> dict[str, list[_BeanInfo]]:
        """Find all Spring beans: stereotype-annotated classes + @Bean methods.

        Returns a dict of bean_type_name -> _BeanInfo. For stereotypes, the
        bean_type is the class name. For @Bean methods, the bean_type is the
        method return type.
        """
        beans: dict[str, list[_BeanInfo]] = {}

        for node in graph.nodes.values():
            if node.kind not in (NodeKind.CLASS, NodeKind.INTERFACE):
                continue
            annotations = set(node.properties.get("annotations", []))
            if annotations & STEREOTYPE_ANNOTATIONS:
                info = _BeanInfo(
                    fqn=node.fqn,
                    name=node.name,
                    bean_type=node.name,
                    is_primary="Primary" in annotations,
                )
                beans.setdefault(node.name, []).append(info)

        # Scan for @Bean methods in @Configuration classes
        for node in graph.nodes.values():
            if node.kind != NodeKind.CLASS:
                continue
            annotations = set(node.properties.get("annotations", []))
            if "Configuration" not in annotations:
                continue
            # Find methods in this class
            for edge in graph.get_edges_from(node.fqn):
                if edge.kind != EdgeKind.CONTAINS:
                    continue
                method = graph.get_node(edge.target_fqn)
                if method is None or method.kind != NodeKind.FUNCTION:
                    continue
                method_annotations = set(method.properties.get("annotations", []))
                if "Bean" in method_annotations:
                    return_type = method.properties.get("return_type")
                    if return_type:
                        info = _BeanInfo(
                            fqn=node.fqn,  # The config class FQN
                            name=method.name,
                            bean_type=return_type,
                            source="bean_method",
                        )
                        beans.setdefault(return_type, []).append(info)

        return beans

    def _classify_layers(self, graph: SymbolGraph) -> dict[str, str]:
        """Assign architectural layers based on stereotype annotations."""
        assignments: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind not in (NodeKind.CLASS, NodeKind.INTERFACE):
                continue
            annotations = node.properties.get("annotations", [])
            for ann in annotations:
                if ann in _LAYER_MAP:
                    assignments[node.fqn] = _LAYER_MAP[ann]
                    break
        return assignments

    def _resolve_injections(
        self, graph: SymbolGraph, beans: dict[str, list[_BeanInfo]]
    ) -> list[GraphEdge]:
        """Resolve @Autowired fields and constructor params to INJECTS edges."""
        edges: list[GraphEdge] = []

        for node in graph.nodes.values():
            if node.kind not in (NodeKind.CLASS, NodeKind.INTERFACE):
                continue
            annotations = set(node.properties.get("annotations", []))
            if not (annotations & STEREOTYPE_ANNOTATIONS):
                continue

            # Check @Autowired fields
            for containment_edge in graph.get_edges_from(node.fqn):
                if containment_edge.kind != EdgeKind.CONTAINS:
                    continue
                child = graph.get_node(containment_edge.target_fqn)
                if child is None:
                    continue

                if child.kind == NodeKind.FIELD:
                    child_annotations = set(child.properties.get("annotations", []))
                    if "Autowired" in child_annotations:
                        field_type = child.properties.get("type", "")
                        qualifier = child.properties.get("annotation_args", {}).get("Qualifier")
                        new_edges = self._resolve_type_to_beans(
                            source_fqn=node.fqn,
                            target_type=field_type,
                            qualifier=qualifier,
                            graph=graph,
                            beans=beans,
                        )
                        edges.extend(new_edges)

                elif child.kind == NodeKind.FUNCTION:
                    if child.properties.get("is_constructor"):
                        params = child.properties.get("params", [])
                        for param in params:
                            # Params may be strings ("Type name") or dicts
                            if isinstance(param, str):
                                parts = param.strip().split()
                                param_type = parts[0] if parts else ""
                                param_qualifier = None
                            else:
                                param_type = param.get("type", "")
                                param_qualifier = None
                                param_annotations = param.get("annotations", [])
                                if isinstance(param_annotations, list):
                                    for pa in param_annotations:
                                        if isinstance(pa, dict) and pa.get("name") == "Qualifier":
                                            param_qualifier = pa.get("value")
                            new_edges = self._resolve_type_to_beans(
                                source_fqn=node.fqn,
                                target_type=param_type,
                                qualifier=param_qualifier,
                                graph=graph,
                                beans=beans,
                            )
                            edges.extend(new_edges)

        return edges

    def _resolve_type_to_beans(
        self,
        source_fqn: str,
        target_type: str,
        qualifier: str | None,
        graph: SymbolGraph,
        beans: dict[str, list[_BeanInfo]],
    ) -> list[GraphEdge]:
        """Resolve a type name to bean(s) and create INJECTS edges.

        Resolution order:
        1. Direct match (concrete class is a bean)
        2. Interface -> find implementors that are beans
        3. @Primary disambiguation
        4. @Qualifier disambiguation
        5. Ambiguous -> LOW confidence edges to all candidates
        """
        if not target_type:
            return []

        # Check if direct bean match exists
        candidates = beans.get(target_type, [])

        if len(candidates) == 1:
            return [self._make_inject_edge(
                source_fqn, candidates[0].fqn, Confidence.HIGH, qualifier=qualifier,
            )]

        if len(candidates) > 1:
            return self._disambiguate(source_fqn, candidates, qualifier)

        # No direct match — look for interface implementors
        # Find the interface node
        interface_node = None
        for n in graph.nodes.values():
            if n.name == target_type and n.properties.get("is_interface", False):
                interface_node = n
                break

        if interface_node is None:
            # No interface found — maybe it's a @Bean-provided type
            return []

        # Find all classes that implement this interface AND are beans
        implementors: list[_BeanInfo] = []
        for edge in graph.get_edges_to(interface_node.fqn):
            if edge.kind != EdgeKind.IMPLEMENTS:
                continue
            impl_node = graph.get_node(edge.source_fqn)
            if impl_node is None:
                continue
            impl_annotations = set(impl_node.properties.get("annotations", []))
            if impl_annotations & STEREOTYPE_ANNOTATIONS:
                implementors.append(_BeanInfo(
                    fqn=impl_node.fqn,
                    name=impl_node.name,
                    bean_type=impl_node.name,
                    is_primary="Primary" in impl_annotations,
                ))

        if len(implementors) == 0:
            return []
        if len(implementors) == 1:
            return [self._make_inject_edge(
                source_fqn, implementors[0].fqn, Confidence.HIGH, qualifier=qualifier,
            )]

        return self._disambiguate(source_fqn, implementors, qualifier)

    def _disambiguate(
        self,
        source_fqn: str,
        candidates: list[_BeanInfo],
        qualifier: str | None,
    ) -> list[GraphEdge]:
        """Disambiguate among multiple bean candidates."""
        # Check @Primary
        primary = [c for c in candidates if c.is_primary]
        if len(primary) == 1:
            return [self._make_inject_edge(
                source_fqn, primary[0].fqn, Confidence.HIGH, qualifier=qualifier,
            )]

        # Check @Qualifier
        if qualifier:
            # Match qualifier against bean name (case-insensitive comparison)
            for candidate in candidates:
                # Bean name matches: class name with lowercase first char, or exact match
                bean_name_lower = candidate.name[0].lower() + candidate.name[1:] if candidate.name else ""
                if qualifier == bean_name_lower or qualifier == candidate.name:
                    return [self._make_inject_edge(
                        source_fqn, candidate.fqn, Confidence.HIGH, qualifier=qualifier,
                    )]

        # Ambiguous — LOW confidence to all
        return [
            self._make_inject_edge(source_fqn, c.fqn, Confidence.LOW, qualifier=qualifier)
            for c in candidates
        ]

    def _make_inject_edge(
        self,
        source_fqn: str,
        target_fqn: str,
        confidence: Confidence,
        qualifier: str | None = None,
    ) -> GraphEdge:
        props: dict = {"framework": "spring"}
        if qualifier:
            props["qualifier"] = qualifier
        return GraphEdge(
            source_fqn=source_fqn,
            target_fqn=target_fqn,
            kind=EdgeKind.INJECTS,
            confidence=confidence,
            evidence="spring-di",
            properties=props,
        )
