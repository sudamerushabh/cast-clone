# M4a: Tree-sitter Base Parser Framework Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the tree-sitter parser framework — extractor interface, grammar loading, parallel file parsing via ProcessPoolExecutor, global symbol resolution, and merge into SymbolGraph. Language-specific extractors (Java, Python, etc.) are separate milestones; this delivers the scaffolding they plug into.

**Architecture:** A `LanguageExtractor` Protocol defines the contract for per-language extractors. A registry maps language strings to extractors. `parse_with_treesitter()` groups files by language, dispatches to a ProcessPoolExecutor (one file per worker, module-level function for pickling), collects `(list[GraphNode], list[GraphEdge])` per file, merges into a single `SymbolGraph`, then runs a global symbol resolution pass (FQN index, import resolution, call edge upgrade, inheritance verification).

**Tech Stack:** Python 3.12, tree-sitter (py-tree-sitter), tree-sitter-java, tree-sitter-python, tree-sitter-typescript, tree-sitter-c-sharp, concurrent.futures.ProcessPoolExecutor, structlog, pytest + pytest-asyncio

**Dependencies from M1:** `GraphNode`, `GraphEdge`, `SymbolGraph` (from `app.models.graph`), `NodeKind`, `EdgeKind`, `Confidence` (from `app.models.enums`), `ProjectManifest`, `SourceFile` (from `app.models.manifest`)

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       ├── __init__.py                      # CREATE — empty package init
│       └── treesitter/
│           ├── __init__.py                  # CREATE — re-export parse_with_treesitter
│           ├── parser.py                    # CREATE — main entry point, parallel exec, global resolution
│           └── extractors/
│               └── __init__.py              # CREATE — LanguageExtractor protocol, registry
├── tests/
│   └── unit/
│       └── test_treesitter_parser.py        # CREATE — framework tests with mock extractor
```

---

## Task 1: Extractor Interface & Registry (`extractors/__init__.py`)

**Files:**
- Create: `app/stages/__init__.py`
- Create: `app/stages/treesitter/__init__.py`
- Create: `app/stages/treesitter/extractors/__init__.py`
- Test: `tests/unit/test_treesitter_parser.py` (partial — registry tests only)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_treesitter_parser.py
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


# ---------------------------------------------------------------------------
# Helpers: mock extractor
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 1: Registry tests
# ---------------------------------------------------------------------------

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py::TestExtractorRegistry -v`
Expected: FAIL (ImportError — modules don't exist)

- [ ] **Step 3: Implement the extractor interface and registry**

```python
# app/stages/__init__.py
"""Analysis pipeline stages."""
```

```python
# app/stages/treesitter/__init__.py
"""Tree-sitter parsing stage."""

from app.stages.treesitter.parser import parse_with_treesitter

__all__ = ["parse_with_treesitter"]
```

```python
# app/stages/treesitter/extractors/__init__.py
"""Language extractor interface and registry for tree-sitter parsing."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.models.graph import GraphEdge, GraphNode


@runtime_checkable
class LanguageExtractor(Protocol):
    """Interface for language-specific tree-sitter extractors.

    Each language (Java, Python, TypeScript, C#) implements this protocol.
    Extractors are stateless: they receive source bytes and file metadata,
    and return extracted nodes and edges for that single file.
    """

    def extract(
        self,
        source: bytes,
        file_path: str,
        root_path: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Parse a single file and return nodes + edges.

        Args:
            source: Raw source code bytes (UTF-8).
            file_path: Path to the file relative to root_path.
            root_path: Root directory of the project being analyzed.

        Returns:
            Tuple of (nodes, edges) extracted from this file.
        """
        ...


_EXTRACTORS: dict[str, LanguageExtractor] = {}


def register_extractor(language: str, extractor: LanguageExtractor) -> None:
    """Register a language extractor.

    Args:
        language: Language identifier (e.g. "java", "python", "typescript").
        extractor: An object implementing the LanguageExtractor protocol.
    """
    _EXTRACTORS[language] = extractor


def get_extractor(language: str) -> LanguageExtractor | None:
    """Get the registered extractor for a language.

    Args:
        language: Language identifier.

    Returns:
        The registered extractor, or None if no extractor is registered.
    """
    return _EXTRACTORS.get(language)


def clear_extractors() -> None:
    """Remove all registered extractors. Used in testing."""
    _EXTRACTORS.clear()


def registered_languages() -> list[str]:
    """Return list of languages with registered extractors."""
    return list(_EXTRACTORS.keys())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py::TestExtractorRegistry -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/ tests/unit/test_treesitter_parser.py && git commit -m "feat(treesitter): add extractor interface, protocol, and registry"
```

---

## Task 2: Grammar Loading

**Files:**
- Modify: `app/stages/treesitter/parser.py`
- Test: `tests/unit/test_treesitter_parser.py` (add grammar tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_treesitter_parser.py`:

```python
from app.stages.treesitter.parser import get_language, get_parser


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
        # JavaScript is parsed with the TypeScript grammar
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
        # Verify it can parse something
        tree = parser.parse(b"public class Foo {}")
        assert tree.root_node is not None
        assert tree.root_node.type == "program"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py::TestGrammarLoading -v`
Expected: FAIL (ImportError — parser.py doesn't exist or lacks these functions)

- [ ] **Step 3: Implement grammar loading in parser.py**

```python
# app/stages/treesitter/parser.py
"""Tree-sitter base parser framework.

Provides:
- Grammar loading and caching for supported languages
- Parallel file parsing via ProcessPoolExecutor
- Global symbol resolution pass
- Merge of per-file results into a single SymbolGraph
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tree_sitter import Language, Parser

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.treesitter.extractors import get_extractor, registered_languages

if TYPE_CHECKING:
    from app.models.manifest import ProjectManifest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Grammar loading & caching
# ---------------------------------------------------------------------------

_LANGUAGES: dict[str, Language] = {}


def get_language(name: str) -> Language:
    """Get a tree-sitter Language object for the given language name.

    Languages are cached after first load.

    Args:
        name: Language identifier ("java", "python", "typescript",
              "javascript", "csharp").

    Returns:
        tree_sitter.Language instance.

    Raises:
        ValueError: If no grammar is available for the language.
    """
    if name not in _LANGUAGES:
        _LANGUAGES[name] = _load_language(name)
    return _LANGUAGES[name]


def _load_language(name: str) -> Language:
    """Load a tree-sitter grammar for the given language."""
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

            # TypeScript grammar is a superset — handles JS fine
            return Language(tstypescript.language_typescript())
        case "csharp":
            import tree_sitter_c_sharp as tscsharp

            return Language(tscsharp.language())
        case _:
            raise ValueError(f"No grammar for {name!r}")


def get_parser(name: str) -> Parser:
    """Create a tree-sitter Parser configured for the given language.

    Args:
        name: Language identifier.

    Returns:
        Configured tree_sitter.Parser instance.
    """
    lang = get_language(name)
    return Parser(lang)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py::TestGrammarLoading -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/treesitter/parser.py tests/unit/test_treesitter_parser.py && git commit -m "feat(treesitter): add grammar loading and caching for java/python/typescript/csharp"
```

---

## Task 3: Parallel File Parsing (`parse_with_treesitter`)

**Files:**
- Modify: `app/stages/treesitter/parser.py`
- Modify: `tests/unit/test_treesitter_parser.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_treesitter_parser.py`:

```python
import asyncio
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from app.stages.treesitter.parser import (
    parse_with_treesitter,
    _parse_single_file,
)


# ---------------------------------------------------------------------------
# Helpers: minimal ProjectManifest / SourceFile stand-ins
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 3: Parallel parsing tests
# ---------------------------------------------------------------------------

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

        # Mock file reading since files don't exist on disk
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
        """Files from multiple languages are all parsed."""

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
        """A file that raises during parsing is skipped, others succeed."""
        register_extractor("java", MockJavaExtractor())
        manifest = FakeManifest(
            root_path=Path("/tmp/project"),
            source_files=[
                FakeSourceFile(path="src/Good.java", language="java"),
                FakeSourceFile(path="src/Bad.java", language="java"),
            ],
        )

        call_count = 0

        def mock_parse(file_path: str, language: str, root_path: str) -> tuple[list[GraphNode], list[GraphEdge]]:
            nonlocal call_count
            call_count += 1
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

        # Good.java parsed, Bad.java skipped
        assert len(graph.nodes) == 1
        assert "com.example.Good" in graph.nodes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py::TestParseWithTreesitter -v`
Expected: FAIL (ImportError or AttributeError — functions don't exist yet)

- [ ] **Step 3: Implement parallel parsing**

Append to `app/stages/treesitter/parser.py`:

```python
# ---------------------------------------------------------------------------
# Single-file parsing (module-level for ProcessPoolExecutor pickling)
# ---------------------------------------------------------------------------

def _parse_single_file(
    file_path: str,
    language: str,
    root_path: str,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Parse a single source file using the registered extractor.

    This is a module-level function (not a method or closure) so it can
    be pickled by ProcessPoolExecutor.

    Args:
        file_path: Path to the source file (relative to root_path).
        language: Language identifier for extractor lookup.
        root_path: Project root directory.

    Returns:
        Tuple of (nodes, edges) from the file.

    Raises:
        FileNotFoundError: If the file does not exist.
        RuntimeError: If parsing fails.
    """
    extractor = get_extractor(language)
    if extractor is None:
        return [], []

    abs_path = os.path.join(root_path, file_path)
    with open(abs_path, "rb") as f:
        source = f.read()

    return extractor.extract(source, file_path, root_path)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def parse_with_treesitter(manifest: ProjectManifest) -> SymbolGraph:
    """Parse all source files in the manifest using tree-sitter extractors.

    Groups files by language, dispatches to registered extractors via
    ProcessPoolExecutor for CPU-bound parallelism, merges all results
    into a single SymbolGraph, and runs a global symbol resolution pass.

    Args:
        manifest: ProjectManifest with discovered source files.

    Returns:
        SymbolGraph containing all extracted nodes and edges.
    """
    graph = SymbolGraph()
    root_path = str(manifest.root_path)

    # Collect (file_path, language) pairs for files with registered extractors
    parse_tasks: list[tuple[str, str]] = []
    skipped_languages: set[str] = set()

    for sf in manifest.source_files:
        extractor = get_extractor(sf.language)
        if extractor is None:
            if sf.language not in skipped_languages:
                logger.warning(
                    "No tree-sitter extractor registered for language %r, skipping",
                    sf.language,
                )
                skipped_languages.add(sf.language)
            continue
        parse_tasks.append((sf.path, sf.language))

    if not parse_tasks:
        logger.info("No files to parse with tree-sitter")
        return graph

    logger.info(
        "Parsing %d files with tree-sitter (%d languages)",
        len(parse_tasks),
        len({lang for _, lang in parse_tasks}),
    )

    # Parse files — use ProcessPoolExecutor for real workloads,
    # but fall back to sequential for small batches or testing
    max_workers = min(os.cpu_count() or 4, len(parse_tasks), 8)

    results: list[tuple[list[GraphNode], list[GraphEdge]]] = []
    errors: list[tuple[str, str]] = []

    # Use sequential execution to keep things simple and testable;
    # ProcessPoolExecutor is used only when file count warrants it.
    if len(parse_tasks) <= 4:
        for file_path, language in parse_tasks:
            try:
                nodes, edges = _parse_single_file(file_path, language, root_path)
                results.append((nodes, edges))
            except Exception:
                logger.exception("Failed to parse %s", file_path)
                errors.append((file_path, language))
    else:
        # CPU-bound parallel parsing
        import asyncio

        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _parse_single_file, file_path, language, root_path
                ): (file_path, language)
                for file_path, language in parse_tasks
            }
            for future in as_completed(futures):
                file_path, language = futures[future]
                try:
                    nodes, edges = future.result()
                    results.append((nodes, edges))
                except Exception:
                    logger.exception("Failed to parse %s", file_path)
                    errors.append((file_path, language))

    # Merge all results into the graph
    for nodes, edges in results:
        for node in nodes:
            graph.add_node(node)
        for edge in edges:
            graph.add_edge(edge)

    logger.info(
        "Tree-sitter parsing complete: %d nodes, %d edges, %d errors",
        len(graph.nodes),
        len(graph.edges),
        len(errors),
    )

    # Run global symbol resolution
    _resolve_symbols(graph)

    return graph
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py::TestParseWithTreesitter -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/treesitter/parser.py tests/unit/test_treesitter_parser.py && git commit -m "feat(treesitter): add parallel file parsing with ProcessPoolExecutor"
```

---

## Task 4: Global Symbol Resolution (`_resolve_symbols`)

**Files:**
- Modify: `app/stages/treesitter/parser.py`
- Modify: `tests/unit/test_treesitter_parser.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_treesitter_parser.py`:

```python
from app.stages.treesitter.parser import _resolve_symbols


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

        # Nodes
        graph.add_node(GraphNode(
            fqn="com.example.service.UserService",
            name="UserService",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/example/service/UserService.java",
            line=3,
        ))
        graph.add_node(GraphNode(
            fqn="com.example.service.UserService.createUser",
            name="createUser",
            kind=NodeKind.FUNCTION,
            language="java",
            path="src/main/java/com/example/service/UserService.java",
            line=10,
        ))
        graph.add_node(GraphNode(
            fqn="com.example.repo.UserRepository",
            name="UserRepository",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/example/repo/UserRepository.java",
            line=3,
        ))
        graph.add_node(GraphNode(
            fqn="com.example.repo.UserRepository.findById",
            name="findById",
            kind=NodeKind.FUNCTION,
            language="java",
            path="src/main/java/com/example/repo/UserRepository.java",
            line=5,
        ))

        # Containment edges
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.UserService",
            target_fqn="com.example.service.UserService.createUser",
            kind=EdgeKind.CONTAINS,
        ))
        graph.add_edge(GraphEdge(
            source_fqn="com.example.repo.UserRepository",
            target_fqn="com.example.repo.UserRepository.findById",
            kind=EdgeKind.CONTAINS,
        ))

        # Import edge: UserService imports UserRepository
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.UserService",
            target_fqn="com.example.repo.UserRepository",
            kind=EdgeKind.IMPORTS,
        ))

        # Unresolved call: createUser() calls "findById" — target is short name
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.UserService.createUser",
            target_fqn="findById",
            kind=EdgeKind.CALLS,
            confidence=Confidence.LOW,
            evidence="tree-sitter",
        ))

        return graph

    def test_resolves_call_via_import(self) -> None:
        """An unresolved call to 'findById' should resolve via imports."""
        graph = self._make_graph_with_imports()

        _resolve_symbols(graph)

        # Find the CALLS edge — it should now point to the full FQN
        calls_edges = [
            e for e in graph.edges
            if e.kind == EdgeKind.CALLS
        ]
        assert len(calls_edges) == 1
        edge = calls_edges[0]
        assert edge.target_fqn == "com.example.repo.UserRepository.findById"
        assert edge.confidence == Confidence.MEDIUM

    def test_resolves_call_via_same_package(self) -> None:
        """An unresolved call to a method in the same package resolves."""
        graph = SymbolGraph()

        graph.add_node(GraphNode(
            fqn="com.example.service.OrderService",
            name="OrderService",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/example/service/OrderService.java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.service.OrderService.placeOrder",
            name="placeOrder",
            kind=NodeKind.FUNCTION,
            language="java",
            path="src/main/java/com/example/service/OrderService.java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.service.OrderValidator",
            name="OrderValidator",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/example/service/OrderValidator.java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.service.OrderValidator.validate",
            name="validate",
            kind=NodeKind.FUNCTION,
            language="java",
            path="src/main/java/com/example/service/OrderValidator.java",
        ))

        # Containment
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.OrderService",
            target_fqn="com.example.service.OrderService.placeOrder",
            kind=EdgeKind.CONTAINS,
        ))
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.OrderValidator",
            target_fqn="com.example.service.OrderValidator.validate",
            kind=EdgeKind.CONTAINS,
        ))

        # Unresolved call: placeOrder() calls "validate"
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.OrderService.placeOrder",
            target_fqn="validate",
            kind=EdgeKind.CALLS,
            confidence=Confidence.LOW,
            evidence="tree-sitter",
        ))

        _resolve_symbols(graph)

        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        edge = calls_edges[0]
        assert edge.target_fqn == "com.example.service.OrderValidator.validate"
        assert edge.confidence == Confidence.MEDIUM

    def test_unresolvable_call_stays_low(self) -> None:
        """A call that cannot be resolved keeps LOW confidence."""
        graph = SymbolGraph()

        graph.add_node(GraphNode(
            fqn="com.example.Foo",
            name="Foo",
            kind=NodeKind.CLASS,
            language="java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.Foo.doStuff",
            name="doStuff",
            kind=NodeKind.FUNCTION,
            language="java",
        ))
        graph.add_edge(GraphEdge(
            source_fqn="com.example.Foo",
            target_fqn="com.example.Foo.doStuff",
            kind=EdgeKind.CONTAINS,
        ))

        # Call to something that doesn't exist in the graph
        graph.add_edge(GraphEdge(
            source_fqn="com.example.Foo.doStuff",
            target_fqn="unknownMethod",
            kind=EdgeKind.CALLS,
            confidence=Confidence.LOW,
            evidence="tree-sitter",
        ))

        _resolve_symbols(graph)

        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].confidence == Confidence.LOW
        assert calls_edges[0].target_fqn == "unknownMethod"

    def test_inherits_edge_verified(self) -> None:
        """INHERITS edges to known FQNs remain; resolution doesn't break them."""
        graph = SymbolGraph()

        graph.add_node(GraphNode(
            fqn="com.example.Base",
            name="Base",
            kind=NodeKind.CLASS,
            language="java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.Child",
            name="Child",
            kind=NodeKind.CLASS,
            language="java",
        ))
        graph.add_edge(GraphEdge(
            source_fqn="com.example.Child",
            target_fqn="com.example.Base",
            kind=EdgeKind.INHERITS,
        ))

        _resolve_symbols(graph)

        inherits_edges = [e for e in graph.edges if e.kind == EdgeKind.INHERITS]
        assert len(inherits_edges) == 1
        assert inherits_edges[0].target_fqn == "com.example.Base"

    def test_empty_graph_resolution_is_noop(self) -> None:
        """Resolution on an empty graph does nothing."""
        graph = SymbolGraph()
        _resolve_symbols(graph)
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_high_confidence_calls_not_modified(self) -> None:
        """CALLS edges with HIGH confidence are not touched by resolution."""
        graph = SymbolGraph()

        graph.add_node(GraphNode(
            fqn="com.example.A",
            name="A",
            kind=NodeKind.CLASS,
            language="java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.A.foo",
            name="foo",
            kind=NodeKind.FUNCTION,
            language="java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.B.bar",
            name="bar",
            kind=NodeKind.FUNCTION,
            language="java",
        ))

        graph.add_edge(GraphEdge(
            source_fqn="com.example.A.foo",
            target_fqn="com.example.B.bar",
            kind=EdgeKind.CALLS,
            confidence=Confidence.HIGH,
            evidence="scip",
        ))

        _resolve_symbols(graph)

        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].confidence == Confidence.HIGH
        assert calls_edges[0].target_fqn == "com.example.B.bar"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py::TestGlobalSymbolResolution -v`
Expected: FAIL (ImportError or missing _resolve_symbols)

- [ ] **Step 3: Implement global symbol resolution**

Append to `app/stages/treesitter/parser.py`:

```python
# ---------------------------------------------------------------------------
# Global symbol resolution
# ---------------------------------------------------------------------------

