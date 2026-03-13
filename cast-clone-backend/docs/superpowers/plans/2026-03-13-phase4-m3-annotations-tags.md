# Phase 4 M3: Annotations & Tags — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let team members attach free-text annotations and predefined tags to graph nodes, enabling knowledge capture directly on the architecture map.

**Architecture:** Two new PostgreSQL tables (annotations, tags) with CRUD APIs requiring auth. Frontend integration in the NodeProperties panel for display and editing. Tag-based filtering in the graph FilterPanel. Visual indicators on annotated/tagged Cytoscape nodes via class-based styling.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, React, Cytoscape.js, Tailwind CSS

**Dependencies:** Phase 4 M2 (auth frontend — AuthContext needed for frontend components that use `useAuth`)

**Spec Reference:** `cast-clone-backend/docs/04-PHASE-4-COLLABORATION.md` §3 (Annotations & Tags)

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── main.py                          # MODIFY — register annotations + tags routers
│   ├── models/
│   │   └── db.py                        # MODIFY — add Annotation and Tag models
│   ├── schemas/
│   │   └── annotations.py              # CREATE — Pydantic schemas
│   └── api/
│       ├── annotations.py              # CREATE — annotation CRUD endpoints
│       └── tags.py                     # CREATE — tag CRUD endpoints
├── tests/
│   └── unit/
│       ├── test_annotation_model.py    # CREATE
│       ├── test_annotations_api.py     # CREATE
│       └── test_tags_api.py            # CREATE

cast-clone-frontend/
├── lib/
│   ├── types.ts                        # MODIFY — add annotation/tag types
│   ├── api.ts                          # MODIFY — add annotation/tag API functions
│   └── graph-styles.ts                 # MODIFY — add annotated/tagged node styles
├── hooks/
│   └── useAnnotations.ts              # CREATE — annotation + tag state management
├── components/
│   ├── annotations/
│   │   ├── AnnotationList.tsx          # CREATE — list annotations for a node
│   │   ├── AddAnnotation.tsx           # CREATE — add annotation form
│   │   ├── TagBadges.tsx              # CREATE — display tags with add/remove
│   │   └── TagFilter.tsx              # CREATE — tag filter for sidebar
│   └── graph/
│       └── NodeProperties.tsx          # MODIFY — integrate annotations + tags
```

---

## Task 1: Backend — Annotation and Tag Models

**Files:**
- Modify: `cast-clone-backend/app/models/db.py`
- Create: `cast-clone-backend/tests/unit/test_annotation_model.py`

- [ ] **Step 1: Write failing tests for Annotation and Tag models**

Create `cast-clone-backend/tests/unit/test_annotation_model.py`:

```python
"""Tests for Annotation and Tag SQLAlchemy models."""
from app.models.db import Annotation, Tag


def test_annotation_model_fields():
    ann = Annotation(
        project_id="proj-1",
        node_fqn="com.app.UserService",
        content="This service is being deprecated in Q3",
        author_id="user-1",
    )
    assert ann.project_id == "proj-1"
    assert ann.node_fqn == "com.app.UserService"
    assert ann.content == "This service is being deprecated in Q3"
    assert ann.author_id == "user-1"


def test_annotation_tablename():
    assert Annotation.__tablename__ == "annotations"


def test_tag_model_fields():
    tag = Tag(
        project_id="proj-1",
        node_fqn="com.app.UserService",
        tag_name="deprecated",
        author_id="user-1",
    )
    assert tag.tag_name == "deprecated"


def test_tag_tablename():
    assert Tag.__tablename__ == "tags"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_annotation_model.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add Annotation and Tag models to db.py**

Add to `cast-clone-backend/app/models/db.py`, after the User model:

```python
class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    node_fqn: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    author: Mapped["User"] = relationship()


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("project_id", "node_fqn", "tag_name", name="uq_tag_node"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    node_fqn: Mapped[str] = mapped_column(String(500), nullable=False)
    tag_name: Mapped[str] = mapped_column(String(100), nullable=False)
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    author: Mapped["User"] = relationship()
```

Also ensure `UniqueConstraint` is imported from SQLAlchemy at the top of `db.py`:

```python
from sqlalchemy import UniqueConstraint
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_annotation_model.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/models/db.py cast-clone-backend/tests/unit/test_annotation_model.py
git commit -m "feat(annotations): add Annotation and Tag SQLAlchemy models"
```

