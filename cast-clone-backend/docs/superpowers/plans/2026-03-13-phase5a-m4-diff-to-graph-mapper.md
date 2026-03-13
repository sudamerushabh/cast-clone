# Phase 5a M4 — Diff-to-Graph Mapper

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Map PR file diffs to architecture graph nodes by querying Neo4j for nodes whose file path and line range overlap with changed hunks.

**Architecture:** A single module `diff_mapper.py` that takes a `PRDiff` and returns a list of `ChangedNode` objects. Uses Neo4j Cypher queries with path + line range matching. Adds path indexes for efficient lookups. Handles edge cases: renames (search old_path), deletes (flag all nodes in file), adds (mark as new/unmapped), non-graph files (config, tests, README).

**Tech Stack:** Neo4j async driver (via existing `Neo4jGraphStore`), Cypher queries.

**Depends On:** M1 (data models — `PRDiff`, `FileDiff`, `DiffHunk`, `ChangedNode` are defined in M1's `pr_analysis/models.py`).

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── pr_analysis/
│       └── diff_mapper.py          # CREATE — diff-to-graph mapping
└── tests/
    └── unit/
        └── test_diff_mapper.py     # CREATE
```

---

### Task 1: Create Neo4j Path Indexes

**Files:**
- Modify: `app/services/neo4j.py`
- Test: `tests/unit/test_diff_mapper.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_diff_mapper.py
"""Tests for diff-to-graph mapping."""
import pytest
from unittest.mock import AsyncMock

from app.pr_analysis.diff_mapper import DiffMapper
from app.pr_analysis.models import DiffHunk, FileDiff, PRDiff


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.query = AsyncMock(return_value=[])
    return store


class TestDiffMapperBasic:
    @pytest.mark.asyncio
    async def test_empty_diff_returns_empty(self, mock_store):
        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(files=[], total_additions=0, total_deletions=0, total_files_changed=0)
        result = await mapper.map_diff_to_nodes(diff)
        assert result.changed_nodes == []
        assert result.new_files == []
        assert result.non_graph_files == []

    @pytest.mark.asyncio
    async def test_modified_file_queries_neo4j(self, mock_store):
        mock_store.query.return_value = [
            {
                "fqn": "com.app.OrderService.createOrder",
                "name": "createOrder",
                "type": "Function",
                "path": "src/main/java/com/app/OrderService.java",
                "line": 45,
                "end_line": 80,
                "language": "java",
                "change_type": "modified",
            }
        ]

        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[
                FileDiff(
                    path="src/main/java/com/app/OrderService.java",
                    status="modified",
                    old_path=None,
                    additions=5,
                    deletions=2,
                    hunks=[DiffHunk(old_start=50, old_count=5, new_start=50, new_count=8)],
                )
            ],
            total_additions=5,
            total_deletions=2,
            total_files_changed=1,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert len(result.changed_nodes) == 1
        assert result.changed_nodes[0].fqn == "com.app.OrderService.createOrder"

    @pytest.mark.asyncio
    async def test_added_file_marked_as_new(self, mock_store):
        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[
                FileDiff(
                    path="src/main/java/com/app/NewService.java",
                    status="added",
                    old_path=None,
                    additions=50,
                    deletions=0,
                    hunks=[DiffHunk(old_start=0, old_count=0, new_start=1, new_count=50)],
                )
            ],
            total_additions=50,
            total_deletions=0,
            total_files_changed=1,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert "src/main/java/com/app/NewService.java" in result.new_files

    @pytest.mark.asyncio
    async def test_deleted_file_queries_all_nodes(self, mock_store):
        """Deleted files should query for ALL nodes in that file."""
        mock_store.query.return_value = [
            {
                "fqn": "com.app.OldService",
                "name": "OldService",
                "type": "Class",
                "path": "src/main/java/com/app/OldService.java",
                "line": 1,
                "end_line": 100,
                "language": "java",
                "change_type": "deleted",
            }
        ]

        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[
                FileDiff(
                    path="src/main/java/com/app/OldService.java",
                    status="deleted",
                    old_path=None,
                    additions=0,
                    deletions=50,
                    hunks=[],
                )
            ],
            total_additions=0,
            total_deletions=50,
            total_files_changed=1,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert len(result.changed_nodes) == 1
        assert result.changed_nodes[0].change_type == "deleted"

    @pytest.mark.asyncio
    async def test_renamed_file_uses_old_path(self, mock_store):
        """Renamed files query using old_path (graph reflects pre-PR state)."""
        mock_store.query.return_value = [
            {
                "fqn": "com.app.Service",
                "name": "Service",
                "type": "Class",
                "path": "old/Service.java",
                "line": 1,
                "end_line": 50,
                "language": "java",
                "change_type": "renamed",
            }
        ]

        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[
                FileDiff(
                    path="new/Service.java",
                    status="renamed",
                    old_path="old/Service.java",
                    additions=0,
                    deletions=0,
                    hunks=[],
                )
            ],
            total_additions=0,
            total_deletions=0,
            total_files_changed=1,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert len(result.changed_nodes) == 1

    @pytest.mark.asyncio
    async def test_non_graph_file_detected(self, mock_store):
        """Files with no matching graph nodes are reported as non_graph_files."""
        mock_store.query.return_value = []  # No nodes found

        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[
                FileDiff(
                    path="README.md",
                    status="modified",
                    old_path=None,
                    additions=5,
                    deletions=2,
                    hunks=[DiffHunk(old_start=1, old_count=5, new_start=1, new_count=8)],
                )
            ],
            total_additions=5,
            total_deletions=2,
            total_files_changed=1,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert "README.md" in result.non_graph_files
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_diff_mapper.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the diff mapper**

```python
# app/pr_analysis/diff_mapper.py
"""Map PR diffs to architecture graph nodes via Neo4j queries."""
from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from app.pr_analysis.models import ChangedNode, FileDiff, PRDiff
from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)


@dataclass
class DiffMapResult:
    """Result of mapping a PR diff to graph nodes."""
    changed_nodes: list[ChangedNode] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    non_graph_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)


class DiffMapper:
    """Maps file-level diffs to architecture graph nodes."""

    def __init__(self, store: GraphStore, app_name: str) -> None:
        self._store = store
        self._app_name = app_name

    async def map_diff_to_nodes(self, diff: PRDiff) -> DiffMapResult:
        """Map all changed files in a PR diff to graph nodes."""
        result = DiffMapResult()

        for file_diff in diff.files:
            if file_diff.status == "added":
                result.new_files.append(file_diff.path)
                continue

            if file_diff.status == "deleted":
                nodes = await self._query_all_nodes_in_file(file_diff.path)
                if nodes:
                    for n in nodes:
                        n.change_type = "deleted"
                    result.changed_nodes.extend(nodes)
                result.deleted_files.append(file_diff.path)
                continue

            # For renamed files, query using old_path
            query_path = file_diff.old_path if file_diff.status == "renamed" else file_diff.path

            if file_diff.hunks:
                nodes = await self._query_nodes_by_hunks(query_path, file_diff)
            else:
                # Renamed with no hunks — query all nodes in old file
                nodes = await self._query_all_nodes_in_file(query_path)

            if nodes:
                for n in nodes:
                    n.change_type = file_diff.status
                result.changed_nodes.extend(nodes)
            else:
                result.non_graph_files.append(file_diff.path)

        return result

    async def _query_nodes_by_hunks(
        self, path: str, file_diff: FileDiff
    ) -> list[ChangedNode]:
        """Query Neo4j for nodes whose line range overlaps with changed hunks."""
        hunk_params = [
            {"new_start": h.new_start, "new_end": h.new_end}
            for h in file_diff.hunks
        ]

        cypher = (
            "UNWIND $hunks AS hunk "
            "MATCH (n) "
            "WHERE n.app_name = $appName "
            "  AND n.path = $path "
            "  AND n.line IS NOT NULL "
            "  AND n.end_line IS NOT NULL "
            "  AND n.line <= hunk.new_end "
            "  AND n.end_line >= hunk.new_start "
            "  AND labels(n)[0] IN ['Class', 'Function', 'Interface', 'Field', 'APIEndpoint'] "
            "RETURN DISTINCT n.fqn AS fqn, n.name AS name, "
            "  labels(n)[0] AS type, n.path AS path, "
            "  n.line AS line, n.end_line AS end_line, "
            "  n.language AS language"
        )

        records = await self._store.query(
            cypher,
            {"appName": self._app_name, "path": path, "hunks": hunk_params},
        )

        return [
            ChangedNode(
                fqn=r["fqn"],
                name=r["name"],
                type=r["type"],
                path=r["path"],
                line=r["line"],
                end_line=r["end_line"],
                language=r.get("language"),
                change_type=file_diff.status,
            )
            for r in records
        ]

    async def _query_all_nodes_in_file(self, path: str) -> list[ChangedNode]:
        """Query all graph nodes in a file (for deletes and renames)."""
        cypher = (
            "MATCH (n) "
            "WHERE n.app_name = $appName "
            "  AND n.path = $path "
            "  AND labels(n)[0] IN ['Class', 'Function', 'Interface', 'Field', 'APIEndpoint'] "
            "RETURN n.fqn AS fqn, n.name AS name, "
            "  labels(n)[0] AS type, n.path AS path, "
            "  n.line AS line, n.end_line AS end_line, "
            "  n.language AS language"
        )

        records = await self._store.query(
            cypher, {"appName": self._app_name, "path": path}
        )

        return [
            ChangedNode(
                fqn=r["fqn"],
                name=r["name"],
                type=r["type"],
                path=r["path"],
                line=r.get("line", 0),
                end_line=r.get("end_line", 0),
                language=r.get("language"),
                change_type="",
            )
            for r in records
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_diff_mapper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/diff_mapper.py tests/unit/test_diff_mapper.py
git commit -m "feat(phase5a): implement diff-to-graph node mapper"
```

---

### Task 2: Add Path Indexes to Neo4j

**Files:**
- Modify: `app/services/neo4j.py`

- [ ] **Step 1: Add path indexes to ensure_indexes**

In `app/services/neo4j.py`, add to the `index_statements` list inside `ensure_indexes()`:

```python
            # Phase 5a: path indexes for diff-to-graph mapping
            "CREATE INDEX IF NOT EXISTS FOR (n:Class) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Function) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Interface) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Field) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:APIEndpoint) ON (n.path)",
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend
git add app/services/neo4j.py
git commit -m "feat(phase5a): add Neo4j path indexes for efficient diff mapping"
```

---

## Success Criteria

- [ ] `DiffMapper.map_diff_to_nodes()` correctly maps modified files to overlapping graph nodes
- [ ] Added files are reported as `new_files`
- [ ] Deleted files query all nodes in the file and mark as `change_type="deleted"`
- [ ] Renamed files use `old_path` for graph lookup
- [ ] Files with no matching nodes are reported as `non_graph_files`
- [ ] Neo4j path indexes added for Class, Function, Interface, Field, APIEndpoint
- [ ] All tests pass: `uv run pytest tests/unit/test_diff_mapper.py -v`
