# M1: Foundation Layer Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data models, service layers, configuration, and test infrastructure that every other milestone depends on.

**Architecture:** Dataclasses for internal models (GraphNode, GraphEdge, SymbolGraph, AnalysisContext, ProjectManifest). Pydantic v2 for API boundaries. SQLAlchemy 2.0 async ORM for PostgreSQL. Neo4j async driver behind a GraphStore ABC. structlog for JSON logging. All services initialized in FastAPI lifespan and accessed via dependency injection.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy[asyncio]+asyncpg, neo4j async driver, redis[hiredis], structlog, Pydantic v2, pytest+pytest-asyncio

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── config.py                    # MODIFY — add analysis config, structlog setup
│   ├── main.py                      # MODIFY — add lifespan service init, new routers
│   ├── models/
│   │   ├── __init__.py              # MODIFY — re-export key types
│   │   ├── enums.py                 # CREATE — NodeKind, EdgeKind, Confidence, AnalysisStatus
│   │   ├── graph.py                 # CREATE — GraphNode, GraphEdge, SymbolGraph
│   │   ├── manifest.py              # CREATE — ProjectManifest, DetectedLanguage, etc.
│   │   ├── context.py              # CREATE — AnalysisContext
│   │   └── db.py                    # CREATE — SQLAlchemy Project, AnalysisRun
│   └── services/
│       ├── __init__.py              # MODIFY — re-export service getters
│       ├── postgres.py              # CREATE — async engine, session factory
│       ├── neo4j.py                 # CREATE — GraphStore ABC, Neo4jGraphStore
│       └── redis.py                 # CREATE — Redis connection pool
├── tests/
│   ├── __init__.py                  # CREATE
│   ├── conftest.py                  # CREATE — shared fixtures
│   ├── unit/
│   │   ├── __init__.py              # CREATE
│   │   ├── test_enums.py            # CREATE
│   │   ├── test_graph_models.py     # CREATE
│   │   ├── test_manifest_models.py  # CREATE
│   │   └── test_context.py          # CREATE
│   └── fixtures/                    # CREATE — sample source for later milestones
│       ├── raw-java/
│       │   ├── pom.xml
│       │   └── src/main/java/com/example/UserService.java
│       ├── express-app/
│       │   ├── package.json
│       │   └── src/index.js
│       └── spring-petclinic/
│           ├── pom.xml
│           └── src/main/java/org/springframework/samples/petclinic/
│               ├── PetClinicApplication.java
│               ├── owner/OwnerController.java
│               ├── owner/OwnerRepository.java
│               ├── owner/Owner.java
│               └── vet/VetController.java
├── docker-compose.yml               # MODIFY (at repo root) — add GDS plugin to neo4j
└── pyproject.toml                   # MODIFY — add structlog dependency
```

---

## Task 1: Enums Module

**Files:**
- Create: `app/models/enums.py`
- Test: `tests/unit/test_enums.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_enums.py
from app.models.enums import NodeKind, EdgeKind, Confidence, AnalysisStatus


def test_node_kind_has_core_types():
    assert NodeKind.CLASS.value == "CLASS"
    assert NodeKind.FUNCTION.value == "FUNCTION"
    assert NodeKind.MODULE.value == "MODULE"
    assert NodeKind.TABLE.value == "TABLE"
    assert NodeKind.API_ENDPOINT.value == "API_ENDPOINT"


def test_edge_kind_has_core_types():
    assert EdgeKind.CALLS.value == "CALLS"
    assert EdgeKind.CONTAINS.value == "CONTAINS"
    assert EdgeKind.INHERITS.value == "INHERITS"
    assert EdgeKind.IMPLEMENTS.value == "IMPLEMENTS"
    assert EdgeKind.INJECTS.value == "INJECTS"
    assert EdgeKind.READS.value == "READS"
    assert EdgeKind.WRITES.value == "WRITES"


def test_confidence_ordering():
    assert Confidence.HIGH.value > Confidence.MEDIUM.value > Confidence.LOW.value


def test_analysis_status_values():
    assert AnalysisStatus.CREATED.value == "created"
    assert AnalysisStatus.ANALYZING.value == "analyzing"
    assert AnalysisStatus.ANALYZED.value == "analyzed"
    assert AnalysisStatus.FAILED.value == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_enums.py -v`
Expected: FAIL (ImportError — module doesn't exist)

- [ ] **Step 3: Implement enums**

```python
# app/models/enums.py
from enum import Enum