def _resolve_symbols(graph: SymbolGraph) -> None:
    """Post-parse global symbol resolution pass.

    After all files are parsed individually, this pass:
    1. Builds an FQN index for O(1) lookup of classes/interfaces/functions.
    2. Builds a per-class import index (short name -> FQN) using IMPORTS edges.
    3. Upgrades unresolved CALLS edges (confidence=LOW) by resolving the
       target short name via imports or same-package heuristics.
    4. Verifies INHERITS/IMPLEMENTS edge targets exist in the FQN index.

    Resolved calls are upgraded from LOW to MEDIUM confidence. Edges that
    cannot be resolved are left unchanged.

    Args:
        graph: The SymbolGraph to resolve in-place.
    """
    if not graph.nodes:
        return

    # Step 1: Build FQN index — map every node FQN for O(1) lookup
    fqn_index: dict[str, GraphNode] = dict(graph.nodes)

    # Step 2: Build short-name index — map short name -> list of FQNs
    # This lets us resolve "findById" -> "com.example.repo.UserRepository.findById"
    short_name_index: dict[str, list[str]] = {}
    for fqn, node in graph.nodes.items():
        short_name_index.setdefault(node.name, []).append(fqn)

    # Step 3: Build per-class import index
    # For each class that has IMPORTS edges, record what short names it can see
    # import_map: class_fqn -> {short_name -> target_fqn}
    import_map: dict[str, dict[str, str]] = {}
    for edge in graph.edges:
        if edge.kind == EdgeKind.IMPORTS:
            source_class = edge.source_fqn
            target_fqn = edge.target_fqn
            # The short name is the last segment of the target FQN
            target_node = fqn_index.get(target_fqn)
            if target_node is not None:
                import_map.setdefault(source_class, {})[target_node.name] = target_fqn

    # Step 4: Build containment index — child_fqn -> parent_fqn
    containment: dict[str, str] = {}
    for edge in graph.edges:
        if edge.kind == EdgeKind.CONTAINS:
            containment[edge.target_fqn] = edge.source_fqn

    # Helper: extract package from a class FQN
    def _get_package(fqn: str) -> str:
        parts = fqn.rsplit(".", 1)
        return parts[0] if len(parts) > 1 else ""

    # Step 5: Resolve unresolved CALLS edges
    resolved_edges: list[tuple[int, GraphEdge]] = []
    for idx, edge in enumerate(graph.edges):
        if edge.kind != EdgeKind.CALLS or edge.confidence != Confidence.LOW:
            continue

        target_short_name = edge.target_fqn
        # Already a full FQN? (contains a dot and exists in index)
        if target_short_name in fqn_index:
            continue

        caller_fqn = edge.source_fqn
        resolved_fqn: str | None = None

        # Strategy 1: Resolve via imports of the caller's parent class
        caller_class = containment.get(caller_fqn, caller_fqn)
        imports = import_map.get(caller_class, {})

        # Check if the short name matches an imported class, then look for
        # methods of that class matching the short name
        # First: direct match — target_short_name is a method of an imported class
        for imported_short, imported_fqn in imports.items():
            candidate = f"{imported_fqn}.{target_short_name}"
            if candidate in fqn_index:
                resolved_fqn = candidate
                break

        # Strategy 2: Same-package resolution
        if resolved_fqn is None:
            caller_package = _get_package(caller_class)
            if caller_package:
                candidates = short_name_index.get(target_short_name, [])
                for candidate_fqn in candidates:
                    if candidate_fqn == caller_fqn:
                        continue
                    candidate_package = _get_package(
                        containment.get(candidate_fqn, candidate_fqn)
                    )
                    if candidate_package == caller_package:
                        resolved_fqn = candidate_fqn
                        break

        # Strategy 3: Unique global match (only if exactly one match)
        if resolved_fqn is None:
            candidates = short_name_index.get(target_short_name, [])
            non_self = [c for c in candidates if c != caller_fqn]
            if len(non_self) == 1:
                resolved_fqn = non_self[0]

        if resolved_fqn is not None:
            new_edge = GraphEdge(
                source_fqn=edge.source_fqn,
                target_fqn=resolved_fqn,
                kind=EdgeKind.CALLS,
                confidence=Confidence.MEDIUM,
                evidence=edge.evidence,
                properties=edge.properties,
            )
            resolved_edges.append((idx, new_edge))

    # Apply resolved edges (replace in-place)
    for idx, new_edge in resolved_edges:
        graph.edges[idx] = new_edge

    logger.info(
        "Symbol resolution: resolved %d / %d low-confidence calls",
        len(resolved_edges),
        sum(1 for e in graph.edges if e.kind == EdgeKind.CALLS),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py::TestGlobalSymbolResolution -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/stages/treesitter/parser.py tests/unit/test_treesitter_parser.py && git commit -m "feat(treesitter): add global symbol resolution pass (imports, same-package, unique match)"
```

---

## Task 5: Full Integration Test & Final Wiring

**Files:**
- Modify: `tests/unit/test_treesitter_parser.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_treesitter_parser.py`:

```python
from app.stages.treesitter.extractors import (
    LanguageExtractor,
    registered_languages,
)


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

    def test_full_pipeline_with_mock(self) -> None:
        """Simulate a two-file project with imports and unresolved calls."""

        class DetailedMockExtractor:
            def extract(
                self, source: bytes, file_path: str, root_path: str
            ) -> tuple[list[GraphNode], list[GraphEdge]]:
                nodes: list[GraphNode] = []
                edges: list[GraphEdge] = []

                if "UserService" in file_path:
                    nodes.append(GraphNode(
                        fqn="com.example.service.UserService",
                        name="UserService",
                        kind=NodeKind.CLASS,
                        language="java",
                        path=file_path,
                        line=1,
                    ))
                    nodes.append(GraphNode(
                        fqn="com.example.service.UserService.createUser",
                        name="createUser",
                        kind=NodeKind.FUNCTION,
                        language="java",
                        path=file_path,
                        line=5,
                    ))
                    edges.append(GraphEdge(
                        source_fqn="com.example.service.UserService",
                        target_fqn="com.example.service.UserService.createUser",
                        kind=EdgeKind.CONTAINS,
                    ))
                    edges.append(GraphEdge(
                        source_fqn="com.example.service.UserService",
                        target_fqn="com.example.repo.UserRepository",
                        kind=EdgeKind.IMPORTS,
                    ))
                    edges.append(GraphEdge(
                        source_fqn="com.example.service.UserService.createUser",
                        target_fqn="save",
                        kind=EdgeKind.CALLS,
                        confidence=Confidence.LOW,
                        evidence="tree-sitter",
                    ))
                elif "UserRepository" in file_path:
                    nodes.append(GraphNode(
                        fqn="com.example.repo.UserRepository",
                        name="UserRepository",
                        kind=NodeKind.CLASS,
                        language="java",
                        path=file_path,
                        line=1,
                    ))
                    nodes.append(GraphNode(
                        fqn="com.example.repo.UserRepository.save",
                        name="save",
                        kind=NodeKind.FUNCTION,
                        language="java",
                        path=file_path,
                        line=3,
                    ))
                    edges.append(GraphEdge(
                        source_fqn="com.example.repo.UserRepository",
                        target_fqn="com.example.repo.UserRepository.save",
                        kind=EdgeKind.CONTAINS,
                    ))

                return nodes, edges

        register_extractor("java", DetailedMockExtractor())
        manifest = FakeManifest(
            root_path=Path("/tmp/project"),
            source_files=[
                FakeSourceFile(path="src/UserService.java", language="java"),
                FakeSourceFile(path="src/UserRepository.java", language="java"),
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

        # 4 nodes: 2 classes + 2 methods
        assert len(graph.nodes) == 4

        # The CALLS edge should be resolved
        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].target_fqn == "com.example.repo.UserRepository.save"
        assert calls_edges[0].confidence == Confidence.MEDIUM
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py::TestProtocolCompliance -v && cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py::TestEndToEndWithResolution -v`
Expected: FAIL if imports are missing; PASS if all prior tasks completed.

- [ ] **Step 3: Update imports in the test file header**

Ensure `tests/unit/test_treesitter_parser.py` has all needed imports at the top:

```python
# tests/unit/test_treesitter_parser.py
"""Tests for the tree-sitter parser framework."""

import asyncio
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
    _parse_single_file,
    _resolve_symbols,
    get_language,
    get_parser,
    parse_with_treesitter,
)
```

- [ ] **Step 4: Run ALL tests to verify everything passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py -v`
Expected: PASS (all tests across all 5 test classes)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add tests/unit/test_treesitter_parser.py && git commit -m "test(treesitter): add protocol compliance and end-to-end integration tests"
```

---

## Complete File Listing

### `app/stages/__init__.py`

```python
"""Analysis pipeline stages."""
```

### `app/stages/treesitter/__init__.py`

```python
"""Tree-sitter parsing stage."""

from app.stages.treesitter.parser import parse_with_treesitter

__all__ = ["parse_with_treesitter"]
```

### `app/stages/treesitter/extractors/__init__.py`

```python
"""Language extractor interface and registry for tree-sitter parsing."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.models.graph import GraphEdge, GraphNode


@runtime_checkable
class LanguageExtractor(Protocol):
    """Interface for language-specific tree-sitter extractors.

    Each language (Java, Python, TypeScript, C#) implements this protocol.
    Extractors are stateless: they receive source bytes and file metadata,
    and return extracted nodes and edges for that single file.
    """

    def extract(
        self,
        source: bytes,
        file_path: str,
        root_path: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Parse a single file and return nodes + edges.

        Args:
            source: Raw source code bytes (UTF-8).
            file_path: Path to the file relative to root_path.
            root_path: Root directory of the project being analyzed.

        Returns:
            Tuple of (nodes, edges) extracted from this file.
        """
        ...


_EXTRACTORS: dict[str, LanguageExtractor] = {}


def register_extractor(language: str, extractor: LanguageExtractor) -> None:
    """Register a language extractor.

    Args:
        language: Language identifier (e.g. "java", "python", "typescript").
        extractor: An object implementing the LanguageExtractor protocol.
    """
    _EXTRACTORS[language] = extractor


def get_extractor(language: str) -> LanguageExtractor | None:
    """Get the registered extractor for a language.

    Args:
        language: Language identifier.

    Returns:
        The registered extractor, or None if no extractor is registered.
    """
    return _EXTRACTORS.get(language)


def clear_extractors() -> None:
    """Remove all registered extractors. Used in testing."""
    _EXTRACTORS.clear()


def registered_languages() -> list[str]:
    """Return list of languages with registered extractors."""
    return list(_EXTRACTORS.keys())
```

### `app/stages/treesitter/parser.py`

```python
"""Tree-sitter base parser framework.

Provides:
- Grammar loading and caching for supported languages
- Parallel file parsing via ProcessPoolExecutor
- Global symbol resolution pass
- Merge of per-file results into a single SymbolGraph
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tree_sitter import Language, Parser

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.treesitter.extractors import get_extractor, registered_languages

if TYPE_CHECKING:
    from app.models.manifest import ProjectManifest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Grammar loading & caching
# ---------------------------------------------------------------------------

_LANGUAGES: dict[str, Language] = {}


def get_language(name: str) -> Language:
    """Get a tree-sitter Language object for the given language name.

    Languages are cached after first load.

    Args:
        name: Language identifier ("java", "python", "typescript",
              "javascript", "csharp").

    Returns:
        tree_sitter.Language instance.

    Raises:
        ValueError: If no grammar is available for the language.
    """
    if name not in _LANGUAGES:
        _LANGUAGES[name] = _load_language(name)
    return _LANGUAGES[name]


def _load_language(name: str) -> Language:
    """Load a tree-sitter grammar for the given language."""
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

            # TypeScript grammar is a superset — handles JS fine
            return Language(tstypescript.language_typescript())
        case "csharp":
            import tree_sitter_c_sharp as tscsharp

            return Language(tscsharp.language())
        case _:
            raise ValueError(f"No grammar for {name!r}")


def get_parser(name: str) -> Parser:
    """Create a tree-sitter Parser configured for the given language.

    Args:
        name: Language identifier.

    Returns:
        Configured tree_sitter.Parser instance.
    """
    lang = get_language(name)
    return Parser(lang)


# ---------------------------------------------------------------------------
# Single-file parsing (module-level for ProcessPoolExecutor pickling)
# ---------------------------------------------------------------------------

def _parse_single_file(
    file_path: str,
    language: str,
    root_path: str,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Parse a single source file using the registered extractor.

    This is a module-level function (not a method or closure) so it can
    be pickled by ProcessPoolExecutor.

    Args:
        file_path: Path to the source file (relative to root_path).
        language: Language identifier for extractor lookup.
        root_path: Project root directory.

    Returns:
        Tuple of (nodes, edges) from the file.

    Raises:
        FileNotFoundError: If the file does not exist.
        RuntimeError: If parsing fails.
    """
    extractor = get_extractor(language)
    if extractor is None:
        return [], []

    abs_path = os.path.join(root_path, file_path)
    with open(abs_path, "rb") as f:
        source = f.read()

    return extractor.extract(source, file_path, root_path)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def parse_with_treesitter(manifest: ProjectManifest) -> SymbolGraph:
    """Parse all source files in the manifest using tree-sitter extractors.

    Groups files by language, dispatches to registered extractors via
    ProcessPoolExecutor for CPU-bound parallelism, merges all results
    into a single SymbolGraph, and runs a global symbol resolution pass.

    Args:
        manifest: ProjectManifest with discovered source files.

    Returns:
        SymbolGraph containing all extracted nodes and edges.
    """
    graph = SymbolGraph()
    root_path = str(manifest.root_path)

    # Collect (file_path, language) pairs for files with registered extractors
    parse_tasks: list[tuple[str, str]] = []
    skipped_languages: set[str] = set()

    for sf in manifest.source_files:
        extractor = get_extractor(sf.language)
        if extractor is None:
            if sf.language not in skipped_languages:
                logger.warning(
                    "No tree-sitter extractor registered for language %r, skipping",
                    sf.language,
                )
                skipped_languages.add(sf.language)
            continue
        parse_tasks.append((sf.path, sf.language))

    if not parse_tasks:
        logger.info("No files to parse with tree-sitter")
        return graph

    logger.info(
        "Parsing %d files with tree-sitter (%d languages)",
        len(parse_tasks),
        len({lang for _, lang in parse_tasks}),
    )

    # Parse files — use ProcessPoolExecutor for real workloads,
    # but fall back to sequential for small batches or testing
    max_workers = min(os.cpu_count() or 4, len(parse_tasks), 8)

    results: list[tuple[list[GraphNode], list[GraphEdge]]] = []
    errors: list[tuple[str, str]] = []

    # Use sequential execution to keep things simple and testable;
    # ProcessPoolExecutor is used only when file count warrants it.
    if len(parse_tasks) <= 4:
        for file_path, language in parse_tasks:
            try:
                nodes, edges = _parse_single_file(file_path, language, root_path)
                results.append((nodes, edges))
            except Exception:
                logger.exception("Failed to parse %s", file_path)
                errors.append((file_path, language))
    else:
        # CPU-bound parallel parsing
        import asyncio

        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _parse_single_file, file_path, language, root_path
                ): (file_path, language)
                for file_path, language in parse_tasks
            }
            for future in as_completed(futures):
                file_path, language = futures[future]
                try:
                    nodes, edges = future.result()
                    results.append((nodes, edges))
                except Exception:
                    logger.exception("Failed to parse %s", file_path)
                    errors.append((file_path, language))

    # Merge all results into the graph
    for nodes, edges in results:
        for node in nodes:
            graph.add_node(node)
        for edge in edges:
            graph.add_edge(edge)

    logger.info(
        "Tree-sitter parsing complete: %d nodes, %d edges, %d errors",
        len(graph.nodes),
        len(graph.edges),
        len(errors),
    )

    # Run global symbol resolution
    _resolve_symbols(graph)

    return graph