---

## Task 2: Backend — Annotation and Tag Pydantic Schemas

**Files:**
- Create: `cast-clone-backend/app/schemas/annotations.py`
- Create: `cast-clone-backend/tests/unit/test_annotation_schemas.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_annotation_schemas.py`:

```python
"""Tests for annotation and tag Pydantic schemas."""
import pytest
from pydantic import ValidationError
from app.schemas.annotations import (
    AnnotationCreate,
    AnnotationResponse,
    AnnotationUpdate,
    TagCreate,
    TagResponse,
    PREDEFINED_TAGS,
)


def test_annotation_create_valid():
    req = AnnotationCreate(node_fqn="com.app.UserService", content="Note here")
    assert req.node_fqn == "com.app.UserService"


def test_annotation_create_empty_content():
    with pytest.raises(ValidationError):
        AnnotationCreate(node_fqn="com.app.Foo", content="")


def test_annotation_update():
    req = AnnotationUpdate(content="Updated note")
    assert req.content == "Updated note"


def test_tag_create_valid():
    req = TagCreate(node_fqn="com.app.UserService", tag_name="deprecated")
    assert req.tag_name == "deprecated"


def test_tag_create_invalid_tag():
    with pytest.raises(ValidationError):
        TagCreate(node_fqn="com.app.Foo", tag_name="invalid-tag")


def test_predefined_tags_exist():
    assert "deprecated" in PREDEFINED_TAGS
    assert "tech-debt" in PREDEFINED_TAGS
    assert "critical-path" in PREDEFINED_TAGS
    assert "security-sensitive" in PREDEFINED_TAGS
    assert "needs-review" in PREDEFINED_TAGS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_annotation_schemas.py -v`
Expected: FAIL

- [ ] **Step 3: Implement schemas**

Create `cast-clone-backend/app/schemas/annotations.py`:

```python
"""Pydantic schemas for annotations and tags."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PREDEFINED_TAGS = frozenset({
    "deprecated",
    "tech-debt",
    "critical-path",
    "security-sensitive",
    "needs-review",
})

TagName = Literal[
    "deprecated",
    "tech-debt",
    "critical-path",
    "security-sensitive",
    "needs-review",
]


class AnnotationCreate(BaseModel):
    """Create an annotation on a node."""
    node_fqn: str = Field(max_length=500)
    content: str = Field(min_length=1)


class AnnotationUpdate(BaseModel):
    """Update an annotation's content."""
    content: str = Field(min_length=1)


class AnnotationAuthor(BaseModel):
    """Embedded author info."""
    id: str
    username: str

    model_config = {"from_attributes": True}


class AnnotationResponse(BaseModel):
    """Annotation with author info."""
    id: str
    project_id: str
    node_fqn: str
    content: str
    author: AnnotationAuthor
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TagCreate(BaseModel):
    """Add a tag to a node."""
    node_fqn: str = Field(max_length=500)
    tag_name: TagName


class TagResponse(BaseModel):
    """Tag with author info."""
    id: str
    project_id: str
    node_fqn: str
    tag_name: str
    author: AnnotationAuthor
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_annotation_schemas.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/schemas/annotations.py cast-clone-backend/tests/unit/test_annotation_schemas.py
git commit -m "feat(annotations): add Pydantic schemas for annotations and tags"
```

---

## Task 3: Backend — Annotations CRUD API

**Files:**
- Create: `cast-clone-backend/app/api/annotations.py`
- Create: `cast-clone-backend/tests/unit/test_annotations_api.py`
- Modify: `cast-clone-backend/app/main.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_annotations_api.py`:

```python
"""Tests for annotations API endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAnnotationEndpointsExist:
    @pytest.mark.asyncio
    async def test_create_annotation_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/projects/proj-1/annotations",
            json={"node_fqn": "com.Foo", "content": "test"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_annotations_requires_auth(self, client):
        resp = await client.get(
            "/api/v1/projects/proj-1/annotations",
            params={"node_fqn": "com.Foo"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_update_annotation_requires_auth(self, client):
        resp = await client.put(
            "/api/v1/annotations/ann-1",
            json={"content": "updated"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_annotation_requires_auth(self, client):
        resp = await client.delete("/api/v1/annotations/ann-1")
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_annotations_api.py -v`
Expected: FAIL (404 — routes not registered)

