# M2: API Layer & Orchestrator Shell Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the REST API endpoints (Project CRUD, Analysis trigger/status, Graph queries), WebSocket progress reporting, and the orchestrator shell (skeleton pipeline with 9 no-op stages) that M3+ stages will plug into.

**Architecture:** Pydantic v2 request/response models at API boundaries. FastAPI `APIRouter` with `/api/v1` prefix. `BackgroundTasks` for async pipeline execution. WebSocket for real-time progress. Neo4j Cypher queries for graph endpoints. All database access via `Depends(get_session)` and `Neo4jGraphStore`. The orchestrator is a single async function calling 9 stage stubs sequentially with per-stage error handling.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy[asyncio]+asyncpg, neo4j async driver, redis[hiredis], pytest+pytest-asyncio, httpx (test client)

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── main.py                          # MODIFY — register new routers
│   ├── api/
│   │   ├── __init__.py                  # MODIFY — re-export routers
│   │   ├── projects.py                  # CREATE — Project CRUD endpoints
│   │   ├── analysis.py                  # CREATE — Analysis trigger + status
│   │   ├── graph.py                     # CREATE — Graph query endpoints
│   │   └── websocket.py                 # CREATE — WebSocket progress endpoint
│   ├── schemas/
│   │   ├── __init__.py                  # CREATE — re-export schemas
│   │   ├── projects.py                  # CREATE — Project request/response Pydantic models
│   │   ├── analysis.py                  # CREATE — Analysis request/response models
│   │   └── graph.py                     # CREATE — Graph query response models
│   └── orchestrator/
│       ├── __init__.py                  # CREATE
│       ├── pipeline.py                  # CREATE — run_analysis_pipeline() skeleton
│       ├── subprocess_utils.py          # CREATE — run_subprocess(), run_in_process_pool()
│       └── progress.py                  # CREATE — WebSocketProgressReporter
├── tests/
│   ├── conftest.py                      # MODIFY — add async client fixture, DB session fixture
│   └── unit/
│       ├── test_projects_api.py         # CREATE
│       ├── test_analysis_api.py         # CREATE
│       ├── test_graph_api.py            # CREATE
│       ├── test_websocket.py            # CREATE
│       ├── test_pipeline.py             # CREATE
│       ├── test_subprocess_utils.py     # CREATE
│       └── test_progress.py            # CREATE
```

---

## Task 1: Pydantic Schemas — Projects

**Files:**
- Create: `app/schemas/__init__.py`
- Create: `app/schemas/projects.py`
- Test: `tests/unit/test_schemas_projects.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_schemas_projects.py
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.projects import (
    ProjectCreate,
    ProjectResponse,
    ProjectListResponse,
)


class TestProjectCreate:
    def test_valid_create(self):
        data = ProjectCreate(name="my-project", source_path="/opt/code/my-project")
        assert data.name == "my-project"
        assert data.source_path == "/opt/code/my-project"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ProjectCreate(source_path="/opt/code/my-project")

    def test_source_path_required(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="my-project")

    def test_name_min_length(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="", source_path="/opt/code")

    def test_name_max_length(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="x" * 256, source_path="/opt/code")

    def test_source_path_min_length(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="proj", source_path="")


class TestProjectResponse:
    def test_from_dict(self):
        now = datetime.now()
        resp = ProjectResponse(
            id="abc-123",
            name="my-project",
            source_path="/opt/code/my-project",
            status="created",
            created_at=now,
            updated_at=now,
        )
        assert resp.id == "abc-123"
        assert resp.status == "created"

    def test_serialization(self):
        now = datetime.now()
        resp = ProjectResponse(
            id="abc-123",
            name="my-project",
            source_path="/opt/code/my-project",
            status="created",
            created_at=now,
            updated_at=now,
        )
        data = resp.model_dump()
        assert "id" in data
        assert "name" in data


class TestProjectListResponse:
    def test_empty_list(self):
        resp = ProjectListResponse(projects=[], total=0)
        assert resp.projects == []
        assert resp.total == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_schemas_projects.py -v`
Expected: FAIL (ImportError — module doesn't exist)

- [ ] **Step 3: Implement schemas**

```python
# app/schemas/__init__.py
"""Pydantic v2 request/response schemas for API boundaries."""
```

```python
# app/schemas/projects.py
"""Pydantic v2 schemas for Project CRUD API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    """POST /api/v1/projects request body."""

    name: str = Field(..., min_length=1, max_length=255)
    source_path: str = Field(..., min_length=1, max_length=1024)


class ProjectResponse(BaseModel):
    """Single project response."""

    id: str
    name: str
    source_path: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """GET /api/v1/projects response."""

    projects: list[ProjectResponse]
    total: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_schemas_projects.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/schemas/ tests/unit/test_schemas_projects.py && git commit -m "feat(schemas): add Pydantic v2 project request/response models"
```

---

## Task 2: Pydantic Schemas — Analysis

**Files:**
- Create: `app/schemas/analysis.py`
- Test: `tests/unit/test_schemas_analysis.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_schemas_analysis.py
from datetime import datetime

from app.schemas.analysis import (
    AnalysisTriggerResponse,
    AnalysisStatusResponse,
    AnalysisRunResponse,
)


class TestAnalysisTriggerResponse:
    def test_create(self):
        resp = AnalysisTriggerResponse(
            project_id="proj-1",
            run_id="run-1",
            status="analyzing",
            message="Analysis started",
        )
        assert resp.project_id == "proj-1"
        assert resp.status == "analyzing"


class TestAnalysisStatusResponse:
    def test_create(self):
        resp = AnalysisStatusResponse(
            project_id="proj-1",
            status="analyzed",
            current_stage=None,
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        assert resp.status == "analyzed"

    def test_analyzing_with_stage(self):
        resp = AnalysisStatusResponse(
            project_id="proj-1",
            status="analyzing",
            current_stage="parsing",
            started_at=datetime.now(),
        )
        assert resp.current_stage == "parsing"
        assert resp.completed_at is None


class TestAnalysisRunResponse:
    def test_create(self):
        resp = AnalysisRunResponse(
            id="run-1",
            project_id="proj-1",
            status="completed",
            stage=None,
            started_at=datetime.now(),
            completed_at=datetime.now(),
            node_count=100,
            edge_count=200,
            error_message=None,
        )
        assert resp.node_count == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_schemas_analysis.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement schemas**

```python
# app/schemas/analysis.py
"""Pydantic v2 schemas for Analysis API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AnalysisTriggerResponse(BaseModel):
    """POST /api/v1/projects/{id}/analyze response."""

    project_id: str
    run_id: str
    status: str
    message: str


class AnalysisStatusResponse(BaseModel):
    """GET /api/v1/projects/{id}/status response."""

    project_id: str
    status: str
    current_stage: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AnalysisRunResponse(BaseModel):
    """Single analysis run detail."""

    id: str
    project_id: str
    status: str
    stage: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    node_count: int | None = None
    edge_count: int | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_schemas_analysis.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/schemas/analysis.py tests/unit/test_schemas_analysis.py && git commit -m "feat(schemas): add Pydantic v2 analysis request/response models"
