# tests/unit/test_enricher.py
"""Tests for Stage 7: Graph Enricher."""

import pytest

from app.models.context import AnalysisContext
from app.models.enums import EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.enricher import (
    aggregate_class_depends_on,
    aggregate_module_imports,
    assign_architectural_layers,
    compute_fan_metrics,
    create_technology_nodes,
    enrich_graph,
    resolve_virtual_dispatch,
)

# ── Helpers ──────────────────────────────────────────────


def _make_context(graph: SymbolGraph | None = None) -> AnalysisContext:
    ctx = AnalysisContext(project_id="test-project")
    if graph is not None:
        ctx.graph = graph
    return ctx


def _make_class(fqn: str, module_fqn: str | None = None) -> GraphNode:
    node = GraphNode(fqn=fqn, name=fqn.split(".")[-1], kind=NodeKind.CLASS)
    if module_fqn is not None:
        node.properties["module_fqn"] = module_fqn
    return node


def _make_function(fqn: str) -> GraphNode:
    return GraphNode(fqn=fqn, name=fqn.split(".")[-1], kind=NodeKind.FUNCTION)


def _make_module(fqn: str) -> GraphNode:
    return GraphNode(fqn=fqn, name=fqn.split(".")[-1], kind=NodeKind.MODULE)


def _calls_edge(src: str, tgt: str) -> GraphEdge:
    return GraphEdge(source_fqn=src, target_fqn=tgt, kind=EdgeKind.CALLS)


def _contains_edge(src: str, tgt: str) -> GraphEdge:
    return GraphEdge(source_fqn=src, target_fqn=tgt, kind=EdgeKind.CONTAINS)


def _injects_edge(src: str, tgt: str) -> GraphEdge:
    return GraphEdge(source_fqn=src, target_fqn=tgt, kind=EdgeKind.INJECTS)


# ── Test 1: Fan-in / Fan-out ────────────────────────────


class TestFanMetrics:
    def test_fan_in_fan_out_basic(self):
        """Graph with known CALLS edges: verify correct counts on CLASS nodes."""
        g = SymbolGraph()

        # Classes
        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_class("com.app.B"))
        g.add_node(_make_class("com.app.C"))

        # Methods
        g.add_node(_make_function("com.app.A.m1"))
        g.add_node(_make_function("com.app.A.m2"))
        g.add_node(_make_function("com.app.B.m1"))
        g.add_node(_make_function("com.app.C.m1"))

        # Containment: class -> method
        g.add_edge(_contains_edge("com.app.A", "com.app.A.m1"))
        g.add_edge(_contains_edge("com.app.A", "com.app.A.m2"))
        g.add_edge(_contains_edge("com.app.B", "com.app.B.m1"))
        g.add_edge(_contains_edge("com.app.C", "com.app.C.m1"))

        # Calls: A.m1 -> B.m1, A.m2 -> B.m1, B.m1 -> C.m1
        g.add_edge(_calls_edge("com.app.A.m1", "com.app.B.m1"))
        g.add_edge(_calls_edge("com.app.A.m2", "com.app.B.m1"))
        g.add_edge(_calls_edge("com.app.B.m1", "com.app.C.m1"))

        compute_fan_metrics(g)

        # A: fan_in=0 (nobody calls A's methods), fan_out=2 (A.m1->B.m1, A.m2->B.m1)
        assert g.get_node("com.app.A").properties["fan_in"] == 0
        assert g.get_node("com.app.A").properties["fan_out"] == 2

        # B: fan_in=2 (A.m1->B.m1, A.m2->B.m1), fan_out=1 (B.m1->C.m1)
        assert g.get_node("com.app.B").properties["fan_in"] == 2
        assert g.get_node("com.app.B").properties["fan_out"] == 1

        # C: fan_in=1 (B.m1->C.m1), fan_out=0
        assert g.get_node("com.app.C").properties["fan_in"] == 1
        assert g.get_node("com.app.C").properties["fan_out"] == 0

    def test_fan_in_includes_injects_edges(self):
        """INJECTS edges should also count toward fan_in."""
        g = SymbolGraph()
        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_class("com.app.B"))

        # A injects B (DI)
        g.add_edge(_injects_edge("com.app.A", "com.app.B"))

        compute_fan_metrics(g)

        assert g.get_node("com.app.B").properties["fan_in"] == 1


