"""Tests for the tree-sitter parser framework."""

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.treesitter.extractors import (
    LanguageExtractor,
    clear_extractors,
    get_extractor,
    register_extractor,
    registered_languages,
)
from app.stages.treesitter.parser import (
    _resolve_symbols,
    get_language,
    get_parser,
    parse_with_treesitter,
)


class MockJavaExtractor:
    """A mock extractor that returns canned nodes/edges for testing."""

    def extract(
        self,
        source: bytes,
        file_path: str,
        root_path: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        nodes = [
            GraphNode(
                fqn=f"com.example.{file_path.split('/')[-1].replace('.java', '')}",
                name=file_path.split("/")[-1].replace(".java", ""),
                kind=NodeKind.CLASS,
                language="java",
                path=file_path,
                line=1,
                end_line=10,
            ),
        ]
        edges: list[GraphEdge] = []
        return nodes, edges


@dataclass
class FakeSourceFile:
    path: str
    language: str
    size_bytes: int = 100


@dataclass
class FakeManifest:
    root_path: Path
    source_files: list[FakeSourceFile]

    def files_for_language(self, lang: str) -> list[FakeSourceFile]:
        return [f for f in self.source_files if f.language == lang]


class TestExtractorRegistry:
    def setup_method(self) -> None:
        clear_extractors()

    def teardown_method(self) -> None:
        clear_extractors()

    def test_register_and_retrieve(self) -> None:
        ext = MockJavaExtractor()
        register_extractor("java", ext)
        assert get_extractor("java") is ext

    def test_get_unknown_returns_none(self) -> None:
        assert get_extractor("cobol") is None

    def test_register_overwrites(self) -> None:
        ext1 = MockJavaExtractor()
        ext2 = MockJavaExtractor()
        register_extractor("java", ext1)
        register_extractor("java", ext2)
        assert get_extractor("java") is ext2

    def test_clear_extractors(self) -> None:
        register_extractor("java", MockJavaExtractor())
        clear_extractors()
        assert get_extractor("java") is None


class TestGrammarLoading:
    def test_load_java_language(self) -> None:
        lang = get_language("java")
        assert lang is not None

    def test_load_python_language(self) -> None:
        lang = get_language("python")
        assert lang is not None

    def test_load_typescript_language(self) -> None:
        lang = get_language("typescript")
        assert lang is not None

    def test_load_csharp_language(self) -> None:
        lang = get_language("csharp")
        assert lang is not None

    def test_load_javascript_uses_typescript_grammar(self) -> None:
        lang = get_language("javascript")
        assert lang is not None

    def test_unknown_language_raises(self) -> None:
        with pytest.raises(ValueError, match="No grammar for"):
            get_language("brainfuck")

    def test_language_is_cached(self) -> None:
        lang1 = get_language("java")
        lang2 = get_language("java")
        assert lang1 is lang2

    def test_get_parser_returns_parser(self) -> None:
        parser = get_parser("java")
        assert parser is not None
        tree = parser.parse(b"public class Foo {}")
        assert tree.root_node is not None
        assert tree.root_node.type == "program"


class TestParseWithTreesitter:
    def setup_method(self) -> None:
        clear_extractors()

    def teardown_method(self) -> None:
        clear_extractors()

    @pytest.mark.asyncio
    async def test_empty_manifest_returns_empty_graph(self) -> None:
        manifest = FakeManifest(root_path=Path("/tmp/project"), source_files=[])
        graph = await parse_with_treesitter(manifest)  # type: ignore[arg-type]
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    @pytest.mark.asyncio
    async def test_unknown_language_is_skipped(self) -> None:
        manifest = FakeManifest(
            root_path=Path("/tmp/project"),
            source_files=[FakeSourceFile(path="main.rs", language="rust")],
        )
        graph = await parse_with_treesitter(manifest)  # type: ignore[arg-type]
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    @pytest.mark.asyncio
    async def test_parses_files_with_registered_extractor(self) -> None:
        register_extractor("java", MockJavaExtractor())
        manifest = FakeManifest(
            root_path=Path("/tmp/project"),
            source_files=[
                FakeSourceFile(path="src/Foo.java", language="java"),
                FakeSourceFile(path="src/Bar.java", language="java"),
            ],
        )

        def mock_parse(
            file_path: str, language: str, root_path: str
        ) -> tuple[list[GraphNode], list[GraphEdge]]:
            ext = get_extractor(language)
            if ext is None:
                return [], []
            return ext.extract(b"// mock source", file_path, root_path)

        with patch(
            "app.stages.treesitter.parser._parse_single_file",
            side_effect=mock_parse,
        ):
            graph = await parse_with_treesitter(manifest)  # type: ignore[arg-type]

        assert len(graph.nodes) == 2
        fqns = set(graph.nodes.keys())
        assert "com.example.Foo" in fqns
        assert "com.example.Bar" in fqns

    @pytest.mark.asyncio
    async def test_multiple_languages(self) -> None:
        class MockPythonExtractor:
            def extract(
                self, source: bytes, file_path: str, root_path: str
            ) -> tuple[list[GraphNode], list[GraphEdge]]:
                mod_name = file_path.split("/")[-1].replace(".py", "")
                return [
                    GraphNode(
                        fqn=f"mypackage.{mod_name}",
                        name=mod_name,
                        kind=NodeKind.MODULE,
                        language="python",
                        path=file_path,
                    )
                ], []

        register_extractor("java", MockJavaExtractor())
        register_extractor("python", MockPythonExtractor())

        manifest = FakeManifest(
            root_path=Path("/tmp/project"),
            source_files=[
                FakeSourceFile(path="src/Foo.java", language="java"),
                FakeSourceFile(path="lib/utils.py", language="python"),
            ],
        )

        def mock_parse(
            file_path: str, language: str, root_path: str
        ) -> tuple[list[GraphNode], list[GraphEdge]]:
            ext = get_extractor(language)
            if ext is None:
                return [], []
            return ext.extract(b"// mock", file_path, root_path)

        with patch(
            "app.stages.treesitter.parser._parse_single_file",
            side_effect=mock_parse,
        ):
            graph = await parse_with_treesitter(manifest)  # type: ignore[arg-type]

        assert len(graph.nodes) == 2
        assert "com.example.Foo" in graph.nodes
        assert "mypackage.utils" in graph.nodes

    @pytest.mark.asyncio
    async def test_file_parse_error_is_skipped(self) -> None:
        register_extractor("java", MockJavaExtractor())
        manifest = FakeManifest(
            root_path=Path("/tmp/project"),
            source_files=[
                FakeSourceFile(path="src/Good.java", language="java"),
                FakeSourceFile(path="src/Bad.java", language="java"),
            ],
        )

        def mock_parse(
            file_path: str, language: str, root_path: str
        ) -> tuple[list[GraphNode], list[GraphEdge]]:
            if "Bad" in file_path:
                raise RuntimeError("Parse error in bad file")
            ext = get_extractor(language)
            if ext is None:
                return [], []
            return ext.extract(b"// mock", file_path, root_path)

        with patch(
            "app.stages.treesitter.parser._parse_single_file",
            side_effect=mock_parse,
        ):
            graph = await parse_with_treesitter(manifest)  # type: ignore[arg-type]

        assert len(graph.nodes) == 1
        assert "com.example.Good" in graph.nodes


class TestGlobalSymbolResolution:
    """Tests for the post-parse global symbol resolution pass."""

    def _make_graph_with_imports(self) -> SymbolGraph:
        """Build a graph simulating two files with imports and unresolved calls.

        File layout:
          com.example.service.UserService (class)
            - imports com.example.repo.UserRepository
            - has method createUser() that calls findById() [UNRESOLVED]
          com.example.repo.UserRepository (class)
            - has method findById()
        """
        graph = SymbolGraph()

        graph.add_node(
            GraphNode(
                fqn="com.example.service.UserService",
                name="UserService",
                kind=NodeKind.CLASS,
                language="java",
                path="src/main/java/com/example/service/UserService.java",
                line=3,
            )
        )
        graph.add_node(
            GraphNode(
                fqn="com.example.service.UserService.createUser",
                name="createUser",
                kind=NodeKind.FUNCTION,
                language="java",
                path="src/main/java/com/example/service/UserService.java",
                line=10,
            )
        )
        graph.add_node(
            GraphNode(
                fqn="com.example.repo.UserRepository",
                name="UserRepository",
                kind=NodeKind.CLASS,
                language="java",
                path="src/main/java/com/example/repo/UserRepository.java",
                line=3,
            )
        )
        graph.add_node(
            GraphNode(
                fqn="com.example.repo.UserRepository.findById",
                name="findById",
                kind=NodeKind.FUNCTION,
                language="java",
                path="src/main/java/com/example/repo/UserRepository.java",
                line=5,
            )
        )

        # Containment edges
        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.service.UserService",
                target_fqn="com.example.service.UserService.createUser",
                kind=EdgeKind.CONTAINS,
            )
        )
        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.repo.UserRepository",
                target_fqn="com.example.repo.UserRepository.findById",
                kind=EdgeKind.CONTAINS,
            )
        )

        # Import edge
        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.service.UserService",
                target_fqn="com.example.repo.UserRepository",
                kind=EdgeKind.IMPORTS,
            )
        )

        # Unresolved call
        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.service.UserService.createUser",
                target_fqn="findById",
                kind=EdgeKind.CALLS,
                confidence=Confidence.LOW,
                evidence="tree-sitter",
            )
        )

        return graph

    def test_resolves_call_via_import(self) -> None:
        graph = self._make_graph_with_imports()
        _resolve_symbols(graph)
        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        edge = calls_edges[0]
        assert edge.target_fqn == "com.example.repo.UserRepository.findById"
        assert edge.confidence == Confidence.MEDIUM

    def test_resolves_call_via_same_package(self) -> None:
        graph = SymbolGraph()

        graph.add_node(
            GraphNode(
                fqn="com.example.service.OrderService",
                name="OrderService",
                kind=NodeKind.CLASS,
                language="java",
                path="src/main/java/com/example/service/OrderService.java",
            )
        )
        graph.add_node(
            GraphNode(
                fqn="com.example.service.OrderService.placeOrder",
                name="placeOrder",
                kind=NodeKind.FUNCTION,
                language="java",
                path="src/main/java/com/example/service/OrderService.java",
            )
        )
        graph.add_node(
            GraphNode(
                fqn="com.example.service.OrderValidator",
                name="OrderValidator",
                kind=NodeKind.CLASS,
                language="java",
                path="src/main/java/com/example/service/OrderValidator.java",
            )
        )
        graph.add_node(
            GraphNode(
                fqn="com.example.service.OrderValidator.validate",
                name="validate",
                kind=NodeKind.FUNCTION,
                language="java",
                path="src/main/java/com/example/service/OrderValidator.java",
            )
        )

        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.service.OrderService",
                target_fqn="com.example.service.OrderService.placeOrder",
                kind=EdgeKind.CONTAINS,
            )
        )
        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.service.OrderValidator",
                target_fqn="com.example.service.OrderValidator.validate",
                kind=EdgeKind.CONTAINS,
            )
        )
        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.service.OrderService.placeOrder",
                target_fqn="validate",
                kind=EdgeKind.CALLS,
                confidence=Confidence.LOW,
                evidence="tree-sitter",
            )
        )

        _resolve_symbols(graph)

        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        assert (
            calls_edges[0].target_fqn == "com.example.service.OrderValidator.validate"
        )
        assert calls_edges[0].confidence == Confidence.MEDIUM

    def test_unresolvable_call_stays_low(self) -> None:
        graph = SymbolGraph()
        graph.add_node(
            GraphNode(
                fqn="com.example.Foo", name="Foo", kind=NodeKind.CLASS, language="java"
            )
        )
        graph.add_node(
            GraphNode(
                fqn="com.example.Foo.doStuff",
                name="doStuff",
                kind=NodeKind.FUNCTION,
                language="java",
            )
        )
        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.Foo",
                target_fqn="com.example.Foo.doStuff",
                kind=EdgeKind.CONTAINS,
            )
        )
        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.Foo.doStuff",
                target_fqn="unknownMethod",
                kind=EdgeKind.CALLS,
                confidence=Confidence.LOW,
                evidence="tree-sitter",
            )
        )

        _resolve_symbols(graph)

        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].confidence == Confidence.LOW
        assert calls_edges[0].target_fqn == "unknownMethod"

    def test_inherits_edge_verified(self) -> None:
        graph = SymbolGraph()
        graph.add_node(
            GraphNode(
                fqn="com.example.Base",
                name="Base",
                kind=NodeKind.CLASS,
                language="java",
            )
        )
        graph.add_node(
            GraphNode(
                fqn="com.example.Child",
                name="Child",
                kind=NodeKind.CLASS,
                language="java",
            )
        )
        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.Child",
                target_fqn="com.example.Base",
                kind=EdgeKind.INHERITS,
            )
        )

        _resolve_symbols(graph)

        inherits_edges = [e for e in graph.edges if e.kind == EdgeKind.INHERITS]
        assert len(inherits_edges) == 1
        assert inherits_edges[0].target_fqn == "com.example.Base"

    def test_empty_graph_resolution_is_noop(self) -> None:
        graph = SymbolGraph()
        _resolve_symbols(graph)
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_high_confidence_calls_not_modified(self) -> None:
        graph = SymbolGraph()
        graph.add_node(
            GraphNode(
                fqn="com.example.A", name="A", kind=NodeKind.CLASS, language="java"
            )
        )
        graph.add_node(
            GraphNode(
                fqn="com.example.A.foo",
                name="foo",
                kind=NodeKind.FUNCTION,
                language="java",
            )
        )
        graph.add_node(
            GraphNode(
                fqn="com.example.B.bar",
                name="bar",
                kind=NodeKind.FUNCTION,
                language="java",
            )
        )
        graph.add_edge(
            GraphEdge(
                source_fqn="com.example.A.foo",
                target_fqn="com.example.B.bar",
                kind=EdgeKind.CALLS,
                confidence=Confidence.HIGH,
                evidence="scip",
            )
        )

        _resolve_symbols(graph)

        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].confidence == Confidence.HIGH
        assert calls_edges[0].target_fqn == "com.example.B.bar"


