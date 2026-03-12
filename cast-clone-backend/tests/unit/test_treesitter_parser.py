"""Tests for the tree-sitter parser framework."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.enums import EdgeKind, NodeKind, Confidence
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.treesitter.extractors import (
    LanguageExtractor,
    get_extractor,
    register_extractor,
    clear_extractors,
)
from app.stages.treesitter.parser import (
    _parse_single_file,
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

    def test_empty_manifest_returns_empty_graph(self) -> None:
        manifest = FakeManifest(root_path=Path("/tmp/project"), source_files=[])
        graph = asyncio.get_event_loop().run_until_complete(
            parse_with_treesitter(manifest)  # type: ignore[arg-type]
        )
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_unknown_language_is_skipped(self) -> None:
        manifest = FakeManifest(
            root_path=Path("/tmp/project"),
            source_files=[FakeSourceFile(path="main.rs", language="rust")],
        )
        graph = asyncio.get_event_loop().run_until_complete(
            parse_with_treesitter(manifest)  # type: ignore[arg-type]
        )
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_parses_files_with_registered_extractor(self) -> None:
        register_extractor("java", MockJavaExtractor())
        manifest = FakeManifest(
            root_path=Path("/tmp/project"),
            source_files=[
                FakeSourceFile(path="src/Foo.java", language="java"),
                FakeSourceFile(path="src/Bar.java", language="java"),
            ],
        )

        def mock_parse(file_path: str, language: str, root_path: str) -> tuple[list[GraphNode], list[GraphEdge]]:
            ext = get_extractor(language)
            if ext is None:
                return [], []
            return ext.extract(b"// mock source", file_path, root_path)

        with patch(
            "app.stages.treesitter.parser._parse_single_file",
            side_effect=mock_parse,
        ):
            graph = asyncio.get_event_loop().run_until_complete(
                parse_with_treesitter(manifest)  # type: ignore[arg-type]
            )

        assert len(graph.nodes) == 2
        fqns = set(graph.nodes.keys())
        assert "com.example.Foo" in fqns
        assert "com.example.Bar" in fqns

    def test_multiple_languages(self) -> None:
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

        def mock_parse(file_path: str, language: str, root_path: str) -> tuple[list[GraphNode], list[GraphEdge]]:
            ext = get_extractor(language)
            if ext is None:
                return [], []
            return ext.extract(b"// mock", file_path, root_path)

        with patch(
            "app.stages.treesitter.parser._parse_single_file",
            side_effect=mock_parse,
        ):
            graph = asyncio.get_event_loop().run_until_complete(
                parse_with_treesitter(manifest)  # type: ignore[arg-type]
            )

        assert len(graph.nodes) == 2
        assert "com.example.Foo" in graph.nodes
        assert "mypackage.utils" in graph.nodes

    def test_file_parse_error_is_skipped(self) -> None:
        register_extractor("java", MockJavaExtractor())
        manifest = FakeManifest(
            root_path=Path("/tmp/project"),
            source_files=[
                FakeSourceFile(path="src/Good.java", language="java"),
                FakeSourceFile(path="src/Bad.java", language="java"),
            ],
        )

        def mock_parse(file_path: str, language: str, root_path: str) -> tuple[list[GraphNode], list[GraphEdge]]:
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
            graph = asyncio.get_event_loop().run_until_complete(
                parse_with_treesitter(manifest)  # type: ignore[arg-type]
            )

        assert len(graph.nodes) == 1
        assert "com.example.Good" in graph.nodes