# ── Test 2: Class-level DEPENDS_ON Aggregation ──────────


class TestClassDependsOn:
    def test_methods_calling_across_classes_create_depends_on(self):
        """Methods calling across classes -> DEPENDS_ON edges with correct weights."""
        g = SymbolGraph()

        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_class("com.app.B"))
        g.add_node(_make_function("com.app.A.m1"))
        g.add_node(_make_function("com.app.A.m2"))
        g.add_node(_make_function("com.app.B.m1"))
        g.add_node(_make_function("com.app.B.m2"))

        g.add_edge(_contains_edge("com.app.A", "com.app.A.m1"))
        g.add_edge(_contains_edge("com.app.A", "com.app.A.m2"))
        g.add_edge(_contains_edge("com.app.B", "com.app.B.m1"))
        g.add_edge(_contains_edge("com.app.B", "com.app.B.m2"))

        # A.m1 -> B.m1, A.m1 -> B.m2, A.m2 -> B.m1
        g.add_edge(_calls_edge("com.app.A.m1", "com.app.B.m1"))
        g.add_edge(_calls_edge("com.app.A.m1", "com.app.B.m2"))
        g.add_edge(_calls_edge("com.app.A.m2", "com.app.B.m1"))

        aggregate_class_depends_on(g)

        depends_on = [
            e
            for e in g.edges
            if e.kind == EdgeKind.DEPENDS_ON
            and e.source_fqn == "com.app.A"
            and e.target_fqn == "com.app.B"
        ]
        assert len(depends_on) == 1
        assert depends_on[0].properties["weight"] == 3

    def test_no_duplicate_depends_on(self):
        """If DEPENDS_ON already exists between two classes, don't add another."""
        g = SymbolGraph()

        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_class("com.app.B"))
        g.add_node(_make_function("com.app.A.m1"))
        g.add_node(_make_function("com.app.B.m1"))

        g.add_edge(_contains_edge("com.app.A", "com.app.A.m1"))
        g.add_edge(_contains_edge("com.app.B", "com.app.B.m1"))
        g.add_edge(_calls_edge("com.app.A.m1", "com.app.B.m1"))

        # Pre-existing DEPENDS_ON edge
        existing = GraphEdge(
            source_fqn="com.app.A",
            target_fqn="com.app.B",
            kind=EdgeKind.DEPENDS_ON,
            properties={"weight": 99},
        )
        g.add_edge(existing)

        aggregate_class_depends_on(g)

        depends_on = [
            e
            for e in g.edges
            if e.kind == EdgeKind.DEPENDS_ON
            and e.source_fqn == "com.app.A"
            and e.target_fqn == "com.app.B"
        ]
        # Should still be exactly 1 (the pre-existing one is left as-is)
        assert len(depends_on) == 1


# ── Test 3: Module-level IMPORTS Aggregation ─────────────