- [ ] **Step 3: Implement annotations API**

Create `cast-clone-backend/app/api/annotations.py`:

```python
"""Annotation CRUD API endpoints."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_user
from app.models.db import Annotation, User
from app.schemas.annotations import (
    AnnotationCreate,
    AnnotationResponse,
    AnnotationUpdate,
)
from app.services.postgres import get_session

logger = structlog.get_logger()

# Project-scoped routes
project_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/annotations", tags=["annotations"]
)

# Direct annotation routes (for update/delete by annotation ID)
annotation_router = APIRouter(prefix="/api/v1/annotations", tags=["annotations"])


@project_router.post("", response_model=AnnotationResponse, status_code=201)
async def create_annotation(
    project_id: str,
    req: AnnotationCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AnnotationResponse:
    """Create an annotation on a node."""
    annotation = Annotation(
        project_id=project_id,
        node_fqn=req.node_fqn,
        content=req.content,
        author_id=user.id,
    )
    session.add(annotation)
    await session.commit()

    # Re-query with author loaded
    result = await session.execute(
        select(Annotation)
        .options(joinedload(Annotation.author))
        .where(Annotation.id == annotation.id)
    )
    annotation = result.scalar_one()

    logger.info(
        "annotation_created",
        annotation_id=annotation.id,
        project_id=project_id,
        node_fqn=req.node_fqn,
    )
    return AnnotationResponse.model_validate(annotation, from_attributes=True)


@project_router.get("", response_model=list[AnnotationResponse])
async def list_annotations(
    project_id: str,
    node_fqn: str = Query(..., description="FQN of the node"),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[AnnotationResponse]:
    """Get all annotations for a node in a project."""
    result = await session.execute(
        select(Annotation)
        .options(joinedload(Annotation.author))
        .where(
            Annotation.project_id == project_id,
            Annotation.node_fqn == node_fqn,
        )
        .order_by(Annotation.created_at.desc())
    )
    annotations = result.scalars().unique().all()
    return [
        AnnotationResponse.model_validate(a, from_attributes=True)
        for a in annotations
    ]


@annotation_router.put("/{annotation_id}", response_model=AnnotationResponse)
async def update_annotation(
    annotation_id: str,
    req: AnnotationUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AnnotationResponse:
    """Update an annotation. Only the author can edit."""
    result = await session.execute(
        select(Annotation)
        .options(joinedload(Annotation.author))
        .where(Annotation.id == annotation_id)
    )
    annotation = result.scalar_one_or_none()
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if annotation.author_id != user.id:
        raise HTTPException(status_code=403, detail="Only the author can edit")

    annotation.content = req.content
    await session.commit()
    await session.refresh(annotation)

    return AnnotationResponse.model_validate(annotation, from_attributes=True)


@annotation_router.delete("/{annotation_id}", status_code=204)
async def delete_annotation(
    annotation_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """Delete an annotation. Author or admin can delete."""
    result = await session.execute(
        select(Annotation).where(Annotation.id == annotation_id)
    )
    annotation = result.scalar_one_or_none()
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if annotation.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the author or admin can delete")

    await session.delete(annotation)
    await session.commit()

    logger.info("annotation_deleted", annotation_id=annotation_id)
```

- [ ] **Step 4: Register routers via api/__init__.py and main.py**

Add to `cast-clone-backend/app/api/__init__.py`:

```python
from app.api.annotations import project_router as annotations_project_router
from app.api.annotations import annotation_router as annotations_router
```

And add both to the `__all__` list.

Then add both to the import block in `cast-clone-backend/app/main.py` and register:

```python
app.include_router(annotations_project_router)
app.include_router(annotations_router)
```