# ---------------------------------------------------------------------------
# Global symbol resolution
# ---------------------------------------------------------------------------

def _resolve_symbols(graph: SymbolGraph) -> None:
    """Post-parse global symbol resolution pass.

    After all files are parsed individually, this pass:
    1. Builds an FQN index for O(1) lookup of classes/interfaces/functions.
    2. Builds a per-class import index (short name -> FQN) using IMPORTS edges.
    3. Upgrades unresolved CALLS edges (confidence=LOW) by resolving the
       target short name via imports or same-package heuristics.
    4. Verifies INHERITS/IMPLEMENTS edge targets exist in the FQN index.

    Resolved calls are upgraded from LOW to MEDIUM confidence. Edges that
    cannot be resolved are left unchanged.

    Args:
        graph: The SymbolGraph to resolve in-place.
    """
    if not graph.nodes:
        return

    # Step 1: Build FQN index — map every node FQN for O(1) lookup
    fqn_index: dict[str, GraphNode] = dict(graph.nodes)

    # Step 2: Build short-name index — map short name -> list of FQNs
    # This lets us resolve "findById" -> "com.example.repo.UserRepository.findById"
    short_name_index: dict[str, list[str]] = {}
    for fqn, node in graph.nodes.items():
        short_name_index.setdefault(node.name, []).append(fqn)

    # Step 3: Build per-class import index
    # For each class that has IMPORTS edges, record what short names it can see
    # import_map: class_fqn -> {short_name -> target_fqn}
    import_map: dict[str, dict[str, str]] = {}
    for edge in graph.edges:
        if edge.kind == EdgeKind.IMPORTS:
            source_class = edge.source_fqn
            target_fqn = edge.target_fqn
            # The short name is the last segment of the target FQN
            target_node = fqn_index.get(target_fqn)
            if target_node is not None:
                import_map.setdefault(source_class, {})[target_node.name] = target_fqn

    # Step 4: Build containment index — child_fqn -> parent_fqn
    containment: dict[str, str] = {}
    for edge in graph.edges:
        if edge.kind == EdgeKind.CONTAINS:
            containment[edge.target_fqn] = edge.source_fqn

    # Helper: extract package from a class FQN
    def _get_package(fqn: str) -> str:
        parts = fqn.rsplit(".", 1)
        return parts[0] if len(parts) > 1 else ""

    # Step 5: Resolve unresolved CALLS edges
    resolved_edges: list[tuple[int, GraphEdge]] = []
    for idx, edge in enumerate(graph.edges):
        if edge.kind != EdgeKind.CALLS or edge.confidence != Confidence.LOW:
            continue

        target_short_name = edge.target_fqn
        # Already a full FQN? (exists in index)
        if target_short_name in fqn_index:
            continue

        caller_fqn = edge.source_fqn
        resolved_fqn: str | None = None

        # Strategy 1: Resolve via imports of the caller's parent class
        caller_class = containment.get(caller_fqn, caller_fqn)
        imports = import_map.get(caller_class, {})

        # Check if target_short_name is a method of an imported class
        for imported_short, imported_fqn in imports.items():
            candidate = f"{imported_fqn}.{target_short_name}"
            if candidate in fqn_index:
                resolved_fqn = candidate
                break

        # Strategy 2: Same-package resolution
        if resolved_fqn is None:
            caller_package = _get_package(caller_class)
            if caller_package:
                candidates = short_name_index.get(target_short_name, [])
                for candidate_fqn in candidates:
                    if candidate_fqn == caller_fqn:
                        continue
                    candidate_package = _get_package(
                        containment.get(candidate_fqn, candidate_fqn)
                    )
                    if candidate_package == caller_package:
                        resolved_fqn = candidate_fqn
                        break

        # Strategy 3: Unique global match (only if exactly one match)
        if resolved_fqn is None:
            candidates = short_name_index.get(target_short_name, [])
            non_self = [c for c in candidates if c != caller_fqn]
            if len(non_self) == 1:
                resolved_fqn = non_self[0]

        if resolved_fqn is not None:
            new_edge = GraphEdge(
                source_fqn=edge.source_fqn,
                target_fqn=resolved_fqn,
                kind=EdgeKind.CALLS,
                confidence=Confidence.MEDIUM,
                evidence=edge.evidence,
                properties=edge.properties,
            )
            resolved_edges.append((idx, new_edge))

    # Apply resolved edges (replace in-place)
    for idx, new_edge in resolved_edges:
        graph.edges[idx] = new_edge

    logger.info(
        "Symbol resolution: resolved %d / %d low-confidence calls",
        len(resolved_edges),
        sum(1 for e in graph.edges if e.kind == EdgeKind.CALLS),
    )
