# Phase 4 M5: Export & Activity Log — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CSV/JSON data export for graph data and impact analysis results, plus a simple activity log that tracks who did what and when.

**Architecture:** Export endpoints stream CSV/JSON directly from Neo4j queries using FastAPI StreamingResponse. Activity log is a PostgreSQL table with a lightweight logging service that other modules call (fire-and-forget). Activity feed is an admin-only API endpoint with a simple frontend page.

**Tech Stack:** FastAPI, StreamingResponse, Neo4j async, SQLAlchemy async, Pydantic v2, React, Tailwind CSS

**Dependencies:** Phase 4 M2 (auth frontend — AuthContext and `getAuthToken` needed for frontend export/activity UI)

**Spec Reference:** `cast-clone-backend/docs/04-PHASE-4-COLLABORATION.md` §5 (Data Export), §6 (Activity Log)

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── main.py                          # MODIFY — register export + activity routers
│   ├── models/
│   │   └── db.py                        # MODIFY — add ActivityLog model
│   ├── schemas/
│   │   ├── export.py                   # CREATE — export query param schemas
│   │   └── activity.py                 # CREATE — activity log schemas
│   ├── services/
│   │   └── activity.py                 # CREATE — activity logging service
│   └── api/
│       ├── export.py                   # CREATE — CSV/JSON export endpoints
│       └── activity.py                 # CREATE — activity feed endpoint
├── tests/
│   └── unit/
│       ├── test_activity_model.py      # CREATE
│       ├── test_activity_service.py    # CREATE
│       ├── test_export_api.py          # CREATE
│       └── test_activity_api.py        # CREATE

cast-clone-frontend/
├── lib/
│   ├── types.ts                        # MODIFY — add export + activity types
│   └── api.ts                          # MODIFY — add export + activity API functions
├── components/
│   ├── export/
│   │   └── ExportMenu.tsx             # CREATE — export dropdown with CSV/JSON options
│   └── activity/
│       └── ActivityFeed.tsx           # CREATE — activity log list
├── app/
│   └── settings/
│       └── activity/
│           └── page.tsx               # CREATE — admin activity feed page
```

---

## Task 1: Backend — ActivityLog Model

**Files:**
- Modify: `cast-clone-backend/app/models/db.py`
- Create: `cast-clone-backend/tests/unit/test_activity_model.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_activity_model.py`:

```python
"""Tests for ActivityLog SQLAlchemy model."""
from app.models.db import ActivityLog


def test_activity_log_fields():
    log = ActivityLog(
        user_id="user-1",
        action="user.login",
        resource_type="user",
        resource_id="user-1",
        details={"ip": "127.0.0.1"},
    )
    assert log.action == "user.login"
    assert log.resource_type == "user"
    assert log.details == {"ip": "127.0.0.1"}


def test_activity_log_tablename():
    assert ActivityLog.__tablename__ == "activity_log"


def test_activity_log_nullable_fields():
    log = ActivityLog(action="system.startup")
    assert log.user_id is None
    assert log.resource_type is None
    assert log.resource_id is None
    assert log.details is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_activity_model.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add ActivityLog model to db.py**

Add to `cast-clone-backend/app/models/db.py`, after the SavedView model:

```python
class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(36))
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User | None"] = relationship()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_activity_model.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/models/db.py cast-clone-backend/tests/unit/test_activity_model.py
git commit -m "feat(activity): add ActivityLog SQLAlchemy model"
```

---

## Task 2: Backend — Activity Logging Service

**Files:**
- Create: `cast-clone-backend/app/services/activity.py`
- Create: `cast-clone-backend/tests/unit/test_activity_service.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_activity_service.py`:

