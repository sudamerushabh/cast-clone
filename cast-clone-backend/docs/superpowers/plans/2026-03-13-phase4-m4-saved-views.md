# Phase 4 M4: Saved Views — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users save the current graph state (view type, visible nodes, layout, zoom, filters) and share it with teammates via URL.

**Architecture:** SavedView model stores serialized Cytoscape + app state as JSONB in PostgreSQL. CRUD API with auth — all saved views visible to all project members (no per-view permissions). Frontend: save button in toolbar triggers a modal, views list in the sidebar/panel, clicking a view restores the exact graph state. Shareable URLs: `/projects/{id}/views/{viewId}`.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, React, Cytoscape.js, Tailwind CSS

**Dependencies:** Phase 4 M2 (auth frontend — AuthContext needed for frontend components that use `useAuth`)

**Spec Reference:** `cast-clone-backend/docs/04-PHASE-4-COLLABORATION.md` §4 (Saved Views)

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── main.py                          # MODIFY — register saved views router
│   ├── models/
│   │   └── db.py                        # MODIFY — add SavedView model
│   ├── schemas/
│   │   └── saved_views.py              # CREATE — Pydantic schemas
│   └── api/
│       └── saved_views.py              # CREATE — saved views CRUD endpoints
├── tests/
│   └── unit/
│       ├── test_saved_view_model.py    # CREATE
│       └── test_saved_views_api.py     # CREATE

cast-clone-frontend/
├── lib/
│   ├── types.ts                        # MODIFY — add saved view types
│   └── api.ts                          # MODIFY — add saved view API functions
├── hooks/
│   └── useSavedViews.ts               # CREATE — saved view state management
├── components/
│   ├── views/
│   │   ├── SaveViewModal.tsx           # CREATE — save view dialog
│   │   └── ViewsList.tsx              # CREATE — list saved views
│   └── graph/
│       └── GraphToolbar.tsx            # MODIFY — add save button
```

---

## Task 1: Backend — SavedView Model

**Files:**
- Modify: `cast-clone-backend/app/models/db.py`
- Create: `cast-clone-backend/tests/unit/test_saved_view_model.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_saved_view_model.py`:

```python
"""Tests for SavedView SQLAlchemy model."""
from app.models.db import SavedView


def test_saved_view_model_fields():
    view = SavedView(
        project_id="proj-1",
        name="Architecture Overview",
        description="Main modules layout",
        author_id="user-1",
        state={"viewType": "architecture", "zoom": 1.5},
    )
    assert view.name == "Architecture Overview"
    assert view.state["viewType"] == "architecture"
    assert view.description == "Main modules layout"


def test_saved_view_tablename():
    assert SavedView.__tablename__ == "saved_views"


def test_saved_view_optional_description():
    view = SavedView(
        project_id="proj-1",
        name="Quick view",
        author_id="user-1",
        state={},
    )
    assert view.description is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_saved_view_model.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add SavedView model to db.py**

Add to `cast-clone-backend/app/models/db.py`, after the Tag model:

```python
class SavedView(Base):
    __tablename__ = "saved_views"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)  # Use JSONB, not JSON
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    author: Mapped["User"] = relationship()
```

Note: `JSON` import from SQLAlchemy should already be present (used by AnalysisRun). If not, add it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_saved_view_model.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/models/db.py cast-clone-backend/tests/unit/test_saved_view_model.py
git commit -m "feat(views): add SavedView SQLAlchemy model with JSONB state column"
```

---

## Task 2: Backend — SavedView Schemas

**Files:**
- Create: `cast-clone-backend/app/schemas/saved_views.py`
- Create: `cast-clone-backend/tests/unit/test_saved_view_schemas.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_saved_view_schemas.py`:

```python
"""Tests for saved view Pydantic schemas."""
import pytest
from pydantic import ValidationError
from app.schemas.saved_views import SavedViewCreate, SavedViewResponse, SavedViewUpdate


def test_create_valid():
    req = SavedViewCreate(
        name="My View",
        state={"viewType": "architecture", "zoom": 1.0},
    )
    assert req.name == "My View"


def test_create_with_description():
    req = SavedViewCreate(
        name="My View",
        description="A saved view for the team",
        state={"viewType": "architecture"},
    )
    assert req.description == "A saved view for the team"


def test_create_empty_name():
    with pytest.raises(ValidationError):
        SavedViewCreate(name="", state={})


def test_update_valid():
    req = SavedViewUpdate(name="Updated Name")
    assert req.name == "Updated Name"
    assert req.state is None