class TestModuleImports:
    def test_classes_across_modules_create_imports(self):
        """Classes across modules -> module-level IMPORTS edges."""
        g = SymbolGraph()

        # Modules
        g.add_node(_make_module("com.app.user"))
        g.add_node(_make_module("com.app.order"))

        # Classes with module_fqn property
        g.add_node(_make_class("com.app.user.UserService", module_fqn="com.app.user"))
        g.add_node(
            _make_class("com.app.order.OrderService", module_fqn="com.app.order")
        )

        # Module containment
        g.add_edge(_contains_edge("com.app.user", "com.app.user.UserService"))
        g.add_edge(_contains_edge("com.app.order", "com.app.order.OrderService"))

        # Class-level DEPENDS_ON
        g.add_edge(
            GraphEdge(
                source_fqn="com.app.user.UserService",
                target_fqn="com.app.order.OrderService",
                kind=EdgeKind.DEPENDS_ON,
                properties={"weight": 5},
            )
        )

        aggregate_module_imports(g)

        imports = [
            e
            for e in g.edges
            if e.kind == EdgeKind.IMPORTS
            and e.source_fqn == "com.app.user"
            and e.target_fqn == "com.app.order"
        ]
        assert len(imports) == 1
        assert imports[0].properties["weight"] == 5

    def test_multiple_classes_sum_weights(self):
        """Multiple class-level DEPENDS_ON between modules -> sum weights."""
        g = SymbolGraph()

        g.add_node(_make_module("mod.A"))
        g.add_node(_make_module("mod.B"))
        g.add_node(_make_class("mod.A.C1", module_fqn="mod.A"))
        g.add_node(_make_class("mod.A.C2", module_fqn="mod.A"))
        g.add_node(_make_class("mod.B.C1", module_fqn="mod.B"))

        g.add_edge(_contains_edge("mod.A", "mod.A.C1"))
        g.add_edge(_contains_edge("mod.A", "mod.A.C2"))
        g.add_edge(_contains_edge("mod.B", "mod.B.C1"))

        g.add_edge(
            GraphEdge(
                source_fqn="mod.A.C1",
                target_fqn="mod.B.C1",
                kind=EdgeKind.DEPENDS_ON,
                properties={"weight": 3},
            )
        )
        g.add_edge(
            GraphEdge(
                source_fqn="mod.A.C2",
                target_fqn="mod.B.C1",
                kind=EdgeKind.DEPENDS_ON,
                properties={"weight": 2},
            )
        )

        aggregate_module_imports(g)

        imports = [
            e
            for e in g.edges
            if e.kind == EdgeKind.IMPORTS
            and e.source_fqn == "mod.A"
            and e.target_fqn == "mod.B"
        ]
        assert len(imports) == 1
        assert imports[0].properties["weight"] == 5


# ── Test 4: No Self-Edges ───────────────────────────────


class TestNoSelfEdges:
    def test_class_does_not_depend_on_itself(self):
        """Internal method calls within the same class must NOT
        produce a DEPENDS_ON self-edge."""
        g = SymbolGraph()

        g.add_node(_make_class("com.app.A"))
        g.add_node(_make_function("com.app.A.m1"))
        g.add_node(_make_function("com.app.A.m2"))

        g.add_edge(_contains_edge("com.app.A", "com.app.A.m1"))
        g.add_edge(_contains_edge("com.app.A", "com.app.A.m2"))
        g.add_edge(_calls_edge("com.app.A.m1", "com.app.A.m2"))

        aggregate_class_depends_on(g)

        self_edges = [
            e
            for e in g.edges
            if e.kind == EdgeKind.DEPENDS_ON
            and e.source_fqn == "com.app.A"
            and e.target_fqn == "com.app.A"
        ]
        assert len(self_edges) == 0

    def test_module_does_not_import_itself(self):
        """Classes in the same module depending on each other
        must NOT produce a module self-IMPORTS."""
        g = SymbolGraph()

        g.add_node(_make_module("com.app"))
        g.add_node(_make_class("com.app.A", module_fqn="com.app"))
        g.add_node(_make_class("com.app.B", module_fqn="com.app"))

        g.add_edge(_contains_edge("com.app", "com.app.A"))
        g.add_edge(_contains_edge("com.app", "com.app.B"))
        g.add_edge(
            GraphEdge(
                source_fqn="com.app.A",
                target_fqn="com.app.B",
                kind=EdgeKind.DEPENDS_ON,
                properties={"weight": 2},
            )
        )

        aggregate_module_imports(g)

        self_imports = [
            e
            for e in g.edges
            if e.kind == EdgeKind.IMPORTS
            and e.source_fqn == "com.app"
            and e.target_fqn == "com.app"
        ]
        assert len(self_imports) == 0