class NodeKind(str, Enum):
    APPLICATION = "APPLICATION"
    MODULE = "MODULE"
    CLASS = "CLASS"
    INTERFACE = "INTERFACE"
    FUNCTION = "FUNCTION"
    FIELD = "FIELD"
    TABLE = "TABLE"
    COLUMN = "COLUMN"
    VIEW = "VIEW"
    STORED_PROCEDURE = "STORED_PROCEDURE"
    API_ENDPOINT = "API_ENDPOINT"
    ROUTE = "ROUTE"
    MESSAGE_TOPIC = "MESSAGE_TOPIC"
    CONFIG_FILE = "CONFIG_FILE"
    CONFIG_ENTRY = "CONFIG_ENTRY"
    LAYER = "LAYER"
    COMPONENT = "COMPONENT"
    COMMUNITY = "COMMUNITY"
    TRANSACTION = "TRANSACTION"


class EdgeKind(str, Enum):
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    DEPENDS_ON = "DEPENDS_ON"
    IMPORTS = "IMPORTS"
    CONTAINS = "CONTAINS"
    INJECTS = "INJECTS"
    READS = "READS"
    WRITES = "WRITES"
    MAPS_TO = "MAPS_TO"
    HAS_COLUMN = "HAS_COLUMN"
    REFERENCES = "REFERENCES"
    EXPOSES = "EXPOSES"
    HANDLES = "HANDLES"
    CALLS_API = "CALLS_API"
    RENDERS = "RENDERS"
    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"
    STARTS_AT = "STARTS_AT"
    ENDS_AT = "ENDS_AT"
    INCLUDES = "INCLUDES"
    PASSES_PROP = "PASSES_PROP"


class Confidence(int, Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class AnalysisStatus(str, Enum):
    CREATED = "created"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    FAILED = "failed"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_enums.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/models/enums.py tests/ && git commit -m "feat(models): add enum types for nodes, edges, confidence, and analysis status"
```

---

## Task 2: Graph Models (GraphNode, GraphEdge, SymbolGraph)

**Files:**
- Create: `app/models/graph.py`
- Test: `tests/unit/test_graph_models.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_graph_models.py
import pytest
from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph


class TestGraphNode:
    def test_create_class_node(self):
        node = GraphNode(
            fqn="com.example.UserService",
            name="UserService",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/com/example/UserService.java",
            line=10,
            end_line=50,
        )
        assert node.fqn == "com.example.UserService"
        assert node.kind == NodeKind.CLASS
        assert node.properties == {}

    def test_node_with_properties(self):
        node = GraphNode(
            fqn="com.example.UserService",
            name="UserService",
            kind=NodeKind.CLASS,
            properties={"is_abstract": True, "annotations": ["Service"]},
        )
        assert node.properties["is_abstract"] is True

    def test_node_label_returns_kind_value(self):
        node = GraphNode(fqn="x", name="x", kind=NodeKind.CLASS)
        assert node.label == "Class"

    def test_node_label_api_endpoint(self):
        node = GraphNode(fqn="x", name="x", kind=NodeKind.API_ENDPOINT)
        assert node.label == "APIEndpoint"


class TestGraphEdge:
    def test_create_calls_edge(self):
        edge = GraphEdge(
            source_fqn="com.example.A.method1",
            target_fqn="com.example.B.method2",
            kind=EdgeKind.CALLS,
        )
        assert edge.confidence == Confidence.HIGH
        assert edge.evidence == "tree-sitter"

    def test_edge_with_low_confidence(self):
        edge = GraphEdge(
            source_fqn="a",
            target_fqn="b",
            kind=EdgeKind.CALLS,
            confidence=Confidence.LOW,
            evidence="heuristic",
        )
        assert edge.confidence == Confidence.LOW


class TestSymbolGraph:
    def test_empty_graph(self):
        g = SymbolGraph()
        assert len(g.nodes) == 0
        assert len(g.edges) == 0

    def test_add_and_get_node(self):
        g = SymbolGraph()
        node = GraphNode(fqn="a.B", name="B", kind=NodeKind.CLASS)
        g.add_node(node)
        assert g.get_node("a.B") is node
        assert g.get_node("nonexistent") is None

    def test_add_duplicate_node_overwrites(self):
        g = SymbolGraph()
        n1 = GraphNode(fqn="a.B", name="B", kind=NodeKind.CLASS, line=1)
        n2 = GraphNode(fqn="a.B", name="B", kind=NodeKind.CLASS, line=99)
        g.add_node(n1)
        g.add_node(n2)
        assert g.get_node("a.B").line == 99
        assert len(g.nodes) == 1

    def test_add_edge(self):
        g = SymbolGraph()
        edge = GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS)
        g.add_edge(edge)
        assert len(g.edges) == 1

    def test_get_edges_from(self):
        g = SymbolGraph()
        g.add_edge(GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="a", target_fqn="c", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="x", target_fqn="y", kind=EdgeKind.CALLS))
        assert len(g.get_edges_from("a")) == 2
        assert len(g.get_edges_from("x")) == 1
        assert len(g.get_edges_from("z")) == 0

    def test_get_edges_to(self):
        g = SymbolGraph()
        g.add_edge(GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS))
        g.add_edge(GraphEdge(source_fqn="c", target_fqn="b", kind=EdgeKind.CALLS))
        assert len(g.get_edges_to("b")) == 2

    def test_merge_graphs(self):
        g1 = SymbolGraph()
        g1.add_node(GraphNode(fqn="a", name="a", kind=NodeKind.CLASS))
        g1.add_edge(GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS))

        g2 = SymbolGraph()
        g2.add_node(GraphNode(fqn="b", name="b", kind=NodeKind.CLASS))
        g2.add_edge(GraphEdge(source_fqn="b", target_fqn="c", kind=EdgeKind.CALLS))

        g1.merge(g2)
        assert len(g1.nodes) == 2
        assert len(g1.edges) == 2

    def test_node_count_and_edge_count(self):
        g = SymbolGraph()
        g.add_node(GraphNode(fqn="a", name="a", kind=NodeKind.CLASS))
        g.add_node(GraphNode(fqn="b", name="b", kind=NodeKind.CLASS))
        g.add_edge(GraphEdge(source_fqn="a", target_fqn="b", kind=EdgeKind.CALLS))
        assert g.node_count == 2
        assert g.edge_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_graph_models.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement graph models**