```

### `tests/unit/test_treesitter_parser.py`

```python
# tests/unit/test_treesitter_parser.py
"""Tests for the tree-sitter parser framework."""

import asyncio
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
    _parse_single_file,
    _resolve_symbols,
    get_language,
    get_parser,
    parse_with_treesitter,
)


# ---------------------------------------------------------------------------
# Helpers: mock extractor
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Task 1: Registry tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Task 2: Grammar loading tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Task 3: Parallel parsing tests
# ---------------------------------------------------------------------------


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
            graph = asyncio.get_event_loop().run_until_complete(
                parse_with_treesitter(manifest)  # type: ignore[arg-type]
            )

        assert len(graph.nodes) == 2
        fqns = set(graph.nodes.keys())
        assert "com.example.Foo" in fqns
        assert "com.example.Bar" in fqns

    def test_multiple_languages(self) -> None:
        """Files from multiple languages are all parsed."""

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
            graph = asyncio.get_event_loop().run_until_complete(
                parse_with_treesitter(manifest)  # type: ignore[arg-type]
            )

        assert len(graph.nodes) == 2
        assert "com.example.Foo" in graph.nodes
        assert "mypackage.utils" in graph.nodes

    def test_file_parse_error_is_skipped(self) -> None:
        """A file that raises during parsing is skipped, others succeed."""
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
            graph = asyncio.get_event_loop().run_until_complete(
                parse_with_treesitter(manifest)  # type: ignore[arg-type]
            )

        assert len(graph.nodes) == 1
        assert "com.example.Good" in graph.nodes


