# Phase 2 M1: Backend API Endpoints — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 7 API endpoints for hierarchical drill-down, transaction listing/detail, and source code viewing.

**Architecture:** New router `app/api/graph_views.py` with endpoints that query Neo4j via the existing `Neo4jGraphStore`. New Pydantic schemas in `app/schemas/graph_views.py`. Follows the exact patterns established in `app/api/graph.py`.

**Tech Stack:** FastAPI, Pydantic v2, Neo4j async driver, aiofiles (for code viewer)

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── api/
│   │   ├── __init__.py              # MODIFY — export graph_views_router
│   │   └── graph_views.py           # CREATE — 7 new endpoints
│   ├── schemas/
│   │   └── graph_views.py           # CREATE — new Pydantic schemas
│   └── main.py                      # MODIFY — register graph_views_router
└── tests/
    └── unit/
        └── test_graph_views_api.py   # CREATE — unit tests
```

---

## Task 1: Create Pydantic Schemas

**Files:**
- Create: `cast-clone-backend/app/schemas/graph_views.py`

- [ ] **Step 1: Create the schemas file**

```python
# cast-clone-backend/app/schemas/graph_views.py
"""Pydantic v2 schemas for Phase 2 graph view endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.graph import GraphEdgeResponse, GraphNodeResponse


class ModuleResponse(BaseModel):
    """A module node with aggregated metrics."""

    fqn: str
    name: str
    kind: str = "MODULE"
    language: str | None = None
    loc: int | None = None
    file_count: int | None = None
    class_count: int | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ModuleListResponse(BaseModel):
    """List of modules for a project."""

    modules: list[ModuleResponse]
    total: int


class ClassListResponse(BaseModel):
    """List of classes within a module."""

    classes: list[GraphNodeResponse]
    total: int
    parent_fqn: str


class MethodListResponse(BaseModel):
    """List of methods within a class."""

    methods: list[GraphNodeResponse]
    total: int
    parent_fqn: str


class AggregatedEdgeResponse(BaseModel):
    """An aggregated edge between two higher-level nodes."""

    source: str
    target: str
    weight: int


class AggregatedEdgeListResponse(BaseModel):
    """List of aggregated edges."""

    edges: list[AggregatedEdgeResponse]
    total: int
    level: str


class TransactionSummary(BaseModel):
    """Summary of a transaction for listing."""

    fqn: str
    name: str
    kind: str = "TRANSACTION"
    properties: dict[str, Any] = Field(default_factory=dict)


class TransactionListResponse(BaseModel):
    """List of transactions for a project."""

    transactions: list[TransactionSummary]
    total: int


class TransactionDetailResponse(BaseModel):
    """Full call graph for a single transaction."""

    fqn: str
    name: str
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class CodeViewerResponse(BaseModel):
    """Source code content for the code viewer."""

    content: str
    language: str
    start_line: int
    highlight_line: int | None = None
    total_lines: int
```

- [ ] **Step 2: Verify the schemas file is valid Python**

```bash
cd cast-clone-backend && uv run python -c "from app.schemas.graph_views import ModuleResponse, ModuleListResponse, ClassListResponse, MethodListResponse, AggregatedEdgeResponse, AggregatedEdgeListResponse, TransactionSummary, TransactionListResponse, TransactionDetailResponse, CodeViewerResponse; print('All schemas imported OK')"
```

Expected output:
```
All schemas imported OK
```

---

## Task 2: Create the Modules Endpoint (TDD)

**Files:**
- Create: `cast-clone-backend/tests/unit/test_graph_views_api.py` (start with first test class)
- Create: `cast-clone-backend/app/api/graph_views.py` (start with first endpoint)

- [ ] **Step 1: Write the failing test for GET /modules**

```python
# cast-clone-backend/tests/unit/test_graph_views_api.py
"""Tests for Phase 2 graph view API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestListModules:
    @pytest.mark.asyncio
    async def test_list_modules_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "n": {
                    "fqn": "com.example.user",
                    "name": "user",
                    "kind": "MODULE",
                    "language": "java",
                    "loc": 500,
                    "file_count": 10,
                },
                "class_count": 5,
            }
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get("/api/v1/graph-views/proj-1/modules")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["modules"][0]["fqn"] == "com.example.user"
        assert data["modules"][0]["name"] == "user"
        assert data["modules"][0]["class_count"] == 5

    @pytest.mark.asyncio
    async def test_list_modules_empty(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get("/api/v1/graph-views/proj-1/modules")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["modules"] == []
```

- [ ] **Step 2: Verify the test fails (module not found)**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestListModules -x 2>&1 | tail -5
```

Expected: `ModuleNotFoundError` or `ImportError` because `app.api.graph_views` does not exist yet.

- [ ] **Step 3: Create the router file with the modules endpoint**

```python
# cast-clone-backend/app/api/graph_views.py
"""Phase 2 graph view API endpoints — drill-down, transactions, code viewer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Project
from app.schemas.graph import GraphEdgeResponse, GraphNodeResponse
from app.schemas.graph_views import (
    AggregatedEdgeListResponse,
    AggregatedEdgeResponse,
    ClassListResponse,
    CodeViewerResponse,
    MethodListResponse,
    ModuleListResponse,
    ModuleResponse,
    TransactionDetailResponse,
    TransactionListResponse,
    TransactionSummary,
)
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/graph-views", tags=["graph-views"])

# Extension-to-language mapping for the code viewer
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".java": "java",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sql": "sql",
    ".xml": "xml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
}


def get_graph_store() -> Neo4jGraphStore:
    """Get a Neo4jGraphStore instance."""
    return Neo4jGraphStore(get_driver())


def _record_to_node(record: dict[str, Any]) -> GraphNodeResponse:
    """Convert a Neo4j record dict to a GraphNodeResponse."""
    n = record.get("n", record)
    return GraphNodeResponse(
        fqn=n.get("fqn", ""),
        name=n.get("name", ""),
        kind=n.get("kind", ""),
        language=n.get("language"),
        path=n.get("path"),
        line=n.get("line"),
        end_line=n.get("end_line"),
        loc=n.get("loc"),
        complexity=n.get("complexity"),
        visibility=n.get("visibility"),
        properties={
            k: v
            for k, v in n.items()
            if k
            not in {
                "fqn",
                "name",
                "kind",
                "language",
                "path",
                "line",
                "end_line",
                "loc",
                "complexity",
                "visibility",
                "app_name",
            }
        },
    )


def _record_to_edge(record: dict[str, Any]) -> GraphEdgeResponse:
    """Convert a Neo4j record to a GraphEdgeResponse."""
    return GraphEdgeResponse(
        source_fqn=record.get("source_fqn", ""),
        target_fqn=record.get("target_fqn", ""),
        kind=record.get("kind", ""),
        confidence=record.get("confidence", "HIGH"),
        evidence=record.get("evidence", "tree-sitter"),
    )


@router.get("/{project_id}/modules", response_model=ModuleListResponse)
async def list_modules(project_id: str) -> ModuleListResponse:
    """List all modules for a project with aggregated class counts."""
    store = get_graph_store()

    cypher = (
        "MATCH (n) WHERE n.app_name = $app_name AND n.kind = 'MODULE' "
        "OPTIONAL MATCH (n)-[:CONTAINS]->(c) "
        "WHERE c.kind = 'CLASS' OR c.kind = 'INTERFACE' "
        "WITH n, count(c) AS class_count "
        "RETURN n, class_count ORDER BY n.name"
    )
    records = await store.query(cypher, {"app_name": project_id})

    modules = [
        ModuleResponse(
            fqn=r["n"].get("fqn", ""),
            name=r["n"].get("name", ""),
            kind=r["n"].get("kind", "MODULE"),
            language=r["n"].get("language"),
            loc=r["n"].get("loc"),
            file_count=r["n"].get("file_count"),
            class_count=r.get("class_count", 0),
            properties={
                k: v
                for k, v in r["n"].items()
                if k
                not in {
                    "fqn",
                    "name",
                    "kind",
                    "language",
                    "loc",
                    "file_count",
                    "app_name",
                }
            },
        )
        for r in records
    ]

    return ModuleListResponse(modules=modules, total=len(modules))
```

- [ ] **Step 4: Verify the test passes**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestListModules -x -v
```

Expected output:
```
tests/unit/test_graph_views_api.py::TestListModules::test_list_modules_200 PASSED
tests/unit/test_graph_views_api.py::TestListModules::test_list_modules_empty PASSED
```

---

## Task 3: Classes-in-Module Endpoint (TDD)

**Files:**
- Modify: `cast-clone-backend/tests/unit/test_graph_views_api.py`
- Modify: `cast-clone-backend/app/api/graph_views.py`

- [ ] **Step 1: Add failing test for GET /modules/{fqn}/classes**

Append to `tests/unit/test_graph_views_api.py`:

```python
class TestListClasses:
    @pytest.mark.asyncio
    async def test_list_classes_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "n": {
                    "fqn": "com.example.user.UserService",
                    "name": "UserService",
                    "kind": "CLASS",
                    "language": "java",
                    "loc": 120,
                    "complexity": 15,
                }
            }
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/modules/com.example.user/classes"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["parent_fqn"] == "com.example.user"
        assert data["classes"][0]["fqn"] == "com.example.user.UserService"
        assert data["classes"][0]["kind"] == "CLASS"

    @pytest.mark.asyncio
    async def test_list_classes_empty(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/modules/com.example.user/classes"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["classes"] == []
        assert data["parent_fqn"] == "com.example.user"
```

- [ ] **Step 2: Verify the test fails**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestListClasses -x 2>&1 | tail -5
```

Expected: 404 or routing error because the endpoint does not exist.

- [ ] **Step 3: Add the classes endpoint to graph_views.py**

Append to `cast-clone-backend/app/api/graph_views.py`:

```python
@router.get(
    "/{project_id}/modules/{fqn:path}/classes",
    response_model=ClassListResponse,
)
async def list_classes(project_id: str, fqn: str) -> ClassListResponse:
    """List classes and interfaces within a module."""
    store = get_graph_store()

    cypher = (
        "MATCH (m {fqn: $fqn, app_name: $app_name})-[:CONTAINS]->(c) "
        "WHERE c.kind = 'CLASS' OR c.kind = 'INTERFACE' "
        "RETURN c AS n ORDER BY c.name"
    )
    records = await store.query(
        cypher, {"fqn": fqn, "app_name": project_id}
    )

    classes = [_record_to_node(r) for r in records]

    return ClassListResponse(
        classes=classes, total=len(classes), parent_fqn=fqn
    )
```

- [ ] **Step 4: Verify the test passes**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestListClasses -x -v
```

Expected output:
```
tests/unit/test_graph_views_api.py::TestListClasses::test_list_classes_200 PASSED
tests/unit/test_graph_views_api.py::TestListClasses::test_list_classes_empty PASSED
```

---

## Task 4: Methods-in-Class Endpoint (TDD)

**Files:**
- Modify: `cast-clone-backend/tests/unit/test_graph_views_api.py`
- Modify: `cast-clone-backend/app/api/graph_views.py`

- [ ] **Step 1: Add failing test for GET /classes/{fqn}/methods**

Append to `tests/unit/test_graph_views_api.py`:

```python
class TestListMethods:
    @pytest.mark.asyncio
    async def test_list_methods_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "n": {
                    "fqn": "com.example.user.UserService.findById",
                    "name": "findById",
                    "kind": "FUNCTION",
                    "language": "java",
                    "loc": 15,
                    "complexity": 3,
                    "visibility": "public",
                }
            }
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/classes/com.example.user.UserService/methods"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["parent_fqn"] == "com.example.user.UserService"
        assert data["methods"][0]["name"] == "findById"
        assert data["methods"][0]["kind"] == "FUNCTION"

    @pytest.mark.asyncio
    async def test_list_methods_empty(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/classes/com.example.user.UserService/methods"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["methods"] == []
```

- [ ] **Step 2: Verify the test fails**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestListMethods -x 2>&1 | tail -5
```

Expected: 404 because the endpoint does not exist.

- [ ] **Step 3: Add the methods endpoint to graph_views.py**

Append to `cast-clone-backend/app/api/graph_views.py`:

```python
@router.get(
    "/{project_id}/classes/{fqn:path}/methods",
    response_model=MethodListResponse,
)
async def list_methods(project_id: str, fqn: str) -> MethodListResponse:
    """List methods/functions within a class."""
    store = get_graph_store()

    cypher = (
        "MATCH (c {fqn: $fqn, app_name: $app_name})-[:CONTAINS]->(f) "
        "WHERE f.kind = 'FUNCTION' "
        "RETURN f AS n ORDER BY f.name"
    )
    records = await store.query(
        cypher, {"fqn": fqn, "app_name": project_id}
    )

    methods = [_record_to_node(r) for r in records]

    return MethodListResponse(
        methods=methods, total=len(methods), parent_fqn=fqn
    )
```

- [ ] **Step 4: Verify the test passes**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestListMethods -x -v
```

Expected output:
```
tests/unit/test_graph_views_api.py::TestListMethods::test_list_methods_200 PASSED
tests/unit/test_graph_views_api.py::TestListMethods::test_list_methods_empty PASSED
```

---

## Task 5: Aggregated Edges Endpoint (TDD)

**Files:**
- Modify: `cast-clone-backend/tests/unit/test_graph_views_api.py`
- Modify: `cast-clone-backend/app/api/graph_views.py`

- [ ] **Step 1: Add failing tests for GET /edges/aggregated**

Append to `tests/unit/test_graph_views_api.py`:

```python
class TestAggregatedEdges:
    @pytest.mark.asyncio
    async def test_module_level_edges(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {"source": "com.example.user", "target": "com.example.db", "weight": 12},
            {"source": "com.example.web", "target": "com.example.user", "weight": 8},
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/edges/aggregated?level=module"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["level"] == "module"
        assert data["edges"][0]["source"] == "com.example.user"
        assert data["edges"][0]["weight"] == 12

    @pytest.mark.asyncio
    async def test_class_level_edges(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {"source": "com.example.user.UserService", "target": "com.example.user.UserRepo", "weight": 5},
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/edges/aggregated?level=class&parent=com.example.user"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["level"] == "class"

    @pytest.mark.asyncio
    async def test_invalid_level_422(self, app_client):
        response = await app_client.get(
            "/api/v1/graph-views/proj-1/edges/aggregated?level=invalid"
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_class_level_without_parent_400(self, app_client):
        with patch(
            "app.api.graph_views.get_graph_store", return_value=AsyncMock()
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/edges/aggregated?level=class"
            )
        assert response.status_code == 400
```

- [ ] **Step 2: Verify the tests fail**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestAggregatedEdges -x 2>&1 | tail -5
```

Expected: 404 because the endpoint does not exist.

- [ ] **Step 3: Add the aggregated edges endpoint to graph_views.py**

Append to `cast-clone-backend/app/api/graph_views.py`:

```python
from enum import Enum


class AggregationLevel(str, Enum):
    module = "module"
    klass = "class"


@router.get(
    "/{project_id}/edges/aggregated",
    response_model=AggregatedEdgeListResponse,
)
async def aggregated_edges(
    project_id: str,
    level: AggregationLevel = Query(..., description="Aggregation level: module or class"),
    parent: str | None = Query(None, description="Parent FQN (required for class level)"),
) -> AggregatedEdgeListResponse:
    """Return aggregated edges between modules or classes."""
    store = get_graph_store()

    if level == AggregationLevel.klass:
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="'parent' query parameter is required for class-level aggregation",
            )
        cypher = (
            "MATCH (m {fqn: $parent, app_name: $app_name})-[:CONTAINS]->(c1) "
            "WHERE c1.kind = 'CLASS' OR c1.kind = 'INTERFACE' "
            "MATCH (c1)-[r:CALLS|DEPENDS_ON]->(c2) "
            "WHERE c2.app_name = $app_name AND (c2.kind = 'CLASS' OR c2.kind = 'INTERFACE') "
            "AND c1 <> c2 "
            "WITH c1.fqn AS source, c2.fqn AS target, count(r) AS weight "
            "RETURN source, target, weight ORDER BY weight DESC"
        )
        records = await store.query(
            cypher, {"parent": parent, "app_name": project_id}
        )
    else:
        # Module-level aggregation
        cypher = (
            "MATCH (m1)-[:CONTAINS]->(c1)-[r:CALLS|DEPENDS_ON]->(c2)<-[:CONTAINS]-(m2) "
            "WHERE m1.app_name = $app_name AND m1.kind = 'MODULE' "
            "AND m2.kind = 'MODULE' AND m1 <> m2 "
            "AND (c1.kind = 'CLASS' OR c1.kind = 'INTERFACE') "
            "AND (c2.kind = 'CLASS' OR c2.kind = 'INTERFACE') "
            "WITH m1.fqn AS source, m2.fqn AS target, count(r) AS weight "
            "RETURN source, target, weight ORDER BY weight DESC"
        )
        records = await store.query(cypher, {"app_name": project_id})

    edges = [
        AggregatedEdgeResponse(
            source=r["source"], target=r["target"], weight=r["weight"]
        )
        for r in records
    ]

    return AggregatedEdgeListResponse(
        edges=edges, total=len(edges), level=level.value
    )
```

**Note:** The `AggregationLevel` enum uses `klass` as the Python name to avoid shadowing the `class` keyword, but its string value is `"class"` so the API accepts `?level=class`.

- [ ] **Step 4: Verify the tests pass**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestAggregatedEdges -x -v
```

Expected output:
```
tests/unit/test_graph_views_api.py::TestAggregatedEdges::test_module_level_edges PASSED
tests/unit/test_graph_views_api.py::TestAggregatedEdges::test_class_level_edges PASSED
tests/unit/test_graph_views_api.py::TestAggregatedEdges::test_invalid_level_422 PASSED
tests/unit/test_graph_views_api.py::TestAggregatedEdges::test_class_level_without_parent_400 PASSED
```

---

## Task 6: Transactions List Endpoint (TDD)

**Files:**
- Modify: `cast-clone-backend/tests/unit/test_graph_views_api.py`
- Modify: `cast-clone-backend/app/api/graph_views.py`

- [ ] **Step 1: Add failing tests for GET /transactions**

Append to `tests/unit/test_graph_views_api.py`:

```python
class TestListTransactions:
    @pytest.mark.asyncio
    async def test_list_transactions_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "n": {
                    "fqn": "txn::GET /api/users",
                    "name": "GET /api/users",
                    "kind": "TRANSACTION",
                    "http_method": "GET",
                    "entry_point": "com.example.UserController.listUsers",
                }
            },
            {
                "n": {
                    "fqn": "txn::POST /api/users",
                    "name": "POST /api/users",
                    "kind": "TRANSACTION",
                    "http_method": "POST",
                    "entry_point": "com.example.UserController.createUser",
                }
            },
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/transactions"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["transactions"][0]["fqn"] == "txn::GET /api/users"
        assert data["transactions"][0]["name"] == "GET /api/users"

    @pytest.mark.asyncio
    async def test_list_transactions_empty(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/transactions"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["transactions"] == []
```

- [ ] **Step 2: Verify the tests fail**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestListTransactions -x 2>&1 | tail -5
```

Expected: 404 because the endpoint does not exist.

- [ ] **Step 3: Add the transactions list endpoint to graph_views.py**

Append to `cast-clone-backend/app/api/graph_views.py`:

```python
@router.get(
    "/{project_id}/transactions",
    response_model=TransactionListResponse,
)
async def list_transactions(project_id: str) -> TransactionListResponse:
    """List all transaction nodes for a project."""
    store = get_graph_store()

    cypher = (
        "MATCH (n) WHERE n.app_name = $app_name AND n.kind = 'TRANSACTION' "
        "RETURN n ORDER BY n.name"
    )
    records = await store.query(cypher, {"app_name": project_id})

    transactions = [
        TransactionSummary(
            fqn=r["n"].get("fqn", ""),
            name=r["n"].get("name", ""),
            kind=r["n"].get("kind", "TRANSACTION"),
            properties={
                k: v
                for k, v in r["n"].items()
                if k not in {"fqn", "name", "kind", "app_name"}
            },
        )
        for r in records
    ]

    return TransactionListResponse(
        transactions=transactions, total=len(transactions)
    )
```

- [ ] **Step 4: Verify the tests pass**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestListTransactions -x -v
```

Expected output:
```
tests/unit/test_graph_views_api.py::TestListTransactions::test_list_transactions_200 PASSED
tests/unit/test_graph_views_api.py::TestListTransactions::test_list_transactions_empty PASSED
```

---

## Task 7: Transaction Detail Endpoint (TDD)

**Files:**
- Modify: `cast-clone-backend/tests/unit/test_graph_views_api.py`
- Modify: `cast-clone-backend/app/api/graph_views.py`

- [ ] **Step 1: Add failing tests for GET /transactions/{fqn}**

Append to `tests/unit/test_graph_views_api.py`:

```python
class TestTransactionDetail:
    @pytest.mark.asyncio
    async def test_transaction_detail_200(self, app_client):
        mock_store = AsyncMock()
        # First query: get the transaction node itself
        mock_store.query_single.return_value = {
            "n": {
                "fqn": "txn::GET /api/users",
                "name": "GET /api/users",
                "kind": "TRANSACTION",
            }
        }
        # Second query: get nodes included in the transaction
        # Third query: get edges between those nodes
        mock_store.query.side_effect = [
            # Nodes in the transaction
            [
                {
                    "n": {
                        "fqn": "com.example.UserController.listUsers",
                        "name": "listUsers",
                        "kind": "FUNCTION",
                        "language": "java",
                    }
                },
                {
                    "n": {
                        "fqn": "com.example.UserService.findAll",
                        "name": "findAll",
                        "kind": "FUNCTION",
                        "language": "java",
                    }
                },
            ],
            # Edges between the nodes
            [
                {
                    "source_fqn": "com.example.UserController.listUsers",
                    "target_fqn": "com.example.UserService.findAll",
                    "kind": "CALLS",
                    "confidence": "HIGH",
                    "evidence": "tree-sitter",
                }
            ],
        ]

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/transactions/txn::GET /api/users"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["fqn"] == "txn::GET /api/users"
        assert data["name"] == "GET /api/users"
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["edges"][0]["source_fqn"] == "com.example.UserController.listUsers"

    @pytest.mark.asyncio
    async def test_transaction_detail_404(self, app_client):
        mock_store = AsyncMock()
        mock_store.query_single.return_value = None

        with patch(
            "app.api.graph_views.get_graph_store", return_value=mock_store
        ):
            response = await app_client.get(
                "/api/v1/graph-views/proj-1/transactions/txn::nonexistent"
            )

        assert response.status_code == 404
```

- [ ] **Step 2: Verify the tests fail**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestTransactionDetail -x 2>&1 | tail -5
```

Expected: 404 because the endpoint does not exist.

- [ ] **Step 3: Add the transaction detail endpoint to graph_views.py**

Append to `cast-clone-backend/app/api/graph_views.py`:

```python
@router.get(
    "/{project_id}/transactions/{fqn:path}",
    response_model=TransactionDetailResponse,
)
async def get_transaction(
    project_id: str, fqn: str
) -> TransactionDetailResponse:
    """Get the full call graph for a specific transaction."""
    store = get_graph_store()

    # First, verify the transaction exists
    txn_result = await store.query_single(
        "MATCH (n {fqn: $fqn, app_name: $app_name}) "
        "WHERE n.kind = 'TRANSACTION' RETURN n",
        {"fqn": fqn, "app_name": project_id},
    )
    if txn_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {fqn} not found in project {project_id}",
        )

    # Get all nodes included in the transaction
    node_records = await store.query(
        "MATCH (t {fqn: $fqn, app_name: $app_name})-[:INCLUDES]->(f) "
        "RETURN f AS n",
        {"fqn": fqn, "app_name": project_id},
    )
    nodes = [_record_to_node(r) for r in node_records]

    # Get edges between the included nodes
    edge_records = await store.query(
        "MATCH (t {fqn: $fqn, app_name: $app_name})-[:INCLUDES]->(f1) "
        "MATCH (f1)-[r:CALLS]->(f2) "
        "WHERE (t)-[:INCLUDES]->(f2) "
        "RETURN f1.fqn AS source_fqn, f2.fqn AS target_fqn, "
        "type(r) AS kind, r.confidence AS confidence, r.evidence AS evidence",
        {"fqn": fqn, "app_name": project_id},
    )
    edges = [_record_to_edge(r) for r in edge_records]

    txn_node = txn_result["n"]
    return TransactionDetailResponse(
        fqn=txn_node.get("fqn", ""),
        name=txn_node.get("name", ""),
        nodes=nodes,
        edges=edges,
    )
```

- [ ] **Step 4: Verify the tests pass**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestTransactionDetail -x -v
```

Expected output:
```
tests/unit/test_graph_views_api.py::TestTransactionDetail::test_transaction_detail_200 PASSED
tests/unit/test_graph_views_api.py::TestTransactionDetail::test_transaction_detail_404 PASSED
```

---

## Task 8: Code Viewer Endpoint (TDD)

This endpoint reads files from disk. It requires path traversal protection and database access to look up the project's `source_path`.

**Files:**
- Modify: `cast-clone-backend/tests/unit/test_graph_views_api.py`
- Modify: `cast-clone-backend/app/api/graph_views.py`

- [ ] **Step 1: Add `aiofiles` dependency**

```bash
cd cast-clone-backend && uv add aiofiles
```

- [ ] **Step 2: Add failing tests for GET /code/{project_id}**

Append to `tests/unit/test_graph_views_api.py`:

```python
from unittest.mock import patch as sync_patch
from pathlib import Path
import tempfile
import os


class TestCodeViewer:
    @pytest.mark.asyncio
    async def test_code_viewer_200(self, app_client, mock_session):
        """Read a file that exists on disk."""
        # Create a temporary file to read
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".java", delete=False, dir="/tmp"
        ) as f:
            f.write("package com.example;\n\npublic class Foo {\n    public void bar() {\n        // hello\n    }\n}\n")
            temp_path = f.name

        try:
            temp_dir = "/tmp"
            relative_file = os.path.basename(temp_path)

            # Mock the DB query to return a project with source_path
            mock_result = MagicMock()
            mock_project = MagicMock()
            mock_project.source_path = temp_dir
            mock_result.scalar_one_or_none.return_value = mock_project
            mock_session.execute.return_value = mock_result

            response = await app_client.get(
                f"/api/v1/graph-views/proj-1/code?file={relative_file}&line=4&context=2"
            )

            assert response.status_code == 200
            data = response.json()
            assert data["language"] == "java"
            assert "public class Foo" in data["content"]
            assert data["highlight_line"] == 4
            assert data["total_lines"] == 7
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_code_viewer_missing_file_param_422(self, app_client):
        response = await app_client.get("/api/v1/graph-views/proj-1/code")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_code_viewer_project_not_found_404(
        self, app_client, mock_session
    ):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = await app_client.get(
            "/api/v1/graph-views/proj-1/code?file=Foo.java"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_code_viewer_path_traversal_400(
        self, app_client, mock_session
    ):
        """Reject paths that try to escape the source directory."""
        mock_result = MagicMock()
        mock_project = MagicMock()
        mock_project.source_path = "/opt/code/myproject"
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_result

        response = await app_client.get(
            "/api/v1/graph-views/proj-1/code?file=../../etc/passwd"
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_code_viewer_file_not_found_404(
        self, app_client, mock_session
    ):
        mock_result = MagicMock()
        mock_project = MagicMock()
        mock_project.source_path = "/opt/code/myproject"
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_result

        response = await app_client.get(
            "/api/v1/graph-views/proj-1/code?file=nonexistent.java"
        )
        assert response.status_code == 404
```

- [ ] **Step 3: Verify the tests fail**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestCodeViewer -x 2>&1 | tail -5
```

Expected: 404 because the endpoint does not exist.

- [ ] **Step 4: Add the code viewer endpoint to graph_views.py**

Add this import at the top of `cast-clone-backend/app/api/graph_views.py`:

```python
import aiofiles
```

Append to `cast-clone-backend/app/api/graph_views.py`:

```python
@router.get("/{project_id}/code", response_model=CodeViewerResponse)
async def get_code(
    project_id: str,
    file: str = Query(..., description="Relative file path within the project"),
    line: int | None = Query(None, description="Line to highlight"),
    context: int = Query(30, description="Lines of context around highlight line"),
    session: AsyncSession = Depends(get_session),
) -> CodeViewerResponse:
    """Read source code from the project's filesystem.

    Returns the file content (or a window around the highlight line),
    the inferred language, and line metadata.
    """
    # Look up the project to get source_path
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # Build and validate the full path (prevent path traversal)
    source_dir = Path(project.source_path).resolve()
    full_path = (source_dir / file).resolve()

    if not full_path.is_relative_to(source_dir):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path: path traversal detected",
        )

    if not full_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {file}",
        )

    # Read the file
    async with aiofiles.open(full_path, mode="r", encoding="utf-8", errors="replace") as f:
        all_lines = await f.readlines()

    total_lines = len(all_lines)

    # If a highlight line is given, return a window around it
    if line is not None and context < total_lines:
        start = max(0, line - context - 1)
        end = min(total_lines, line + context)
        content = "".join(all_lines[start:end])
        start_line = start + 1
    else:
        content = "".join(all_lines)
        start_line = 1

    # Infer language from extension
    ext = full_path.suffix.lower()
    language = _EXT_TO_LANGUAGE.get(ext, "plaintext")

    return CodeViewerResponse(
        content=content,
        language=language,
        start_line=start_line,
        highlight_line=line,
        total_lines=total_lines,
    )
```

- [ ] **Step 5: Verify the tests pass**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py::TestCodeViewer -x -v
```

Expected output:
```
tests/unit/test_graph_views_api.py::TestCodeViewer::test_code_viewer_200 PASSED
tests/unit/test_graph_views_api.py::TestCodeViewer::test_code_viewer_missing_file_param_422 PASSED
tests/unit/test_graph_views_api.py::TestCodeViewer::test_code_viewer_project_not_found_404 PASSED
tests/unit/test_graph_views_api.py::TestCodeViewer::test_code_viewer_path_traversal_400 PASSED
tests/unit/test_graph_views_api.py::TestCodeViewer::test_code_viewer_file_not_found_404 PASSED
```

---

## Task 9: Register Router in main.py

**Files:**
- Modify: `cast-clone-backend/app/api/__init__.py`
- Modify: `cast-clone-backend/app/main.py`

- [ ] **Step 1: Export the new router from api/__init__.py**

Edit `cast-clone-backend/app/api/__init__.py` to add:

```python
"""API router registry."""

from app.api.analysis import router as analysis_router
from app.api.graph import router as graph_router
from app.api.graph_views import router as graph_views_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.websocket import router as websocket_router

__all__ = [
    "analysis_router",
    "graph_router",
    "graph_views_router",
    "health_router",
    "projects_router",
    "websocket_router",
]
```

- [ ] **Step 2: Register the router in main.py**

Edit `cast-clone-backend/app/main.py` to import and include the new router.

In the imports section, change:

```python
from app.api import (
    analysis_router,
    graph_router,
    health_router,
    projects_router,
    websocket_router,
)
```

to:

```python
from app.api import (
    analysis_router,
    graph_router,
    graph_views_router,
    health_router,
    projects_router,
    websocket_router,
)
```

In the `create_app()` function, after `application.include_router(graph_router)`, add:

```python
    application.include_router(graph_views_router)
```

- [ ] **Step 3: Verify all tests pass**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_graph_views_api.py -v
```

Expected output: all 15 tests pass.

- [ ] **Step 4: Verify existing tests still pass**

```bash
cd cast-clone-backend && uv run pytest tests/unit/ -v
```

Expected: all existing tests still pass, no regressions.

- [ ] **Step 5: Run linting**

```bash
cd cast-clone-backend && uv run ruff check app/api/graph_views.py app/schemas/graph_views.py tests/unit/test_graph_views_api.py
```

Expected: no errors. Fix any issues reported.

- [ ] **Step 6: Verify the app starts and routes are registered**

```bash
cd cast-clone-backend && uv run python -c "
from app.main import create_app
app = create_app()
routes = [r.path for r in app.routes if hasattr(r, 'path')]
expected = [
    '/api/v1/graph-views/{project_id}/modules',
    '/api/v1/graph-views/{project_id}/modules/{fqn:path}/classes',
    '/api/v1/graph-views/{project_id}/classes/{fqn:path}/methods',
    '/api/v1/graph-views/{project_id}/edges/aggregated',
    '/api/v1/graph-views/{project_id}/transactions',
    '/api/v1/graph-views/{project_id}/transactions/{fqn:path}',
    '/api/v1/graph-views/{project_id}/code',
]
for e in expected:
    assert e in routes, f'Missing route: {e}'
print(f'All {len(expected)} routes registered OK')
"
```

Expected output:
```
All 7 routes registered OK
```

---

## Summary

| Task | Endpoint | Tests | Est. Time |
|------|----------|-------|-----------|
| 1 | Schemas only | Import check | 3 min |
| 2 | `GET /modules` | 2 tests | 5 min |
| 3 | `GET /modules/{fqn}/classes` | 2 tests | 4 min |
| 4 | `GET /classes/{fqn}/methods` | 2 tests | 4 min |
| 5 | `GET /edges/aggregated` | 4 tests | 5 min |
| 6 | `GET /transactions` | 2 tests | 4 min |
| 7 | `GET /transactions/{fqn}` | 2 tests | 5 min |
| 8 | `GET /code/{project_id}` | 5 tests | 5 min |
| 9 | Router registration + final checks | 0 new tests | 3 min |
| **Total** | **7 endpoints** | **19 tests** | **~38 min** |

### Commit Strategy

One commit per task (9 commits) with messages like:
- `feat(p2-m1): add Pydantic schemas for graph view endpoints`
- `feat(p2-m1): add GET /modules endpoint with TDD`
- `feat(p2-m1): add GET /modules/{fqn}/classes endpoint with TDD`
- `feat(p2-m1): add GET /classes/{fqn}/methods endpoint with TDD`
- `feat(p2-m1): add GET /edges/aggregated endpoint with TDD`
- `feat(p2-m1): add GET /transactions list endpoint with TDD`
- `feat(p2-m1): add GET /transactions/{fqn} detail endpoint with TDD`
- `feat(p2-m1): add GET /code/{project_id} endpoint with path traversal protection`
- `feat(p2-m1): register graph_views_router in main.py`