```

---

## Task 3: Pydantic Schemas — Graph Queries

**Files:**
- Create: `app/schemas/graph.py`
- Test: `tests/unit/test_schemas_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_schemas_graph.py
from app.schemas.graph import (
    GraphNodeResponse,
    GraphEdgeResponse,
    GraphNodeListResponse,
    GraphEdgeListResponse,
    NodeWithNeighborsResponse,
    GraphSearchResponse,
    GraphSearchHit,
)


class TestGraphNodeResponse:
    def test_create(self):
        node = GraphNodeResponse(
            fqn="com.example.UserService",
            name="UserService",
            kind="CLASS",
            language="java",
            path="src/main/java/com/example/UserService.java",
            line=10,
            end_line=50,
            properties={"annotations": ["Service"]},
        )
        assert node.fqn == "com.example.UserService"
        assert node.kind == "CLASS"

    def test_optional_fields(self):
        node = GraphNodeResponse(
            fqn="x",
            name="x",
            kind="CLASS",
        )
        assert node.language is None
        assert node.path is None
        assert node.properties == {}


class TestGraphEdgeResponse:
    def test_create(self):
        edge = GraphEdgeResponse(
            source_fqn="a.B.method1",
            target_fqn="a.C.method2",
            kind="CALLS",
            confidence="HIGH",
            evidence="tree-sitter",
        )
        assert edge.kind == "CALLS"


class TestGraphNodeListResponse:
    def test_pagination(self):
        resp = GraphNodeListResponse(
            nodes=[],
            total=100,
            offset=0,
            limit=50,
        )
        assert resp.total == 100
        assert resp.limit == 50


class TestGraphEdgeListResponse:
    def test_pagination(self):
        resp = GraphEdgeListResponse(
            edges=[],
            total=200,
            offset=0,
            limit=50,
        )
        assert resp.total == 200


class TestNodeWithNeighborsResponse:
    def test_create(self):
        node = GraphNodeResponse(fqn="a", name="a", kind="CLASS")
        resp = NodeWithNeighborsResponse(
            node=node,
            incoming_edges=[],
            outgoing_edges=[],
            neighbors=[],
        )
        assert resp.node.fqn == "a"


class TestGraphSearchResponse:
    def test_create(self):
        hit = GraphSearchHit(
            fqn="com.example.UserService",
            name="UserService",
            kind="CLASS",
            language="java",
            score=0.95,
        )
        resp = GraphSearchResponse(
            query="UserService",
            hits=[hit],
            total=1,
        )
        assert resp.hits[0].score == 0.95
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_schemas_graph.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement schemas**

```python
# app/schemas/graph.py
"""Pydantic v2 schemas for Graph Query API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphNodeResponse(BaseModel):
    """Single graph node in API responses."""

    fqn: str
    name: str
    kind: str
    language: str | None = None
    path: str | None = None
    line: int | None = None
    end_line: int | None = None
    loc: int | None = None
    complexity: int | None = None
    visibility: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeResponse(BaseModel):
    """Single graph edge in API responses."""

    source_fqn: str
    target_fqn: str
    kind: str
    confidence: str = "HIGH"
    evidence: str = "tree-sitter"
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphNodeListResponse(BaseModel):
    """Paginated list of graph nodes."""

    nodes: list[GraphNodeResponse]
    total: int
    offset: int
    limit: int


class GraphEdgeListResponse(BaseModel):
    """Paginated list of graph edges."""

    edges: list[GraphEdgeResponse]
    total: int
    offset: int
    limit: int


class NodeWithNeighborsResponse(BaseModel):
    """Single node with its incoming/outgoing edges and neighbor nodes."""

    node: GraphNodeResponse
    incoming_edges: list[GraphEdgeResponse]
    outgoing_edges: list[GraphEdgeResponse]
    neighbors: list[GraphNodeResponse]


class GraphSearchHit(BaseModel):
    """A single search result."""

    fqn: str
    name: str
    kind: str
    language: str | None = None
    score: float = 0.0


class GraphSearchResponse(BaseModel):
    """Full-text search response."""

    query: str
    hits: list[GraphSearchHit]
    total: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_schemas_graph.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/schemas/graph.py tests/unit/test_schemas_graph.py && git commit -m "feat(schemas): add Pydantic v2 graph query response models"
```

---

## Task 4: WebSocket Progress Reporter

