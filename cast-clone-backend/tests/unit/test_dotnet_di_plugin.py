"""Tests for the ASP.NET Core DI plugin -- service registration, constructor injection, layer classification."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult
from app.stages.plugins.dotnet.di import ASPNetDIPlugin
from tests.unit.helpers import make_dotnet_context, add_class, add_method, add_field


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
        ctx = make_dotnet_context()
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

    def test_detects_via_di_registrations_fallback(self):
        """Detects ASP.NET via di_registrations property when no framework in manifest."""
        plugin = ASPNetDIPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.graph = SymbolGraph()
        ctx.manifest = ProjectManifest(root_path=Path("/code"))
        ctx.manifest.detected_frameworks = []
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"di_registrations": [
                {"method": "AddScoped", "interface": "IService", "implementation": "ServiceImpl"},
            ]},
        ))
        result = plugin.detect(ctx)
        assert result.is_active


# ---------------------------------------------------------------------------
# Service registration tests
# ---------------------------------------------------------------------------

class TestServiceRegistration:
    @pytest.mark.asyncio
    async def test_addscoped_creates_injects_edge(self):
        """AddScoped<IService, ServiceImpl> creates INJECTS edge with lifetime=scoped."""
        plugin = ASPNetDIPlugin()
        ctx = make_dotnet_context()

        # Program class with DI registration
        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddScoped", "interface": "IUserService", "implementation": "UserService"},
        ])

        # The interface and implementation
        add_class(ctx.graph, "MyApp.IUserService", "IUserService", is_interface=True)
        add_class(ctx.graph, "MyApp.UserService", "UserService", implements=["IUserService"])

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
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddSingleton", "interface": "ICacheService", "implementation": "CacheService"},
        ])

        add_class(ctx.graph, "MyApp.ICacheService", "ICacheService", is_interface=True)
        add_class(ctx.graph, "MyApp.CacheService", "CacheService", implements=["ICacheService"])

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].properties.get("lifetime") == "singleton"

    @pytest.mark.asyncio
    async def test_addtransient_lifetime(self):
        """AddTransient registration records lifetime=transient."""
        plugin = ASPNetDIPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddTransient", "interface": "IEmailSender", "implementation": "EmailSender"},
        ])

        add_class(ctx.graph, "MyApp.IEmailSender", "IEmailSender", is_interface=True)
        add_class(ctx.graph, "MyApp.EmailSender", "EmailSender", implements=["IEmailSender"])

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].properties.get("lifetime") == "transient"

    @pytest.mark.asyncio
    async def test_self_registration_without_interface(self):
        """AddScoped<Service>() with no interface -> registers class as its own type."""
        plugin = ASPNetDIPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.EmailService", "EmailService")
        ctx.graph.add_node(GraphNode(
            fqn="MyApp.Program", name="Program", kind=NodeKind.CLASS, language="csharp",
            properties={"di_registrations": [
                {"method": "AddScoped", "interface": "EmailService", "implementation": "EmailService"},
            ]},
        ))
        result = await plugin.extract(ctx)
        injects = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(injects) >= 1
        assert injects[0].properties.get("lifetime") == "scoped"


# ---------------------------------------------------------------------------
# Constructor injection tests
# ---------------------------------------------------------------------------

class TestConstructorInjection:
    @pytest.mark.asyncio
    async def test_constructor_params_resolved_via_di(self):
        """Constructor with interface-typed params resolves to concrete impl via DI registration."""
        plugin = ASPNetDIPlugin()
        ctx = make_dotnet_context()

        # DI registrations
        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddScoped", "interface": "IUserService", "implementation": "UserService"},
            {"method": "AddScoped", "interface": "IOrderService", "implementation": "OrderService"},
        ])

        # Interfaces
        add_class(ctx.graph, "MyApp.IUserService", "IUserService", is_interface=True)
        add_class(ctx.graph, "MyApp.IOrderService", "IOrderService", is_interface=True)

        # Implementations
        add_class(ctx.graph, "MyApp.UserService", "UserService", implements=["IUserService"])
        add_class(ctx.graph, "MyApp.OrderService", "OrderService", implements=["IOrderService"])

        # Controller with constructor injection
        add_class(ctx.graph, "MyApp.UserController", "UserController")
        add_method(
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
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddScoped", "interface": "IUserService", "implementation": "UserService"},
        ])

        add_class(ctx.graph, "MyApp.IUserService", "IUserService", is_interface=True)
        add_class(ctx.graph, "MyApp.UserService", "UserService", implements=["IUserService"])

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.UserService") == "Business Logic"

    @pytest.mark.asyncio
    async def test_repository_classified_as_data_access(self):
        """Classes ending in 'Repository' are classified as Data Access."""
        plugin = ASPNetDIPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Program", "Program")
        _add_di_registrations(ctx.graph, "MyApp.Program", [
            {"method": "AddScoped", "interface": "IUserRepository", "implementation": "UserRepository"},
        ])

        add_class(ctx.graph, "MyApp.IUserRepository", "IUserRepository", is_interface=True)
        add_class(ctx.graph, "MyApp.UserRepository", "UserRepository", implements=["IUserRepository"])

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.UserRepository") == "Data Access"