class TestProtocolCompliance:
    """Verify the LanguageExtractor protocol works correctly."""

    def test_mock_extractor_satisfies_protocol(self) -> None:
        ext = MockJavaExtractor()
        assert isinstance(ext, LanguageExtractor)

    def test_non_extractor_fails_protocol(self) -> None:
        class NotAnExtractor:
            pass

        obj = NotAnExtractor()
        assert not isinstance(obj, LanguageExtractor)

    def test_registered_languages_list(self) -> None:
        clear_extractors()
        register_extractor("java", MockJavaExtractor())
        register_extractor("python", MockJavaExtractor())
        langs = registered_languages()
        assert sorted(langs) == ["java", "python"]
        clear_extractors()


class TestEndToEndWithResolution:
    """Full flow: parse files -> merge -> resolve."""

    def setup_method(self) -> None:
        clear_extractors()

    def teardown_method(self) -> None:
        clear_extractors()

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mock(self) -> None:
        """Simulate a two-file project with imports and unresolved calls."""

        class DetailedMockExtractor:
            def extract(
                self, source: bytes, file_path: str, root_path: str
            ) -> tuple[list[GraphNode], list[GraphEdge]]:
                nodes: list[GraphNode] = []
                edges: list[GraphEdge] = []

                if "UserService" in file_path:
                    nodes.append(
                        GraphNode(
                            fqn="com.example.service.UserService",
                            name="UserService",
                            kind=NodeKind.CLASS,
                            language="java",
                            path=file_path,
                            line=1,
                        )
                    )
                    nodes.append(
                        GraphNode(
                            fqn="com.example.service.UserService.createUser",
                            name="createUser",
                            kind=NodeKind.FUNCTION,
                            language="java",
                            path=file_path,
                            line=5,
                        )
                    )
                    edges.append(
                        GraphEdge(
                            source_fqn="com.example.service.UserService",
                            target_fqn="com.example.service.UserService.createUser",
                            kind=EdgeKind.CONTAINS,
                        )
                    )
                    edges.append(
                        GraphEdge(
                            source_fqn="com.example.service.UserService",
                            target_fqn="com.example.repo.UserRepository",
                            kind=EdgeKind.IMPORTS,
                        )
                    )
                    edges.append(
                        GraphEdge(
                            source_fqn="com.example.service.UserService.createUser",
                            target_fqn="save",
                            kind=EdgeKind.CALLS,
                            confidence=Confidence.LOW,
                            evidence="tree-sitter",
                        )
                    )
                elif "UserRepository" in file_path:
                    nodes.append(
                        GraphNode(
                            fqn="com.example.repo.UserRepository",
                            name="UserRepository",
                            kind=NodeKind.CLASS,
                            language="java",
                            path=file_path,
                            line=1,
                        )
                    )
                    nodes.append(
                        GraphNode(
                            fqn="com.example.repo.UserRepository.save",
                            name="save",
                            kind=NodeKind.FUNCTION,
                            language="java",
                            path=file_path,
                            line=3,
                        )
                    )
                    edges.append(
                        GraphEdge(
                            source_fqn="com.example.repo.UserRepository",
                            target_fqn="com.example.repo.UserRepository.save",
                            kind=EdgeKind.CONTAINS,
                        )
                    )

                return nodes, edges

        register_extractor("java", DetailedMockExtractor())
        manifest = FakeManifest(
            root_path=Path("/tmp/project"),
            source_files=[
                FakeSourceFile(path="src/UserService.java", language="java"),
                FakeSourceFile(path="src/UserRepository.java", language="java"),
            ],
        )

        def mock_parse(
            file_path: str, language: str, root_path: str
        ) -> tuple[list[GraphNode], list[GraphEdge]]:
            ext = get_extractor(language)
            if ext is None:
                return [], []
            return ext.extract(b"// mock", file_path, root_path)

        with patch(
            "app.stages.treesitter.parser._parse_single_file",
            side_effect=mock_parse,
        ):
            graph = await parse_with_treesitter(manifest)  # type: ignore[arg-type]

        # 4 nodes: 2 classes + 2 methods
        assert len(graph.nodes) == 4

        # The CALLS edge should be resolved
        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].target_fqn == "com.example.repo.UserRepository.save"
        assert calls_edges[0].confidence == Confidence.MEDIUM