```python
# app/models/graph.py
"""In-memory graph representation: GraphNode, GraphEdge, SymbolGraph.

These are internal dataclasses used throughout the pipeline. NOT Pydantic
models — we use dataclasses for performance since these are created in bulk
during parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import Confidence, EdgeKind, NodeKind

# Map NodeKind -> Neo4j label (PascalCase, no underscores)
_KIND_TO_LABEL: dict[NodeKind, str] = {
    NodeKind.APPLICATION: "Application",
    NodeKind.MODULE: "Module",
    NodeKind.CLASS: "Class",
    NodeKind.INTERFACE: "Interface",
    NodeKind.FUNCTION: "Function",
    NodeKind.FIELD: "Field",
    NodeKind.TABLE: "Table",
    NodeKind.COLUMN: "Column",
    NodeKind.VIEW: "View",
    NodeKind.STORED_PROCEDURE: "StoredProcedure",
    NodeKind.API_ENDPOINT: "APIEndpoint",
    NodeKind.ROUTE: "Route",
    NodeKind.MESSAGE_TOPIC: "MessageTopic",
    NodeKind.CONFIG_FILE: "ConfigFile",
    NodeKind.CONFIG_ENTRY: "ConfigEntry",
    NodeKind.LAYER: "Layer",
    NodeKind.COMPONENT: "Component",
    NodeKind.COMMUNITY: "Community",
    NodeKind.TRANSACTION: "Transaction",
}


@dataclass
class GraphNode:
    """A node in the code graph (class, function, table, endpoint, etc.)."""

    fqn: str
    name: str
    kind: NodeKind
    language: str | None = None
    path: str | None = None
    line: int | None = None
    end_line: int | None = None
    loc: int | None = None
    complexity: int | None = None
    visibility: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Neo4j node label derived from kind."""
        return _KIND_TO_LABEL[self.kind]


@dataclass
class GraphEdge:
    """A directed edge in the code graph (CALLS, CONTAINS, INJECTS, etc.)."""

    source_fqn: str
    target_fqn: str
    kind: EdgeKind
    confidence: Confidence = Confidence.HIGH
    evidence: str = "tree-sitter"
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class SymbolGraph:
    """Mutable in-memory graph accumulating nodes and edges through the pipeline."""

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    # Lazily-built reverse indexes (invalidated on mutation)
    _edges_from: dict[str, list[GraphEdge]] = field(
        default_factory=dict, repr=False
    )
    _edges_to: dict[str, list[GraphEdge]] = field(
        default_factory=dict, repr=False
    )
    _index_dirty: bool = field(default=True, repr=False)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.fqn] = node

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)
        self._index_dirty = True

    def get_node(self, fqn: str) -> GraphNode | None:
        return self.nodes.get(fqn)

    def _rebuild_index(self) -> None:
        self._edges_from.clear()
        self._edges_to.clear()
        for e in self.edges:
            self._edges_from.setdefault(e.source_fqn, []).append(e)
            self._edges_to.setdefault(e.target_fqn, []).append(e)
        self._index_dirty = False

    def get_edges_from(self, fqn: str) -> list[GraphEdge]:
        if self._index_dirty:
            self._rebuild_index()
        return self._edges_from.get(fqn, [])

    def get_edges_to(self, fqn: str) -> list[GraphEdge]:
        if self._index_dirty:
            self._rebuild_index()
        return self._edges_to.get(fqn, [])

    def merge(self, other: SymbolGraph) -> None:
        for node in other.nodes.values():
            self.add_node(node)
        for edge in other.edges:
            self.add_edge(edge)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_graph_models.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/models/graph.py tests/unit/test_graph_models.py && git commit -m "feat(models): add GraphNode, GraphEdge, SymbolGraph with indexed edge lookups"
```

