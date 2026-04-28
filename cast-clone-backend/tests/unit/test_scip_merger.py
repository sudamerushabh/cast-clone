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
    scip_descriptor_kind,
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
        assert (
            fqn
            == "org.springframework.samples.petclinic.owner.OwnerController.showOwner"
        )

    def test_semanticdb_java_nested_class(self):
        fqn = scip_symbol_to_fqn(
            "semanticdb maven maven/org.example/app "
            "1.0 com/example/Outer#Inner#method()."
        )
        assert fqn == "com.example.Outer.Inner.method"

    def test_semanticdb_java_init(self):
        """Back-ticked <init> should have back-ticks stripped."""
        fqn = scip_symbol_to_fqn(
            "semanticdb maven maven/org.example/app 1.0 com/example/Foo#`<init>`()."
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

    def test_kind_hint_rejects_wrong_kind_at_same_line(self):
        """A SCIP field at line 6 (0-indexed) must NOT bind to a CLASS at line 6
        (1-indexed).  This is the regression that turned ``TodoCreate``'s
        INHERITS edge source into ``TodoCreate.title`` for fastapi-todo.
        """
        graph = SymbolGraph()
        cls = GraphNode(
            fqn="app.schemas.todo.TodoCreate",
            name="TodoCreate",
            kind=NodeKind.CLASS,
            path="app/schemas/todo.py",
            line=6,  # tree-sitter 1-indexed
            end_line=9,
        )
        graph.add_node(cls)

        # SCIP field definition: 0-indexed line 6 == tree-sitter line 7
        # would normally collide with the class at line 6 via the legacy
        # file:line scan.  The ``field`` kind hint must reject CLASS.
        matched = match_scip_symbol_to_node(
            graph,
            fqn="fastapi-todo.app.schemas.todo.TodoCreate.title",
            file_path="app/schemas/todo.py",
            line=6,
            kind_hint="field",
        )
        assert matched is None

    def test_kind_hint_accepts_off_by_one_line_for_python(self):
        """Tree-sitter is 1-indexed, scip-python is 0-indexed; ``line+1`` must
        also be a valid match when a kind hint is supplied so the class at
        tree-sitter line 6 binds to the SCIP class definition at 0-indexed
        line 5.
        """
        graph = SymbolGraph()
        cls = GraphNode(
            fqn="app.schemas.todo.TodoCreate",
            name="TodoCreate",
            kind=NodeKind.CLASS,
            path="app/schemas/todo.py",
            line=6,  # tree-sitter 1-indexed
        )
        graph.add_node(cls)

        matched = match_scip_symbol_to_node(
            graph,
            fqn="fastapi-todo.app.schemas.todo.TodoCreate",
            file_path="app/schemas/todo.py",
            line=5,  # SCIP 0-indexed
            kind_hint="class",
        )
        assert matched is cls

    def test_no_kind_hint_keeps_legacy_strict_line_match(self):
        """Without a kind hint, the line must match exactly (no off-by-one
        widening).  This preserves Java/Spring behaviour where the unit-test
        fixtures assume aligned line numbers.
        """
        graph = SymbolGraph()
        node = GraphNode(
            fqn="UserService",
            name="UserService",
            kind=NodeKind.CLASS,
            path="src/UserService.java",
            line=10,
        )
        graph.add_node(node)
        # Legacy callers (no hint) require strict line equality.
        assert (
            match_scip_symbol_to_node(
                graph, fqn="x", file_path="src/UserService.java", line=11
            )
            is None
        )


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

    def test_python_class_field_collision_does_not_rewrite_class_fqn(self):
        """Regression: a SCIP field-definition occurrence at the same file:line
        as a tree-sitter CLASS (because tree-sitter is 1-indexed and
        scip-python is 0-indexed) must NOT rewrite the CLASS FQN to the field
        FQN.  Before the kind-gating fix, ``TodoCreate`` was being renamed
        to ``TodoCreate.title`` and INHERITS edges followed the rename,
        which broke M3's Pydantic plugin (it tagged FIELDs as Pydantic
        models instead of CLASSes).
        """
        graph = SymbolGraph()
        cls = GraphNode(
            fqn="app.schemas.todo.TodoCreate",
            name="TodoCreate",
            kind=NodeKind.CLASS,
            path="app/schemas/todo.py",
            line=6,
            end_line=9,
        )
        field = GraphNode(
            fqn="app.schemas.todo.TodoCreate.title",
            name="title",
            kind=NodeKind.FIELD,
            path="app/schemas/todo.py",
            line=7,
        )
        graph.add_node(cls)
        graph.add_node(field)
        graph.add_edge(
            GraphEdge(
                source_fqn="app.schemas.todo.TodoCreate",
                target_fqn="BaseModel",
                kind=EdgeKind.INHERITS,
            )
        )

        ctx = self._make_context(graph)

        scip_index = SCIPIndex(
            documents=[
                SCIPDocument(
                    relative_path="app/schemas/todo.py",
                    occurrences=[
                        # Class at SCIP 0-indexed line 5 (tree-sitter line 6)
                        SCIPOccurrence(
                            range=[5, 6, 16],
                            symbol=(
                                "scip-python python myapp 0.1.0 "
                                "`app.schemas.todo`/TodoCreate#"
                            ),
                            symbol_roles=0x1,
                        ),
                        # Field at SCIP 0-indexed line 6 (tree-sitter line 7) —
                        # this used to collide with the class at line 6
                        # (1-indexed) and rename CLASS -> CLASS.title.
                        SCIPOccurrence(
                            range=[6, 4, 9],
                            symbol=(
                                "scip-python python myapp 0.1.0 "
                                "`app.schemas.todo`/TodoCreate#title."
                            ),
                            symbol_roles=0x1,
                        ),
                    ],
                    symbols=[],
                ),
            ],
        )

        merge_scip_into_context(ctx, scip_index, "python")

        # The class FQN should be the SCIP-upgraded form.
        renamed_class = graph.get_node("myapp.app.schemas.todo.TodoCreate")
        assert renamed_class is not None
        assert renamed_class.kind == NodeKind.CLASS

        # The INHERITS edge must follow the class rename and source must
        # still point at the CLASS, NOT at a FIELD.
        inherits = [e for e in graph.edges if e.kind == EdgeKind.INHERITS]
        assert len(inherits) == 1
        src_fqn = inherits[0].source_fqn
        src_node = graph.get_node(src_fqn)
        assert src_node is not None
        assert src_node.kind == NodeKind.CLASS, (
            f"INHERITS source rebound to {src_node.kind} ({src_fqn}); "
            "must remain CLASS"
        )

    def test_python_function_parameter_does_not_rewrite_function_fqn(self):
        """Regression: a SCIP parameter occurrence (``foo().(param)``) must NOT
        be matched against any graph node — kept it would rewrite the
        containing function's FQN to ``foo().(param)``, garbling
        downstream consumers like the FastAPI Pydantic plugin which does
        ``handler.fqn.rsplit('.', 1)``.
        """
        graph = SymbolGraph()
        func = GraphNode(
            fqn="app.routes.todos.update_todo",
            name="update_todo",
            kind=NodeKind.FUNCTION,
            path="app/routes/todos.py",
            line=8,
            end_line=15,
        )
        graph.add_node(func)

        ctx = self._make_context(graph)

        scip_index = SCIPIndex(
            documents=[
                SCIPDocument(
                    relative_path="app/routes/todos.py",
                    occurrences=[
                        # Function definition.
                        SCIPOccurrence(
                            range=[7, 4, 14],
                            symbol=(
                                "scip-python python myapp 0.1.0 "
                                "`app.routes.todos`/update_todo()."
                            ),
                            symbol_roles=0x1,
                        ),
                        # Parameter definition (would collide via file:line).
                        SCIPOccurrence(
                            range=[7, 15, 22],
                            symbol=(
                                "scip-python python myapp 0.1.0 "
                                "`app.routes.todos`/update_todo().(todo_id)"
                            ),
                            symbol_roles=0x1,
                        ),
                    ],
                    symbols=[],
                ),
            ],
        )

        merge_scip_into_context(ctx, scip_index, "python")

        # The function FQN must be the SCIP-upgraded plain form — never the
        # parameter-suffixed form.
        renamed = graph.get_node("myapp.app.routes.todos.update_todo")
        assert renamed is not None
        assert renamed.kind == NodeKind.FUNCTION
        # Confirm no node carries the malformed parameter-suffixed FQN.
        for n in graph.nodes.values():
            assert "()." not in n.fqn, f"parameter FQN leaked: {n.fqn}"

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

    def test_parameter_descriptor_returns_empty(self):
        """SCIP parameter symbols (``foo().(param)``) must NOT produce an FQN.

        Pyright/scip-python emits one of these per function parameter; if we
        kept them they would collide with the parent function via file:line
        fallback and rewrite the function FQN to e.g.
        ``update_todo().(todo_id)`` — which then breaks any plugin that does
        ``handler.fqn.rsplit('.', 1)`` to derive the module path.
        """
        s = (
            "scip-python python myapp 0.1.0 "
            "myapp/routes/todos.py/update_todo().(todo_id)"
        )
        assert scip_symbol_to_fqn(s) == ""

    def test_type_parameter_descriptor_returns_empty(self):
        """SCIP generic-type-parameter descriptors (``foo().[T]``) also skip."""
        s = "scip-python python myapp 0.1.0 myapp/utils.py/identity().[T]"
        assert scip_symbol_to_fqn(s) == ""


class TestScipDescriptorKind:
    """Locks in the kind-hint extraction used to gate file:line matching."""

    def test_class_descriptor(self):
        assert (
            scip_descriptor_kind(
                "scip-python python myapp 0.1.0 myapp/models.py/User#"
            )
            == "class"
        )

    def test_function_descriptor(self):
        assert (
            scip_descriptor_kind(
                "scip-python python myapp 0.1.0 myapp/views.py/index()."
            )
            == "function"
        )

    def test_field_descriptor(self):
        assert (
            scip_descriptor_kind(
                "scip-python python myapp 0.1.0 myapp/models.py/User#name."
            )
            == "field"
        )

    def test_module_descriptor(self):
        assert (
            scip_descriptor_kind(
                "scip-python python myapp 0.1.0 `myapp.routes`/__init__:"
            )
            == "module"
        )

    def test_parameter_descriptor(self):
        assert (
            scip_descriptor_kind(
                "scip-python python myapp 0.1.0 myapp/views.py/index().(req)"
            )
            == "parameter"
        )

    def test_local_descriptor(self):
        assert scip_descriptor_kind("local 42") == "local"

    def test_empty_returns_none(self):
        assert scip_descriptor_kind("") is None