- [ ] **Step 5: Run tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_annotations_api.py -v`
Expected: 4 passed (all return 401, not 404)

- [ ] **Step 6: Commit**

```bash
git add cast-clone-backend/app/api/annotations.py cast-clone-backend/app/main.py cast-clone-backend/tests/unit/test_annotations_api.py
git commit -m "feat(annotations): add annotation CRUD API endpoints"
```

---

## Task 4: Backend — Tags CRUD API

**Files:**
- Create: `cast-clone-backend/app/api/tags.py`
- Create: `cast-clone-backend/tests/unit/test_tags_api.py`
- Modify: `cast-clone-backend/app/main.py`

- [ ] **Step 1: Write failing tests**

Create `cast-clone-backend/tests/unit/test_tags_api.py`:

```python
"""Tests for tags API endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestTagEndpointsExist:
    @pytest.mark.asyncio
    async def test_add_tag_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/projects/proj-1/tags",
            json={"node_fqn": "com.Foo", "tag_name": "deprecated"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_tags_by_node_requires_auth(self, client):
        resp = await client.get(
            "/api/v1/projects/proj-1/tags",
            params={"node_fqn": "com.Foo"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_nodes_by_tag_requires_auth(self, client):
        resp = await client.get(
            "/api/v1/projects/proj-1/tags",
            params={"tag_name": "deprecated"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_tag_requires_auth(self, client):
        resp = await client.delete("/api/v1/tags/tag-1")
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_tags_api.py -v`
Expected: FAIL (404)

- [ ] **Step 3: Implement tags API**

Create `cast-clone-backend/app/api/tags.py`:

```python
"""Tag CRUD API endpoints."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_user
from app.models.db import Tag, User
from app.schemas.annotations import TagCreate, TagResponse
from app.services.postgres import get_session

logger = structlog.get_logger()

project_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/tags", tags=["tags"]
)
tag_router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