**Files:**
- Create: `app/orchestrator/__init__.py`
- Create: `app/orchestrator/progress.py`
- Test: `tests/unit/test_progress.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_progress.py
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestrator.progress import (
    WebSocketProgressReporter,
    active_connections,
)


@pytest.fixture(autouse=True)
def clear_connections():
    """Ensure clean state for each test."""
    active_connections.clear()
    yield
    active_connections.clear()


class TestWebSocketProgressReporter:
    @pytest.mark.asyncio
    async def test_emit_sends_json_to_connected_ws(self):
        ws = AsyncMock()
        active_connections["proj-1"] = [ws]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit("discovery", "running", "Scanning filesystem...")

        ws.send_json.assert_called_once()
        event = ws.send_json.call_args[0][0]
        assert event["stage"] == "discovery"
        assert event["status"] == "running"
        assert event["message"] == "Scanning filesystem..."
        assert "timestamp" in event

    @pytest.mark.asyncio
    async def test_emit_with_details(self):
        ws = AsyncMock()
        active_connections["proj-1"] = [ws]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit("parsing", "complete", details={"nodes": 100, "edges": 200})

        event = ws.send_json.call_args[0][0]
        assert event["details"]["nodes"] == 100
        assert event["details"]["edges"] == 200

    @pytest.mark.asyncio
    async def test_emit_no_connections(self):
        reporter = WebSocketProgressReporter("proj-no-ws")
        # Should not raise
        await reporter.emit("discovery", "running", "test")

    @pytest.mark.asyncio
    async def test_emit_handles_broken_connection(self):
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = RuntimeError("connection closed")
        active_connections["proj-1"] = [ws_bad, ws_good]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit("discovery", "running", "test")

        # Good connection still receives the message
        ws_good.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_complete(self):
        ws = AsyncMock()
        active_connections["proj-1"] = [ws]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit_complete({"total_nodes": 500, "total_edges": 1000})

        event = ws.send_json.call_args[0][0]
        assert event["stage"] == "complete"
        assert event["status"] == "complete"
        assert event["details"]["total_nodes"] == 500

    @pytest.mark.asyncio
    async def test_emit_error(self):
        ws = AsyncMock()
        active_connections["proj-1"] = [ws]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit_error("Stage 1 failed: path not found")

        event = ws.send_json.call_args[0][0]
        assert event["stage"] == "error"
        assert event["status"] == "failed"
        assert "path not found" in event["message"]

    @pytest.mark.asyncio
    async def test_emit_to_multiple_connections(self):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        active_connections["proj-1"] = [ws1, ws2]
        reporter = WebSocketProgressReporter("proj-1")

        await reporter.emit("discovery", "complete")

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_progress.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement progress reporter**

```python
# app/orchestrator/__init__.py
"""Analysis orchestrator — pipeline coordination and progress reporting."""
```

```python
# app/orchestrator/progress.py
"""WebSocket-based progress reporting for analysis pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

# Active WebSocket connections per project_id
active_connections: dict[str, list[WebSocket]] = {}


class WebSocketProgressReporter:
    """Emits progress events to all WebSocket clients watching a project."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    async def emit(
        self,
        stage: str,
        status: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Send a progress event to all connected clients for this project."""
        event = {
            "stage": stage,
            "status": status,
            "message": message,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for ws in active_connections.get(self.project_id, []):
            try:
                await ws.send_json(event)
            except Exception:
                pass  # Connection may have closed

    async def emit_complete(self, report: dict[str, Any]) -> None:
        """Emit pipeline completion event."""
        await self.emit("complete", "complete", details=report)

    async def emit_error(self, error: str) -> None:
        """Emit pipeline error event."""
        await self.emit("error", "failed", message=error)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_progress.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/orchestrator/ tests/unit/test_progress.py && git commit -m "feat(orchestrator): add WebSocketProgressReporter for real-time pipeline events"
```

---

## Task 5: Subprocess Utilities

**Files:**
- Create: `app/orchestrator/subprocess_utils.py`
- Test: `tests/unit/test_subprocess_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_subprocess_utils.py
import asyncio
import sys

import pytest

from app.orchestrator.subprocess_utils import (
    SubprocessResult,
    run_subprocess,
    run_in_process_pool,
)


class TestSubprocessResult:
    def test_create(self):
        result = SubprocessResult(returncode=0, stdout="hello", stderr="")
        assert result.returncode == 0
        assert result.stdout == "hello"

    def test_success_property(self):
        assert SubprocessResult(returncode=0, stdout="", stderr="").success is True
        assert SubprocessResult(returncode=1, stdout="", stderr="").success is False


class TestRunSubprocess:
    @pytest.mark.asyncio
    async def test_echo_command(self, tmp_path):
        result = await run_subprocess(
            command=["echo", "hello world"],
            cwd=tmp_path,
            timeout=10,
        )
        assert result.returncode == 0
        assert "hello world" in result.stdout

    @pytest.mark.asyncio
    async def test_failing_command(self, tmp_path):
        result = await run_subprocess(
            command=["false"],
            cwd=tmp_path,
            timeout=10,
        )
        assert result.returncode != 0

    @pytest.mark.asyncio
    async def test_timeout(self, tmp_path):
        with pytest.raises(TimeoutError, match="timed out"):
            await run_subprocess(
                command=["sleep", "30"],
                cwd=tmp_path,
                timeout=1,
            )

    @pytest.mark.asyncio
    async def test_capture_stderr(self, tmp_path):
        result = await run_subprocess(
            command=[sys.executable, "-c", "import sys; sys.stderr.write('error msg')"],
            cwd=tmp_path,
            timeout=10,
        )
        assert "error msg" in result.stderr

    @pytest.mark.asyncio
    async def test_custom_env(self, tmp_path):
        result = await run_subprocess(
            command=[sys.executable, "-c", "import os; print(os.environ.get('TEST_VAR', ''))"],
            cwd=tmp_path,
            timeout=10,
            env={"TEST_VAR": "hello_from_env"},
        )
        assert "hello_from_env" in result.stdout


def _square(x: int) -> int:
    return x * x


class TestRunInProcessPool:
    @pytest.mark.asyncio
    async def test_single_function(self):
        result = await run_in_process_pool(_square, 5)
        assert result == 25

    @pytest.mark.asyncio
    async def test_max_workers_respected(self):
        result = await run_in_process_pool(_square, 7, max_workers=2)
        assert result == 49
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_subprocess_utils.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement subprocess utilities**

```python
# app/orchestrator/subprocess_utils.py
"""Async subprocess execution with timeout and process pool utilities."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


@dataclass
class SubprocessResult:
    """Result of an async subprocess execution."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


async def run_subprocess(
    command: list[str],
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> SubprocessResult:
    """Run an external command asynchronously with timeout and capture output.

    Args:
        command: Command and arguments to execute.
        cwd: Working directory for the subprocess.
        timeout: Maximum execution time in seconds.
        env: Optional environment variable overrides (merged with os.environ).

    Returns:
        SubprocessResult with returncode, stdout, stderr.

    Raises:
        TimeoutError: If the command exceeds the timeout.
    """
    merged_env = {**os.environ, **(env or {})}

    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=merged_env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return SubprocessResult(
            returncode=proc.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(
            f"Command timed out after {timeout}s: {' '.join(command)}"
        )


async def run_in_process_pool(
    func: Callable[..., T],
    *args: Any,
    max_workers: int | None = None,
) -> T:
    """Run a CPU-bound function in a process pool.

    Args:
        func: Picklable function to execute.
        *args: Positional arguments for the function.
        max_workers: Max pool workers (default: os.cpu_count()).

    Returns:
        The function's return value.
    """
    loop = asyncio.get_event_loop()
    with ProcessPoolExecutor(max_workers=max_workers or os.cpu_count()) as pool:
        result = await loop.run_in_executor(pool, func, *args)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_subprocess_utils.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/orchestrator/subprocess_utils.py tests/unit/test_subprocess_utils.py && git commit -m "feat(orchestrator): add async subprocess runner and process pool utility"
```

---

## Task 6: Orchestrator Pipeline Shell

**Files:**
- Create: `app/orchestrator/pipeline.py`
- Test: `tests/unit/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pipeline.py
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestrator.pipeline import (
    run_analysis_pipeline,
    PIPELINE_STAGES,
)


class TestPipelineStages:
    def test_stage_order(self):
        """Pipeline stages must run in the documented order."""
        expected = [
            "discovery",
            "dependencies",
            "parsing",
            "scip",
            "lsp_fallback",
            "plugins",
            "linking",
            "enrichment",
            "writing",
            "transactions",
        ]
        assert [s.name for s in PIPELINE_STAGES] == expected

    def test_critical_stages(self):
        """Only discovery and writing are critical (fatal on failure)."""
        critical = [s.name for s in PIPELINE_STAGES if s.critical]
        assert critical == ["discovery", "writing"]


class TestRunAnalysisPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_runs_all_stages(self):
        """With no-op stage functions, the pipeline should complete successfully."""
        mock_session_factory = AsyncMock()
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        # Mock the Project query result
        mock_project = MagicMock()
        mock_project.id = "proj-1"
        mock_project.name = "test-project"
        mock_project.source_path = "/tmp/test"
        mock_project.status = "created"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch("app.orchestrator.pipeline.get_session_factory") as mock_get_sf:
            mock_get_sf.return_value = mock_session_factory
            with patch("app.orchestrator.pipeline.WebSocketProgressReporter") as mock_ws:
                mock_reporter = AsyncMock()
                mock_ws.return_value = mock_reporter

                await run_analysis_pipeline("proj-1")

                # Pipeline should emit progress for each stage
                assert mock_reporter.emit.call_count >= len(PIPELINE_STAGES)
                # Pipeline should mark complete
                mock_reporter.emit_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_updates_status_to_analyzing(self):
        """Pipeline should set project status to 'analyzing' at start."""
        mock_session_factory = AsyncMock()
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_project = MagicMock()
        mock_project.id = "proj-1"
        mock_project.name = "test-project"
        mock_project.source_path = "/tmp/test"
        mock_project.status = "created"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch("app.orchestrator.pipeline.get_session_factory") as mock_get_sf:
            mock_get_sf.return_value = mock_session_factory
            with patch("app.orchestrator.pipeline.WebSocketProgressReporter"):
                await run_analysis_pipeline("proj-1")

        # Project status should be set to "analyzing" then "analyzed"
        assert mock_project.status == "analyzed"

    @pytest.mark.asyncio
    async def test_pipeline_handles_project_not_found(self):
        """Pipeline should raise if project not found."""
        mock_session_factory = AsyncMock()
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.orchestrator.pipeline.get_session_factory") as mock_get_sf:
            mock_get_sf.return_value = mock_session_factory
            with pytest.raises(ValueError, match="not found"):
                await run_analysis_pipeline("nonexistent")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pipeline.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement pipeline shell**

```python
# app/orchestrator/pipeline.py
"""Analysis pipeline orchestrator — runs 9 stages sequentially.

