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

from app.models.enums import Confidence, EdgeKind
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
    """Post-parse global symbol resolution.

    Resolves unresolved CALLS edges (confidence=LOW, target not in FQN index)
    using three strategies in priority order:
      1. Import-based: caller's parent class imports a class containing the target method
      2. Same-package: a class in the same package contains the target method
      3. Unique global: exactly one node in the graph matches the short name

    Resolved edges get their target_fqn updated and confidence raised to MEDIUM.
    """
    fqn_index: dict[str, GraphNode] = dict(graph.nodes)

    # Short-name -> list of FQNs
    short_name_index: dict[str, list[str]] = {}
    for fqn, node in fqn_index.items():
        short_name_index.setdefault(node.name, []).append(fqn)

    # Containment: child_fqn -> parent_fqn
    containment: dict[str, str] = {}
    for edge in graph.edges:
        if edge.kind == EdgeKind.CONTAINS:
            containment[edge.target_fqn] = edge.source_fqn

    # Per-class import index: class_fqn -> {imported_short_name: imported_fqn}
    import_index: dict[str, dict[str, str]] = {}
    for edge in graph.edges:
        if edge.kind == EdgeKind.IMPORTS:
            target_node = fqn_index.get(edge.target_fqn)
            if target_node is not None:
                import_index.setdefault(edge.source_fqn, {})[target_node.name] = edge.target_fqn

    def _get_package(fqn: str) -> str:
        """Extract the package prefix from a fully-qualified name."""
        parts = fqn.rsplit(".", 1)
        return parts[0] if len(parts) > 1 else ""

    for i, edge in enumerate(graph.edges):
        # Only resolve LOW-confidence CALLS with unresolved targets
        if edge.kind != EdgeKind.CALLS:
            continue
        if edge.confidence != Confidence.LOW:
            continue
        if edge.target_fqn in fqn_index:
            continue

        target_short = edge.target_fqn  # e.g. "findById"
        resolved_fqn: str | None = None

        # Find the caller's parent class
        caller_class = containment.get(edge.source_fqn)

        # Strategy 1: Import-based resolution
        if caller_class and caller_class in import_index:
            for _short_name, imported_fqn in import_index[caller_class].items():
                candidate = f"{imported_fqn}.{target_short}"
                if candidate in fqn_index:
                    resolved_fqn = candidate
                    break

        # Strategy 2: Same-package resolution
        if resolved_fqn is None and caller_class:
            caller_pkg = _get_package(caller_class)
            candidates = short_name_index.get(target_short, [])
            same_pkg = [
                c for c in candidates
                if _get_package(_get_package(c)) == caller_pkg  # grandparent package
                or _get_package(c).startswith(caller_pkg + ".")
                or caller_pkg == _get_package(c)
            ]
            if len(same_pkg) == 1:
                resolved_fqn = same_pkg[0]

        # Strategy 3: Unique global match
        if resolved_fqn is None:
            candidates = short_name_index.get(target_short, [])
            if len(candidates) == 1:
                resolved_fqn = candidates[0]

        if resolved_fqn is not None:
            graph.edges[i] = GraphEdge(
                source_fqn=edge.source_fqn,
                target_fqn=resolved_fqn,
                kind=edge.kind,
                confidence=Confidence.MEDIUM,
                evidence=edge.evidence,
                properties=edge.properties,
            )
            logger.debug(
                "Resolved %s -> %s to %s",
                edge.source_fqn,
                target_short,
                resolved_fqn,
            )


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
