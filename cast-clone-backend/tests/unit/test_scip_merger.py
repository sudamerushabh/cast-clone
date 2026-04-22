"""Tests for SCIP merger.

Matching SCIP symbols to tree-sitter nodes and upgrading edges.
"""

from pathlib import Path

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.manifest import ProjectManifest
from app.stages.scip.merger import (
    MergeStats,
    match_scip_symbol_to_node,
    merge_scip_into_context,
    scip_symbol_to_fqn,
)
from app.stages.scip.protobuf_parser import (
    SCIPDocument,
    SCIPIndex,
    SCIPOccurrence,
    SCIPRelationship,
    SCIPSymbolInfo,
)


class TestSCIPSymbolToFQN:
    """Test converting SCIP symbol strings to our FQN format."""

    def test_java_class(self):
        fqn = scip_symbol_to_fqn("maven . com/example 1.0 UserService#")
        assert fqn == "com.example.UserService"

    def test_java_method(self):
        fqn = scip_symbol_to_fqn("maven . com/example 1.0 UserService#createUser().")
        assert fqn == "com.example.UserService.createUser"

    def test_java_field(self):
        fqn = scip_symbol_to_fqn("maven . com/example 1.0 UserService#userRepository.")
        assert fqn == "com.example.UserService.userRepository"

    def test_semanticdb_java_class(self):
        """Real scip-java output uses semanticdb scheme with Maven coordinates."""
        fqn = scip_symbol_to_fqn(
            "semanticdb maven maven/org.springframework.samples/spring-petclinic "
            "4.0.0-SNAPSHOT org/springframework/samples/petclinic/owner/OwnerController#"
        )
        assert fqn == "org.springframework.samples.petclinic.owner.OwnerController"

    def test_semanticdb_java_method(self):
        fqn = scip_symbol_to_fqn(
            "semanticdb maven maven/org.springframework.samples/spring-petclinic "
            "4.0.0-SNAPSHOT org/springframework/samples/petclinic/owner/OwnerController#showOwner()."
        )
        assert fqn == "org.springframework.samples.petclinic.owner.OwnerController.showOwner"

    def test_semanticdb_java_nested_class(self):
        fqn = scip_symbol_to_fqn(
            "semanticdb maven maven/org.example/app "
            "1.0 com/example/Outer#Inner#method()."
        )
        assert fqn == "com.example.Outer.Inner.method"

    def test_semanticdb_java_init(self):
        """Back-ticked <init> should have back-ticks stripped."""
        fqn = scip_symbol_to_fqn(
            "semanticdb maven maven/org.example/app "
            "1.0 com/example/Foo#`<init>`()."
        )
        assert fqn == "com.example.Foo.<init>"

    def test_typescript_symbol(self):
        fqn = scip_symbol_to_fqn(
            "npm @sourcegraph/scip-typescript 0.2.0 src/index.ts/App#"
        )
        assert "App" in fqn

    def test_python_symbol(self):
        fqn = scip_symbol_to_fqn("pip . myproject 0.1.0 app/main.py/create_app().")
        assert "create_app" in fqn

    def test_empty_symbol(self):
        fqn = scip_symbol_to_fqn("")
        assert fqn == ""

    def test_local_symbol_ignored(self):
        """Local symbols (starting with 'local ') have no stable FQN."""
        fqn = scip_symbol_to_fqn("local 42")
        assert fqn == ""


class TestMatchSCIPSymbolToNode:
    """Test matching SCIP symbols to existing GraphNodes."""

    def test_match_by_fqn(self):
        graph = SymbolGraph()
        node = GraphNode(
            fqn="com.example.UserService",
            name="UserService",
            kind=NodeKind.CLASS,
            path="src/main/java/com/example/UserService.java",
            line=10,
        )
        graph.add_node(node)

        matched = match_scip_symbol_to_node(
            graph,
            fqn="com.example.UserService",
            file_path="src/main/java/com/example/UserService.java",
            line=10,
        )
        assert matched is node

    def test_match_by_file_and_line(self):
        """When FQN doesn't match, fall back to file:line matching."""
        graph = SymbolGraph()
        node = GraphNode(
            fqn="UserService",  # tree-sitter may have a short FQN
            name="UserService",
            kind=NodeKind.CLASS,
            path="src/main/java/com/example/UserService.java",
            line=10,
        )
        graph.add_node(node)

        matched = match_scip_symbol_to_node(
            graph,
            fqn="com.example.UserService",  # SCIP has the full FQN
            file_path="src/main/java/com/example/UserService.java",
            line=10,
        )
        assert matched is node

    def test_no_match_returns_none(self):
        graph = SymbolGraph()
        matched = match_scip_symbol_to_node(
            graph,
            fqn="com.example.NonExistent",
            file_path="src/Missing.java",
            line=1,
        )
        assert matched is None