---

## Task 3: Manifest Models

**Files:**
- Create: `app/models/manifest.py`
- Test: `tests/unit/test_manifest_models.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_manifest_models.py
from pathlib import Path

from app.models.enums import Confidence
from app.models.manifest import (
    BuildTool,
    DetectedFramework,
    DetectedLanguage,
    ProjectManifest,
    SourceFile,
)


class TestSourceFile:
    def test_create(self):
        sf = SourceFile(path="src/Main.java", language="java", size_bytes=1024)
        assert sf.language == "java"


class TestDetectedLanguage:
    def test_create(self):
        lang = DetectedLanguage(name="java", file_count=100, total_loc=5000)
        assert lang.name == "java"


class TestDetectedFramework:
    def test_create(self):
        fw = DetectedFramework(
            name="spring-boot",
            language="java",
            confidence=Confidence.HIGH,
            evidence=["pom.xml contains spring-boot-starter"],
        )
        assert fw.name == "spring-boot"
        assert fw.confidence == Confidence.HIGH


class TestProjectManifest:
    def test_create_empty(self):
        m = ProjectManifest(root_path=Path("/tmp/test"))
        assert m.total_files == 0
        assert m.total_loc == 0
        assert m.source_files == []

    def test_language_names(self):
        m = ProjectManifest(
            root_path=Path("/tmp"),
            detected_languages=[
                DetectedLanguage(name="java", file_count=10, total_loc=1000),
                DetectedLanguage(name="python", file_count=5, total_loc=500),
            ],
        )
        assert m.language_names == ["java", "python"]

    def test_has_language(self):
        m = ProjectManifest(
            root_path=Path("/tmp"),
            detected_languages=[
                DetectedLanguage(name="java", file_count=10, total_loc=1000),
            ],
        )
        assert m.has_language("java") is True
        assert m.has_language("python") is False

    def test_files_for_language(self):
        m = ProjectManifest(
            root_path=Path("/tmp"),
            source_files=[
                SourceFile(path="A.java", language="java", size_bytes=100),
                SourceFile(path="B.py", language="python", size_bytes=200),
                SourceFile(path="C.java", language="java", size_bytes=300),
            ],
        )
        java_files = m.files_for_language("java")
        assert len(java_files) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_manifest_models.py -v`
Expected: FAIL

- [ ] **Step 3: Implement manifest models**