# ── Test 5: Layer Assignment ─────────────────────────────


class TestLayerAssignment:
    def test_layer_nodes_created_from_assignments(self):
        """Nodes with layer_assignments produce Layer nodes
        with CONTAINS edges."""
        g = SymbolGraph()

        # Classes with layer hints (set by framework plugins)
        svc = _make_class("com.app.UserService")
        svc.properties["layer"] = "Business Logic"
        g.add_node(svc)

        ctrl = _make_class("com.app.UserController")
        ctrl.properties["layer"] = "Presentation"
        g.add_node(ctrl)

        repo = _make_class("com.app.UserRepository")
        repo.properties["layer"] = "Data Access"
        g.add_node(repo)

        assign_architectural_layers(g, app_name="test-app")

        # Layer nodes should exist
        layer_nodes = [n for n in g.nodes.values() if n.kind == NodeKind.LAYER]
        layer_names = {n.name for n in layer_nodes}
        assert "Business Logic" in layer_names
        assert "Presentation" in layer_names
        assert "Data Access" in layer_names

        # Each layer should have a CONTAINS edge to the class
        contains_from_layers = [
            e
            for e in g.edges
            if e.kind == EdgeKind.CONTAINS
            and g.get_node(e.source_fqn) is not None
            and g.get_node(e.source_fqn).kind == NodeKind.LAYER
        ]
        assert len(contains_from_layers) == 3

    def test_layer_node_count_property(self):
        """Layer nodes should have node_count reflecting member count."""
        g = SymbolGraph()

        c1 = _make_class("com.app.A")
        c1.properties["layer"] = "Business Logic"
        g.add_node(c1)

        c2 = _make_class("com.app.B")
        c2.properties["layer"] = "Business Logic"
        g.add_node(c2)

        assign_architectural_layers(g, app_name="test-app")

        bl_layer = g.get_node("layer:test-app:Business Logic")
        assert bl_layer is not None
        assert bl_layer.properties["node_count"] == 2


# ── Test 6: Empty Graph ─────────────────────────────────


class TestEmptyGraph:
    @pytest.mark.asyncio
    async def test_empty_graph_no_crash(self):
        """Enriching an empty graph should not crash."""
        ctx = _make_context(SymbolGraph())
        await enrich_graph(ctx)
        assert ctx.warnings == [] or all(isinstance(w, str) for w in ctx.warnings)


# ── Test 7: Single Class ────────────────────────────────


class TestSingleClass:
    def test_single_class_zero_metrics(self):
        """One class with no calls: fan_in=0, fan_out=0."""
        g = SymbolGraph()
        g.add_node(_make_class("com.app.Lonely"))
        g.add_node(_make_function("com.app.Lonely.doNothing"))
        g.add_edge(_contains_edge("com.app.Lonely", "com.app.Lonely.doNothing"))

        compute_fan_metrics(g)

        assert g.get_node("com.app.Lonely").properties["fan_in"] == 0
        assert g.get_node("com.app.Lonely").properties["fan_out"] == 0


# ── Test 9: Full Integration ─────────────────────────────