Each stage function is a no-op stub in M2. Real implementations are added
in M3 (tree-sitter), M4 (SCIP), M5 (plugins), etc.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Coroutine, Any

from sqlalchemy import select

from app.models.context import AnalysisContext
from app.models.db import Project, AnalysisRun
from app.orchestrator.progress import WebSocketProgressReporter
from app.services.postgres import get_session_factory

logger = logging.getLogger(__name__)


@dataclass
class PipelineStage:
    """Definition of a single pipeline stage."""

    name: str
    description: str
    critical: bool = False  # If True, failure aborts the pipeline


# ── Stage stub functions (no-op in M2, replaced in later milestones) ──────


async def _stage_discovery(context: AnalysisContext) -> None:
    """Stage 1: Discover project files, languages, frameworks."""
    pass


async def _stage_dependencies(context: AnalysisContext) -> None:
    """Stage 2: Resolve build dependencies."""
    pass


async def _stage_parsing(context: AnalysisContext) -> None:
    """Stage 3: Parse source files with tree-sitter."""
    pass


async def _stage_scip(context: AnalysisContext) -> None:
    """Stage 4: Run SCIP indexers for type resolution."""
    pass


async def _stage_lsp_fallback(context: AnalysisContext) -> None:
    """Stage 4b: LSP fallback for languages where SCIP failed."""
    pass


async def _stage_plugins(context: AnalysisContext) -> None:
    """Stage 5: Run framework-specific plugins."""
    pass


async def _stage_linking(context: AnalysisContext) -> None:
    """Stage 6: Link cross-technology dependencies."""
    pass


async def _stage_enrichment(context: AnalysisContext) -> None:
    """Stage 7: Compute metrics and run community detection."""
    pass


async def _stage_writing(context: AnalysisContext) -> None:
    """Stage 8: Write graph to Neo4j."""
    pass


async def _stage_transactions(context: AnalysisContext) -> None:
    """Stage 9: Discover transaction flows."""
    pass


# ── Stage registry ────────────────────────────────────────────────────────


@dataclass
class _StageEntry:
    """Internal: stage definition paired with its function."""

    name: str
    description: str
    critical: bool
    func: Callable[[AnalysisContext], Coroutine[Any, Any, None]]


PIPELINE_STAGES: list[PipelineStage] = [
    PipelineStage("discovery", "Scanning filesystem...", critical=True),
    PipelineStage("dependencies", "Resolving dependencies..."),
    PipelineStage("parsing", "Parsing source files..."),
    PipelineStage("scip", "Running SCIP indexers..."),
    PipelineStage("lsp_fallback", "LSP fallback for unsupported languages..."),
    PipelineStage("plugins", "Running framework plugins..."),
    PipelineStage("linking", "Linking cross-technology dependencies..."),
    PipelineStage("enrichment", "Computing metrics and communities..."),
    PipelineStage("writing", "Writing to database...", critical=True),
    PipelineStage("transactions", "Discovering transaction flows..."),
]

_STAGE_FUNCS: dict[str, Callable[[AnalysisContext], Coroutine[Any, Any, None]]] = {
    "discovery": _stage_discovery,
    "dependencies": _stage_dependencies,
    "parsing": _stage_parsing,
    "scip": _stage_scip,
    "lsp_fallback": _stage_lsp_fallback,
    "plugins": _stage_plugins,
    "linking": _stage_linking,
    "enrichment": _stage_enrichment,
    "writing": _stage_writing,
    "transactions": _stage_transactions,
}


def get_session_factory():
    """Get the async session factory. Separated for testability."""
    from app.services.postgres import _session_factory

    assert _session_factory is not None, "PostgreSQL not initialized"
    return _session_factory


# ── Main pipeline function ────────────────────────────────────────────────