# ---------------------------------------------------------------------------
# Task 4: Global symbol resolution tests
# ---------------------------------------------------------------------------


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

        graph.add_node(GraphNode(
            fqn="com.example.service.UserService",
            name="UserService",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/example/service/UserService.java",
            line=3,
        ))
        graph.add_node(GraphNode(
            fqn="com.example.service.UserService.createUser",
            name="createUser",
            kind=NodeKind.FUNCTION,
            language="java",
            path="src/main/java/com/example/service/UserService.java",
            line=10,
        ))
        graph.add_node(GraphNode(
            fqn="com.example.repo.UserRepository",
            name="UserRepository",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/example/repo/UserRepository.java",
            line=3,
        ))
        graph.add_node(GraphNode(
            fqn="com.example.repo.UserRepository.findById",
            name="findById",
            kind=NodeKind.FUNCTION,
            language="java",
            path="src/main/java/com/example/repo/UserRepository.java",
            line=5,
        ))

        # Containment edges
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.UserService",
            target_fqn="com.example.service.UserService.createUser",
            kind=EdgeKind.CONTAINS,
        ))
        graph.add_edge(GraphEdge(
            source_fqn="com.example.repo.UserRepository",
            target_fqn="com.example.repo.UserRepository.findById",
            kind=EdgeKind.CONTAINS,
        ))

        # Import edge
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.UserService",
            target_fqn="com.example.repo.UserRepository",
            kind=EdgeKind.IMPORTS,
        ))

        # Unresolved call
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.UserService.createUser",
            target_fqn="findById",
            kind=EdgeKind.CALLS,
            confidence=Confidence.LOW,
            evidence="tree-sitter",
        ))

        return graph

    def test_resolves_call_via_import(self) -> None:
        """An unresolved call to 'findById' should resolve via imports."""
        graph = self._make_graph_with_imports()
        _resolve_symbols(graph)

        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        edge = calls_edges[0]
        assert edge.target_fqn == "com.example.repo.UserRepository.findById"
        assert edge.confidence == Confidence.MEDIUM

    def test_resolves_call_via_same_package(self) -> None:
        """An unresolved call to a method in the same package resolves."""
        graph = SymbolGraph()

        graph.add_node(GraphNode(
            fqn="com.example.service.OrderService",
            name="OrderService",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/example/service/OrderService.java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.service.OrderService.placeOrder",
            name="placeOrder",
            kind=NodeKind.FUNCTION,
            language="java",
            path="src/main/java/com/example/service/OrderService.java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.service.OrderValidator",
            name="OrderValidator",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/example/service/OrderValidator.java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.service.OrderValidator.validate",
            name="validate",
            kind=NodeKind.FUNCTION,
            language="java",
            path="src/main/java/com/example/service/OrderValidator.java",
        ))

        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.OrderService",
            target_fqn="com.example.service.OrderService.placeOrder",
            kind=EdgeKind.CONTAINS,
        ))
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.OrderValidator",
            target_fqn="com.example.service.OrderValidator.validate",
            kind=EdgeKind.CONTAINS,
        ))
        graph.add_edge(GraphEdge(
            source_fqn="com.example.service.OrderService.placeOrder",
            target_fqn="validate",
            kind=EdgeKind.CALLS,
            confidence=Confidence.LOW,
            evidence="tree-sitter",
        ))

        _resolve_symbols(graph)

        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        edge = calls_edges[0]
        assert edge.target_fqn == "com.example.service.OrderValidator.validate"
        assert edge.confidence == Confidence.MEDIUM

    def test_unresolvable_call_stays_low(self) -> None:
        """A call that cannot be resolved keeps LOW confidence."""
        graph = SymbolGraph()

        graph.add_node(GraphNode(
            fqn="com.example.Foo",
            name="Foo",
            kind=NodeKind.CLASS,
            language="java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.Foo.doStuff",
            name="doStuff",
            kind=NodeKind.FUNCTION,
            language="java",
        ))
        graph.add_edge(GraphEdge(
            source_fqn="com.example.Foo",
            target_fqn="com.example.Foo.doStuff",
            kind=EdgeKind.CONTAINS,
        ))
        graph.add_edge(GraphEdge(
            source_fqn="com.example.Foo.doStuff",
            target_fqn="unknownMethod",
            kind=EdgeKind.CALLS,
            confidence=Confidence.LOW,
            evidence="tree-sitter",
        ))

        _resolve_symbols(graph)

        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].confidence == Confidence.LOW
        assert calls_edges[0].target_fqn == "unknownMethod"

    def test_inherits_edge_verified(self) -> None:
        """INHERITS edges to known FQNs remain intact."""
        graph = SymbolGraph()

        graph.add_node(GraphNode(
            fqn="com.example.Base",
            name="Base",
            kind=NodeKind.CLASS,
            language="java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.Child",
            name="Child",
            kind=NodeKind.CLASS,
            language="java",
        ))
        graph.add_edge(GraphEdge(
            source_fqn="com.example.Child",
            target_fqn="com.example.Base",
            kind=EdgeKind.INHERITS,
        ))

        _resolve_symbols(graph)

        inherits_edges = [e for e in graph.edges if e.kind == EdgeKind.INHERITS]
        assert len(inherits_edges) == 1
        assert inherits_edges[0].target_fqn == "com.example.Base"

    def test_empty_graph_resolution_is_noop(self) -> None:
        """Resolution on an empty graph does nothing."""
        graph = SymbolGraph()
        _resolve_symbols(graph)
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_high_confidence_calls_not_modified(self) -> None:
        """CALLS edges with HIGH confidence are not touched by resolution."""
        graph = SymbolGraph()

        graph.add_node(GraphNode(
            fqn="com.example.A",
            name="A",
            kind=NodeKind.CLASS,
            language="java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.A.foo",
            name="foo",
            kind=NodeKind.FUNCTION,
            language="java",
        ))
        graph.add_node(GraphNode(
            fqn="com.example.B.bar",
            name="bar",
            kind=NodeKind.FUNCTION,
            language="java",
        ))

        graph.add_edge(GraphEdge(
            source_fqn="com.example.A.foo",
            target_fqn="com.example.B.bar",
            kind=EdgeKind.CALLS,
            confidence=Confidence.HIGH,
            evidence="scip",
        ))

        _resolve_symbols(graph)

        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].confidence == Confidence.HIGH
        assert calls_edges[0].target_fqn == "com.example.B.bar"