```python
# app/models/manifest.py
"""Project discovery output: files, languages, frameworks, build tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.models.enums import Confidence


@dataclass
class SourceFile:
    path: str  # Relative to project root
    language: str
    size_bytes: int


@dataclass
class DetectedLanguage:
    name: str  # "java", "python", "typescript", "csharp"
    file_count: int
    total_loc: int


@dataclass
class DetectedFramework:
    name: str  # "spring-boot", "express", "django", etc.
    language: str
    confidence: Confidence
    evidence: list[str] = field(default_factory=list)


@dataclass
class BuildTool:
    name: str  # "maven", "gradle", "npm", "pip", etc.
    config_file: str  # Relative path to build config
    language: str


@dataclass
class ResolvedDependency:
    name: str
    version: str | None = None
    scope: str = "compile"  # compile, test, runtime, dev


@dataclass
class ResolvedEnvironment:
    """Output of Stage 2 — dependency resolution."""

    dependencies: dict[str, list[ResolvedDependency]] = field(
        default_factory=dict
    )  # language -> deps
    env_vars: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class ProjectManifest:
    root_path: Path
    source_files: list[SourceFile] = field(default_factory=list)
    detected_languages: list[DetectedLanguage] = field(default_factory=list)
    detected_frameworks: list[DetectedFramework] = field(default_factory=list)
    build_tools: list[BuildTool] = field(default_factory=list)
    total_files: int = 0
    total_loc: int = 0

    @property
    def language_names(self) -> list[str]:
        return [lang.name for lang in self.detected_languages]

    def has_language(self, name: str) -> bool:
        return name in self.language_names

    def files_for_language(self, language: str) -> list[SourceFile]:
        return [f for f in self.source_files if f.language == language]
```

- [ ] **Step 4: Run tests — verify pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_manifest_models.py -v`

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/models/manifest.py tests/unit/test_manifest_models.py && git commit -m "feat(models): add ProjectManifest, SourceFile, DetectedLanguage, and related types"
```

---

## Task 4: AnalysisContext

**Files:**
- Create: `app/models/context.py`
- Test: `tests/unit/test_context.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_context.py
from pathlib import Path

from app.models.context import AnalysisContext
from app.models.enums import EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.models.manifest import ProjectManifest


class TestAnalysisContext:
    def test_create_with_defaults(self):
        ctx = AnalysisContext(project_id="proj-1")
        assert ctx.project_id == "proj-1"
        assert ctx.manifest is None
        assert ctx.graph.node_count == 0
        assert ctx.warnings == []

    def test_add_warning(self):
        ctx = AnalysisContext(project_id="proj-1")
        ctx.warnings.append("SCIP failed for java")
        assert len(ctx.warnings) == 1

    def test_graph_is_mutable(self):
        ctx = AnalysisContext(project_id="proj-1")
        ctx.graph.add_node(
            GraphNode(fqn="a.B", name="B", kind=NodeKind.CLASS)
        )
        assert ctx.graph.node_count == 1

    def test_manifest_assignable(self):
        ctx = AnalysisContext(project_id="proj-1")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"))
        assert ctx.manifest.root_path == Path("/tmp")

    def test_scip_tracking(self):
        ctx = AnalysisContext(project_id="proj-1")
        ctx.scip_resolved_languages.add("java")
        assert "java" in ctx.scip_resolved_languages
        ctx.languages_needing_fallback.append("python")
        assert "python" in ctx.languages_needing_fallback
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_context.py -v`

- [ ] **Step 3: Implement AnalysisContext**