class TestMergeStats:
    def test_defaults(self):
        stats = MergeStats()
        assert stats.resolved_count == 0
        assert stats.new_nodes == 0
        assert stats.upgraded_edges == 0
        assert stats.new_implements_edges == 0

    def test_add(self):
        s1 = MergeStats(
            resolved_count=5,
            new_nodes=1,
            upgraded_edges=3,
            new_implements_edges=1,
        )
        s2 = MergeStats(
            resolved_count=10,
            new_nodes=2,
            upgraded_edges=7,
            new_implements_edges=0,
        )
        total = MergeStats(
            resolved_count=s1.resolved_count + s2.resolved_count,
            new_nodes=s1.new_nodes + s2.new_nodes,
            upgraded_edges=s1.upgraded_edges + s2.upgraded_edges,
            new_implements_edges=s1.new_implements_edges + s2.new_implements_edges,
        )
        assert total.resolved_count == 15


class TestMergeSCIPIntoContext:
    def _make_context(self, graph: SymbolGraph | None = None) -> AnalysisContext:
        ctx = AnalysisContext(project_id="test-proj")
        ctx.manifest = ProjectManifest(root_path=Path("/code"))
        if graph:
            ctx.graph = graph
        return ctx

    def test_upgrade_edge_confidence(self):
        """SCIP reference upgrades a tree-sitter CALLS edge from LOW to HIGH."""
        graph = SymbolGraph()
        # Tree-sitter created nodes
        caller = GraphNode(
            fqn="com.example.UserService.createUser",
            name="createUser",
            kind=NodeKind.FUNCTION,
            path="src/main/java/com/example/UserService.java",
            line=15,
        )
        callee = GraphNode(
            fqn="com.example.UserRepository.save",
            name="save",
            kind=NodeKind.FUNCTION,
            path="src/main/java/com/example/UserRepository.java",
            line=20,
        )
        graph.add_node(caller)
        graph.add_node(callee)

        # Tree-sitter created a low-confidence edge
        edge = GraphEdge(
            source_fqn="com.example.UserService.createUser",
            target_fqn="com.example.UserRepository.save",
            kind=EdgeKind.CALLS,
            confidence=Confidence.LOW,
            evidence="tree-sitter",
        )
        graph.add_edge(edge)

        ctx = self._make_context(graph)

        # SCIP provides a reference from createUser -> save
        scip_index = SCIPIndex(
            documents=[
                SCIPDocument(
                    relative_path="src/main/java/com/example/UserService.java",
                    occurrences=[
                        # Definition of createUser
                        SCIPOccurrence(
                            range=[15, 16, 26],
                            symbol="maven . com/example 1.0 UserService#createUser().",
                            symbol_roles=0x1,
                        ),
                        # Reference to save (call)
                        SCIPOccurrence(
                            range=[20, 20, 24],
                            symbol="maven . com/example 1.0 UserRepository#save().",
                            symbol_roles=0x0,
                        ),
                    ],
                    symbols=[
                        SCIPSymbolInfo(
                            symbol="maven . com/example 1.0 UserService#createUser().",
                            documentation=["Creates a new user."],
                            relationships=[],
                        ),
                    ],
                ),
            ],
            metadata_tool_name="scip-java",
            metadata_tool_version="0.8.0",
        )

        stats = merge_scip_into_context(ctx, scip_index, "java")

        # Edge should be upgraded
        edges = graph.get_edges_from("com.example.UserService.createUser")
        assert len(edges) == 1
        assert edges[0].confidence == Confidence.HIGH
        assert edges[0].evidence == "scip"
        assert stats.upgraded_edges >= 1

    def test_add_documentation_to_node(self):
        """SCIP documentation is added to matching node properties."""
        graph = SymbolGraph()
        node = GraphNode(
            fqn="com.example.UserService",
            name="UserService",
            kind=NodeKind.CLASS,
            path="src/main/java/com/example/UserService.java",
            line=10,
        )
        graph.add_node(node)

        ctx = self._make_context(graph)

        scip_index = SCIPIndex(
            documents=[
                SCIPDocument(
                    relative_path="src/main/java/com/example/UserService.java",
                    occurrences=[
                        SCIPOccurrence(
                            range=[10, 13, 24],
                            symbol="maven . com/example 1.0 UserService#",
                            symbol_roles=0x1,
                        ),
                    ],
                    symbols=[
                        SCIPSymbolInfo(
                            symbol="maven . com/example 1.0 UserService#",
                            documentation=["Service for managing users."],
                            relationships=[],
                        ),
                    ],
                ),
            ],
            metadata_tool_name="scip-java",
            metadata_tool_version="0.8.0",
        )

        merge_scip_into_context(ctx, scip_index, "java")

        assert "documentation" in node.properties
        assert "managing users" in node.properties["documentation"]

    def test_add_implements_edge(self):
        """SCIP implementation relationship creates an IMPLEMENTS edge."""
        graph = SymbolGraph()
        impl_node = GraphNode(
            fqn="com.example.UserServiceImpl",
            name="UserServiceImpl",
            kind=NodeKind.CLASS,
            path="src/main/java/com/example/UserServiceImpl.java",
            line=5,
        )
        iface_node = GraphNode(
            fqn="com.example.UserService",
            name="UserService",
            kind=NodeKind.INTERFACE,
            path="src/main/java/com/example/UserService.java",
            line=3,
        )
        graph.add_node(impl_node)
        graph.add_node(iface_node)

        ctx = self._make_context(graph)

        scip_index = SCIPIndex(
            documents=[
                SCIPDocument(
                    relative_path="src/main/java/com/example/UserServiceImpl.java",
                    occurrences=[
                        SCIPOccurrence(
                            range=[5, 13, 29],
                            symbol="maven . com/example 1.0 UserServiceImpl#",
                            symbol_roles=0x1,
                        ),
                    ],
                    symbols=[
                        SCIPSymbolInfo(
                            symbol="maven . com/example 1.0 UserServiceImpl#",
                            documentation=[],
                            relationships=[
                                SCIPRelationship(
                                    symbol="maven . com/example 1.0 UserService#",
                                    is_implementation=True,
                                ),
                            ],
                        ),
                    ],
                ),
            ],
            metadata_tool_name="scip-java",
            metadata_tool_version="0.8.0",
        )

        stats = merge_scip_into_context(ctx, scip_index, "java")

        implements_edges = [e for e in graph.edges if e.kind == EdgeKind.IMPLEMENTS]
        assert len(implements_edges) >= 1
        assert implements_edges[0].source_fqn == "com.example.UserServiceImpl"
        assert implements_edges[0].target_fqn == "com.example.UserService"
        assert implements_edges[0].confidence == Confidence.HIGH
        assert implements_edges[0].evidence == "scip"
        assert stats.new_implements_edges >= 1

    def test_upgrade_fqn_from_scip(self):
        """When tree-sitter had a short FQN, SCIP upgrades it."""
        graph = SymbolGraph()
        node = GraphNode(
            fqn="UserService",
            name="UserService",
            kind=NodeKind.CLASS,
            path="src/main/java/com/example/UserService.java",
            line=10,
        )
        graph.add_node(node)

        ctx = self._make_context(graph)

        scip_index = SCIPIndex(
            documents=[
                SCIPDocument(
                    relative_path="src/main/java/com/example/UserService.java",
                    occurrences=[
                        SCIPOccurrence(
                            range=[10, 13, 24],
                            symbol="maven . com/example 1.0 UserService#",
                            symbol_roles=0x1,
                        ),
                    ],
                    symbols=[],
                ),
            ],
            metadata_tool_name="scip-java",
            metadata_tool_version="0.8.0",
        )

        merge_scip_into_context(ctx, scip_index, "java")

        # Old short FQN should no longer be in graph
        assert graph.get_node("UserService") is None
        # New full FQN should exist
        upgraded = graph.get_node("com.example.UserService")
        assert upgraded is not None
        assert upgraded.name == "UserService"

    def test_empty_scip_index(self):
        """Empty SCIP index produces zero stats, no errors."""
        graph = SymbolGraph()
        ctx = self._make_context(graph)

        scip_index = SCIPIndex(documents=[])
        stats = merge_scip_into_context(ctx, scip_index, "java")

        assert stats.resolved_count == 0
        assert stats.upgraded_edges == 0

    def test_scip_local_symbols_skipped(self):
        """Local symbols (compiler internals) are ignored."""
        graph = SymbolGraph()
        ctx = self._make_context(graph)

        scip_index = SCIPIndex(
            documents=[
                SCIPDocument(
                    relative_path="src/App.java",
                    occurrences=[
                        SCIPOccurrence(
                            range=[5, 10, 20],
                            symbol="local 42",
                            symbol_roles=0x1,
                        ),
                    ],
                    symbols=[],
                ),
            ],
            metadata_tool_name="scip-java",
            metadata_tool_version="0.8.0",
        )

        stats = merge_scip_into_context(ctx, scip_index, "java")
        assert stats.resolved_count == 0


