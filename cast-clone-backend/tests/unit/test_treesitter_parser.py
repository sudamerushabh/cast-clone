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