```python
# app/models/context.py
"""Shared mutable state passed through all pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.graph import SymbolGraph
from app.models.manifest import ProjectManifest, ResolvedEnvironment


@dataclass
class EntryPoint:
    """A transaction starting point (e.g., an API endpoint handler)."""

    fqn: str
    kind: str  # "http", "message_consumer", "scheduled", "main"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class AnalysisContext:
    """Mutable state accumulated across all 9 pipeline stages.

    Each stage reads from previous stages' outputs and writes its own.
    This is the single object threaded through the entire pipeline.
    """

    project_id: str

    # Stage 1 output
    manifest: ProjectManifest | None = None

    # Stage 2 output
    environment: ResolvedEnvironment | None = None

    # Stages 3-7 accumulate into this graph
    graph: SymbolGraph = field(default_factory=SymbolGraph)

    # Stage 4 tracking
    scip_resolved_languages: set[str] = field(default_factory=set)
    languages_needing_fallback: list[str] = field(default_factory=list)

    # Stage 5 tracking
    plugin_new_nodes: int = 0
    plugin_new_edges: int = 0

    # Stage 6 tracking
    cross_tech_edge_count: int = 0

    # Stage 7 tracking
    community_count: int = 0

    # Stage 9 tracking
    transaction_count: int = 0

    # Entry points collected by plugins for transaction discovery (Stage 9)
    entry_points: list[EntryPoint] = field(default_factory=list)

    # Warnings from non-fatal stage failures
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Run tests — verify pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_context.py -v`

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/models/context.py tests/unit/test_context.py && git commit -m "feat(models): add AnalysisContext for shared pipeline state"
```

---

## Task 5: SQLAlchemy DB Models

**Files:**
- Create: `app/models/db.py`

- [ ] **Step 1: Implement DB models**

```python
# app/models/db.py
"""SQLAlchemy ORM models for PostgreSQL metadata storage."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="created"
    )  # created | analyzing | analyzed | failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    analysis_runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending | running | completed | failed
    stage: Mapped[str | None] = mapped_column(String(50))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    node_count: Mapped[int | None] = mapped_column(Integer)
    edge_count: Mapped[int | None] = mapped_column(Integer)
    report: Mapped[dict | None] = mapped_column(JSON)

    project: Mapped[Project] = relationship(back_populates="analysis_runs")
```

- [ ] **Step 2: Commit** (no unit test needed — ORM models are tested via integration tests)

```bash
cd cast-clone-backend && git add app/models/db.py && git commit -m "feat(models): add SQLAlchemy Project and AnalysisRun ORM models"
```

---

## Task 6: Models __init__.py re-exports

**Files:**
- Modify: `app/models/__init__.py`

- [ ] **Step 1: Add re-exports**

```python
# app/models/__init__.py
"""Public API for the models package."""

from app.models.context import AnalysisContext, EntryPoint
from app.models.db import AnalysisRun, Base, Project
from app.models.enums import AnalysisStatus, Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.manifest import (
    BuildTool,
    DetectedFramework,
    DetectedLanguage,
    ProjectManifest,
    ResolvedDependency,
    ResolvedEnvironment,
    SourceFile,
)

__all__ = [
    "AnalysisContext",
    "AnalysisRun",
    "AnalysisStatus",
    "Base",
    "BuildTool",
    "Confidence",
    "DetectedFramework",
    "DetectedLanguage",
    "EdgeKind",
    "EntryPoint",
    "GraphEdge",
    "GraphNode",
    "NodeKind",
    "Project",
    "ProjectManifest",
    "ResolvedDependency",
    "ResolvedEnvironment",
    "SourceFile",
    "SymbolGraph",
]
```

- [ ] **Step 2: Verify imports work**

Run: `cd cast-clone-backend && uv run python -c "from app.models import GraphNode, SymbolGraph, ProjectManifest, AnalysisContext, Project; print('OK')"`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add app/models/__init__.py && git commit -m "feat(models): add public re-exports from models package"
```

---

## Task 7: Service Layer — PostgreSQL

**Files:**
- Create: `app/services/postgres.py`

- [ ] **Step 1: Implement PostgreSQL service**

```python
# app/services/postgres.py
"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.models.db import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_postgres(settings: Settings) -> None:
    """Create engine and ensure tables exist. Called during app lifespan startup."""
    global _engine, _session_factory
    _engine = create_async_engine(settings.database_url, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_postgres() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an async session."""
    assert _session_factory is not None, "PostgreSQL not initialized"
    async with _session_factory() as session:
        yield session
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend && git add app/services/postgres.py && git commit -m "feat(services): add async PostgreSQL engine and session factory"
```

---

## Task 8: Service Layer — Neo4j (GraphStore ABC + Implementation)

**Files:**
- Create: `app/services/neo4j.py`

- [ ] **Step 1: Implement Neo4j service with GraphStore abstraction**

```python
# app/services/neo4j.py
"""Neo4j async driver wrapper and GraphStore abstraction.

The GraphStore ABC allows swapping Neo4j for Memgraph/AGE in the future.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import Settings
from app.models.graph import GraphEdge, GraphNode

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


async def init_neo4j(settings: Settings) -> None:
    global _driver
    _driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    await _driver.verify_connectivity()


async def close_neo4j() -> None:
    global _driver
    if _driver:
        await _driver.close()
    _driver = None


def get_driver() -> AsyncDriver:
    assert _driver is not None, "Neo4j not initialized"
    return _driver


class GraphStore(ABC):
    """Abstract graph database interface."""

    @abstractmethod
    async def write_nodes_batch(
        self, nodes: list[GraphNode], app_name: str
    ) -> int: ...

    @abstractmethod
    async def write_edges_batch(
        self, edges: list[GraphEdge]
    ) -> int: ...

    @abstractmethod
    async def ensure_indexes(self) -> None: ...

    @abstractmethod
    async def clear_project(self, project_id: str) -> None: ...

    @abstractmethod
    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def query_single(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None: ...


class Neo4jGraphStore(GraphStore):
    """Neo4j implementation of GraphStore."""

    def __init__(self, driver: AsyncDriver, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    async def ensure_indexes(self) -> None:
        """Create indexes and full-text search index."""
        index_statements = [
            "CREATE INDEX IF NOT EXISTS FOR (n:Class) ON (n.fqn)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Function) ON (n.fqn)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Interface) ON (n.fqn)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Module) ON (n.fqn)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Table) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:APIEndpoint) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Column) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Transaction) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Class) ON (n.language)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Function) ON (n.language)",
        ]
        async with self._driver.session(database=self._database) as session:
            for stmt in index_statements:
                await session.run(stmt)

    async def write_nodes_batch(
        self, nodes: list[GraphNode], app_name: str
    ) -> int:
        """Write nodes in batches of 5000 using UNWIND."""
        batch_size = 5000
        total = 0
        for i in range(0, len(nodes), batch_size):
            batch = nodes[i : i + batch_size]
            records = []
            for node in batch:
                props = {
                    "fqn": node.fqn,
                    "name": node.name,
                    "app_name": app_name,
                    **({"language": node.language} if node.language else {}),
                    **({"path": node.path} if node.path else {}),
                    **({"line": node.line} if node.line is not None else {}),
                    **({"end_line": node.end_line} if node.end_line is not None else {}),
                    **({"loc": node.loc} if node.loc is not None else {}),
                    **({"complexity": node.complexity} if node.complexity is not None else {}),
                    **({"visibility": node.visibility} if node.visibility else {}),
                    **node.properties,
                }
                records.append({"label": node.label, "properties": props})
            cypher = """
            UNWIND $batch AS n
            CALL apoc.create.node([n.label], n.properties) YIELD node
            RETURN count(node) AS cnt
            """
            async with self._driver.session(database=self._database) as session:
                result = await session.run(cypher, {"batch": records})
                record = await result.single()
                total += record["cnt"] if record else 0
        return total

    async def write_edges_batch(self, edges: list[GraphEdge]) -> int:
        """Write edges in batches of 5000 using UNWIND."""
        batch_size = 5000
        total = 0
        for i in range(0, len(edges), batch_size):
            batch = edges[i : i + batch_size]
            records = []
            for edge in batch:
                props = {
                    "confidence": edge.confidence.name,
                    "evidence": edge.evidence,
                    **edge.properties,
                }
                records.append({
                    "from_fqn": edge.source_fqn,
                    "to_fqn": edge.target_fqn,
                    "type": edge.kind.value,
                    "properties": props,
                })
            cypher = """
            UNWIND $batch AS e
            MATCH (from {fqn: e.from_fqn})
            MATCH (to {fqn: e.to_fqn})
            CALL apoc.create.relationship(from, e.type, e.properties, to) YIELD rel
            RETURN count(rel) AS cnt
            """
            async with self._driver.session(database=self._database) as session:
                result = await session.run(cypher, {"batch": records})
                record = await result.single()
                total += record["cnt"] if record else 0
        return total

    async def clear_project(self, project_id: str) -> None:
        cypher = """
        MATCH (n {app_name: $app_name})
        DETACH DELETE n
        """
        async with self._driver.session(database=self._database) as session:
            await session.run(cypher, {"app_name": project_id})

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, params or {})
            return [dict(record) async for record in result]

    async def query_single(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, params or {})
            record = await result.single()
            return dict(record) if record else None
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend && git add app/services/neo4j.py && git commit -m "feat(services): add Neo4j driver wrapper and GraphStore abstraction"
```

---

## Task 9: Service Layer — Redis

**Files:**
- Create: `app/services/redis.py`

- [ ] **Step 1: Implement Redis service**

```python
# app/services/redis.py
"""Redis async connection for caching and pub/sub."""

from __future__ import annotations

import redis.asyncio as aioredis

from app.config import Settings

_redis: aioredis.Redis | None = None


async def init_redis(settings: Settings) -> None:
    global _redis
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    await _redis.ping()


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
    _redis = None


def get_redis() -> aioredis.Redis:
    assert _redis is not None, "Redis not initialized"
    return _redis
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend && git add app/services/redis.py && git commit -m "feat(services): add async Redis connection pool"
```

---

## Task 10: Update Config, Docker Compose, Dependencies

**Files:**
- Modify: `app/config.py` — add analysis-specific settings
- Modify: `docker-compose.yml` (repo root) — add GDS plugin to Neo4j
- Modify: `pyproject.toml` — add structlog
- Modify: `.env.example` — add new vars

- [ ] **Step 1: Update config.py**

Add to `Settings` class:
```python
    # Analysis defaults
    scip_timeout: int = 600
    total_analysis_timeout: int = 3600
    max_traversal_depth: int = 15
    treesitter_workers: int | None = None  # None = os.cpu_count()
    log_level: str = "info"
```

- [ ] **Step 2: Update docker-compose.yml — add GDS plugin**

Change Neo4j `NEO4J_PLUGINS` to: `'["apoc", "graph-data-science"]'`

- [ ] **Step 3: Add structlog to pyproject.toml**

Add `"structlog>=24.0.0"` to the `dependencies` list.

- [ ] **Step 4: Run uv sync**

Run: `cd cast-clone-backend && uv sync`

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/pyproject.toml cast-clone-backend/app/config.py cast-clone-backend/.env.example docker-compose.yml cast-clone-backend/uv.lock && git commit -m "feat(config): add analysis settings, GDS plugin, structlog dependency"
```

---

## Task 11: Update main.py lifespan + services __init__

**Files:**
- Modify: `app/main.py` — initialize/shutdown services in lifespan
- Modify: `app/services/__init__.py`

- [ ] **Step 1: Update main.py**

Replace lifespan with proper service init:
```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    # Startup
    await init_postgres(settings)
    await init_neo4j(settings)
    await init_redis(settings)
    yield
    # Shutdown
    await close_redis()
    await close_neo4j()
    await close_postgres()
```

Import the init/close functions from services.

- [ ] **Step 2: Update services/__init__.py**

```python
# app/services/__init__.py
from app.services.neo4j import (
    Neo4jGraphStore,
    close_neo4j,
    get_driver,
    init_neo4j,
)
from app.services.postgres import close_postgres, get_session, init_postgres
from app.services.redis import close_redis, get_redis, init_redis

__all__ = [
    "Neo4jGraphStore",
    "close_neo4j",
    "close_postgres",
    "close_redis",
    "get_driver",
    "get_redis",
    "get_session",
    "init_neo4j",
    "init_postgres",
    "init_redis",
]
```

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add app/main.py app/services/__init__.py && git commit -m "feat(app): wire service lifecycle into FastAPI lifespan"
```

---

## Task 12: Test Infrastructure + Fixtures

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/` sample files
- Modify: `pyproject.toml` — add pytest-asyncio config

- [ ] **Step 1: Create conftest.py**

```python
# tests/conftest.py
"""Shared pytest fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_java_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "raw-java"


@pytest.fixture
def spring_petclinic_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "spring-petclinic"


@pytest.fixture
def express_app_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "express-app"
```

- [ ] **Step 2: Add pytest config to pyproject.toml**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Create fixture files**

Create minimal Java/JS fixture files for testing extractors (exact content specified in M3/M4 plans — create directory structure with placeholder files here).

- [ ] **Step 4: Run all tests to confirm green baseline**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v`
Expected: All tests from Tasks 1-4 pass.

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add tests/ cast-clone-backend/pyproject.toml && git commit -m "feat(tests): add test infrastructure, conftest, and fixture directories"
```

---

## Final M1 Verification

- [ ] **Run full test suite**: `cd cast-clone-backend && uv run pytest tests/unit/ -v --tb=short`
- [ ] **Run linter**: `cd cast-clone-backend && uv run ruff check app/ tests/`
- [ ] **Verify imports**: `cd cast-clone-backend && uv run python -c "from app.models import *; from app.services import *; print('All imports OK')"`