```python
"""Tests for activity logging service."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.activity import log_activity


class TestLogActivity:
    @pytest.mark.asyncio
    async def test_log_activity_adds_to_session(self):
        mock_session = AsyncMock()
        await log_activity(
            session=mock_session,
            action="user.login",
            user_id="user-1",
            resource_type="user",
            resource_id="user-1",
            details={"ip": "127.0.0.1"},
        )
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_activity_without_user(self):
        mock_session = AsyncMock()
        await log_activity(
            session=mock_session,
            action="system.startup",
        )
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_activity_swallows_errors(self):
        """Activity logging should never raise — it's fire-and-forget."""
        mock_session = AsyncMock()
        mock_session.commit.side_effect = Exception("DB error")
        # Should not raise
        await log_activity(
            session=mock_session,
            action="test.action",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_activity_service.py -v`
Expected: FAIL

- [ ] **Step 3: Implement activity service**

Create `cast-clone-backend/app/services/activity.py`:

```python
"""Activity logging service — fire-and-forget action recording."""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import ActivityLog

logger = structlog.get_logger()


async def log_activity(
    session: AsyncSession,
    action: str,
    user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Record an activity log entry.

    This function never raises — logging failures are swallowed and logged.
    It should be called after the primary operation has committed.
    """
    try:
        entry = ActivityLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        session.add(entry)
        await session.commit()
        logger.debug(
            "activity_logged",
            action=action,
            user_id=user_id,
            resource_type=resource_type,
        )
    except Exception:
        logger.warning(
            "activity_log_failed",
            action=action,
            exc_info=True,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_activity_service.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/services/activity.py cast-clone-backend/tests/unit/test_activity_service.py
git commit -m "feat(activity): add fire-and-forget activity logging service"
```

---

## Task 3: Backend — Activity and Export Schemas

**Files:**
- Create: `cast-clone-backend/app/schemas/activity.py`
- Create: `cast-clone-backend/app/schemas/export.py`

- [ ] **Step 1: Create activity schemas**

Create `cast-clone-backend/app/schemas/activity.py`:

```python
"""Pydantic schemas for activity log."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ActivityAuthor(BaseModel):
    """Embedded user info for activity log."""
    id: str
    username: str

    model_config = {"from_attributes": True}


class ActivityLogResponse(BaseModel):
    """Single activity log entry."""
    id: str
    user: ActivityAuthor | None
    action: str
    resource_type: str | None
    resource_id: str | None
    details: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Create export schemas**

Create `cast-clone-backend/app/schemas/export.py`:

```python
"""Pydantic schemas for export query parameters."""
from __future__ import annotations

from pydantic import BaseModel, Field


class NodeExportParams(BaseModel):
    """Query parameters for node CSV export."""
    types: str | None = Field(
        default=None,
        description="Comma-separated node kinds to include (e.g., 'Class,Function')",
    )
    fields: str = Field(
        default="fqn,name,kind,language,loc,complexity",
        description="Comma-separated fields to include in export",
    )


class EdgeExportParams(BaseModel):
    """Query parameters for edge CSV export."""
    types: str | None = Field(
        default=None,
        description="Comma-separated edge types to include (e.g., 'CALLS,DEPENDS_ON')",
    )
    fields: str = Field(
        default="source,target,type,weight",
        description="Comma-separated fields to include in export",
    )


class GraphExportParams(BaseModel):
    """Query parameters for JSON graph export."""
    level: str = Field(
        default="class",
        description="Export level: 'module' or 'class'",
    )
```

- [ ] **Step 3: Commit**

```bash
git add cast-clone-backend/app/schemas/activity.py cast-clone-backend/app/schemas/export.py
git commit -m "feat(export): add Pydantic schemas for activity log and export parameters"
```

---

## Task 4: Backend — Activity Feed API

**Files:**
- Create: `cast-clone-backend/app/api/activity.py`
- Create: `cast-clone-backend/tests/unit/test_activity_api.py`
- Modify: `cast-clone-backend/app/main.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_activity_api.py`:

```python
"""Tests for activity feed API endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestActivityEndpointsExist:
    @pytest.mark.asyncio
    async def test_activity_feed_requires_auth(self, client):
        resp = await client.get("/api/v1/activity")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_activity_feed_with_params(self, client):
        resp = await client.get(
            "/api/v1/activity",
            params={"limit": 20, "action": "user.login"},
        )
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_activity_api.py -v`
Expected: FAIL (404)

- [ ] **Step 3: Implement activity feed API**

Create `cast-clone-backend/app/api/activity.py`:

```python
"""Activity feed API endpoint — admin only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import require_admin
from app.models.db import ActivityLog, User
from app.schemas.activity import ActivityLogResponse
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


