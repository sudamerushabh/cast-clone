"""Shared test helpers for building AnalysisContext with graph nodes."""

from __future__ import annotations

from pathlib import Path

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.manifest import DetectedFramework, ProjectManifest


def make_dotnet_context() -> AnalysisContext:
    """Create a minimal AnalysisContext pre-configured for .NET/ASP.NET tests."""
    ctx = AnalysisContext(project_id="test-dotnet")
    ctx.graph = SymbolGraph()
    ctx.manifest = ProjectManifest(root_path=Path("/code"))
    ctx.manifest.detected_frameworks = [
        DetectedFramework(
            name="aspnet",
            language="csharp",
            confidence=Confidence.HIGH,
            evidence=["csproj"],
        ),
    ]
    return ctx


def add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    *,
    base_class: str = "",
    implements: list[str] | None = None,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    is_interface: bool = False,
    type_args: list[str] | None = None,
) -> GraphNode:
    """Add a CLASS (or INTERFACE) node to the graph."""
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.INTERFACE if is_interface else NodeKind.CLASS,
        language="csharp",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "base_class": base_class,
            "implements": implements or [],
            "type_args": type_args or [],
        },
    )
    graph.add_node(node)
    return node


def add_method(
    graph: SymbolGraph,
    class_fqn: str,
    method_name: str,
    *,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    parameters: list[dict] | None = None,
    return_type: str = "void",
    is_constructor: bool = False,
    is_override: bool = False,
) -> GraphNode:
    """Add a FUNCTION node to the graph and a CONTAINS edge from its parent class."""
    fqn = f"{class_fqn}.{method_name}"
    node = GraphNode(
        fqn=fqn,
        name=method_name,
        kind=NodeKind.FUNCTION,
        language="csharp",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "parameters": parameters or [],
            "return_type": return_type,
            "is_constructor": is_constructor,
            "is_override": is_override,
        },
    )
    graph.add_node(node)
    graph.add_edge(
        GraphEdge(
            source_fqn=class_fqn,
            target_fqn=fqn,
            kind=EdgeKind.CONTAINS,
            confidence=Confidence.HIGH,
            evidence="treesitter",
        )
    )
    return node


def add_field(
    graph: SymbolGraph,
    class_fqn: str,
    field_name: str,
    field_type: str,
    *,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    is_property: bool = False,
    type_args: list[str] | None = None,
) -> GraphNode:
    """Add a FIELD node to the graph and a CONTAINS edge from its parent class."""
    fqn = f"{class_fqn}.{field_name}"
    node = GraphNode(
        fqn=fqn,
        name=field_name,
        kind=NodeKind.FIELD,
        language="csharp",
        properties={
            "type": field_type,
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "is_property": is_property,
            "type_args": type_args or [],
        },
    )
    graph.add_node(node)
    graph.add_edge(
        GraphEdge(
            source_fqn=class_fqn,
            target_fqn=fqn,
            kind=EdgeKind.CONTAINS,
            confidence=Confidence.HIGH,
            evidence="treesitter",
        )
    )
    return node


def add_hub_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    *,
    hub_type_arg: str | None = None,
    methods: list[str] | None = None,
    client_events: list[str] | None = None,
) -> GraphNode:
    """Add a SignalR Hub class node with optional methods and client events.

    Args:
        hub_type_arg: Generic type arg for strongly-typed hubs (e.g., "INotificationClient").
        methods: List of hub method names to add (excluding lifecycle methods).
        client_events: Shared list of client event names. For test convenience, this is
            assigned to ALL hub methods (not per-method). The plugin itself discovers events
            from either method-level client_events OR strongly-typed hub interface methods.
    """
    base_class = f"Hub<{hub_type_arg}>" if hub_type_arg else "Hub"
    node = add_class(graph, fqn, name, base_class=base_class)

    for method_name in (methods or []):
        method_node = add_method(graph, fqn, method_name, return_type="Task")
        if client_events:
            method_node.properties["client_events"] = list(client_events)

    return node


def add_grpc_service(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    *,
    base_class: str,
    override_methods: list[dict] | None = None,
) -> GraphNode:
    """Add a gRPC service class node with override methods.

    Args:
        base_class: The protobuf-generated base class (e.g., "Greeter.GreeterBase").
        override_methods: List of dicts with keys: name, request_type, response_type.
    """
    node = add_class(graph, fqn, name, base_class=base_class)

    for method_info in (override_methods or []):
        add_method(
            graph,
            fqn,
            method_info["name"],
            is_override=True,
            parameters=[{"name": "request", "type": method_info.get("request_type", "object")}],
            return_type=method_info.get("response_type", "Task<object>"),
        )

    return node