class TestEnrichGraphIntegration:
    @pytest.mark.asyncio
    async def test_realistic_graph_all_enrichments(self):
        """Realistic graph with multiple classes across modules
        -- all enrichments applied."""
        g = SymbolGraph()

        # Modules
        g.add_node(_make_module("com.app.web"))
        g.add_node(_make_module("com.app.service"))
        g.add_node(_make_module("com.app.data"))

        # Classes with layer assignments
        ctrl = _make_class("com.app.web.UserController", module_fqn="com.app.web")
        ctrl.properties["layer"] = "Presentation"
        g.add_node(ctrl)

        svc = _make_class("com.app.service.UserService", module_fqn="com.app.service")
        svc.properties["layer"] = "Business Logic"
        g.add_node(svc)

        repo = _make_class("com.app.data.UserRepository", module_fqn="com.app.data")
        repo.properties["layer"] = "Data Access"
        g.add_node(repo)

        # Methods
        g.add_node(_make_function("com.app.web.UserController.getUser"))
        g.add_node(_make_function("com.app.service.UserService.findUser"))
        g.add_node(_make_function("com.app.data.UserRepository.findById"))

        # Containment: module -> class
        g.add_edge(_contains_edge("com.app.web", "com.app.web.UserController"))
        g.add_edge(_contains_edge("com.app.service", "com.app.service.UserService"))
        g.add_edge(_contains_edge("com.app.data", "com.app.data.UserRepository"))

        # Containment: class -> method
        g.add_edge(
            _contains_edge(
                "com.app.web.UserController",
                "com.app.web.UserController.getUser",
            )
        )
        g.add_edge(
            _contains_edge(
                "com.app.service.UserService",
                "com.app.service.UserService.findUser",
            )
        )
        g.add_edge(
            _contains_edge(
                "com.app.data.UserRepository",
                "com.app.data.UserRepository.findById",
            )
        )

        # Call chain: controller -> service -> repository
        g.add_edge(
            _calls_edge(
                "com.app.web.UserController.getUser",
                "com.app.service.UserService.findUser",
            )
        )
        g.add_edge(
            _calls_edge(
                "com.app.service.UserService.findUser",
                "com.app.data.UserRepository.findById",
            )
        )

        ctx = _make_context(g)
        await enrich_graph(ctx)

        # 1. Fan metrics computed
        assert g.get_node("com.app.web.UserController").properties["fan_in"] == 0
        assert g.get_node("com.app.web.UserController").properties["fan_out"] == 1
        assert g.get_node("com.app.service.UserService").properties["fan_in"] == 1
        assert g.get_node("com.app.service.UserService").properties["fan_out"] == 1
        assert g.get_node("com.app.data.UserRepository").properties["fan_in"] == 1
        assert g.get_node("com.app.data.UserRepository").properties["fan_out"] == 0

        # 2. Class-level DEPENDS_ON edges created
        depends_on_edges = [e for e in g.edges if e.kind == EdgeKind.DEPENDS_ON]
        assert len(depends_on_edges) >= 2  # ctrl->svc, svc->repo

        # 3. Module-level IMPORTS edges created
        import_edges = [e for e in g.edges if e.kind == EdgeKind.IMPORTS]
        assert len(import_edges) >= 2  # web->service, service->data

        # 4. Layer nodes created
        layer_nodes = [n for n in g.nodes.values() if n.kind == NodeKind.LAYER]
        assert len(layer_nodes) == 3

        # Note: Community detection moved to Stage 10 (GDS Louvain)


# ── Test: Technology Nodes ───────────────────────────────


def _make_app(fqn: str, frameworks: list[str] | None = None) -> GraphNode:
    node = GraphNode(fqn=fqn, name=fqn, kind=NodeKind.APPLICATION)
    if frameworks:
        node.properties["detected_frameworks"] = frameworks
    return node


def _make_table(fqn: str, engine: str | None = None) -> GraphNode:
    node = GraphNode(fqn=fqn, name=fqn.split(".")[-1], kind=NodeKind.TABLE)
    if engine:
        node.properties["engine"] = engine
    return node