@router.get("", response_model=list[ActivityLogResponse])
async def get_activity_feed(
    limit: int = Query(default=50, ge=1, le=200),
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> list[ActivityLogResponse]:
    """Get recent activity log entries. Admin only.

    Filters by user_id and/or action type. Returns most recent first.
    """
    query = (
        select(ActivityLog)
        .options(joinedload(ActivityLog.user))
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )

    if user_id:
        query = query.where(ActivityLog.user_id == user_id)
    if action:
        query = query.where(ActivityLog.action == action)

    result = await session.execute(query)
    entries = result.scalars().unique().all()
    return [
        ActivityLogResponse.model_validate(e, from_attributes=True)
        for e in entries
    ]
```

- [ ] **Step 4: Register router via api/__init__.py and main.py**

Add to `cast-clone-backend/app/api/__init__.py`:

```python
from app.api.activity import router as activity_router
```

And add `"activity_router"` to the `__all__` list.

Then add `activity_router` to the import block in `cast-clone-backend/app/main.py` and register:

```python
app.include_router(activity_router)
```

- [ ] **Step 5: Run tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_activity_api.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add cast-clone-backend/app/api/activity.py cast-clone-backend/app/main.py cast-clone-backend/tests/unit/test_activity_api.py
git commit -m "feat(activity): add admin-only activity feed API endpoint"
```

---

## Task 5: Backend — CSV/JSON Export API

**Files:**
- Create: `cast-clone-backend/app/api/export.py`
- Create: `cast-clone-backend/tests/unit/test_export_api.py`
- Modify: `cast-clone-backend/app/main.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_export_api.py`:

```python
"""Tests for export API endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestExportEndpointsExist:
    @pytest.mark.asyncio
    async def test_export_nodes_csv_requires_auth(self, client):
        resp = await client.get("/api/v1/export/proj-1/nodes.csv")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_edges_csv_requires_auth(self, client):
        resp = await client.get("/api/v1/export/proj-1/edges.csv")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_graph_json_requires_auth(self, client):
        resp = await client.get("/api/v1/export/proj-1/graph.json")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_export_impact_csv_requires_auth(self, client):
        resp = await client.get(
            "/api/v1/export/proj-1/impact.csv",
            params={"node": "com.app.Foo"},
        )
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_export_api.py -v`
Expected: FAIL (404)

- [ ] **Step 3: Implement export API**

Create `cast-clone-backend/app/api/export.py`:

```python
"""CSV and JSON export API endpoints."""
from __future__ import annotations

import csv
import io
import json
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_current_user
from app.models.db import User
from app.services.neo4j import get_driver

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/export", tags=["export"])


async def _neo4j_query(app_name: str, cypher: str, params: dict | None = None) -> list[dict]:
    """Run a Cypher query and return results as dicts."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(cypher, **(params or {}))
        return [dict(record) for record in await result.data()]


def _csv_stream(rows: list[dict], fields: list[str]) -> AsyncGenerator[str, None]:
    """Generate CSV content from rows."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    yield output.getvalue()
    output.truncate(0)
    output.seek(0)

    for row in rows:
        writer.writerow(row)
        yield output.getvalue()
        output.truncate(0)
        output.seek(0)


@router.get("/{project_id}/nodes.csv")
async def export_nodes_csv(
    project_id: str,
    types: str | None = Query(default=None, description="Comma-separated node kinds"),
    fields: str = Query(default="fqn,name,kind,language,loc,complexity"),
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export node list as CSV."""
    field_list = [f.strip() for f in fields.split(",")]

    cypher = "MATCH (n) WHERE n.app_name = $app_name"
    params: dict = {"app_name": project_id}

    if types:
        type_list = [t.strip() for t in types.split(",")]
        cypher += " AND n.kind IN $kinds"
        params["kinds"] = type_list

    cypher += " RETURN " + ", ".join(f"n.{f} AS {f}" for f in field_list)

    rows = await _neo4j_query(project_id, cypher, params)

    return StreamingResponse(
        _csv_stream(rows, field_list),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}_nodes.csv"'
        },
    )


@router.get("/{project_id}/edges.csv")
async def export_edges_csv(
    project_id: str,
    types: str | None = Query(default=None, description="Comma-separated edge types"),
    fields: str = Query(default="source,target,type,weight"),
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export edge list as CSV."""
    field_list = [f.strip() for f in fields.split(",")]

    cypher = """
    MATCH (a)-[r]->(b)
    WHERE a.app_name = $app_name AND b.app_name = $app_name
    """
    params: dict = {"app_name": project_id}

    if types:
        type_list = [t.strip() for t in types.split(",")]
        cypher += " AND type(r) IN $types"
        params["types"] = type_list

    cypher += """
    RETURN a.fqn AS source, b.fqn AS target, type(r) AS type,
           COALESCE(r.weight, 1) AS weight
    """

    rows = await _neo4j_query(project_id, cypher, params)

    return StreamingResponse(
        _csv_stream(rows, field_list),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}_edges.csv"'
        },
    )


@router.get("/{project_id}/graph.json")
async def export_graph_json(
    project_id: str,
    level: str = Query(default="class", description="Export level: 'module' or 'class'"),
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export full graph data as JSON."""
    kind_filter = "n.kind IN ['Module']" if level == "module" else "true"

    nodes_cypher = f"""
    MATCH (n)
    WHERE n.app_name = $app_name AND {kind_filter}
    RETURN n {{
        .fqn, .name, .kind, .language, .loc, .complexity,
        .fan_in, .fan_out, .community_id, .layer, .file, .line
    }} AS node
    """

    edges_cypher = """
    MATCH (a)-[r]->(b)
    WHERE a.app_name = $app_name AND b.app_name = $app_name
    RETURN a.fqn AS source, b.fqn AS target, type(r) AS type,
           COALESCE(r.weight, 1) AS weight
    """

    params = {"app_name": project_id}
    nodes = await _neo4j_query(project_id, nodes_cypher, params)
    edges = await _neo4j_query(project_id, edges_cypher, params)

    graph_data = {
        "project_id": project_id,
        "level": level,
        "nodes": [n.get("node", n) for n in nodes],
        "edges": edges,
    }

    content = json.dumps(graph_data, indent=2, default=str)

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}_graph.json"'
        },
    )


@router.get("/{project_id}/impact.csv")
async def export_impact_csv(
    project_id: str,
    node: str = Query(..., description="FQN of the starting node"),
    direction: str = Query(default="both", description="downstream, upstream, or both"),
    max_depth: int = Query(default=5, ge=1, le=10),
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export impact analysis result as CSV."""
    if direction == "downstream":
        path_pattern = "(start)-[*1..{depth}]->(affected)"
    elif direction == "upstream":
        path_pattern = "(affected)-[*1..{depth}]->(start)"
    else:
        path_pattern = "(start)-[*1..{depth}]-(affected)"

    path_pattern = path_pattern.format(depth=max_depth)

    cypher = f"""
    MATCH (start {{fqn: $fqn, app_name: $app_name}})
    MATCH path = {path_pattern}
    WHERE affected.app_name = $app_name
    WITH DISTINCT affected, length(shortestPath((start)-[*]-(affected))) AS depth
    RETURN affected.fqn AS fqn, affected.name AS name,
           affected.kind AS type, depth,
           affected.file AS file, affected.line AS line
    ORDER BY depth, fqn
    """

    params = {"fqn": node, "app_name": project_id}
    rows = await _neo4j_query(project_id, cypher, params)

    fields = ["fqn", "name", "type", "depth", "file", "line"]
    return StreamingResponse(
        _csv_stream(rows, fields),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}_impact.csv"'
        },
    )
```

- [ ] **Step 4: Register router via api/__init__.py and main.py**

Add to `cast-clone-backend/app/api/__init__.py`:

```python
from app.api.export import router as export_router
```

And add `"export_router"` to the `__all__` list.

Then add `export_router` to the import block in `cast-clone-backend/app/main.py` and register:

```python
app.include_router(export_router)
```

- [ ] **Step 5: Run tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_export_api.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add cast-clone-backend/app/api/export.py cast-clone-backend/app/main.py cast-clone-backend/tests/unit/test_export_api.py
git commit -m "feat(export): add CSV and JSON export API endpoints with streaming responses"
```

---

## Task 6: Frontend — Export and Activity Types + API Client

**Files:**
- Modify: `cast-clone-frontend/lib/types.ts`
- Modify: `cast-clone-frontend/lib/api.ts`

- [ ] **Step 1: Add types**

Add to `cast-clone-frontend/lib/types.ts`:

```typescript
// ── Phase 4: Export ──

// Export endpoints return file downloads, no response types needed.

// ── Phase 4: Activity Log ──

export interface ActivityAuthor {
  id: string;
  username: string;
}

export interface ActivityLogEntry {
  id: string;
  user: ActivityAuthor | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}
```

- [ ] **Step 2: Add API functions**

Add to `cast-clone-frontend/lib/api.ts`:

```typescript
// ── Export ──

export function getExportUrl(
  projectId: string,
  type: "nodes.csv" | "edges.csv" | "graph.json" | "impact.csv",
  params?: Record<string, string>
): string {
  const searchParams = new URLSearchParams(params);
  const token = getAuthToken();
  if (token) searchParams.set("token", token);
  return `${BASE_URL}/api/v1/export/${projectId}/${type}?${searchParams}`;
}

export function downloadExport(
  projectId: string,
  type: "nodes.csv" | "edges.csv" | "graph.json" | "impact.csv",
  params?: Record<string, string>
) {
  const url = getExportUrl(projectId, type, params);
  // Use fetch with auth header for download
  const token = getAuthToken();
  fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
    .then((resp) => resp.blob())
    .then((blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${projectId}_${type}`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
}

// ── Activity Feed ──

export async function getActivityFeed(params?: {
  limit?: number;
  user_id?: string;
  action?: string;
}): Promise<ActivityLogEntry[]> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.user_id) searchParams.set("user_id", params.user_id);
  if (params?.action) searchParams.set("action", params.action);
  return apiFetch<ActivityLogEntry[]>(`/api/v1/activity?${searchParams}`);
}
```

- [ ] **Step 3: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/lib/types.ts cast-clone-frontend/lib/api.ts
git commit -m "feat(export): add export and activity types and API client functions"
```

---

## Task 7: Frontend — ExportMenu Component

**Files:**
- Create: `cast-clone-frontend/components/export/ExportMenu.tsx`
- Modify: `cast-clone-frontend/components/graph/GraphToolbar.tsx`

- [ ] **Step 1: Create ExportMenu**

Create `cast-clone-frontend/components/export/ExportMenu.tsx`:

```tsx
"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Download, FileSpreadsheet, FileJson, FileText } from "lucide-react";
import { downloadExport } from "@/lib/api";

interface ExportMenuProps {
  projectId: string;
  /** FQN of selected node for impact export, if any */
  selectedNodeFqn?: string;
}

export function ExportMenu({ projectId, selectedNodeFqn }: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  return (
    <div className="relative" ref={menuRef}>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(!open)}
        title="Export data"
        className="gap-1"
      >
        <Download className="h-4 w-4" />
        <span className="hidden sm:inline text-xs">Export</span>
      </Button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-52 rounded-md border bg-popover p-1 shadow-md">
          <button
            className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent"
            onClick={() => {
              downloadExport(projectId, "nodes.csv");
              setOpen(false);
            }}
          >
            <FileSpreadsheet className="h-4 w-4" />
            Nodes (CSV)
          </button>
          <button
            className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent"
            onClick={() => {
              downloadExport(projectId, "edges.csv");
              setOpen(false);
            }}
          >
            <FileSpreadsheet className="h-4 w-4" />
            Edges (CSV)
          </button>
          <button
            className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent"
            onClick={() => {
              downloadExport(projectId, "graph.json");
              setOpen(false);
            }}
          >
            <FileJson className="h-4 w-4" />
            Graph (JSON)
          </button>
          {selectedNodeFqn && (
            <>
              <div className="h-px bg-border my-1" />
              <button
                className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent"
                onClick={() => {
                  downloadExport(projectId, "impact.csv", {
                    node: selectedNodeFqn,
                  });
                  setOpen(false);
                }}
              >
                <FileText className="h-4 w-4" />
                Impact Analysis (CSV)
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add ExportMenu to GraphToolbar**

In `GraphToolbar.tsx`, import and render ExportMenu alongside the existing export buttons:

```tsx
import { ExportMenu } from "@/components/export/ExportMenu";

// In the toolbar, add:
<ExportMenu projectId={projectId} selectedNodeFqn={selectedNodeFqn} />
```

Add `projectId: string` and `selectedNodeFqn?: string` to the GraphToolbar props.

- [ ] **Step 3: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/components/export/ExportMenu.tsx cast-clone-frontend/components/graph/GraphToolbar.tsx
git commit -m "feat(export): add ExportMenu component with CSV and JSON download options"
```

---

## Task 8: Frontend — Activity Feed Page (Admin)

**Files:**
- Create: `cast-clone-frontend/components/activity/ActivityFeed.tsx`
- Create: `cast-clone-frontend/app/settings/activity/page.tsx`
- Modify: `cast-clone-frontend/components/layout/ContextPanel.tsx`

- [ ] **Step 1: Create ActivityFeed component**

Create `cast-clone-frontend/components/activity/ActivityFeed.tsx`:

```tsx
"use client";

import type { ActivityLogEntry } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

const ACTION_LABELS: Record<string, string> = {
  "user.login": "Signed in",
  "user.created": "User created",
  "project.created": "Project created",
  "project.deleted": "Project deleted",
  "analysis.started": "Analysis started",
  "analysis.completed": "Analysis completed",
  "analysis.failed": "Analysis failed",
  "annotation.created": "Annotation added",
  "annotation.deleted": "Annotation removed",
  "view.saved": "View saved",
  "view.deleted": "View deleted",
  "tag.added": "Tag added",
  "tag.removed": "Tag removed",
};

interface ActivityFeedProps {
  entries: ActivityLogEntry[];
  loading: boolean;
}

export function ActivityFeed({ entries, loading }: ActivityFeedProps) {
  if (loading) {
    return (
      <div className="text-center text-sm text-muted-foreground py-8">
        Loading activity...
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="text-center text-sm text-muted-foreground py-8">
        No activity recorded yet
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {entries.map((entry) => (
        <div
          key={entry.id}
          className="flex items-start gap-3 rounded-md border px-4 py-3"
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">
                {entry.user?.username ?? "System"}
              </span>
              <Badge variant="outline" className="text-xs">
                {ACTION_LABELS[entry.action] ?? entry.action}
              </Badge>
            </div>
            {entry.resource_type && (
              <p className="text-xs text-muted-foreground mt-0.5">
                {entry.resource_type}
                {entry.resource_id ? `: ${entry.resource_id.slice(0, 8)}...` : ""}
              </p>
            )}
          </div>
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            {new Date(entry.created_at).toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create activity page**

Create `cast-clone-frontend/app/settings/activity/page.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { getActivityFeed } from "@/lib/api";
import type { ActivityLogEntry } from "@/lib/types";
import { ActivityFeed } from "@/components/activity/ActivityFeed";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

export default function ActivityPage() {
  const { user } = useAuth();
  const [entries, setEntries] = useState<ActivityLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const loadActivity = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getActivityFeed({ limit: 100 });
      setEntries(data);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadActivity();
  }, [loadActivity]);

  if (!user || user.role !== "admin") {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Admin access required
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Activity Log</h1>
          <p className="text-sm text-muted-foreground">
            Recent actions across the platform
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={loadActivity}
          className="gap-1.5"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
      </div>

      <ActivityFeed entries={entries} loading={loading} />
    </div>
  );
}
```

- [ ] **Step 3: Add Activity link to Settings ContextPanel**

Modify `cast-clone-frontend/components/layout/ContextPanel.tsx` — in the Settings section nav, add an "Activity" link pointing to `/settings/activity`. This should appear only for admin users. Add it after the "Team" nav item.

- [ ] **Step 4: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add cast-clone-frontend/components/activity/ActivityFeed.tsx cast-clone-frontend/app/settings/activity/page.tsx cast-clone-frontend/components/layout/ContextPanel.tsx
git commit -m "feat(activity): add admin activity feed page with chronological action list"
```

---

## Task 9: Backend — Wire Activity Logging into Existing Endpoints

**Files:**
- Modify: `cast-clone-backend/app/api/auth.py`
- Modify: `cast-clone-backend/app/api/annotations.py`
- Modify: `cast-clone-backend/app/api/saved_views.py`

- [ ] **Step 1: Add activity logging to auth endpoints**

In `cast-clone-backend/app/api/auth.py`, import and call `log_activity` after successful login and setup:

```python
from app.services.activity import log_activity

# In login(), after session.commit():
await log_activity(session, "user.login", user_id=user.id, resource_type="user", resource_id=user.id)

# In initial_setup(), after session.commit():
await log_activity(session, "user.created", user_id=user.id, resource_type="user", resource_id=user.id)
```

- [ ] **Step 2: Add activity logging to annotations**

In `cast-clone-backend/app/api/annotations.py`:

```python
from app.services.activity import log_activity

# In create_annotation(), after session.commit():
await log_activity(session, "annotation.created", user_id=user.id, resource_type="annotation", resource_id=annotation.id)

# In delete_annotation(), after session.commit():
await log_activity(session, "annotation.deleted", user_id=user.id, resource_type="annotation", resource_id=annotation_id)
```

- [ ] **Step 3: Add activity logging to saved views**

In `cast-clone-backend/app/api/saved_views.py`:

```python
from app.services.activity import log_activity

# In save_view(), after session.commit():
await log_activity(session, "view.saved", user_id=user.id, resource_type="view", resource_id=view.id)

# In delete_view(), after session.commit():
await log_activity(session, "view.deleted", user_id=user.id, resource_type="view", resource_id=view_id)
```

- [ ] **Step 4: Run all tests to verify nothing broke**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/api/auth.py cast-clone-backend/app/api/annotations.py cast-clone-backend/app/api/saved_views.py
git commit -m "feat(activity): wire activity logging into auth, annotations, and saved views"
```

---

## Verification Checklist

- [ ] Backend: ActivityLog model in db.py
- [ ] Backend: `log_activity()` service — fire-and-forget, never raises
- [ ] Backend: `GET /api/v1/activity` returns activity entries (admin only, 401 without auth)
- [ ] Backend: `GET /api/v1/export/{project}/nodes.csv` streams CSV (401 without auth)
- [ ] Backend: `GET /api/v1/export/{project}/edges.csv` streams CSV
- [ ] Backend: `GET /api/v1/export/{project}/graph.json` streams JSON
- [ ] Backend: `GET /api/v1/export/{project}/impact.csv?node=...` streams CSV
- [ ] Backend: Activity logged for login, setup, annotation create/delete, view save/delete
- [ ] Frontend: ActivityLogEntry type in types.ts
- [ ] Frontend: `downloadExport()` triggers browser file download
- [ ] Frontend: ExportMenu component with CSV/JSON options in GraphToolbar
- [ ] Frontend: ActivityFeed component renders chronological action list
- [ ] Frontend: `/settings/activity` page shows activity feed (admin only)
- [ ] Frontend: Activity link in Settings ContextPanel nav
- [ ] All backend tests pass
- [ ] `npx tsc --noEmit` passes
- [ ] `ruff check` passes on all new backend files
