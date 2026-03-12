"""Tests for the Spring DI plugin — bean detection, injection resolution, layer classification."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult
from app.stages.plugins.spring.di import SpringDIPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_spring() -> AnalysisContext:
    """Create an AnalysisContext with spring-boot detected and a populated graph."""
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="spring-boot",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains spring-boot-starter"],
            ),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph,
    fqn: str,
    name: str,
    annotations: list[str] | None = None,
    implements: list[str] | None = None,
    is_interface: bool = False,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn,
        name=name,
        kind=NodeKind.INTERFACE if is_interface else NodeKind.CLASS,
        language="java",
        properties={
            "annotations": annotations or [],
            "implements": implements or [],
            "is_interface": is_interface,
        },
    )
    graph.add_node(node)
    return node


def _add_field(
    graph: SymbolGraph,
    class_fqn: str,
    field_name: str,
    field_type: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{field_name}"
    node = GraphNode(
        fqn=fqn,
        name=field_name,
        kind=NodeKind.FIELD,
        language="java",
        properties={
            "type": field_type,
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


def _add_constructor(
    graph: SymbolGraph,
    class_fqn: str,
    params: list[dict],
) -> GraphNode:
    fqn = f"{class_fqn}.<init>"
    node = GraphNode(
        fqn=fqn,
        name="<init>",
        kind=NodeKind.FUNCTION,
        language="java",
        properties={
            "is_constructor": True,
            "params": params,
            "annotations": [],
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


def _add_method(
    graph: SymbolGraph,
    class_fqn: str,
    method_name: str,
    annotations: list[str] | None = None,
    annotation_args: dict[str, str] | None = None,
    return_type: str | None = None,
    params: list[dict] | None = None,
) -> GraphNode:
    fqn = f"{class_fqn}.{method_name}"
    node = GraphNode(
        fqn=fqn,
        name=method_name,
        kind=NodeKind.FUNCTION,
        language="java",
        properties={
            "annotations": annotations or [],
            "annotation_args": annotation_args or {},
            "return_type": return_type,
            "params": params or [],
            "is_constructor": False,
        },
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestSpringDIPluginDetection:
    def test_detect_high_when_spring_boot_present(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_when_no_spring(self):
        plugin = SpringDIPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp/test"),
            detected_frameworks=[],
        )
        result = plugin.detect(ctx)
        assert result.is_active is False

    def test_detect_medium_when_annotations_found_but_no_framework(self):
        """If no spring-boot in frameworks but @Component annotations exist in graph."""
        plugin = SpringDIPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(
            root_path=Path("/tmp/test"),
            detected_frameworks=[],
        )
        _add_class(ctx.graph, "com.example.Foo", "Foo", annotations=["Component"])
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM


# ---------------------------------------------------------------------------
# Bean detection tests
# ---------------------------------------------------------------------------

class TestSpringDIBeanDetection:
    @pytest.mark.asyncio
    async def test_stereotype_annotations_detected_as_beans(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserService", "UserService", annotations=["Service"])
        _add_class(ctx.graph, "com.example.UserRepo", "UserRepo", annotations=["Repository"])
        _add_class(ctx.graph, "com.example.UserController", "UserController", annotations=["RestController"])
        _add_class(ctx.graph, "com.example.AppConfig", "AppConfig", annotations=["Configuration"])
        _add_class(ctx.graph, "com.example.NotABean", "NotABean")

        result = await plugin.extract(ctx)
        # Layer assignments should exist for all annotated beans
        assert result.layer_assignments.get("com.example.UserService") == "Business Logic"
        assert result.layer_assignments.get("com.example.UserRepo") == "Data Access"
        assert result.layer_assignments.get("com.example.UserController") == "Presentation"
        assert result.layer_assignments.get("com.example.AppConfig") == "Configuration"
        assert "com.example.NotABean" not in result.layer_assignments

    @pytest.mark.asyncio
    async def test_bean_methods_in_configuration_class(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.AppConfig", "AppConfig", annotations=["Configuration"])
        _add_method(
            ctx.graph,
            "com.example.AppConfig",
            "dataSource",
            annotations=["Bean"],
            return_type="DataSource",
        )

        result = await plugin.extract(ctx)
        # The @Bean method should register DataSource as a bean type
        # We verify by checking that if someone injects DataSource, it resolves
        # (tested in injection resolution tests below)
        assert result.layer_assignments.get("com.example.AppConfig") == "Configuration"


# ---------------------------------------------------------------------------
# Injection resolution tests
# ---------------------------------------------------------------------------

class TestSpringDIInjectionResolution:
    @pytest.mark.asyncio
    async def test_autowired_field_concrete_class(self):
        """@Autowired on a field with a concrete class type -> direct HIGH confidence edge."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserService", "UserService", annotations=["Service"])
        _add_class(ctx.graph, "com.example.UserController", "UserController", annotations=["RestController"])
        _add_field(
            ctx.graph, "com.example.UserController", "userService",
            field_type="UserService", annotations=["Autowired"],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].source_fqn == "com.example.UserController"
        assert inject_edges[0].target_fqn == "com.example.UserService"
        assert inject_edges[0].confidence == Confidence.HIGH
        assert inject_edges[0].properties.get("framework") == "spring"

    @pytest.mark.asyncio
    async def test_autowired_interface_single_implementor(self):
        """Interface with exactly one implementor -> HIGH confidence."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserRepo", "UserRepo", is_interface=True)
        _add_class(
            ctx.graph, "com.example.UserRepoImpl", "UserRepoImpl",
            annotations=["Repository"], implements=["UserRepo"],
        )
        # Add IMPLEMENTS edge (tree-sitter would have created this)
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.UserRepoImpl",
            target_fqn="com.example.UserRepo",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(ctx.graph, "com.example.UserService", "UserService", annotations=["Service"])
        _add_field(
            ctx.graph, "com.example.UserService", "userRepo",
            field_type="UserRepo", annotations=["Autowired"],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].source_fqn == "com.example.UserService"
        assert inject_edges[0].target_fqn == "com.example.UserRepoImpl"
        assert inject_edges[0].confidence == Confidence.HIGH

    @pytest.mark.asyncio
    async def test_autowired_interface_multiple_impls_with_primary(self):
        """Multiple implementors with @Primary -> resolve to the @Primary one."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.Notifier", "Notifier", is_interface=True)
        _add_class(
            ctx.graph, "com.example.EmailNotifier", "EmailNotifier",
            annotations=["Component", "Primary"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.EmailNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(
            ctx.graph, "com.example.SmsNotifier", "SmsNotifier",
            annotations=["Component"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.SmsNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(ctx.graph, "com.example.AlertService", "AlertService", annotations=["Service"])
        _add_field(
            ctx.graph, "com.example.AlertService", "notifier",
            field_type="Notifier", annotations=["Autowired"],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].target_fqn == "com.example.EmailNotifier"
        assert inject_edges[0].confidence == Confidence.HIGH

    @pytest.mark.asyncio
    async def test_autowired_interface_multiple_impls_with_qualifier(self):
        """Multiple implementors with @Qualifier -> resolve by qualifier match."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.Notifier", "Notifier", is_interface=True)
        _add_class(
            ctx.graph, "com.example.EmailNotifier", "EmailNotifier",
            annotations=["Component"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.EmailNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(
            ctx.graph, "com.example.SmsNotifier", "SmsNotifier",
            annotations=["Component"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.SmsNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(ctx.graph, "com.example.AlertService", "AlertService", annotations=["Service"])
        _add_field(
            ctx.graph, "com.example.AlertService", "notifier",
            field_type="Notifier",
            annotations=["Autowired", "Qualifier"],
            annotation_args={"Qualifier": "smsNotifier"},
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 1
        assert inject_edges[0].target_fqn == "com.example.SmsNotifier"
        assert inject_edges[0].confidence == Confidence.HIGH
        assert inject_edges[0].properties.get("qualifier") == "smsNotifier"

    @pytest.mark.asyncio
    async def test_autowired_interface_multiple_impls_ambiguous(self):
        """Multiple implementors, no @Primary, no @Qualifier -> LOW confidence edges to all."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.Notifier", "Notifier", is_interface=True)
        _add_class(
            ctx.graph, "com.example.EmailNotifier", "EmailNotifier",
            annotations=["Component"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.EmailNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(
            ctx.graph, "com.example.SmsNotifier", "SmsNotifier",
            annotations=["Component"], implements=["Notifier"],
        )
        ctx.graph.add_edge(GraphEdge(
            source_fqn="com.example.SmsNotifier",
            target_fqn="com.example.Notifier",
            kind=EdgeKind.IMPLEMENTS,
        ))
        _add_class(ctx.graph, "com.example.AlertService", "AlertService", annotations=["Service"])
        _add_field(
            ctx.graph, "com.example.AlertService", "notifier",
            field_type="Notifier", annotations=["Autowired"],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 2
        targets = {e.target_fqn for e in inject_edges}
        assert targets == {"com.example.EmailNotifier", "com.example.SmsNotifier"}
        assert all(e.confidence == Confidence.LOW for e in inject_edges)

    @pytest.mark.asyncio
    async def test_constructor_injection(self):
        """Constructor params matching bean types -> INJECTS edges."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserService", "UserService", annotations=["Service"])
        _add_class(ctx.graph, "com.example.OrderService", "OrderService", annotations=["Service"])
        _add_class(ctx.graph, "com.example.UserController", "UserController", annotations=["RestController"])
        _add_constructor(ctx.graph, "com.example.UserController", params=[
            {"name": "userService", "type": "UserService", "annotations": []},
            {"name": "orderService", "type": "OrderService", "annotations": []},
        ])

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        assert len(inject_edges) == 2
        targets = {e.target_fqn for e in inject_edges}
        assert "com.example.UserService" in targets
        assert "com.example.OrderService" in targets

    @pytest.mark.asyncio
    async def test_bean_method_injection(self):
        """@Bean method return type is injectable."""
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.AppConfig", "AppConfig", annotations=["Configuration"])
        _add_method(
            ctx.graph, "com.example.AppConfig", "dataSource",
            annotations=["Bean"], return_type="DataSource",
        )
        _add_class(ctx.graph, "com.example.UserRepo", "UserRepo", annotations=["Repository"])
        _add_field(
            ctx.graph, "com.example.UserRepo", "ds",
            field_type="DataSource", annotations=["Autowired"],
        )

        result = await plugin.extract(ctx)
        inject_edges = [e for e in result.edges if e.kind == EdgeKind.INJECTS]
        # Should resolve DataSource -> the @Bean method's declaring class (AppConfig)
        assert len(inject_edges) == 1
        assert inject_edges[0].source_fqn == "com.example.UserRepo"
        assert inject_edges[0].target_fqn == "com.example.AppConfig"
        assert inject_edges[0].confidence == Confidence.HIGH


# ---------------------------------------------------------------------------
# Layer classification tests
# ---------------------------------------------------------------------------

class TestSpringDILayerClassification:
    def test_layer_rules(self):
        plugin = SpringDIPlugin()
        rules = plugin.get_layer_classification()
        assert len(rules.rules) > 0

    @pytest.mark.asyncio
    async def test_controller_is_presentation(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserController", "UserController", annotations=["Controller"])
        result = await plugin.extract(ctx)
        assert result.layer_assignments["com.example.UserController"] == "Presentation"

    @pytest.mark.asyncio
    async def test_rest_controller_is_presentation(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.ApiController", "ApiController", annotations=["RestController"])
        result = await plugin.extract(ctx)
        assert result.layer_assignments["com.example.ApiController"] == "Presentation"

    @pytest.mark.asyncio
    async def test_service_is_business_logic(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserService", "UserService", annotations=["Service"])
        result = await plugin.extract(ctx)
        assert result.layer_assignments["com.example.UserService"] == "Business Logic"

    @pytest.mark.asyncio
    async def test_repository_is_data_access(self):
        plugin = SpringDIPlugin()
        ctx = _make_context_with_spring()
        _add_class(ctx.graph, "com.example.UserRepo", "UserRepo", annotations=["Repository"])
        result = await plugin.extract(ctx)
        assert result.layer_assignments["com.example.UserRepo"] == "Data Access"


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestSpringDIPluginMetadata:
    def test_plugin_name(self):
        plugin = SpringDIPlugin()
        assert plugin.name == "spring-di"

    def test_supported_languages(self):
        plugin = SpringDIPlugin()
        assert plugin.supported_languages == {"java"}

    def test_depends_on_empty(self):
        plugin = SpringDIPlugin()
        assert plugin.depends_on == []