def test_update_state_only():
    req = SavedViewUpdate(state={"viewType": "dependency"})
    assert req.state == {"viewType": "dependency"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_saved_view_schemas.py -v`
Expected: FAIL

- [ ] **Step 3: Implement schemas**

Create `cast-clone-backend/app/schemas/saved_views.py`:

```python
"""Pydantic schemas for saved views."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SavedViewCreate(BaseModel):
    """Request to save the current graph state."""
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    state: dict[str, Any]


class SavedViewUpdate(BaseModel):
    """Request to update a saved view."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    state: dict[str, Any] | None = None


class SavedViewAuthor(BaseModel):
    """Embedded author info."""
    id: str
    username: str

    model_config = {"from_attributes": True}


class SavedViewResponse(BaseModel):
    """Saved view with author info."""
    id: str
    project_id: str
    name: str
    description: str | None
    author: SavedViewAuthor
    state: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SavedViewListItem(BaseModel):
    """Saved view summary for list (without full state)."""
    id: str
    project_id: str
    name: str
    description: str | None
    author: SavedViewAuthor
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_saved_view_schemas.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/schemas/saved_views.py cast-clone-backend/tests/unit/test_saved_view_schemas.py
git commit -m "feat(views): add Pydantic schemas for saved views"
```

---

## Task 3: Backend — SavedView CRUD API

**Files:**
- Create: `cast-clone-backend/app/api/saved_views.py`
- Create: `cast-clone-backend/tests/unit/test_saved_views_api.py`
- Modify: `cast-clone-backend/app/main.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_saved_views_api.py`:

```python
"""Tests for saved views API endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestSavedViewEndpointsExist:
    @pytest.mark.asyncio
    async def test_save_view_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/projects/proj-1/views",
            json={"name": "test", "state": {}},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_views_requires_auth(self, client):
        resp = await client.get("/api/v1/projects/proj-1/views")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_view_requires_auth(self, client):
        resp = await client.get("/api/v1/views/view-1")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_update_view_requires_auth(self, client):
        resp = await client.put(
            "/api/v1/views/view-1",
            json={"name": "updated"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_view_requires_auth(self, client):
        resp = await client.delete("/api/v1/views/view-1")
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_saved_views_api.py -v`
Expected: FAIL (404)

- [ ] **Step 3: Implement saved views API**

Create `cast-clone-backend/app/api/saved_views.py`:

```python
"""Saved views CRUD API endpoints."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_user
from app.models.db import SavedView, User
from app.schemas.saved_views import (
    SavedViewCreate,
    SavedViewListItem,
    SavedViewResponse,
    SavedViewUpdate,
)
from app.services.postgres import get_session

logger = structlog.get_logger()

project_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/views", tags=["saved-views"]
)
view_router = APIRouter(prefix="/api/v1/views", tags=["saved-views"])