async def run_analysis_pipeline(project_id: str) -> None:
    """Run the full 9-stage analysis pipeline.

    Called as a FastAPI BackgroundTask. Loads the project from DB,
    runs each stage sequentially, updates status, and reports progress
    via WebSocket.

    Args:
        project_id: UUID of the project to analyze.

    Raises:
        ValueError: If the project is not found in the database.
    """
    session_factory = get_session_factory()
    ws = WebSocketProgressReporter(project_id)
    pipeline_start = time.monotonic()

    async with session_factory() as session:
        # Load project
        result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        # Create analysis run record
        run = AnalysisRun(
            project_id=project_id,
            status="running",
        )
        session.add(run)

        # Update project status
        project.status = "analyzing"
        await session.commit()

        # Initialize context
        context = AnalysisContext(project_id=project_id)

        # Run each stage
        for stage_def in PIPELINE_STAGES:
            stage_func = _STAGE_FUNCS[stage_def.name]
            stage_start = time.monotonic()

            try:
                await ws.emit(stage_def.name, "running", stage_def.description)
                logger.info(
                    "pipeline.stage.start",
                    extra={"project_id": project_id, "stage": stage_def.name},
                )

                await stage_func(context)

                elapsed = time.monotonic() - stage_start
                await ws.emit(
                    stage_def.name,
                    "complete",
                    details={"duration_seconds": round(elapsed, 2)},
                )
                logger.info(
                    "pipeline.stage.complete",
                    extra={
                        "project_id": project_id,
                        "stage": stage_def.name,
                        "duration": round(elapsed, 2),
                    },
                )

                # Track current stage in run record
                run.stage = stage_def.name

            except Exception as e:
                elapsed = time.monotonic() - stage_start
                logger.error(
                    "pipeline.stage.failed",
                    extra={
                        "project_id": project_id,
                        "stage": stage_def.name,
                        "error": str(e),
                        "duration": round(elapsed, 2),
                    },
                )
                await ws.emit(
                    stage_def.name,
                    "failed",
                    message=str(e),
                    details={"duration_seconds": round(elapsed, 2)},
                )

                if stage_def.critical:
                    # Critical stage failure — abort pipeline
                    project.status = "failed"
                    run.status = "failed"
                    run.error_message = f"Critical stage '{stage_def.name}' failed: {e}"
                    await session.commit()
                    await ws.emit_error(
                        f"Pipeline aborted: critical stage '{stage_def.name}' failed: {e}"
                    )
                    raise
                else:
                    # Non-critical — warn and continue
                    context.warnings.append(
                        f"Stage '{stage_def.name}' failed: {e}"
                    )

        # Pipeline complete
        total_elapsed = time.monotonic() - pipeline_start
        project.status = "analyzed"
        run.status = "completed"
        run.node_count = context.graph.node_count
        run.edge_count = context.graph.edge_count
        await session.commit()

        report = {
            "total_nodes": context.graph.node_count,
            "total_edges": context.graph.edge_count,
            "warnings": context.warnings,
            "duration_seconds": round(total_elapsed, 2),
        }
        await ws.emit_complete(report)

        logger.info(
            "pipeline.complete",
            extra={
                "project_id": project_id,
                "duration": round(total_elapsed, 2),
                "nodes": context.graph.node_count,
                "edges": context.graph.edge_count,
                "warnings": len(context.warnings),
            },
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pipeline.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/orchestrator/pipeline.py tests/unit/test_pipeline.py && git commit -m "feat(orchestrator): add 9-stage analysis pipeline shell with per-stage error handling"
```

---

## Task 7: Test Infrastructure — Async Client Fixture

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/unit/conftest.py`

- [ ] **Step 1: Update conftest.py with shared fixtures for API testing**

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

```python
# tests/unit/conftest.py
"""Unit test fixtures — no external services required."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.db import Project


@pytest_asyncio.fixture
async def mock_session():
    """Mock AsyncSession for DB-dependent tests."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest_asyncio.fixture
async def app_client(mock_session):
    """Async test client with mocked database session.

    Patches get_session to yield the mock session, so API endpoint tests
    don't need a real PostgreSQL connection.
    """
    from app.main import create_app
    from app.services.postgres import get_session

    app = create_app()

    async def override_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


def make_project(
    id: str | None = None,
    name: str = "test-project",
    source_path: str = "/opt/code/test",
    status: str = "created",
) -> MagicMock:
    """Factory for mock Project ORM objects."""
    project = MagicMock(spec=Project)
    project.id = id or str(uuid4())
    project.name = name
    project.source_path = source_path
    project.status = status
    project.created_at = datetime.now(timezone.utc)
    project.updated_at = datetime.now(timezone.utc)
    return project
```

- [ ] **Step 2: Add httpx dev dependency**

Run: `cd cast-clone-backend && uv add --dev httpx`

- [ ] **Step 3: Verify import works**

Run: `cd cast-clone-backend && uv run python -c "from httpx import AsyncClient; print('OK')"`

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend && git add tests/conftest.py tests/unit/conftest.py pyproject.toml uv.lock && git commit -m "feat(tests): add async HTTP client fixture and mock session factory"
```

---

## Task 8: Project CRUD API

**Files:**
- Create: `app/api/projects.py`
- Test: `tests/unit/test_projects_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_projects_api.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.unit.conftest import make_project


class TestCreateProject:
    @pytest.mark.asyncio
    async def test_create_project_201(self, app_client, mock_session):
        # Mock session.refresh to populate the project with an ID
        async def mock_refresh(obj):
            obj.id = str(uuid4())
            obj.status = "created"
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)

        mock_session.refresh = mock_refresh

        response = await app_client.post(
            "/api/v1/projects",
            json={"name": "my-project", "source_path": "/opt/code/my-project"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "my-project"
        assert data["source_path"] == "/opt/code/my-project"
        assert data["status"] == "created"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_project_missing_name_422(self, app_client):
        response = await app_client.post(
            "/api/v1/projects",
            json={"source_path": "/opt/code"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_project_empty_name_422(self, app_client):
        response = await app_client.post(
            "/api/v1/projects",
            json={"name": "", "source_path": "/opt/code"},
        )
        assert response.status_code == 422


class TestListProjects:
    @pytest.mark.asyncio
    async def test_list_projects_200(self, app_client, mock_session):
        project = make_project()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [project]

        # Count query
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_result]
        )

        response = await app_client.get("/api/v1/projects")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["projects"]) == 1

    @pytest.mark.asyncio
    async def test_list_projects_empty(self, app_client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0

        mock_session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_result]
        )

        response = await app_client.get("/api/v1/projects")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["projects"] == []


