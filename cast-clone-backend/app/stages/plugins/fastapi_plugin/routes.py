"""FastAPI plugin.

Detects FastAPI route decorators (@app.get, @router.post, etc.),
resolves Depends() dependency injection wiring, and links Pydantic
request/response models to endpoints.

Produces:
- APIEndpoint nodes: (:APIEndpoint {method, path})
- HANDLES edges: (:Function)-[:HANDLES]->(:APIEndpoint)
- INJECTS edges: (:Function)-[:INJECTS {framework: "fastapi"}]->(:Function)
- Layer assignments: route handlers -> Presentation
"""

from __future__ import annotations

import re
import structlog

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

# Regex to match route decorators: app.get("/path") or router.post("/path")
_ROUTE_DECORATOR_RE = re.compile(
    r"^(\w+)\.(get|post|put|delete|patch|options|head)\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)

# Regex to extract Depends(func_name) from default values
_DEPENDS_RE = re.compile(r"Depends\(\s*([a-zA-Z_][\w.]*)\s*\)")

# Regex to extract APIRouter prefix
_ROUTER_PREFIX_RE = re.compile(r'APIRouter\([^)]*prefix\s*=\s*["\'](.[^"\']+)["\']')


class FastAPIPlugin(FrameworkPlugin):
    name = "fastapi"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "fastapi" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        for node in context.graph.nodes.values():
            if node.language != "python":
                continue
            for deco in node.properties.get("annotations", []):
                if _ROUTE_DECORATOR_RE.match(deco):
                    return PluginDetectionResult(
                        confidence=Confidence.MEDIUM,
                        reason="FastAPI route decorators found in graph",
                    )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("fastapi_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        router_prefixes = self._build_router_prefix_map(graph)

        for func_node in graph.nodes.values():
            if func_node.kind != NodeKind.FUNCTION or func_node.language != "python":
                continue

            for deco in func_node.properties.get("annotations", []):
                match = _ROUTE_DECORATOR_RE.match(deco)
                if not match:
                    continue

                router_var, http_method, path = match.groups()
                http_method = http_method.upper()

                prefix = router_prefixes.get(router_var, "")
                full_path = prefix + path

                endpoint_fqn = f"{http_method}:{full_path}"
                endpoint_node = GraphNode(
                    fqn=endpoint_fqn,
                    name=f"{http_method} {full_path}",
                    kind=NodeKind.API_ENDPOINT,
                    language="python",
                    properties={
                        "method": http_method,
                        "path": full_path,
                        "framework": "fastapi",
                    },
                )
                nodes.append(endpoint_node)

                edges.append(GraphEdge(
                    source_fqn=func_node.fqn,
                    target_fqn=endpoint_fqn,
                    kind=EdgeKind.HANDLES,
                    confidence=Confidence.HIGH,
                    evidence="fastapi-decorator",
                ))

                entry_points.append(EntryPoint(
                    fqn=endpoint_fqn,
                    kind="http_endpoint",
                    metadata={"method": http_method, "path": full_path},
                ))

                layer_assignments[func_node.fqn] = "Presentation"

        inject_edges = self._resolve_depends(graph)
        edges.extend(inject_edges)

        log.info(
            "fastapi_extract_complete",
            endpoints=len([n for n in nodes if n.kind == NodeKind.API_ENDPOINT]),
            injects=len(inject_edges),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[
            LayerRule(pattern="@app.get", layer="Presentation"),
            LayerRule(pattern="@app.post", layer="Presentation"),
            LayerRule(pattern="@router.get", layer="Presentation"),
        ])

    def _build_router_prefix_map(self, graph: SymbolGraph) -> dict[str, str]:
        prefix_map: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind != NodeKind.FIELD or node.language != "python":
                continue
            value = node.properties.get("value", "")
            match = _ROUTER_PREFIX_RE.search(value)
            if match:
                prefix_map[node.name] = match.group(1)
        return prefix_map

    def _resolve_depends(self, graph: SymbolGraph) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for node in graph.nodes.values():
            if node.kind != NodeKind.FUNCTION or node.language != "python":
                continue
            for param in node.properties.get("params", []):
                default = param.get("default", "")
                match = _DEPENDS_RE.search(default)
                if not match:
                    continue

                dep_ref = match.group(1)
                dep_fqn = self._resolve_dependency_fqn(graph, node.fqn, dep_ref)
                if dep_fqn:
                    edges.append(GraphEdge(
                        source_fqn=dep_fqn,
                        target_fqn=node.fqn,
                        kind=EdgeKind.INJECTS,
                        confidence=Confidence.HIGH,
                        evidence="fastapi-depends",
                        properties={"framework": "fastapi"},
                    ))
        return edges

    def _resolve_dependency_fqn(
        self, graph: SymbolGraph, consumer_fqn: str, dep_ref: str
    ) -> str | None:
        module_fqn = ".".join(consumer_fqn.split(".")[:-1])
        candidate = f"{module_fqn}.{dep_ref}"
        if candidate in graph.nodes:
            return candidate

        if dep_ref in graph.nodes:
            return dep_ref

        for fqn in graph.nodes:
            if fqn.endswith(f".{dep_ref}"):
                return fqn

        return None