@project_router.post("", response_model=TagResponse, status_code=201)
async def add_tag(
    project_id: str,
    req: TagCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TagResponse:
    """Add a tag to a node. Duplicate tag on same node returns 409."""
    # Check for existing tag
    existing = await session.execute(
        select(Tag).where(
            Tag.project_id == project_id,
            Tag.node_fqn == req.node_fqn,
            Tag.tag_name == req.tag_name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409, detail="Tag already exists on this node"
        )

    tag = Tag(
        project_id=project_id,
        node_fqn=req.node_fqn,
        tag_name=req.tag_name,
        author_id=user.id,
    )
    session.add(tag)
    await session.commit()

    result = await session.execute(
        select(Tag)
        .options(joinedload(Tag.author))
        .where(Tag.id == tag.id)
    )
    tag = result.scalar_one()

    logger.info("tag_added", tag_name=req.tag_name, node_fqn=req.node_fqn)
    return TagResponse.model_validate(tag, from_attributes=True)


@project_router.get("", response_model=list[TagResponse])
async def list_tags(
    project_id: str,
    node_fqn: str | None = Query(default=None),
    tag_name: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[TagResponse]:
    """List tags filtered by node FQN or tag name (or both)."""
    query = (
        select(Tag)
        .options(joinedload(Tag.author))
        .where(Tag.project_id == project_id)
    )

    if node_fqn:
        query = query.where(Tag.node_fqn == node_fqn)
    if tag_name:
        query = query.where(Tag.tag_name == tag_name)

    query = query.order_by(Tag.created_at.desc())
    result = await session.execute(query)
    tags = result.scalars().unique().all()
    return [TagResponse.model_validate(t, from_attributes=True) for t in tags]


@tag_router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """Remove a tag. Author or admin can remove."""
    result = await session.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the author or admin can remove")

    await session.delete(tag)
    await session.commit()

    logger.info("tag_removed", tag_id=tag_id)
```

- [ ] **Step 4: Register routers via api/__init__.py and main.py**

Add to `cast-clone-backend/app/api/__init__.py`:

```python
from app.api.tags import project_router as tags_project_router
from app.api.tags import tag_router as tags_router
```

And add both to the `__all__` list.

Then add both to the import block in `cast-clone-backend/app/main.py` and register:

```python
app.include_router(tags_project_router)
app.include_router(tags_router)
```

- [ ] **Step 5: Run tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_tags_api.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add cast-clone-backend/app/api/tags.py cast-clone-backend/app/main.py cast-clone-backend/tests/unit/test_tags_api.py
git commit -m "feat(annotations): add tag CRUD API endpoints with predefined tag validation"
```

---

## Task 5: Frontend — Annotation and Tag Types + API Client

**Files:**
- Modify: `cast-clone-frontend/lib/types.ts`
- Modify: `cast-clone-frontend/lib/api.ts`

- [ ] **Step 1: Add annotation/tag types**

Add to `cast-clone-frontend/lib/types.ts`:

```typescript
// ── Phase 4: Annotations & Tags ──

export const PREDEFINED_TAGS = [
  "deprecated",
  "tech-debt",
  "critical-path",
  "security-sensitive",
  "needs-review",
] as const;

export type TagName = (typeof PREDEFINED_TAGS)[number];

export interface AnnotationAuthor {
  id: string;
  username: string;
}

export interface AnnotationResponse {
  id: string;
  project_id: string;
  node_fqn: string;
  content: string;
  author: AnnotationAuthor;
  created_at: string;
  updated_at: string;
}

export interface TagResponse {
  id: string;
  project_id: string;
  node_fqn: string;
  tag_name: TagName;
  author: AnnotationAuthor;
  created_at: string;
}
```

- [ ] **Step 2: Add API functions**

Add to `cast-clone-frontend/lib/api.ts`:

```typescript
// ── Annotations ──

export async function createAnnotation(
  projectId: string,
  nodeFqn: string,
  content: string
): Promise<AnnotationResponse> {
  return apiFetch<AnnotationResponse>(
    `/api/v1/projects/${projectId}/annotations`,
    {
      method: "POST",
      body: JSON.stringify({ node_fqn: nodeFqn, content }),
    }
  );
}

export async function listAnnotations(
  projectId: string,
  nodeFqn: string
): Promise<AnnotationResponse[]> {
  return apiFetch<AnnotationResponse[]>(
    `/api/v1/projects/${projectId}/annotations?node_fqn=${encodeURIComponent(nodeFqn)}`
  );
}

export async function updateAnnotation(
  annotationId: string,
  content: string
): Promise<AnnotationResponse> {
  return apiFetch<AnnotationResponse>(`/api/v1/annotations/${annotationId}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export async function deleteAnnotation(annotationId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/annotations/${annotationId}`, {
    method: "DELETE",
  });
}

// ── Tags ──

export async function addTag(
  projectId: string,
  nodeFqn: string,
  tagName: string
): Promise<TagResponse> {
  return apiFetch<TagResponse>(`/api/v1/projects/${projectId}/tags`, {
    method: "POST",
    body: JSON.stringify({ node_fqn: nodeFqn, tag_name: tagName }),
  });
}

export async function listTags(
  projectId: string,
  params: { node_fqn?: string; tag_name?: string }
): Promise<TagResponse[]> {
  const searchParams = new URLSearchParams();
  if (params.node_fqn) searchParams.set("node_fqn", params.node_fqn);
  if (params.tag_name) searchParams.set("tag_name", params.tag_name);
  return apiFetch<TagResponse[]>(
    `/api/v1/projects/${projectId}/tags?${searchParams}`
  );
}

export async function deleteTag(tagId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/tags/${tagId}`, { method: "DELETE" });
}
```

- [ ] **Step 3: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/lib/types.ts cast-clone-frontend/lib/api.ts
git commit -m "feat(annotations): add annotation and tag types and API client functions"
```

---

## Task 6: Frontend — useAnnotations Hook

**Files:**
- Create: `cast-clone-frontend/hooks/useAnnotations.ts`

- [ ] **Step 1: Create hook**

Create `cast-clone-frontend/hooks/useAnnotations.ts`:

```typescript
"use client";

import { useCallback, useState } from "react";
import type { AnnotationResponse, TagResponse, TagName } from "@/lib/types";
import {
  createAnnotation,
  listAnnotations,
  updateAnnotation,
  deleteAnnotation,
  addTag,
  listTags,
  deleteTag,
} from "@/lib/api";

interface UseAnnotationsResult {
  annotations: AnnotationResponse[];
  tags: TagResponse[];
  loading: boolean;
  loadForNode: (projectId: string, nodeFqn: string) => Promise<void>;
  addAnnotation: (
    projectId: string,
    nodeFqn: string,
    content: string
  ) => Promise<void>;
  editAnnotation: (annotationId: string, content: string) => Promise<void>;
  removeAnnotation: (annotationId: string) => Promise<void>;
  addNodeTag: (
    projectId: string,
    nodeFqn: string,
    tagName: TagName
  ) => Promise<void>;
  removeTag: (tagId: string) => Promise<void>;
}

export function useAnnotations(): UseAnnotationsResult {
  const [annotations, setAnnotations] = useState<AnnotationResponse[]>([]);
  const [tags, setTags] = useState<TagResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [currentProject, setCurrentProject] = useState("");
  const [currentNode, setCurrentNode] = useState("");

  const loadForNode = useCallback(
    async (projectId: string, nodeFqn: string) => {
      setLoading(true);
      setCurrentProject(projectId);
      setCurrentNode(nodeFqn);
      try {
        const [anns, tgs] = await Promise.all([
          listAnnotations(projectId, nodeFqn),
          listTags(projectId, { node_fqn: nodeFqn }),
        ]);
        setAnnotations(anns);
        setTags(tgs);
      } catch {
        setAnnotations([]);
        setTags([]);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const addAnnotationFn = useCallback(
    async (projectId: string, nodeFqn: string, content: string) => {
      const ann = await createAnnotation(projectId, nodeFqn, content);
      setAnnotations((prev) => [ann, ...prev]);
    },
    []
  );

  const editAnnotation = useCallback(
    async (annotationId: string, content: string) => {
      const updated = await updateAnnotation(annotationId, content);
      setAnnotations((prev) =>
        prev.map((a) => (a.id === annotationId ? updated : a))
      );
    },
    []
  );

  const removeAnnotation = useCallback(async (annotationId: string) => {
    await deleteAnnotation(annotationId);
    setAnnotations((prev) => prev.filter((a) => a.id !== annotationId));
  }, []);

  const addNodeTag = useCallback(
    async (projectId: string, nodeFqn: string, tagName: TagName) => {
      const tag = await addTag(projectId, nodeFqn, tagName);
      setTags((prev) => [tag, ...prev]);
    },
    []
  );

  const removeTagFn = useCallback(async (tagId: string) => {
    await deleteTag(tagId);
    setTags((prev) => prev.filter((t) => t.id !== tagId));
  }, []);

  return {
    annotations,
    tags,
    loading,
    loadForNode,
    addAnnotation: addAnnotationFn,
    editAnnotation,
    removeAnnotation,
    addNodeTag,
    removeTag: removeTagFn,
  };
}
```

- [ ] **Step 2: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add cast-clone-frontend/hooks/useAnnotations.ts
git commit -m "feat(annotations): add useAnnotations hook for annotation and tag state"
```

---

## Task 7: Frontend — Annotation and Tag Components

**Files:**
- Create: `cast-clone-frontend/components/annotations/AnnotationList.tsx`
- Create: `cast-clone-frontend/components/annotations/AddAnnotation.tsx`
- Create: `cast-clone-frontend/components/annotations/TagBadges.tsx`

- [ ] **Step 1: Create AnnotationList component**

Create `cast-clone-frontend/components/annotations/AnnotationList.tsx`:

```tsx
"use client";

import { useState } from "react";
import type { AnnotationResponse } from "@/lib/types";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Pencil, Trash2, X, Check } from "lucide-react";

interface AnnotationListProps {
  annotations: AnnotationResponse[];
  onEdit: (id: string, content: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export function AnnotationList({
  annotations,
  onEdit,
  onDelete,
}: AnnotationListProps) {
  const { user } = useAuth();
  const [editId, setEditId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");

  if (annotations.length === 0) {
    return (
      <p className="text-xs text-muted-foreground py-1">No annotations yet</p>
    );
  }

  return (
    <div className="space-y-2">
      {annotations.map((ann) => (
        <div
          key={ann.id}
          className="rounded-md border p-2 text-sm space-y-1"
        >
          {editId === ann.id ? (
            <div className="space-y-1">
              <textarea
                className="w-full rounded border bg-background px-2 py-1 text-sm"
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                rows={2}
              />
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0"
                  onClick={async () => {
                    await onEdit(ann.id, editContent);
                    setEditId(null);
                  }}
                >
                  <Check className="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0"
                  onClick={() => setEditId(null)}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            </div>
          ) : (
            <>
              <p>{ann.content}</p>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {ann.author.username} &middot;{" "}
                  {new Date(ann.created_at).toLocaleDateString()}
                </span>
                {(user?.id === ann.author.id || user?.role === "admin") && (
                  <div className="flex gap-0.5">
                    {user?.id === ann.author.id && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-5 w-5 p-0"
                        onClick={() => {
                          setEditId(ann.id);
                          setEditContent(ann.content);
                        }}
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-5 w-5 p-0 text-destructive"
                      onClick={() => onDelete(ann.id)}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create AddAnnotation component**

Create `cast-clone-frontend/components/annotations/AddAnnotation.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { MessageSquarePlus } from "lucide-react";

interface AddAnnotationProps {
  onAdd: (content: string) => Promise<void>;
}

export function AddAnnotation({ onAdd }: AddAnnotationProps) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;
    setLoading(true);
    try {
      await onAdd(content.trim());
      setContent("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-1.5">
      <input
        className="flex-1 rounded-md border bg-background px-2 py-1 text-sm"
        placeholder="Add a note..."
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      <Button
        type="submit"
        variant="ghost"
        size="sm"
        disabled={loading || !content.trim()}
        className="shrink-0"
      >
        <MessageSquarePlus className="h-4 w-4" />
      </Button>
    </form>
  );
}
```

- [ ] **Step 3: Create TagBadges component**

Create `cast-clone-frontend/components/annotations/TagBadges.tsx`:

```tsx
"use client";

import { useState } from "react";
import type { TagResponse, TagName } from "@/lib/types";
import { PREDEFINED_TAGS } from "@/lib/types";
import { useAuth } from "@/lib/auth-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Plus, X } from "lucide-react";

const TAG_COLORS: Record<string, string> = {
  deprecated: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  "tech-debt": "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  "critical-path": "bg-violet-100 text-violet-800 dark:bg-violet-900 dark:text-violet-200",
  "security-sensitive": "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  "needs-review": "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
};

interface TagBadgesProps {
  tags: TagResponse[];
  onAdd: (tagName: TagName) => Promise<void>;
  onRemove: (tagId: string) => Promise<void>;
}

export function TagBadges({ tags, onAdd, onRemove }: TagBadgesProps) {
  const { user } = useAuth();
  const [showPicker, setShowPicker] = useState(false);
  const existingNames = new Set(tags.map((t) => t.tag_name));

  const availableTags = PREDEFINED_TAGS.filter((t) => !existingNames.has(t));

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1">
        {tags.map((tag) => (
          <Badge
            key={tag.id}
            variant="secondary"
            className={`gap-1 text-xs ${TAG_COLORS[tag.tag_name] ?? ""}`}
          >
            {tag.tag_name}
            {(user?.id === tag.author.id || user?.role === "admin") && (
              <button
                className="ml-0.5 hover:text-destructive"
                onClick={() => onRemove(tag.id)}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </Badge>
        ))}

        {availableTags.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-5 px-1"
            onClick={() => setShowPicker(!showPicker)}
          >
            <Plus className="h-3 w-3" />
          </Button>
        )}
      </div>

      {showPicker && availableTags.length > 0 && (
        <div className="flex flex-wrap gap-1 rounded-md border p-1.5">
          {availableTags.map((tagName) => (
            <Badge
              key={tagName}
              variant="outline"
              className={`cursor-pointer text-xs hover:opacity-80 ${TAG_COLORS[tagName] ?? ""}`}
              onClick={async () => {
                await onAdd(tagName);
                setShowPicker(false);
              }}
            >
              + {tagName}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add cast-clone-frontend/components/annotations/AnnotationList.tsx cast-clone-frontend/components/annotations/AddAnnotation.tsx cast-clone-frontend/components/annotations/TagBadges.tsx
git commit -m "feat(annotations): add AnnotationList, AddAnnotation, and TagBadges components"
```

---

## Task 8: Frontend — Integrate Annotations/Tags into NodeProperties Panel

**Files:**
- Modify: `cast-clone-frontend/components/graph/NodeProperties.tsx`
- Modify: `cast-clone-frontend/lib/graph-styles.ts`

- [ ] **Step 1: Add annotations/tags section to NodeProperties**

Modify `cast-clone-frontend/components/graph/NodeProperties.tsx`. Import the annotation components and hook:

```tsx
import { AnnotationList } from "@/components/annotations/AnnotationList";
import { AddAnnotation } from "@/components/annotations/AddAnnotation";
import { TagBadges } from "@/components/annotations/TagBadges";
```

The NodeProperties component needs to accept `projectId`, `annotations`, `tags`, and handler props. Add these to the props interface and render the annotation/tag sections below the existing node details:

```tsx
{/* After the existing metrics/details section */}
<div className="border-t pt-3 space-y-3">
  <div>
    <h4 className="text-xs font-medium text-muted-foreground mb-1">Tags</h4>
    <TagBadges
      tags={tags}
      onAdd={(tagName) => onAddTag(projectId, selectedNode.fqn, tagName)}
      onRemove={onRemoveTag}
    />
  </div>
  <div>
    <h4 className="text-xs font-medium text-muted-foreground mb-1">Annotations</h4>
    <AnnotationList
      annotations={annotations}
      onEdit={onEditAnnotation}
      onDelete={onDeleteAnnotation}
    />
    <AddAnnotation
      onAdd={(content) => onAddAnnotation(projectId, selectedNode.fqn, content)}
    />
  </div>
</div>
```

Note: The exact integration depends on the current NodeProperties structure. The `useAnnotations` hook should be called in the graph page and props passed down. When a node is selected (via `useEffect` watching `selectedNode`), call `loadForNode(projectId, selectedNode.fqn)`.

- [ ] **Step 2: Add annotated/tagged node styles to graph-styles.ts**

Add to `cast-clone-frontend/lib/graph-styles.ts`, in the `defaultStylesheet` array:

```typescript
// Annotated nodes — small note icon indicator
{
  selector: "node.has-annotations",
  style: {
    "border-width": 2,
    "border-color": "#3b82f6",
    "border-style": "solid",
  },
},
// Deprecated nodes — strikethrough style
{
  selector: "node.tag-deprecated",
  style: {
    "text-decoration": "line-through" as any,
    opacity: 0.6,
  },
},
// Critical path nodes — emphasized
{
  selector: "node.tag-critical-path",
  style: {
    "border-width": 3,
    "border-color": "#7c3aed",
    "border-style": "double",
  },
},
// Security-sensitive nodes
{
  selector: "node.tag-security-sensitive",
  style: {
    "border-width": 2,
    "border-color": "#f97316",
    "border-style": "dashed",
  },
},
```

To apply these classes dynamically, after loading annotations/tags for the visible graph, add classes to Cytoscape nodes:

```typescript
// In graph page, after loading annotations/tags for visible nodes:
function applyAnnotationClasses(
  cy: cytoscape.Core,
  annotatedFqns: Set<string>,
  taggedNodes: Map<string, string[]>
) {
  cy.nodes().forEach((node) => {
    const fqn = node.data("fqn");
    node.removeClass("has-annotations tag-deprecated tag-critical-path tag-security-sensitive tag-needs-review tag-tech-debt");
    if (annotatedFqns.has(fqn)) {
      node.addClass("has-annotations");
    }
    const tags = taggedNodes.get(fqn) ?? [];
    tags.forEach((tag) => node.addClass(`tag-${tag}`));
  });
}
```

- [ ] **Step 3: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/components/graph/NodeProperties.tsx cast-clone-frontend/lib/graph-styles.ts
git commit -m "feat(annotations): integrate annotations and tags into NodeProperties and graph styles"
```

---

## Verification Checklist

- [ ] Backend: Annotation + Tag models in db.py with correct table names and constraints
- [ ] Backend: `POST/GET /api/v1/projects/{id}/annotations` works (returns 401 without auth)
- [ ] Backend: `PUT/DELETE /api/v1/annotations/{id}` works
- [ ] Backend: `POST/GET /api/v1/projects/{id}/tags` works
- [ ] Backend: `DELETE /api/v1/tags/{id}` works
- [ ] Backend: Tag creation rejects invalid tag names (not in predefined list)
- [ ] Frontend: annotation/tag types in types.ts
- [ ] Frontend: API client functions for annotations and tags
- [ ] Frontend: useAnnotations hook manages state
- [ ] Frontend: AnnotationList, AddAnnotation, TagBadges components render correctly
- [ ] Frontend: NodeProperties panel shows annotations and tags for selected node
- [ ] Frontend: Annotated/tagged nodes have visual indicators in Cytoscape
- [ ] All backend tests pass
- [ ] `npx tsc --noEmit` passes
- [ ] `ruff check` passes on all new backend files
