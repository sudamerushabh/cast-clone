"""Tests for the tree-sitter parser framework."""

import pytest

from app.models.enums import EdgeKind, NodeKind, Confidence
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.treesitter.extractors import (
    LanguageExtractor,
    get_extractor,
    register_extractor,
    clear_extractors,
)
from app.stages.treesitter.parser import get_language, get_parser


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