@project_router.post("", response_model=SavedViewResponse, status_code=201)
async def save_view(
    project_id: str,
    req: SavedViewCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SavedViewResponse:
    """Save the current graph state as a named view."""
    view = SavedView(
        project_id=project_id,
        name=req.name,
        description=req.description,
        author_id=user.id,
        state=req.state,
    )
    session.add(view)
    await session.commit()

    result = await session.execute(
        select(SavedView)
        .options(joinedload(SavedView.author))
        .where(SavedView.id == view.id)
    )
    view = result.scalar_one()

    logger.info("view_saved", view_id=view.id, name=req.name)
    return SavedViewResponse.model_validate(view, from_attributes=True)


@project_router.get("", response_model=list[SavedViewListItem])
async def list_views(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[SavedViewListItem]:
    """List all saved views for a project (without full state)."""
    result = await session.execute(
        select(SavedView)
        .options(joinedload(SavedView.author))
        .where(SavedView.project_id == project_id)
        .order_by(SavedView.updated_at.desc())
    )
    views = result.scalars().unique().all()
    return [
        SavedViewListItem.model_validate(v, from_attributes=True) for v in views
    ]


@view_router.get("/{view_id}", response_model=SavedViewResponse)
async def get_view(
    view_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> SavedViewResponse:
    """Load a saved view with full state."""
    result = await session.execute(
        select(SavedView)
        .options(joinedload(SavedView.author))
        .where(SavedView.id == view_id)
    )
    view = result.scalar_one_or_none()
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    return SavedViewResponse.model_validate(view, from_attributes=True)


@view_router.put("/{view_id}", response_model=SavedViewResponse)
async def update_view(
    view_id: str,
    req: SavedViewUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SavedViewResponse:
    """Update a saved view. Only the author can edit."""
    result = await session.execute(
        select(SavedView)
        .options(joinedload(SavedView.author))
        .where(SavedView.id == view_id)
    )
    view = result.scalar_one_or_none()
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    if view.author_id != user.id:
        raise HTTPException(status_code=403, detail="Only the author can edit")

    if req.name is not None:
        view.name = req.name
    if req.description is not None:
        view.description = req.description
    if req.state is not None:
        view.state = req.state

    await session.commit()

    # Re-query with author loaded to avoid lazy-load error
    result = await session.execute(
        select(SavedView)
        .options(joinedload(SavedView.author))
        .where(SavedView.id == view_id)
    )
    view = result.scalar_one()

    return SavedViewResponse.model_validate(view, from_attributes=True)


@view_router.delete("/{view_id}", status_code=204)
async def delete_view(
    view_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """Delete a saved view. Author or admin can delete."""
    result = await session.execute(
        select(SavedView).where(SavedView.id == view_id)
    )
    view = result.scalar_one_or_none()
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    if view.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the author or admin can delete")

    await session.delete(view)
    await session.commit()

    logger.info("view_deleted", view_id=view_id)
```

- [ ] **Step 4: Register routers via api/__init__.py and main.py**

Add to `cast-clone-backend/app/api/__init__.py`:

```python
from app.api.saved_views import project_router as views_project_router
from app.api.saved_views import view_router as views_router
```

And add both to the `__all__` list.

Then add both to the import block in `cast-clone-backend/app/main.py` and register:

```python
app.include_router(views_project_router)
app.include_router(views_router)
```

- [ ] **Step 5: Run tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_saved_views_api.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add cast-clone-backend/app/api/saved_views.py cast-clone-backend/app/main.py cast-clone-backend/tests/unit/test_saved_views_api.py
git commit -m "feat(views): add saved views CRUD API endpoints"
```

---

## Task 4: Frontend — Saved View Types + API Client

**Files:**
- Modify: `cast-clone-frontend/lib/types.ts`
- Modify: `cast-clone-frontend/lib/api.ts`

- [ ] **Step 1: Add saved view types**

Add to `cast-clone-frontend/lib/types.ts`:

```typescript
// ── Phase 4: Saved Views ──

export interface SavedViewState {
  viewType: ViewMode;
  selectedTransaction?: string;
  visibleNodeFqns: string[];
  drilldownPath: string[];
  layout: { name: string; [key: string]: unknown };
  zoom: number;
  pan: { x: number; y: number };
  filters: {
    nodeTypes?: string[];
    languages?: string[];
  };
  highlights?: {
    impact?: { startNode: string; depth: number; direction: string };
    path?: { from: string; to: string };
  };
}

export interface SavedViewResponse {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  author: { id: string; username: string };
  state: SavedViewState;
  created_at: string;
  updated_at: string;
}

export interface SavedViewListItem {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  author: { id: string; username: string };
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 2: Add API functions**

Add to `cast-clone-frontend/lib/api.ts`:

```typescript
// ── Saved Views ──

export async function saveView(
  projectId: string,
  name: string,
  state: Record<string, unknown>,
  description?: string
): Promise<SavedViewResponse> {
  return apiFetch<SavedViewResponse>(
    `/api/v1/projects/${projectId}/views`,
    {
      method: "POST",
      body: JSON.stringify({ name, description, state }),
    }
  );
}

export async function listViews(
  projectId: string
): Promise<SavedViewListItem[]> {
  return apiFetch<SavedViewListItem[]>(
    `/api/v1/projects/${projectId}/views`
  );
}

export async function getView(viewId: string): Promise<SavedViewResponse> {
  return apiFetch<SavedViewResponse>(`/api/v1/views/${viewId}`);
}

export async function updateView(
  viewId: string,
  data: { name?: string; description?: string; state?: Record<string, unknown> }
): Promise<SavedViewResponse> {
  return apiFetch<SavedViewResponse>(`/api/v1/views/${viewId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteView(viewId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/views/${viewId}`, { method: "DELETE" });
}
```

- [ ] **Step 3: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/lib/types.ts cast-clone-frontend/lib/api.ts
git commit -m "feat(views): add saved view types and API client functions"
```

---

## Task 5: Frontend — useSavedViews Hook

**Files:**
- Create: `cast-clone-frontend/hooks/useSavedViews.ts`

- [ ] **Step 1: Create hook**

Create `cast-clone-frontend/hooks/useSavedViews.ts`:

```typescript
"use client";

import { useCallback, useState } from "react";
import type { SavedViewListItem, SavedViewResponse } from "@/lib/types";
import { saveView, listViews, getView, deleteView } from "@/lib/api";

interface UseSavedViewsResult {
  views: SavedViewListItem[];
  loading: boolean;
  loadViews: (projectId: string) => Promise<void>;
  save: (
    projectId: string,
    name: string,
    state: Record<string, unknown>,
    description?: string
  ) => Promise<SavedViewResponse>;
  load: (viewId: string) => Promise<SavedViewResponse>;
  remove: (viewId: string) => Promise<void>;
}

export function useSavedViews(): UseSavedViewsResult {
  const [views, setViews] = useState<SavedViewListItem[]>([]);
  const [loading, setLoading] = useState(false);

  const loadViews = useCallback(async (projectId: string) => {
    setLoading(true);
    try {
      const data = await listViews(projectId);
      setViews(data);
    } catch {
      setViews([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const save = useCallback(
    async (
      projectId: string,
      name: string,
      state: Record<string, unknown>,
      description?: string
    ) => {
      const view = await saveView(projectId, name, state, description);
      setViews((prev) => [
        {
          id: view.id,
          project_id: view.project_id,
          name: view.name,
          description: view.description,
          author: view.author,
          created_at: view.created_at,
          updated_at: view.updated_at,
        },
        ...prev,
      ]);
      return view;
    },
    []
  );

  const load = useCallback(async (viewId: string) => {
    return getView(viewId);
  }, []);

  const remove = useCallback(async (viewId: string) => {
    await deleteView(viewId);
    setViews((prev) => prev.filter((v) => v.id !== viewId));
  }, []);

  return { views, loading, loadViews, save, load, remove };
}
```

- [ ] **Step 2: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add cast-clone-frontend/hooks/useSavedViews.ts
git commit -m "feat(views): add useSavedViews hook for saved view state management"
```

---

## Task 6: Frontend — SaveViewModal and ViewsList Components

**Files:**
- Create: `cast-clone-frontend/components/views/SaveViewModal.tsx`
- Create: `cast-clone-frontend/components/views/ViewsList.tsx`

- [ ] **Step 1: Create SaveViewModal**

Create `cast-clone-frontend/components/views/SaveViewModal.tsx`:

```tsx
"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface SaveViewModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (name: string, description?: string) => Promise<void>;
}

export function SaveViewModal({
  open,
  onOpenChange,
  onSave,
}: SaveViewModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setError("");
    setLoading(true);
    try {
      await onSave(name.trim(), description.trim() || undefined);
      setName("");
      setDescription("");
      onOpenChange(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save view");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Save Current View</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="view-name">Name</Label>
            <Input
              id="view-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Payment Module Overview"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="view-desc">Description (optional)</Label>
            <Input
              id="view-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this view show?"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={loading || !name.trim()}>
              {loading ? "Saving..." : "Save View"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Create ViewsList**

Create `cast-clone-frontend/components/views/ViewsList.tsx`:

```tsx
"use client";

import type { SavedViewListItem } from "@/lib/types";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Eye, Trash2, Link2 } from "lucide-react";

interface ViewsListProps {
  views: SavedViewListItem[];
  loading: boolean;
  onLoad: (viewId: string) => void;
  onDelete: (viewId: string) => void;
}

export function ViewsList({
  views,
  loading,
  onLoad,
  onDelete,
}: ViewsListProps) {
  const { user } = useAuth();

  if (loading) {
    return (
      <div className="text-center text-sm text-muted-foreground py-4">
        Loading views...
      </div>
    );
  }

  if (views.length === 0) {
    return (
      <div className="text-center text-sm text-muted-foreground py-4">
        No saved views yet. Save the current graph state to share with your
        team.
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {views.map((view) => (
        <div
          key={view.id}
          className="group flex items-center justify-between rounded-md border px-3 py-2 hover:bg-accent cursor-pointer"
          onClick={() => onLoad(view.id)}
        >
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium truncate">{view.name}</p>
            {view.description && (
              <p className="text-xs text-muted-foreground truncate">
                {view.description}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              {view.author.username} &middot;{" "}
              {new Date(view.updated_at).toLocaleDateString()}
            </p>
          </div>
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              onClick={(e) => {
                e.stopPropagation();
                const url = `${window.location.origin}/projects/${view.project_id}/views/${view.id}`;
                navigator.clipboard.writeText(url);
              }}
              title="Copy shareable link"
            >
              <Link2 className="h-3.5 w-3.5" />
            </Button>
            {(user?.id === view.author.id || user?.role === "admin") && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0 text-destructive"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(view.id);
                }}
                title="Delete view"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/components/views/SaveViewModal.tsx cast-clone-frontend/components/views/ViewsList.tsx
git commit -m "feat(views): add SaveViewModal and ViewsList components"
```

---

## Task 7: Frontend — Integrate Saved Views into Graph Page

**Files:**
- Modify: `cast-clone-frontend/components/graph/GraphToolbar.tsx`
- Modify: `cast-clone-frontend/app/projects/[id]/graph/page.tsx` (or the active graph page)

- [ ] **Step 1: Add Save button to GraphToolbar**

Import and add a Save button to `GraphToolbar.tsx`:

```tsx
import { Save } from "lucide-react";

// In the toolbar's right-side actions:
<Button
  variant="ghost"
  size="sm"
  onClick={onSaveView}
  title="Save current view"
  className="gap-1"
>
  <Save className="h-4 w-4" />
  <span className="hidden sm:inline text-xs">Save</span>
</Button>
```

Add `onSaveView: () => void` to the GraphToolbar props interface.

- [ ] **Step 2: Wire saved views into graph page**

In the graph page component, integrate `useSavedViews`:

```tsx
import { useSavedViews } from "@/hooks/useSavedViews";
import { SaveViewModal } from "@/components/views/SaveViewModal";

// Inside the component:
const { views, loading: viewsLoading, loadViews, save, load, remove } = useSavedViews();
const [saveModalOpen, setSaveModalOpen] = useState(false);

// Load views on mount:
useEffect(() => {
  if (projectId) loadViews(projectId);
}, [projectId, loadViews]);

// Capture current state for saving:
function captureGraphState(): Record<string, unknown> {
  const cy = cyInstanceRef.current;
  return {
    viewType: viewMode,
    drilldownPath: drilldownPath,
    visibleNodeFqns: cy ? cy.nodes().map((n) => n.data("fqn")).filter(Boolean) : [],
    layout: { name: viewMode === "dependency" ? "fcose" : "dagre" },
    zoom: cy?.zoom() ?? 1,
    pan: cy?.pan() ?? { x: 0, y: 0 },
    filters: {},
  };
}

// Save handler:
async function handleSaveView(name: string, description?: string) {
  const state = captureGraphState();
  await save(projectId, name, state, description);
}

// Load handler — restore Cytoscape state:
async function handleLoadView(viewId: string) {
  const view = await load(viewId);
  // Restore view type
  setViewMode(view.state.viewType);
  // Restore drilldown path (triggers data load)
  // Restore zoom/pan after layout settles
  const cy = cyInstanceRef.current;
  if (cy) {
    setTimeout(() => {
      cy.zoom(view.state.zoom);
      cy.pan(view.state.pan);
    }, 200);
  }
}
```

Pass `onSaveView={() => setSaveModalOpen(true)}` to `GraphToolbar`, and render the modal:

```tsx
<SaveViewModal
  open={saveModalOpen}
  onOpenChange={setSaveModalOpen}
  onSave={handleSaveView}
/>
```

- [ ] **Step 3: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/components/graph/GraphToolbar.tsx "cast-clone-frontend/app/projects/[id]/graph/page.tsx"
git commit -m "feat(views): integrate save/load views into graph page and toolbar"
```

---

## Verification Checklist

- [ ] Backend: SavedView model in db.py with JSONB state column
- [ ] Backend: `POST /api/v1/projects/{id}/views` creates a saved view (401 without auth)
- [ ] Backend: `GET /api/v1/projects/{id}/views` lists views (without full state)
- [ ] Backend: `GET /api/v1/views/{id}` loads a view with full state
- [ ] Backend: `PUT /api/v1/views/{id}` updates (author only)
- [ ] Backend: `DELETE /api/v1/views/{id}` deletes (author or admin)
- [ ] Frontend: SavedView types in types.ts
- [ ] Frontend: API client functions for CRUD operations
- [ ] Frontend: useSavedViews hook manages view list
- [ ] Frontend: SaveViewModal captures name + description
- [ ] Frontend: ViewsList shows views with load/delete/copy-link actions
- [ ] Frontend: Save button in GraphToolbar opens modal
- [ ] Frontend: Loading a view restores view type, zoom, and pan
- [ ] All backend tests pass
- [ ] `npx tsc --noEmit` passes