class TestScipPythonSymbolFormat:
    def test_external_package_method(self):
        """scip-python external package method symbol → dotted FQN."""
        s = "scip-python python PyYAML 6.0 yaml/dump()."
        assert scip_symbol_to_fqn(s) == "PyYAML.yaml.dump"

    def test_project_local_function(self):
        """scip-python project-local module function."""
        s = "scip-python python myapp 0.1.0 myapp/routes/users.py/create_user()."
        assert scip_symbol_to_fqn(s) == "myapp.myapp.routes.users.py.create_user"

    def test_project_local_class(self):
        """scip-python project-local class."""
        s = "scip-python python myapp 0.1.0 myapp/models/user.py/User#"
        assert scip_symbol_to_fqn(s) == "myapp.myapp.models.user.py.User"

    def test_project_local_class_method(self):
        """scip-python class method with receiver."""
        s = "scip-python python myapp 0.1.0 myapp/models/user.py/User#save()."
        assert scip_symbol_to_fqn(s) == "myapp.myapp.models.user.py.User.save"

    def test_local_symbol_returns_empty(self):
        """Local symbols (function-scope vars) should return empty string."""
        assert scip_symbol_to_fqn("local 42") == ""

    def test_empty_symbol_returns_empty(self):
        assert scip_symbol_to_fqn("") == ""