class TestGetProject:
    @pytest.mark.asyncio
    async def test_get_project_200(self, app_client, mock_session):
        project = make_project(id="proj-123")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.get("/api/v1/projects/proj-123")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "proj-123"

    @pytest.mark.asyncio
    async def test_get_project_404(self, app_client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.get("/api/v1/projects/nonexistent")
        assert response.status_code == 404


class TestDeleteProject:
    @pytest.mark.asyncio
    async def test_delete_project_204(self, app_client, mock_session):
        project = make_project(id="proj-123")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.delete("/api/v1/projects/proj-123")
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_project_404(self, app_client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.delete("/api/v1/projects/nonexistent")
        assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_projects_api.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement Project CRUD API**

```python
# app/api/projects.py
"""Project CRUD API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Project
from app.schemas.projects import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
)
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    """Create a new project."""
    project = Project(
        name=body.name,
        source_path=body.source_path,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    return ProjectResponse(
        id=project.id,
        name=project.name,
        source_path=project.source_path,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    offset: int = 0,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> ProjectListResponse:
    """List all projects with pagination."""
    # Count total
    count_result = await session.execute(select(func.count(Project.id)))
    total = count_result.scalar_one()

    # Fetch page
    result = await session.execute(
        select(Project)
        .order_by(Project.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    projects = result.scalars().all()

    return ProjectListResponse(
        projects=[
            ProjectResponse(
                id=p.id,
                name=p.name,
                source_path=p.source_path,
                status=p.status,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
            for p in projects
        ],
        total=total,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    """Get a single project by ID."""
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    return ProjectResponse(
        id=project.id,
        name=project.name,
        source_path=project.source_path,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a project by ID."""
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    await session.delete(project)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_projects_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/api/projects.py tests/unit/test_projects_api.py && git commit -m "feat(api): add Project CRUD endpoints (POST/GET/LIST/DELETE)"
```

---

## Task 9: Analysis API

**Files:**
- Create: `app/api/analysis.py`
- Test: `tests/unit/test_analysis_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_analysis_api.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.conftest import make_project


class TestTriggerAnalysis:
    @pytest.mark.asyncio
    async def test_trigger_202(self, app_client, mock_session):
        project = make_project(id="proj-1", status="created")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def mock_refresh(obj):
            obj.id = "run-1"
            obj.status = "running"

        mock_session.refresh = mock_refresh

        response = await app_client.post("/api/v1/projects/proj-1/analyze")
        assert response.status_code == 202
        data = response.json()
        assert data["project_id"] == "proj-1"
        assert data["status"] == "analyzing"

    @pytest.mark.asyncio
    async def test_trigger_404_project_not_found(self, app_client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.post("/api/v1/projects/nonexistent/analyze")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_trigger_409_already_analyzing(self, app_client, mock_session):
        project = make_project(id="proj-1", status="analyzing")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.post("/api/v1/projects/proj-1/analyze")
        assert response.status_code == 409


class TestAnalysisStatus:
    @pytest.mark.asyncio
    async def test_status_200(self, app_client, mock_session):
        project = make_project(id="proj-1", status="analyzed")

        # First call returns project, second returns latest run
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_run = MagicMock()
        mock_run.id = "run-1"
        mock_run.status = "completed"
        mock_run.stage = None
        mock_run.started_at = datetime.now(timezone.utc)
        mock_run.completed_at = datetime.now(timezone.utc)

        mock_run_result = MagicMock()
        mock_run_result.scalar_one_or_none.return_value = mock_run

        mock_session.execute = AsyncMock(
            side_effect=[mock_project_result, mock_run_result]
        )

        response = await app_client.get("/api/v1/projects/proj-1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == "proj-1"
        assert data["status"] == "analyzed"

    @pytest.mark.asyncio
    async def test_status_404(self, app_client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        response = await app_client.get("/api/v1/projects/nonexistent/status")
        assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_analysis_api.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement Analysis API**

```python
# app/api/analysis.py
"""Analysis trigger and status API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AnalysisRun, Project
from app.orchestrator.pipeline import run_analysis_pipeline
from app.schemas.analysis import (
    AnalysisStatusResponse,
    AnalysisTriggerResponse,
)
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/projects", tags=["analysis"])


@router.post(
    "/{project_id}/analyze",
    response_model=AnalysisTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_analysis(
    project_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> AnalysisTriggerResponse:
    """Trigger analysis for a project. Runs as a background task."""
    # Load project
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # Prevent duplicate analysis
    if project.status == "analyzing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project {project_id} is already being analyzed",
        )

    # Create analysis run
    run = AnalysisRun(project_id=project_id, status="pending")
    session.add(run)

    # Update project status
    project.status = "analyzing"
    await session.commit()
    await session.refresh(run)

    # Launch pipeline as background task
    background_tasks.add_task(run_analysis_pipeline, project_id)

    return AnalysisTriggerResponse(
        project_id=project_id,
        run_id=run.id,
        status="analyzing",
        message="Analysis started",
    )


@router.get(
    "/{project_id}/status",
    response_model=AnalysisStatusResponse,
)
async def get_analysis_status(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> AnalysisStatusResponse:
    """Get the current analysis status for a project."""
    # Load project
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # Get latest analysis run
    run_result = await session.execute(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == project_id)
        .order_by(AnalysisRun.id.desc())
        .limit(1)
    )
    latest_run = run_result.scalar_one_or_none()

    return AnalysisStatusResponse(
        project_id=project_id,
        status=project.status,
        current_stage=latest_run.stage if latest_run else None,
        started_at=latest_run.started_at if latest_run else None,
        completed_at=latest_run.completed_at if latest_run else None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_analysis_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/api/analysis.py tests/unit/test_analysis_api.py && git commit -m "feat(api): add analysis trigger (POST 202) and status (GET) endpoints"
```

---

## Task 10: Graph Query API

**Files:**
- Create: `app/api/graph.py`
- Test: `tests/unit/test_graph_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_graph_api.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestListNodes:
    @pytest.mark.asyncio
    async def test_list_nodes_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "n": {
                    "fqn": "com.example.UserService",
                    "name": "UserService",
                    "kind": "CLASS",
                    "language": "java",
                    "path": "src/UserService.java",
                    "line": 10,
                    "end_line": 50,
                }
            }
        ]
        mock_store.query_single.return_value = {"count": 1}

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get("/api/v1/graphs/proj-1/nodes")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["nodes"][0]["fqn"] == "com.example.UserService"

    @pytest.mark.asyncio
    async def test_list_nodes_filter_by_kind(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []
        mock_store.query_single.return_value = {"count": 0}

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get(
                "/api/v1/graphs/proj-1/nodes?kind=CLASS"
            )

        assert response.status_code == 200
        # Verify the query was called with kind filter
        call_args = mock_store.query.call_args
        assert "CLASS" in str(call_args)

    @pytest.mark.asyncio
    async def test_list_nodes_pagination(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = []
        mock_store.query_single.return_value = {"count": 0}

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get(
                "/api/v1/graphs/proj-1/nodes?offset=10&limit=20"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["offset"] == 10
        assert data["limit"] == 20


class TestListEdges:
    @pytest.mark.asyncio
    async def test_list_edges_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "source_fqn": "a.B",
                "target_fqn": "a.C",
                "kind": "CALLS",
                "confidence": "HIGH",
                "evidence": "tree-sitter",
            }
        ]
        mock_store.query_single.return_value = {"count": 1}

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get("/api/v1/graphs/proj-1/edges")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1


class TestGetNode:
    @pytest.mark.asyncio
    async def test_get_node_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query_single.return_value = {
            "n": {
                "fqn": "com.example.UserService",
                "name": "UserService",
                "kind": "CLASS",
                "language": "java",
            }
        }
        mock_store.query.side_effect = [
            # incoming edges
            [{"source_fqn": "a.A", "target_fqn": "com.example.UserService", "kind": "CALLS", "confidence": "HIGH", "evidence": "tree-sitter"}],
            # outgoing edges
            [],
            # neighbors
            [{"n": {"fqn": "a.A", "name": "A", "kind": "CLASS"}}],
        ]

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get(
                "/api/v1/graphs/proj-1/node/com.example.UserService"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["node"]["fqn"] == "com.example.UserService"

    @pytest.mark.asyncio
    async def test_get_node_404(self, app_client):
        mock_store = AsyncMock()
        mock_store.query_single.return_value = None

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get(
                "/api/v1/graphs/proj-1/node/nonexistent"
            )

        assert response.status_code == 404


class TestSearchNodes:
    @pytest.mark.asyncio
    async def test_search_200(self, app_client):
        mock_store = AsyncMock()
        mock_store.query.return_value = [
            {
                "fqn": "com.example.UserService",
                "name": "UserService",
                "kind": "CLASS",
                "language": "java",
                "score": 0.95,
            }
        ]

        with patch("app.api.graph.get_graph_store", return_value=mock_store):
            response = await app_client.get(
                "/api/v1/graphs/proj-1/search?q=UserService"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "UserService"
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_search_empty_query_422(self, app_client):
        response = await app_client.get("/api/v1/graphs/proj-1/search?q=")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_search_missing_query_422(self, app_client):
        response = await app_client.get("/api/v1/graphs/proj-1/search")
        assert response.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_graph_api.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement Graph Query API**

```python
# app/api/graph.py
"""Graph query API endpoints — all backed by Neo4j Cypher queries."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.graph import (
    GraphEdgeListResponse,
    GraphEdgeResponse,
    GraphNodeListResponse,
    GraphNodeResponse,
    GraphSearchHit,
    GraphSearchResponse,
    NodeWithNeighborsResponse,
)
from app.services.neo4j import Neo4jGraphStore, get_driver

router = APIRouter(prefix="/api/v1/graphs", tags=["graph"])


def get_graph_store() -> Neo4jGraphStore:
    """Get a Neo4jGraphStore instance."""
    return Neo4jGraphStore(get_driver())


def _record_to_node(record: dict[str, Any]) -> GraphNodeResponse:
    """Convert a Neo4j record to a GraphNodeResponse."""
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


@router.get("/{project_id}/nodes", response_model=GraphNodeListResponse)
async def list_nodes(
    project_id: str,
    kind: str | None = None,
    language: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> GraphNodeListResponse:
    """List graph nodes for a project, with optional filtering by kind/language."""
    store = get_graph_store()

    # Build WHERE clause
    where_parts = ["n.app_name = $app_name"]
    params: dict[str, Any] = {"app_name": project_id}

    if kind:
        where_parts.append("n.kind = $kind")
        params["kind"] = kind
    if language:
        where_parts.append("n.language = $language")
        params["language"] = language

    where_clause = " AND ".join(where_parts)

    # Count query
    count_cypher = f"MATCH (n) WHERE {where_clause} RETURN count(n) AS count"
    count_result = await store.query_single(count_cypher, params)
    total = count_result["count"] if count_result else 0

    # Data query
    data_cypher = (
        f"MATCH (n) WHERE {where_clause} "
        f"RETURN n ORDER BY n.fqn SKIP $offset LIMIT $limit"
    )
    params["offset"] = offset
    params["limit"] = limit
    records = await store.query(data_cypher, params)

    return GraphNodeListResponse(
        nodes=[_record_to_node(r) for r in records],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{project_id}/edges", response_model=GraphEdgeListResponse)
async def list_edges(
    project_id: str,
    kind: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> GraphEdgeListResponse:
    """List graph edges for a project, with optional filtering by kind."""
    store = get_graph_store()

    where_parts = ["a.app_name = $app_name"]
    params: dict[str, Any] = {"app_name": project_id}

    rel_filter = ""
    if kind:
        rel_filter = f":{kind}"

    # Count query
    count_cypher = (
        f"MATCH (a)-[r{rel_filter}]->(b) "
        f"WHERE {' AND '.join(where_parts)} "
        f"RETURN count(r) AS count"
    )
    count_result = await store.query_single(count_cypher, params)
    total = count_result["count"] if count_result else 0

    # Data query
    data_cypher = (
        f"MATCH (a)-[r{rel_filter}]->(b) "
        f"WHERE {' AND '.join(where_parts)} "
        f"RETURN a.fqn AS source_fqn, b.fqn AS target_fqn, "
        f"type(r) AS kind, r.confidence AS confidence, r.evidence AS evidence "
        f"SKIP $offset LIMIT $limit"
    )
    params["offset"] = offset
    params["limit"] = limit
    records = await store.query(data_cypher, params)

    return GraphEdgeListResponse(
        edges=[_record_to_edge(r) for r in records],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{project_id}/node/{fqn:path}", response_model=NodeWithNeighborsResponse)
async def get_node(
    project_id: str,
    fqn: str,
) -> NodeWithNeighborsResponse:
    """Get a single node by FQN with its neighbors and edges."""
    store = get_graph_store()

    # Find node
    node_result = await store.query_single(
        "MATCH (n {fqn: $fqn, app_name: $app_name}) RETURN n",
        {"fqn": fqn, "app_name": project_id},
    )
    if node_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node {fqn} not found in project {project_id}",
        )

    node = _record_to_node(node_result)

    # Incoming edges
    incoming_records = await store.query(
        "MATCH (a)-[r]->(n {fqn: $fqn, app_name: $app_name}) "
        "RETURN a.fqn AS source_fqn, n.fqn AS target_fqn, "
        "type(r) AS kind, r.confidence AS confidence, r.evidence AS evidence",
        {"fqn": fqn, "app_name": project_id},
    )
    incoming_edges = [_record_to_edge(r) for r in incoming_records]

    # Outgoing edges
    outgoing_records = await store.query(
        "MATCH (n {fqn: $fqn, app_name: $app_name})-[r]->(b) "
        "RETURN n.fqn AS source_fqn, b.fqn AS target_fqn, "
        "type(r) AS kind, r.confidence AS confidence, r.evidence AS evidence",
        {"fqn": fqn, "app_name": project_id},
    )
    outgoing_edges = [_record_to_edge(r) for r in outgoing_records]

    # Neighbor nodes
    neighbor_records = await store.query(
        "MATCH (n {fqn: $fqn, app_name: $app_name})--(neighbor) "
        "RETURN DISTINCT neighbor AS n",
        {"fqn": fqn, "app_name": project_id},
    )
    neighbors = [_record_to_node(r) for r in neighbor_records]

    return NodeWithNeighborsResponse(
        node=node,
        incoming_edges=incoming_edges,
        outgoing_edges=outgoing_edges,
        neighbors=neighbors,
    )


@router.get("/{project_id}/neighbors/{fqn:path}", response_model=GraphNodeListResponse)
async def get_neighbors(
    project_id: str,
    fqn: str,
    depth: int = 1,
    limit: int = 100,
) -> GraphNodeListResponse:
    """Get neighbor subgraph around a node."""
    store = get_graph_store()

    cypher = (
        "MATCH (n {fqn: $fqn, app_name: $app_name})-[*1..$depth]-(neighbor) "
        "RETURN DISTINCT neighbor AS n LIMIT $limit"
    )
    records = await store.query(
        cypher, {"fqn": fqn, "app_name": project_id, "depth": depth, "limit": limit}
    )

    return GraphNodeListResponse(
        nodes=[_record_to_node(r) for r in records],
        total=len(records),
        offset=0,
        limit=limit,
    )


@router.get("/{project_id}/search", response_model=GraphSearchResponse)
async def search_nodes(
    project_id: str,
    q: str = Query(..., min_length=1),
) -> GraphSearchResponse:
    """Full-text search across graph nodes."""
    store = get_graph_store()

    # Use CONTAINS for basic search; full-text index search in production
    cypher = (
        "MATCH (n) WHERE n.app_name = $app_name "
        "AND (toLower(n.name) CONTAINS toLower($query) "
        "OR toLower(n.fqn) CONTAINS toLower($query)) "
        "RETURN n.fqn AS fqn, n.name AS name, n.kind AS kind, "
        "n.language AS language, 1.0 AS score "
        "LIMIT 50"
    )
    records = await store.query(
        cypher, {"app_name": project_id, "query": q}
    )

    hits = [
        GraphSearchHit(
            fqn=r["fqn"],
            name=r["name"],
            kind=r["kind"],
            language=r.get("language"),
            score=r.get("score", 0.0),
        )
        for r in records
    ]

    return GraphSearchResponse(
        query=q,
        hits=hits,
        total=len(hits),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_graph_api.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/api/graph.py tests/unit/test_graph_api.py && git commit -m "feat(api): add graph query endpoints (nodes, edges, node detail, neighbors, search)"
```

---

## Task 11: WebSocket Endpoint

**Files:**
- Create: `app/api/websocket.py`
- Test: `tests/unit/test_websocket.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_websocket.py
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.orchestrator.progress import active_connections


@pytest.fixture(autouse=True)
def clear_ws_connections():
    active_connections.clear()
    yield
    active_connections.clear()


class TestWebSocketEndpoint:
    def test_websocket_connects_and_registers(self):
        """WebSocket connection should be registered in active_connections."""
        from app.main import create_app

        app = create_app()
        client = TestClient(app)

        with client.websocket_connect("/api/v1/projects/proj-1/progress") as ws:
            assert "proj-1" in active_connections
            assert len(active_connections["proj-1"]) == 1

        # After disconnect, connection should be removed
        assert len(active_connections.get("proj-1", [])) == 0

    def test_websocket_multiple_connections(self):
        """Multiple WebSocket clients can connect to the same project."""
        from app.main import create_app

        app = create_app()
        client = TestClient(app)

        with client.websocket_connect("/api/v1/projects/proj-1/progress") as ws1:
            with client.websocket_connect("/api/v1/projects/proj-1/progress") as ws2:
                assert len(active_connections["proj-1"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_websocket.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement WebSocket endpoint**

```python
# app/api/websocket.py
"""WebSocket endpoint for real-time analysis progress."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.orchestrator.progress import active_connections

router = APIRouter(tags=["websocket"])


@router.websocket("/api/v1/projects/{project_id}/progress")
async def analysis_progress(websocket: WebSocket, project_id: str) -> None:
    """WebSocket endpoint for streaming analysis progress events.

    Clients connect here before triggering analysis. The pipeline's
    WebSocketProgressReporter emits events to all connected clients.
    """
    await websocket.accept()
    active_connections.setdefault(project_id, []).append(websocket)

    try:
        while True:
            # Keep connection alive — client can send pings or messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connections = active_connections.get(project_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections and project_id in active_connections:
            del active_connections[project_id]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_websocket.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/api/websocket.py tests/unit/test_websocket.py && git commit -m "feat(api): add WebSocket endpoint for analysis progress streaming"
```

---

## Task 12: Register Routers in main.py

**Files:**
- Modify: `app/main.py`
- Modify: `app/api/__init__.py`
- Test: `tests/unit/test_router_registration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_router_registration.py
import pytest


class TestRouterRegistration:
    def test_all_routes_registered(self):
        """All API routes from M2 should be registered in the app."""
        from app.main import create_app

        app = create_app()
        routes = [route.path for route in app.routes]

        # Project CRUD
        assert "/api/v1/projects" in routes
        assert "/api/v1/projects/{project_id}" in routes

        # Analysis
        assert "/api/v1/projects/{project_id}/analyze" in routes
        assert "/api/v1/projects/{project_id}/status" in routes

        # Graph queries
        assert "/api/v1/graphs/{project_id}/nodes" in routes
        assert "/api/v1/graphs/{project_id}/edges" in routes
        assert "/api/v1/graphs/{project_id}/node/{fqn:path}" in routes
        assert "/api/v1/graphs/{project_id}/neighbors/{fqn:path}" in routes
        assert "/api/v1/graphs/{project_id}/search" in routes

        # WebSocket
        assert "/api/v1/projects/{project_id}/progress" in routes

        # Health (existing)
        assert "/health" in routes

    def test_health_endpoint_still_works(self):
        """Existing health endpoint must not break."""
        from app.main import create_app

        app = create_app()
        routes = [route.path for route in app.routes]
        assert "/health" in routes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_router_registration.py -v`
Expected: FAIL (routes not registered yet)

- [ ] **Step 3: Update main.py and api/__init__.py**

```python
# app/api/__init__.py
"""API router registry."""

from app.api.analysis import router as analysis_router
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.websocket import router as websocket_router

__all__ = [
    "analysis_router",
    "graph_router",
    "health_router",
    "projects_router",
    "websocket_router",
]
```

Update `app/main.py` — replace `from app.api.health import router as health_router` and `application.include_router(health_router)` with:

```python
# app/main.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analysis_router,
    graph_router,
    health_router,
    projects_router,
    websocket_router,
)
from app.config import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    print("Starting up codelens-backend...")
    yield
    print("Shutting down codelens-backend...")


def create_app() -> FastAPI:
    settings = Settings()

    application = FastAPI(
        title="CodeLens Backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    application.include_router(health_router)
    application.include_router(projects_router)
    application.include_router(analysis_router)
    application.include_router(graph_router)
    application.include_router(websocket_router)

    return application


app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_router_registration.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/main.py app/api/__init__.py tests/unit/test_router_registration.py && git commit -m "feat(app): register all M2 API routers (projects, analysis, graph, websocket)"
```

---

## Task 13: Update schemas __init__.py

**Files:**
- Modify: `app/schemas/__init__.py`

- [ ] **Step 1: Add re-exports**

```python
# app/schemas/__init__.py
"""Pydantic v2 request/response schemas for API boundaries."""

from app.schemas.analysis import (
    AnalysisRunResponse,
    AnalysisStatusResponse,
    AnalysisTriggerResponse,
)
from app.schemas.graph import (
    GraphEdgeListResponse,
    GraphEdgeResponse,
    GraphNodeListResponse,
    GraphNodeResponse,
    GraphSearchHit,
    GraphSearchResponse,
    NodeWithNeighborsResponse,
)
from app.schemas.projects import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
)

__all__ = [
    "AnalysisRunResponse",
    "AnalysisStatusResponse",
    "AnalysisTriggerResponse",
    "GraphEdgeListResponse",
    "GraphEdgeResponse",
    "GraphNodeListResponse",
    "GraphNodeResponse",
    "GraphSearchHit",
    "GraphSearchResponse",
    "NodeWithNeighborsResponse",
    "ProjectCreate",
    "ProjectListResponse",
    "ProjectResponse",
]
```

- [ ] **Step 2: Verify imports work**

Run: `cd cast-clone-backend && uv run python -c "from app.schemas import ProjectCreate, AnalysisTriggerResponse, GraphNodeResponse; print('OK')"`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add app/schemas/__init__.py && git commit -m "feat(schemas): add public re-exports from schemas package"
```

---

## Final M2 Verification

- [ ] **Run full test suite**: `cd cast-clone-backend && uv run pytest tests/unit/ -v --tb=short`
- [ ] **Run linter**: `cd cast-clone-backend && uv run ruff check app/ tests/`
- [ ] **Verify all imports**: `cd cast-clone-backend && uv run python -c "from app.schemas import *; from app.orchestrator.pipeline import run_analysis_pipeline, PIPELINE_STAGES; from app.orchestrator.progress import WebSocketProgressReporter; from app.orchestrator.subprocess_utils import run_subprocess, run_in_process_pool; print('All M2 imports OK')"`
- [ ] **Verify route count**: `cd cast-clone-backend && uv run python -c "from app.main import app; print(f'{len([r for r in app.routes if hasattr(r, \"methods\")])} HTTP routes + WS registered')"`

---

## Summary of Deliverables

| Component | Endpoints / Functions | Status |
|-----------|----------------------|--------|
| Project CRUD | POST/GET/LIST/DELETE `/api/v1/projects` | Functional with PostgreSQL |
| Analysis API | POST `/analyze` (202), GET `/status` | Functional, launches background pipeline |
| Graph Query API | GET nodes, edges, node/{fqn}, neighbors/{fqn}, search | Functional with Neo4j |
| WebSocket | WS `/progress` | Functional, registers/deregisters clients |
| Orchestrator | `run_analysis_pipeline()` — 9 no-op stages | Shell ready for M3+ stage implementations |
| Subprocess Utils | `run_subprocess()`, `run_in_process_pool()` | Functional with timeout handling |
| Progress Reporter | `WebSocketProgressReporter` | Functional, broadcasts to connected clients |
| Pydantic Schemas | 12 request/response models | All with validation |

**M3 depends on:** The orchestrator's `_stage_discovery`, `_stage_parsing` stubs being replaced with real implementations. The pipeline shell, progress reporter, and all API endpoints from M2 are the foundation.