class TestTechnologyNodes:
    def test_framework_classes_grouped_into_tech_nodes(self):
        """Classes with framework property are grouped into COMPONENT nodes."""
        g = SymbolGraph()

        # Layer nodes must exist (created by assign_architectural_layers)
        g.add_node(
            GraphNode(
                fqn="layer:app:Presentation",
                name="Presentation",
                kind=NodeKind.LAYER,
                properties={"app_name": "app"},
            )
        )
        g.add_node(
            GraphNode(
                fqn="layer:app:Business Logic",
                name="Business Logic",
                kind=NodeKind.LAYER,
                properties={"app_name": "app"},
            )
        )

        # Classes with framework hints
        ctrl = _make_class("com.app.UserController")
        ctrl.properties["layer"] = "Presentation"
        ctrl.properties["framework"] = "spring-web"
        g.add_node(ctrl)

        svc = _make_class("com.app.UserService")
        svc.properties["layer"] = "Business Logic"
        svc.properties["framework"] = "spring-boot"
        g.add_node(svc)

        count = create_technology_nodes(g, app_name="app")
        assert count == 2

        # Check COMPONENT nodes exist
        comp_nodes = [n for n in g.nodes.values() if n.kind == NodeKind.COMPONENT]
        assert len(comp_nodes) == 2

        names = {n.name for n in comp_nodes}
        assert "Spring Web" in names
        assert "Spring Boot" in names

    def test_fallback_language_classes(self):
        """Classes with layer but no framework get grouped as language classes."""
        g = SymbolGraph()

        g.add_node(
            GraphNode(
                fqn="layer:app:Business Logic",
                name="Business Logic",
                kind=NodeKind.LAYER,
                properties={"app_name": "app"},
            )
        )

        cls = _make_class("com.app.Helper")
        cls.properties["layer"] = "Business Logic"
        cls.language = "java"
        g.add_node(cls)

        count = create_technology_nodes(g, app_name="app")
        assert count == 1

        comp = [n for n in g.nodes.values() if n.kind == NodeKind.COMPONENT][0]
        assert comp.name == "Java Classes"
        assert comp.properties["category"] == "language_classes"

    def test_table_nodes_create_database_component(self):
        """TABLE nodes get grouped under a database COMPONENT."""
        g = SymbolGraph()

        g.add_node(
            GraphNode(
                fqn="layer:app:Data Access",
                name="Data Access",
                kind=NodeKind.LAYER,
                properties={"app_name": "app"},
            )
        )
        g.add_node(_make_table("db.users", engine="postgresql"))
        g.add_node(_make_table("db.orders", engine="postgresql"))

        count = create_technology_nodes(g, app_name="app")
        assert count == 1

        comp = [n for n in g.nodes.values() if n.kind == NodeKind.COMPONENT][0]
        assert comp.name == "PostgreSQL"
        assert comp.properties["category"] == "database"
        assert comp.properties["table_count"] == 2

    def test_layer_contains_component_edges(self):
        """Layer -> CONTAINS -> Component edges are created."""
        g = SymbolGraph()

        g.add_node(
            GraphNode(
                fqn="layer:app:Presentation",
                name="Presentation",
                kind=NodeKind.LAYER,
                properties={"app_name": "app"},
            )
        )

        ctrl = _make_class("com.app.Controller")
        ctrl.properties["layer"] = "Presentation"
        ctrl.properties["framework"] = "spring-web"
        g.add_node(ctrl)

        create_technology_nodes(g, app_name="app")

        # Check Layer -> Component -> Class containment
        layer_to_comp = [
            e
            for e in g.edges
            if e.kind == EdgeKind.CONTAINS
            and e.source_fqn == "layer:app:Presentation"
            and g.get_node(e.target_fqn) is not None
            and g.get_node(e.target_fqn).kind == NodeKind.COMPONENT
        ]
        assert len(layer_to_comp) == 1

        comp_fqn = layer_to_comp[0].target_fqn
        comp_to_class = [
            e
            for e in g.edges
            if e.kind == EdgeKind.CONTAINS
            and e.source_fqn == comp_fqn
            and e.target_fqn == "com.app.Controller"
        ]
        assert len(comp_to_class) == 1

    def test_empty_graph_returns_zero(self):
        """Empty graph produces no technology nodes."""
        g = SymbolGraph()
        count = create_technology_nodes(g, app_name="app")
        assert count == 0

    def test_loc_total_aggregated(self):
        """LOC is summed across member classes."""
        g = SymbolGraph()

        g.add_node(
            GraphNode(
                fqn="layer:app:Presentation",
                name="Presentation",
                kind=NodeKind.LAYER,
                properties={"app_name": "app"},
            )
        )

        c1 = _make_class("com.app.A")
        c1.properties["layer"] = "Presentation"
        c1.properties["framework"] = "fastapi"
        c1.loc = 100
        g.add_node(c1)

        c2 = _make_class("com.app.B")
        c2.properties["layer"] = "Presentation"
        c2.properties["framework"] = "fastapi"
        c2.loc = 200
        g.add_node(c2)

        create_technology_nodes(g, app_name="app")

        comp = [n for n in g.nodes.values() if n.kind == NodeKind.COMPONENT][0]
        assert comp.properties["loc_total"] == 300
        assert comp.properties["class_count"] == 2


