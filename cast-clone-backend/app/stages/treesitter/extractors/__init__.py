"""Language extractor interface and registry for tree-sitter parsing."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models.graph import GraphEdge, GraphNode


@runtime_checkable
class LanguageExtractor(Protocol):
    """Interface for language-specific tree-sitter extractors."""

    def extract(
        self,
        source: bytes,
        file_path: str,
        root_path: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        ...


_EXTRACTORS: dict[str, LanguageExtractor] = {}


def register_extractor(language: str, extractor: LanguageExtractor) -> None:
    _EXTRACTORS[language] = extractor


def get_extractor(language: str) -> LanguageExtractor | None:
    return _EXTRACTORS.get(language)


def clear_extractors() -> None:
    _EXTRACTORS.clear()


def registered_languages() -> list[str]:
    return list(_EXTRACTORS.keys())
