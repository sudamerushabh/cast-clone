"""Tree-sitter base parser framework.

Provides:
- Grammar loading and caching for supported languages
- Parallel file parsing via ProcessPoolExecutor
- Global symbol resolution pass
- Merge of per-file results into a single SymbolGraph
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from tree_sitter import Language, Parser

from app.models.graph import GraphEdge, GraphNode, SymbolGraph
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


def _parse_single_file(
    file_path: str, language: str, root_path: str
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Parse a single source file using its language extractor.

    This is a module-level function so it can be pickled for ProcessPoolExecutor.
    Reads the file from disk, delegates to the registered extractor.
    """
    extractor = get_extractor(language)
    if extractor is None:
        return [], []
    full_path = Path(root_path) / file_path
    source = full_path.read_bytes()
    return extractor.extract(source, file_path, root_path)


def _resolve_symbols(graph: SymbolGraph) -> None:
    """Post-parse global symbol resolution — implemented in Task 4."""
    pass


_SEQUENTIAL_THRESHOLD = 4


async def parse_with_treesitter(manifest: "ProjectManifest") -> SymbolGraph:
    """Parse all source files using tree-sitter and merge into a SymbolGraph.

    For small file counts (<=4), parsing runs sequentially.
    For larger counts, uses ProcessPoolExecutor for CPU-bound parallelism.
    Errors in individual files are logged and skipped.
    """
    graph = SymbolGraph()
    root_path = str(manifest.root_path)

    # Filter to files with registered extractors
    parseable_files: list[tuple[str, str]] = []
    for sf in manifest.source_files:
        if get_extractor(sf.language) is not None:
            parseable_files.append((sf.path, sf.language))
        else:
            logger.debug("Skipping %s: no extractor for %s", sf.path, sf.language)

    if not parseable_files:
        return graph

    if len(parseable_files) <= _SEQUENTIAL_THRESHOLD:
        # Sequential execution for small file counts
        for file_path, language in parseable_files:
            try:
                nodes, edges = _parse_single_file(file_path, language, root_path)
                for node in nodes:
                    graph.add_node(node)
                for edge in edges:
                    graph.add_edge(edge)
            except Exception:
                logger.warning(
                    "Failed to parse %s, skipping", file_path, exc_info=True
                )
    else:
        # Parallel execution via ProcessPoolExecutor
        max_workers = min(os.cpu_count() or 1, len(parseable_files), 8)
        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                loop.run_in_executor(
                    executor, _parse_single_file, file_path, language, root_path
                )
                for file_path, language in parseable_files
            ]
            results = await asyncio.gather(*futures, return_exceptions=True)

        for i, result in enumerate(results):
            file_path = parseable_files[i][0]
            if isinstance(result, Exception):
                logger.warning(
                    "Failed to parse %s, skipping: %s", file_path, result
                )
                continue
            nodes, edges = result
            for node in nodes:
                graph.add_node(node)
            for edge in edges:
                graph.add_edge(edge)

    logger.info(
        "Tree-sitter parsing complete: %d nodes, %d edges",
        len(graph.nodes),
        len(graph.edges),
    )

    _resolve_symbols(graph)
    return graph