# ── Test: Virtual Dispatch Resolution ──────────────────


class TestVirtualDispatch:
    """Tests for resolve_virtual_dispatch() — creating synthetic CALLS from
    interface methods to implementation methods."""

    def _build_interface_impl_graph(self):
        """Helper: build a graph with UserService (interface) + UserServiceImpl (class)."""
        g = SymbolGraph()
        iface = GraphNode(fqn="com.UserService", name="UserService", kind=NodeKind.INTERFACE)
        impl = _make_class("com.UserServiceImpl")
        iface_method = _make_function("com.UserService.createUser")
        impl_method = _make_function("com.UserServiceImpl.createUser")

        g.add_node(iface)
        g.add_node(impl)
        g.add_node(iface_method)
        g.add_node(impl_method)

        # Containment: interface/class → method
        g.add_edge(_contains_edge("com.UserService", "com.UserService.createUser"))
        g.add_edge(_contains_edge("com.UserServiceImpl", "com.UserServiceImpl.createUser"))

        return g

    def test_creates_dispatch_edge_for_method_implements(self):
        """Interface.method → Impl.method CALLS edge should be created."""
        g = self._build_interface_impl_graph()

        # impl_method IMPLEMENTS iface_method
        g.add_edge(GraphEdge(
            source_fqn="com.UserServiceImpl.createUser",
            target_fqn="com.UserService.createUser",
            kind=EdgeKind.IMPLEMENTS,
        ))

        count = resolve_virtual_dispatch(g)
        assert count == 1

        # Should have a CALLS edge: interface method → impl method
        dispatch_edges = [
            e for e in g.edges
            if e.kind == EdgeKind.CALLS
            and e.source_fqn == "com.UserService.createUser"
            and e.target_fqn == "com.UserServiceImpl.createUser"
        ]
        assert len(dispatch_edges) == 1
        assert dispatch_edges[0].evidence == "virtual-dispatch"

    def test_handles_reverse_implements_direction(self):
        """IMPLEMENTS from interface→impl (SCIP direction) also creates dispatch edge."""
        g = self._build_interface_impl_graph()

        # interface→impl direction (as SCIP sometimes produces)
        g.add_edge(GraphEdge(
            source_fqn="com.UserService.createUser",
            target_fqn="com.UserServiceImpl.createUser",
            kind=EdgeKind.IMPLEMENTS,
        ))

        count = resolve_virtual_dispatch(g)
        assert count == 1

        dispatch_edges = [
            e for e in g.edges
            if e.kind == EdgeKind.CALLS
            and e.source_fqn == "com.UserService.createUser"
            and e.target_fqn == "com.UserServiceImpl.createUser"
        ]
        assert len(dispatch_edges) == 1

    def test_skips_class_level_implements(self):
        """CLASS → INTERFACE IMPLEMENTS should not generate dispatch edges."""
        g = SymbolGraph()
        iface = GraphNode(fqn="com.UserService", name="UserService", kind=NodeKind.INTERFACE)
        impl = _make_class("com.UserServiceImpl")

        g.add_node(iface)
        g.add_node(impl)

        # class-level IMPLEMENTS
        g.add_edge(GraphEdge(
            source_fqn="com.UserServiceImpl",
            target_fqn="com.UserService",
            kind=EdgeKind.IMPLEMENTS,
        ))

        count = resolve_virtual_dispatch(g)
        assert count == 0

    def test_no_duplicate_calls(self):
        """Should not create a dispatch edge if CALLS already exists."""
        g = self._build_interface_impl_graph()

        # IMPLEMENTS edge
        g.add_edge(GraphEdge(
            source_fqn="com.UserServiceImpl.createUser",
            target_fqn="com.UserService.createUser",
            kind=EdgeKind.IMPLEMENTS,
        ))
        # Pre-existing CALLS edge in the dispatch direction
        g.add_edge(GraphEdge(
            source_fqn="com.UserService.createUser",
            target_fqn="com.UserServiceImpl.createUser",
            kind=EdgeKind.CALLS,
        ))

        count = resolve_virtual_dispatch(g)
        assert count == 0

    def test_multiple_implementors(self):
        """Multiple implementations of the same interface method get dispatch edges."""
        g = SymbolGraph()
        iface = GraphNode(fqn="com.Service", name="Service", kind=NodeKind.INTERFACE)
        impl_a = _make_class("com.ServiceImplA")
        impl_b = _make_class("com.ServiceImplB")
        iface_method = _make_function("com.Service.run")
        impl1 = _make_function("com.ServiceImplA.run")
        impl2 = _make_function("com.ServiceImplB.run")

        for n in [iface, impl_a, impl_b, iface_method, impl1, impl2]:
            g.add_node(n)

        # Containment edges
        g.add_edge(_contains_edge("com.Service", "com.Service.run"))
        g.add_edge(_contains_edge("com.ServiceImplA", "com.ServiceImplA.run"))
        g.add_edge(_contains_edge("com.ServiceImplB", "com.ServiceImplB.run"))

        g.add_edge(GraphEdge(
            source_fqn="com.ServiceImplA.run",
            target_fqn="com.Service.run",
            kind=EdgeKind.IMPLEMENTS,
        ))
        g.add_edge(GraphEdge(
            source_fqn="com.ServiceImplB.run",
            target_fqn="com.Service.run",
            kind=EdgeKind.IMPLEMENTS,
        ))

        count = resolve_virtual_dispatch(g)
        assert count == 2

    def test_deduplicates_implements_edges(self):
        """Duplicate IMPLEMENTS edges (from tree-sitter + SCIP) should produce one CALLS edge."""
        g = self._build_interface_impl_graph()

        # Two duplicate IMPLEMENTS edges
        g.add_edge(GraphEdge(
            source_fqn="com.UserServiceImpl.createUser", target_fqn="com.UserService.createUser",
            kind=EdgeKind.IMPLEMENTS, evidence="tree-sitter",
        ))
        g.add_edge(GraphEdge(
            source_fqn="com.UserServiceImpl.createUser", target_fqn="com.UserService.createUser",
            kind=EdgeKind.IMPLEMENTS, evidence="scip",
        ))

        count = resolve_virtual_dispatch(g)
        assert count == 1

    def test_bidirectional_implements_creates_one_dispatch(self):
        """IMPLEMENTS in both directions should still create only one dispatch CALLS edge."""
        g = self._build_interface_impl_graph()

        # Both directions (as seen in real Neo4j data)
        g.add_edge(GraphEdge(
            source_fqn="com.UserServiceImpl.createUser",
            target_fqn="com.UserService.createUser",
            kind=EdgeKind.IMPLEMENTS,
        ))
        g.add_edge(GraphEdge(
            source_fqn="com.UserService.createUser",
            target_fqn="com.UserServiceImpl.createUser",
            kind=EdgeKind.IMPLEMENTS,
        ))

        count = resolve_virtual_dispatch(g)
        assert count == 1

        # Only interface → impl, NOT impl → interface
        dispatch = [e for e in g.edges if e.kind == EdgeKind.CALLS]
        assert len(dispatch) == 1
        assert dispatch[0].source_fqn == "com.UserService.createUser"
        assert dispatch[0].target_fqn == "com.UserServiceImpl.createUser"
