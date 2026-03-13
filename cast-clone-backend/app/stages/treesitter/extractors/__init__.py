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
        """Parse source bytes and return extracted nodes and edges."""
        ...


_EXTRACTORS: dict[str, LanguageExtractor] = {}


def register_extractor(language: str, extractor: LanguageExtractor) -> None:
    """Register a language extractor for the given language name."""
    _EXTRACTORS[language] = extractor


def get_extractor(language: str) -> LanguageExtractor | None:
    """Return the extractor for the given language, or None if not registered."""
    return _EXTRACTORS.get(language)


def clear_extractors() -> None:
    """Remove all registered extractors."""
    _EXTRACTORS.clear()


def registered_languages() -> list[str]:
    """Return a list of all languages with registered extractors."""
    return list(_EXTRACTORS.keys())


def _auto_register() -> None:
    """Import all extractor modules so they self-register."""
    from app.stages.treesitter.extractors import java, typescript, python, csharp  # noqa: F401


_auto_register()
