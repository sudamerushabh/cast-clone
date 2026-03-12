"""Tree-sitter base parser framework.

Provides:
- Grammar loading and caching for supported languages
- Parallel file parsing via ProcessPoolExecutor
- Global symbol resolution pass
- Merge of per-file results into a single SymbolGraph
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from tree_sitter import Language, Parser

from app.stages.treesitter.extractors import get_extractor, registered_languages

if TYPE_CHECKING:
    from app.models.manifest import ProjectManifest

logger = logging.getLogger(__name__)

_LANGUAGES: dict[str, Language] = {}


def get_language(name: str) -> Language:
    """Return a cached Language object for the given language name."""
    if name not in _LANGUAGES:
        _LANGUAGES[name] = _load_language(name)
    return _LANGUAGES[name]


def _load_language(name: str) -> Language:
    match name:
        case "java":
            import tree_sitter_java as tsjava

            return Language(tsjava.language())
        case "python":
            import tree_sitter_python as tspython

            return Language(tspython.language())
        case "typescript":
            import tree_sitter_typescript as tstypescript

            return Language(tstypescript.language_typescript())
        case "javascript":
            import tree_sitter_typescript as tstypescript

            return Language(tstypescript.language_typescript())
        case "csharp":
            import tree_sitter_c_sharp as tscsharp

            return Language(tscsharp.language())
        case _:
            raise ValueError(f"No grammar for {name!r}")


def get_parser(name: str) -> Parser:
    """Return a Parser configured for the given language."""
    lang = get_language(name)
    return Parser(lang)


async def parse_with_treesitter(manifest: "ProjectManifest") -> object:
    """Parse all source files — full implementation in Task 3."""
    raise NotImplementedError("parse_with_treesitter not yet implemented")