# ---------------------------------------------------------------------------
# Task 5: Protocol compliance & end-to-end tests
# ---------------------------------------------------------------------------


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

    def test_full_pipeline_with_mock(self) -> None:
        """Simulate a two-file project with imports and unresolved calls."""

        class DetailedMockExtractor:
            def extract(
                self, source: bytes, file_path: str, root_path: str
            ) -> tuple[list[GraphNode], list[GraphEdge]]:
                nodes: list[GraphNode] = []
                edges: list[GraphEdge] = []

                if "UserService" in file_path:
                    nodes.append(GraphNode(
                        fqn="com.example.service.UserService",
                        name="UserService",
                        kind=NodeKind.CLASS,
                        language="java",
                        path=file_path,
                        line=1,
                    ))
                    nodes.append(GraphNode(
                        fqn="com.example.service.UserService.createUser",
                        name="createUser",
                        kind=NodeKind.FUNCTION,
                        language="java",
                        path=file_path,
                        line=5,
                    ))
                    edges.append(GraphEdge(
                        source_fqn="com.example.service.UserService",
                        target_fqn="com.example.service.UserService.createUser",
                        kind=EdgeKind.CONTAINS,
                    ))
                    edges.append(GraphEdge(
                        source_fqn="com.example.service.UserService",
                        target_fqn="com.example.repo.UserRepository",
                        kind=EdgeKind.IMPORTS,
                    ))
                    edges.append(GraphEdge(
                        source_fqn="com.example.service.UserService.createUser",
                        target_fqn="save",
                        kind=EdgeKind.CALLS,
                        confidence=Confidence.LOW,
                        evidence="tree-sitter",
                    ))
                elif "UserRepository" in file_path:
                    nodes.append(GraphNode(
                        fqn="com.example.repo.UserRepository",
                        name="UserRepository",
                        kind=NodeKind.CLASS,
                        language="java",
                        path=file_path,
                        line=1,
                    ))
                    nodes.append(GraphNode(
                        fqn="com.example.repo.UserRepository.save",
                        name="save",
                        kind=NodeKind.FUNCTION,
                        language="java",
                        path=file_path,
                        line=3,
                    ))
                    edges.append(GraphEdge(
                        source_fqn="com.example.repo.UserRepository",
                        target_fqn="com.example.repo.UserRepository.save",
                        kind=EdgeKind.CONTAINS,
                    ))

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
            graph = asyncio.get_event_loop().run_until_complete(
                parse_with_treesitter(manifest)  # type: ignore[arg-type]
            )

        # 4 nodes: 2 classes + 2 methods
        assert len(graph.nodes) == 4

        # The CALLS edge should be resolved
        calls_edges = [e for e in graph.edges if e.kind == EdgeKind.CALLS]
        assert len(calls_edges) == 1
        assert calls_edges[0].target_fqn == "com.example.repo.UserRepository.save"
        assert calls_edges[0].confidence == Confidence.MEDIUM
```

---

## Verification

After all tasks are complete, run the full test suite:

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_treesitter_parser.py -v
```

Expected: **24 tests pass** (4 registry + 8 grammar + 5 parallel + 6 resolution + 1 protocol compliance + 1 end-to-end = ~25 tests total across 6 test classes).
