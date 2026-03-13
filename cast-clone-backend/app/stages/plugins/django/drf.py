"""Django REST Framework plugin -- ViewSet->Serializer->Model chain resolution.

Finds DRF ViewSets (ModelViewSet, ReadOnlyModelViewSet, GenericAPIView,
APIView), resolves their queryset to a Django model, links through
serializers, and generates CRUD API endpoint nodes.

Produces:
- Nodes: (:API_ENDPOINT) for each CRUD action
- Edges: (:ViewSet)-[:MANAGES]->(:Model)
         (:ViewSet)-[:READS]->(:Table)
         (:ViewSet)-[:WRITES]->(:Table)
         (:ViewSet)-[:HANDLES]->(:API_ENDPOINT)
"""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_QUERYSET_MODEL_RE = re.compile(r"^(\w+)\.objects")

# ViewSet base classes we recognise (substring match on INHERITS target)
_VIEWSET_BASES = (
    "viewsets.ModelViewSet",
    "viewsets.ReadOnlyModelViewSet",
    "viewsets.ViewSet",
    "generics.",
    "views.APIView",
)

# CRUD actions generated per ViewSet type
_VIEWSET_ACTIONS: dict[str, list[tuple[str, str, str]]] = {
    "ModelViewSet": [
        ("list", "GET", ""),
        ("create", "POST", ""),
        ("retrieve", "GET", "/{pk}"),
        ("update", "PUT", "/{pk}"),
        ("partial_update", "PATCH", "/{pk}"),
        ("destroy", "DELETE", "/{pk}"),
    ],
    "ReadOnlyModelViewSet": [
        ("list", "GET", ""),
        ("retrieve", "GET", "/{pk}"),
    ],
}


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class DjangoDRFPlugin(FrameworkPlugin):
    name = "django-drf"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = ["django-orm", "django-urls"]

    # -----------------------------------------------------------------------
    # Detection
    # -----------------------------------------------------------------------

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        # Check manifest for DRF framework
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                low = fw.name.lower()
                if "djangorestframework" in low or "rest_framework" in low:
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: look for classes inheriting from DRF ViewSet bases
        for edge in context.graph.edges:
            if edge.kind == EdgeKind.INHERITS and any(
                base in edge.target_fqn for base in _VIEWSET_BASES
            ):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="Class inheriting from DRF ViewSet found in graph",
                )

        return PluginDetectionResult.not_detected()

    # -----------------------------------------------------------------------
    # Extraction
    # -----------------------------------------------------------------------

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("django_drf_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []
        layer_assignments: dict[str, str] = {}
        entry_points: list[EntryPoint] = []

        # Build a lookup: class name -> fqn for model resolution
        class_name_to_fqn: dict[str, str] = {}
        for node in graph.nodes.values():
            if node.kind == NodeKind.CLASS:
                class_name_to_fqn[node.name] = node.fqn

        # Find all ViewSet classes
        viewset_fqns = self._find_viewsets(context)
        log.info("django_drf_viewsets_found", count=len(viewset_fqns))

        for vs_fqn in viewset_fqns:
            vs_node = graph.get_node(vs_fqn)
            if vs_node is None:
                continue

            # Layer assignment
            layer_assignments[vs_fqn] = "Presentation"

            # Extract queryset model name
            model_name = self._extract_queryset_model(context, vs_fqn)
            model_fqn: str | None = None

            if model_name:
                model_fqn = class_name_to_fqn.get(model_name)

            # Try serializer_class -> Meta.model fallback
            if model_fqn is None:
                model_fqn = self._resolve_via_serializer(
                    context,
                    vs_fqn,
                    class_name_to_fqn,
                )

            # Create MANAGES edge: ViewSet -> Model
            if model_fqn:
                edges.append(
                    GraphEdge(
                        source_fqn=vs_fqn,
                        target_fqn=model_fqn,
                        kind=EdgeKind.MANAGES,
                        confidence=Confidence.HIGH,
                        evidence="django-drf",
                        properties={"via": "queryset"},
                    )
                )

                # READS/WRITES edges to tables (if ORM plugin has run)
                viewset_type = self._classify_viewset(context, vs_fqn)
                table_edges = self._find_table_edges(
                    context, vs_fqn, model_fqn, viewset_type
                )
                edges.extend(table_edges)
            else:
                viewset_type = self._classify_viewset(context, vs_fqn)
            resource_name = self._derive_resource_name(model_name or vs_node.name)
            actions = _VIEWSET_ACTIONS.get(viewset_type, [])

            for action_name, method, suffix in actions:
                raw = (
                    f"/{resource_name}/{suffix.lstrip('/')}"
                    if suffix
                    else f"/{resource_name}/"
                )
                path = raw if raw.endswith("/") else raw + "/"
                ep_fqn = f"{method}:{path}"
                ep_node = GraphNode(
                    fqn=ep_fqn,
                    name=f"{method} {path}",
                    kind=NodeKind.API_ENDPOINT,
                    language="python",
                    properties={
                        "method": method,
                        "path": path,
                        "action": action_name,
                        "viewset": vs_fqn,
                    },
                )
                nodes.append(ep_node)

                # HANDLES edge: ViewSet -> Endpoint
                edges.append(
                    GraphEdge(
                        source_fqn=vs_fqn,
                        target_fqn=ep_fqn,
                        kind=EdgeKind.HANDLES,
                        confidence=Confidence.HIGH,
                        evidence="django-drf",
                    )
                )

                entry_points.append(
                    EntryPoint(
                        fqn=ep_fqn,
                        kind="http_endpoint",
                        metadata={"method": method, "path": path},
                    )
                )

        log.info(
            "django_drf_extract_complete",
            viewsets=len(viewset_fqns),
            endpoints=len(nodes),
            edges=len(edges),
        )

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=warnings,
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _find_viewsets(self, context: AnalysisContext) -> list[str]:
        """Find all classes inheriting from DRF ViewSet bases."""
        viewset_fqns: list[str] = []
        for edge in context.graph.edges:
            if edge.kind == EdgeKind.INHERITS and any(
                base in edge.target_fqn for base in _VIEWSET_BASES
            ):
                viewset_fqns.append(edge.source_fqn)
        return viewset_fqns

    def _extract_queryset_model(
        self,
        context: AnalysisContext,
        vs_fqn: str,
    ) -> str | None:
        """Extract model name from ViewSet's queryset field."""
        for edge in context.graph.get_edges_from(vs_fqn):
            if edge.kind != EdgeKind.CONTAINS:
                continue
            field_node = context.graph.get_node(edge.target_fqn)
            if field_node is None or field_node.name != "queryset":
                continue
            value = field_node.properties.get("value", "")
            match = _QUERYSET_MODEL_RE.match(value)
            if match:
                return match.group(1)
        return None

    def _resolve_via_serializer(
        self,
        context: AnalysisContext,
        vs_fqn: str,
        class_name_to_fqn: dict[str, str],
    ) -> str | None:
        """Resolve model via ViewSet.serializer_class -> Serializer.Meta.model."""
        # Find serializer_class field
        serializer_name: str | None = None
        for edge in context.graph.get_edges_from(vs_fqn):
            if edge.kind != EdgeKind.CONTAINS:
                continue
            field_node = context.graph.get_node(edge.target_fqn)
            if field_node and field_node.name == "serializer_class":
                serializer_name = field_node.properties.get("value", "")
                break

        if not serializer_name:
            return None

        # Find the serializer class
        serializer_fqn = class_name_to_fqn.get(serializer_name)
        if not serializer_fqn:
            return None

        # Find _meta_model field on the serializer
        for edge in context.graph.get_edges_from(serializer_fqn):
            if edge.kind != EdgeKind.CONTAINS:
                continue
            field_node = context.graph.get_node(edge.target_fqn)
            if field_node and field_node.name == "_meta_model":
                model_name = field_node.properties.get("value", "")
                if model_name:
                    return class_name_to_fqn.get(model_name)

        return None

    def _find_table_edges(
        self,
        context: AnalysisContext,
        vs_fqn: str,
        model_fqn: str,
        viewset_type: str,
    ) -> list[GraphEdge]:
        """Find MAPS_TO edges from model to table and create READS/WRITES.

        Only emits WRITES edges for viewset types that support write
        operations (e.g. ModelViewSet). ReadOnlyModelViewSet only gets READS.
        """
        read_only = viewset_type == "ReadOnlyModelViewSet"
        edges: list[GraphEdge] = []
        for edge in context.graph.get_edges_from(model_fqn):
            if edge.kind == EdgeKind.MAPS_TO:
                table_fqn = edge.target_fqn
                edges.append(
                    GraphEdge(
                        source_fqn=vs_fqn,
                        target_fqn=table_fqn,
                        kind=EdgeKind.READS,
                        confidence=Confidence.HIGH,
                        evidence="django-drf",
                    )
                )
                if not read_only:
                    edges.append(
                        GraphEdge(
                            source_fqn=vs_fqn,
                            target_fqn=table_fqn,
                            kind=EdgeKind.WRITES,
                            confidence=Confidence.HIGH,
                            evidence="django-drf",
                        )
                    )
        return edges

    def _classify_viewset(self, context: AnalysisContext, vs_fqn: str) -> str:
        """Determine the ViewSet type (ModelViewSet, ReadOnlyModelViewSet, etc.)."""
        for edge in context.graph.get_edges_from(vs_fqn):
            if edge.kind == EdgeKind.INHERITS:
                target = edge.target_fqn
                if "ReadOnlyModelViewSet" in target:
                    return "ReadOnlyModelViewSet"
                if "ModelViewSet" in target:
                    return "ModelViewSet"
        return "ModelViewSet"  # default

    def _derive_resource_name(self, model_name: str) -> str:
        """Derive REST resource name from model name: User -> users."""
        # Strip 'ViewSet' suffix if present
        name = model_name
        if name.endswith("ViewSet"):
            name = name[: -len("ViewSet")]
        return name.lower() + "s"
