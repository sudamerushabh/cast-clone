"""Tests for the ASP.NET Core DI plugin -- service registration, constructor injection, layer classification."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult
from app.stages.plugins.aspnet.di import ASPNetDIPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test-dotnet")
    ctx.graph = SymbolGraph()
    ctx.manifest = ProjectManifest(root_path=Path("/code"))
    ctx.manifest.detected_frameworks = [
        DetectedFramework(name="aspnet", language="csharp", confidence=Confidence.HIGH, evidence=["csproj"]),
    ]
    return ctx


def _add_class(
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


def _add_method(
    graph: SymbolGraph,
    class_fqn: str,
    method_name: str,
    *,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    parameters: list[dict] | None = None,
    return_type: str = "void",
    is_constructor: bool = False,
) -> GraphNode:
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
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
        confidence=Confidence.HIGH, evidence="treesitter",
    ))
    return node


def _add_field(
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
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
        confidence=Confidence.HIGH, evidence="treesitter",
    ))
    return node


def _add_di_registrations(graph: SymbolGraph, class_fqn: str, registrations: list[dict]) -> None:
    """Set di_registrations property on a Program/Startup class node."""
    node = graph.get_node(class_fqn)
    assert node is not None
    node.properties["di_registrations"] = registrations


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestDetection:
    def test_detects_aspnet_framework(self):
        """Plugin detects ASP.NET when 'aspnet' framework is in manifest."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH
        assert result.is_active is True

    def test_no_detection_without_framework(self):
        """Plugin returns not-detected when no ASP.NET framework in manifest."""
        plugin = ASPNetDIPlugin()
        ctx = AnalysisContext(project_id="test-dotnet")
        ctx.graph = SymbolGraph()
        ctx.manifest = ProjectManifest(root_path=Path("/code"))
        ctx.manifest.detected_frameworks = []
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# Service registration tests
# ---------------------------------------------------------------------------

class TestServiceRegistration:
    @pytest.mark.asyncio
    async def test_addscoped_creates_injects_edge(self):
        """AddScoped<IService, ServiceImpl> creates INJECTS edge with lifetime=scoped."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()

        # Program class with DI registration
        _add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddScoped", "interface": "IUserService", "implementation": "UserService"},
        ])

        # The interface and implementation
        _add_class(ctx.graph, "MyApp.IUserService", "IUserService", is_interface=True)
        _add_class(ctx.graph, "MyApp.UserService", "UserService", implements=["IUserService"])

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        edge = inject_edges[0]
        assert edge.source_fqn == "MyApp.IUserService"
        assert edge.target_fqn == "MyApp.UserService"
        assert edge.properties.get("lifetime") == "scoped"
        assert edge.properties.get("framework") == "aspnet"
        assert edge.confidence == Confidence.HIGH

    @pytest.mark.asyncio
    async def test_addsingleton_lifetime(self):
        """AddSingleton registration records lifetime=singleton."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddSingleton", "interface": "ICacheService", "implementation": "CacheService"},
        ])

        _add_class(ctx.graph, "MyApp.ICacheService", "ICacheService", is_interface=True)
        _add_class(ctx.graph, "MyApp.CacheService", "CacheService", implements=["ICacheService"])

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].properties.get("lifetime") == "singleton"

    @pytest.mark.asyncio
    async def test_addtransient_lifetime(self):
        """AddTransient registration records lifetime=transient."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddTransient", "interface": "IEmailSender", "implementation": "EmailSender"},
        ])

        _add_class(ctx.graph, "MyApp.IEmailSender", "IEmailSender", is_interface=True)
        _add_class(ctx.graph, "MyApp.EmailSender", "EmailSender", implements=["IEmailSender"])

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].properties.get("lifetime") == "transient"


# ---------------------------------------------------------------------------
# Constructor injection tests
# ---------------------------------------------------------------------------

class TestConstructorInjection:
    @pytest.mark.asyncio
    async def test_constructor_params_resolved_via_di(self):
        """Constructor with interface-typed params resolves to concrete impl via DI registration."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()

        # DI registrations
        _add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddScoped", "interface": "IUserService", "implementation": "UserService"},
            {"method": "AddScoped", "interface": "IOrderService", "implementation": "OrderService"},
        ])

        # Interfaces
        _add_class(ctx.graph, "MyApp.IUserService", "IUserService", is_interface=True)
        _add_class(ctx.graph, "MyApp.IOrderService", "IOrderService", is_interface=True)

        # Implementations
        _add_class(ctx.graph, "MyApp.UserService", "UserService", implements=["IUserService"])
        _add_class(ctx.graph, "MyApp.OrderService", "OrderService", implements=["IOrderService"])

        # Controller with constructor injection
        _add_class(ctx.graph, "MyApp.UserController", "UserController")
        _add_method(
            ctx.graph, "MyApp.UserController", ".ctor",
            is_constructor=True,
            parameters=[
                {"name": "_userService", "type": "IUserService"},
                {"name": "_orderService", "type": "IOrderService"},
            ],
        )

        result = await plugin.extract(ctx)

        # Should have 2 registration edges + 2 constructor injection edges
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        # Registration edges: IUserService->UserService, IOrderService->OrderService
        reg_edges = [e for e in inject_edges if e.properties.get("lifetime")]
        assert len(reg_edges) == 2

        # Constructor injection edges: UserController->UserService, UserController->OrderService
        ctor_edges = [e for e in inject_edges if e.properties.get("injection_type") == "constructor"]
        assert len(ctor_edges) == 2
        ctor_targets = {e.target_fqn for e in ctor_edges}
        assert "MyApp.UserService" in ctor_targets
        assert "MyApp.OrderService" in ctor_targets
        assert all(e.source_fqn == "MyApp.UserController" for e in ctor_edges)


# ---------------------------------------------------------------------------
# Layer classification tests
# ---------------------------------------------------------------------------

class TestLayerClassification:
    @pytest.mark.asyncio
    async def test_service_classified_as_business_logic(self):
        """Classes registered as services are classified as Business Logic."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddScoped", "interface": "IUserService", "implementation": "UserService"},
        ])

        _add_class(ctx.graph, "MyApp.IUserService", "IUserService", is_interface=True)
        _add_class(ctx.graph, "MyApp.UserService", "UserService", implements=["IUserService"])

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.UserService") == "Business Logic"

    @pytest.mark.asyncio
    async def test_repository_classified_as_data_access(self):
        """Classes ending in 'Repository' are classified as Data Access."""
        plugin = ASPNetDIPlugin()
        ctx = _make_context()

        _add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddScoped", "interface": "IUserRepository", "implementation": "UserRepository"},
        ])

        _add_class(ctx.graph, "MyApp.IUserRepository", "IUserRepository", is_interface=True)
        _add_class(ctx.graph, "MyApp.UserRepository", "UserRepository", implements=["IUserRepository"])

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.UserRepository") == "Data Access"
