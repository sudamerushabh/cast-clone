# Phase 5b-M5: API Key Management UI + Cost Tracking + Docs

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `AiUsageLog` ORM model for cost tracking, backend usage stats endpoints (admin-only), and a frontend with API key management (table, create modal, revoke), MCP setup guide, and AI usage dashboard.

**Architecture:** An `AiUsageLog` PostgreSQL table records every AI API call (chat, summary, PR analysis) with token counts and estimated cost. Admin-only endpoints in `app/api/ai_usage.py` aggregate usage by project, source, and time period. The frontend adds an API Keys settings page (`/settings/api-keys`) with key CRUD, copy-paste MCP setup snippets, and an `AiUsageDashboard` component showing token/cost breakdowns. API key management calls the M4 endpoints (`POST/GET/DELETE /api/v1/api-keys`). Usage stats come from new `GET /api/v1/admin/ai-usage` endpoints.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async (ORM), Pydantic v2, pytest + pytest-asyncio (backend). Next.js 14 App Router, TypeScript, Tailwind CSS, lucide-react icons, shadcn/ui components (frontend).

**Depends on:** M4 (API key model + management endpoints), M1 (chat service for usage logging integration), M2 (summary generator for usage logging integration).

**Note:** Alembic migration for the `ai_usage_log` table should be generated after the ORM model is added (Task 2). Run `uv run alembic revision --autogenerate -m "add ai_usage_log table"` and verify the generated migration. The table also needs the index `idx_usage_project_date ON ai_usage_log(project_id, created_at DESC)`.

**Frontend nav note:** The settings navigation lives in `cast-clone-frontend/components/layout/ContextPanel.tsx` — add the "API Keys" entry after the existing items using the `Key` icon from `lucide-react`.

---

## File Structure

```
cast-clone-backend/
├── app/models/db.py                  # MODIFY — add AiUsageLog model
├── app/schemas/ai_usage.py           # NEW — response models for usage stats
├── app/api/ai_usage.py               # NEW — admin usage stats endpoints
├── app/api/__init__.py               # MODIFY — register ai_usage_router
├── app/main.py                       # MODIFY — include ai_usage_router
├── app/config.py                     # MODIFY — add cost pricing settings
└── tests/unit/
    ├── test_ai_usage_schemas.py      # NEW — schema validation tests
    ├── test_ai_usage_model.py        # NEW — ORM model tests
    └── test_ai_usage_endpoint.py     # NEW — endpoint routing + auth tests

cast-clone-frontend/
├── app/settings/api-keys/
│   └── page.tsx                      # NEW — API key management page
├── components/settings/
│   ├── ApiKeyTable.tsx               # NEW — key list table
│   ├── CreateKeyModal.tsx            # NEW — create key modal with copy
│   └── McpSetupGuide.tsx             # NEW — setup instructions component
└── components/admin/
    └── AiUsageDashboard.tsx          # NEW — cost tracking dashboard
```

---

## Task 1: Config Additions — Cost Pricing Settings

**Files:**
- Modify: `app/config.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_config.py (append to existing file)

def test_ai_cost_settings_defaults():
    from app.config import Settings
    s = Settings(database_url="postgresql+asyncpg://x", neo4j_uri="bolt://x")
    assert s.ai_cost_input_per_mtok == 3.0
    assert s.ai_cost_output_per_mtok == 15.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_config.py::test_ai_cost_settings_defaults -v`
Expected: FAIL — `Settings` has no `ai_cost_input_per_mtok` attribute.

- [ ] **Step 3: Add cost pricing settings to config**

In `app/config.py`, add after the chat settings block:

```python
    # Phase 5b-M5: AI usage cost estimation (Sonnet pricing, USD per million tokens)
    ai_cost_input_per_mtok: float = 3.0
    ai_cost_output_per_mtok: float = 15.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_config.py::test_ai_cost_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/config.py tests/unit/test_config.py
git commit -m "feat(5b-m5): add AI cost pricing settings"
```

---

## Task 2: AiUsageLog ORM Model

**Files:**
- Modify: `app/models/db.py`
- Test: `tests/unit/test_ai_usage_model.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_ai_usage_model.py
"""Unit tests for the AiUsageLog ORM model."""
from __future__ import annotations

from decimal import Decimal

from app.models.db import AiUsageLog


class TestAiUsageLogModel:
    def test_create_instance(self):
        log = AiUsageLog(
            project_id="proj-123",
            user_id="user-456",
            source="chat",
            model="us.anthropic.claude-sonnet-4-6",
            input_tokens=3200,
            output_tokens=850,
            estimated_cost_usd=Decimal("0.022350"),
        )
        assert log.project_id == "proj-123"
        assert log.user_id == "user-456"
        assert log.source == "chat"
        assert log.model == "us.anthropic.claude-sonnet-4-6"
        assert log.input_tokens == 3200
        assert log.output_tokens == 850
        assert log.estimated_cost_usd == Decimal("0.022350")

    def test_tablename(self):
        assert AiUsageLog.__tablename__ == "ai_usage_log"

    def test_default_id_generated(self):
        log = AiUsageLog(
            project_id="p1",
            source="summary",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
        )
        assert log.id is not None
        assert len(log.id) == 36  # UUID format

    def test_nullable_user_id(self):
        """MCP calls may not have a user_id."""
        log = AiUsageLog(
            project_id="p1",
            source="mcp",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
        )
        assert log.user_id is None

    def test_nullable_estimated_cost(self):
        log = AiUsageLog(
            project_id="p1",
            source="chat",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
        )
        assert log.estimated_cost_usd is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_usage_model.py -v`
Expected: FAIL — `AiUsageLog` not found in `app.models.db`.

- [ ] **Step 3: Add AiUsageLog model to db.py**

In `app/models/db.py`, add the `Numeric` import to the SQLAlchemy imports block:

```python
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
```

Then add the model at the end of the file (after the `PrAnalysis` class):

```python
class AiUsageLog(Base):
    __tablename__ = "ai_usage_log"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'chat', 'summary', 'mcp', 'pr_analysis'
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped[Project] = relationship()
    user: Mapped[User | None] = relationship()
```

Also add the `Decimal` import at the top of the file:

```python
from decimal import Decimal
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_usage_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/models/db.py tests/unit/test_ai_usage_model.py
git commit -m "feat(5b-m5): add AiUsageLog ORM model for cost tracking"
```

---

## Task 3: AI Usage Schemas (Pydantic v2)

**Files:**
- Create: `app/schemas/ai_usage.py`
- Test: `tests/unit/test_ai_usage_schemas.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_ai_usage_schemas.py
"""Unit tests for AI usage response schemas."""
from __future__ import annotations

from datetime import datetime

from app.schemas.ai_usage import (
    UsageLogResponse,
    UsageSummaryResponse,
    UsageBySourceItem,
    UsageByProjectItem,
)


class TestUsageLogResponse:
    def test_from_dict(self):
        resp = UsageLogResponse(
            id="log-1",
            project_id="proj-1",
            user_id="user-1",
            source="chat",
            model="us.anthropic.claude-sonnet-4-6",
            input_tokens=3200,
            output_tokens=850,
            estimated_cost_usd=0.022350,
            created_at=datetime(2026, 3, 13, 10, 0, 0),
        )
        assert resp.source == "chat"
        assert resp.input_tokens == 3200

    def test_nullable_fields(self):
        resp = UsageLogResponse(
            id="log-1",
            project_id="proj-1",
            user_id=None,
            source="mcp",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_usd=None,
            created_at=datetime(2026, 3, 13),
        )
        assert resp.user_id is None
        assert resp.estimated_cost_usd is None


class TestUsageSummaryResponse:
    def test_summary(self):
        resp = UsageSummaryResponse(
            total_input_tokens=100000,
            total_output_tokens=25000,
            total_estimated_cost_usd=1.675,
            by_source=[
                UsageBySourceItem(source="chat", input_tokens=80000, output_tokens=20000, estimated_cost_usd=1.34, count=15),
                UsageBySourceItem(source="summary", input_tokens=20000, output_tokens=5000, estimated_cost_usd=0.335, count=40),
            ],
            by_project=[
                UsageByProjectItem(project_id="p1", project_name="MyApp", input_tokens=100000, output_tokens=25000, estimated_cost_usd=1.675, count=55),
            ],
        )
        assert resp.total_input_tokens == 100000
        assert len(resp.by_source) == 2
        assert len(resp.by_project) == 1


class TestUsageBySourceItem:
    def test_fields(self):
        item = UsageBySourceItem(
            source="pr_analysis",
            input_tokens=50000,
            output_tokens=10000,
            estimated_cost_usd=0.30,
            count=5,
        )
        assert item.source == "pr_analysis"
        assert item.count == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_usage_schemas.py -v`
Expected: FAIL — `app.schemas.ai_usage` not found.

- [ ] **Step 3: Create the schemas**

```python
# app/schemas/ai_usage.py
"""Response models for AI usage tracking endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UsageLogResponse(BaseModel):
    """Single AI usage log entry."""

    id: str
    project_id: str
    user_id: str | None
    source: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UsageBySourceItem(BaseModel):
    """Aggregated usage stats for a single source (chat, summary, etc.)."""

    source: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    count: int


class UsageByProjectItem(BaseModel):
    """Aggregated usage stats for a single project."""

    project_id: str
    project_name: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    count: int


class UsageSummaryResponse(BaseModel):
    """Aggregated AI usage summary for the admin dashboard."""

    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float
    by_source: list[UsageBySourceItem]
    by_project: list[UsageByProjectItem]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_usage_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/schemas/ai_usage.py tests/unit/test_ai_usage_schemas.py
git commit -m "feat(5b-m5): add AI usage Pydantic response schemas"
```

---

## Task 4: AI Usage Stats Endpoint (Admin-Only)

**Files:**
- Create: `app/api/ai_usage.py`
- Modify: `app/api/__init__.py`
- Modify: `app/main.py`
- Test: `tests/unit/test_ai_usage_endpoint.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_ai_usage_endpoint.py
"""Tests for the AI usage stats endpoint.

Tests endpoint routing, admin auth, and response format.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch, AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_usage_summary_returns_200():
    """GET /api/v1/admin/ai-usage returns usage summary for admins."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/ai-usage")
        # With auth_disabled=True (default), admin access is granted
        assert resp.status_code == 200
        data = resp.json()
        assert "total_input_tokens" in data
        assert "total_output_tokens" in data
        assert "total_estimated_cost_usd" in data
        assert "by_source" in data
        assert "by_project" in data


@pytest.mark.asyncio
async def test_usage_by_project_returns_200():
    """GET /api/v1/admin/ai-usage/project/{id} returns project usage."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/ai-usage/project/proj-123")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_usage_endpoint.py -v`
Expected: FAIL — route not found (404).

- [ ] **Step 3: Create the endpoint**

```python
# app/api/ai_usage.py
"""Admin endpoints for AI usage statistics and cost tracking."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.models.db import AiUsageLog, Project, User
from app.schemas.ai_usage import (
    UsageByProjectItem,
    UsageBySourceItem,
    UsageLogResponse,
    UsageSummaryResponse,
)
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/admin/ai-usage", tags=["ai-usage"])


@router.get("", response_model=UsageSummaryResponse)
async def get_usage_summary(
    days: int = Query(default=30, ge=1, le=365),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UsageSummaryResponse:
    """Get aggregated AI usage summary (admin only).

    Returns total tokens, estimated cost, and breakdowns by source and project
    for the specified time window (default: last 30 days).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Totals
    totals_q = await session.execute(
        select(
            func.coalesce(func.sum(AiUsageLog.input_tokens), 0).label("total_input"),
            func.coalesce(func.sum(AiUsageLog.output_tokens), 0).label("total_output"),
            func.coalesce(func.sum(AiUsageLog.estimated_cost_usd), 0).label("total_cost"),
        ).where(AiUsageLog.created_at >= cutoff)
    )
    totals = totals_q.one()

    # By source
    source_q = await session.execute(
        select(
            AiUsageLog.source,
            func.sum(AiUsageLog.input_tokens).label("input_tokens"),
            func.sum(AiUsageLog.output_tokens).label("output_tokens"),
            func.coalesce(func.sum(AiUsageLog.estimated_cost_usd), 0).label("cost"),
            func.count().label("count"),
        )
        .where(AiUsageLog.created_at >= cutoff)
        .group_by(AiUsageLog.source)
        .order_by(func.sum(AiUsageLog.estimated_cost_usd).desc())
    )
    by_source = [
        UsageBySourceItem(
            source=row.source,
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            estimated_cost_usd=float(row.cost or 0),
            count=int(row.count),
        )
        for row in source_q.all()
    ]

    # By project
    project_q = await session.execute(
        select(
            AiUsageLog.project_id,
            Project.name.label("project_name"),
            func.sum(AiUsageLog.input_tokens).label("input_tokens"),
            func.sum(AiUsageLog.output_tokens).label("output_tokens"),
            func.coalesce(func.sum(AiUsageLog.estimated_cost_usd), 0).label("cost"),
            func.count().label("count"),
        )
        .join(Project, AiUsageLog.project_id == Project.id)
        .where(AiUsageLog.created_at >= cutoff)
        .group_by(AiUsageLog.project_id, Project.name)
        .order_by(func.sum(AiUsageLog.estimated_cost_usd).desc())
    )
    by_project = [
        UsageByProjectItem(
            project_id=row.project_id,
            project_name=row.project_name or "Unknown",
            input_tokens=int(row.input_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            estimated_cost_usd=float(row.cost or 0),
            count=int(row.count),
        )
        for row in project_q.all()
    ]

    return UsageSummaryResponse(
        total_input_tokens=int(totals.total_input),
        total_output_tokens=int(totals.total_output),
        total_estimated_cost_usd=float(totals.total_cost),
        by_source=by_source,
        by_project=by_project,
    )


@router.get("/project/{project_id}", response_model=list[UsageLogResponse])
async def get_project_usage(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[UsageLogResponse]:
    """Get recent AI usage log entries for a specific project (admin only)."""
    result = await session.execute(
        select(AiUsageLog)
        .where(AiUsageLog.project_id == project_id)
        .order_by(AiUsageLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [UsageLogResponse.model_validate(log) for log in logs]
```

- [ ] **Step 4: Register the router**

In `app/api/__init__.py`, add:

```python
from app.api.ai_usage import router as ai_usage_router
```

And add `"ai_usage_router"` to the `__all__` list.

In `app/main.py`, add to the imports:

```python
from app.api import ai_usage_router
```

And add to the router registration section:

```python
application.include_router(ai_usage_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_usage_endpoint.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/api/ai_usage.py app/api/__init__.py app/main.py tests/unit/test_ai_usage_endpoint.py
git commit -m "feat(5b-m5): add admin AI usage stats endpoints"
```

---

## Task 5: Usage Logging Helper Function

**Files:**
- Create: `app/ai/usage_logging.py`
- Test: `tests/unit/test_usage_logging.py`

This helper is called by the chat service (M1), summary generator (M2), and PR analysis (5a) to record usage.

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_usage_logging.py
"""Unit tests for AI usage logging helper."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.usage_logging import log_ai_usage, estimate_cost


class TestEstimateCost:
    def test_basic_cost(self):
        """3.0 per Mtok input + 15.0 per Mtok output."""
        cost = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            input_price_per_mtok=3.0,
            output_price_per_mtok=15.0,
        )
        assert cost == Decimal("18.000000")

    def test_small_usage(self):
        cost = estimate_cost(
            input_tokens=3200,
            output_tokens=850,
            input_price_per_mtok=3.0,
            output_price_per_mtok=15.0,
        )
        # 3200/1M * 3.0 = 0.0096, 850/1M * 15.0 = 0.01275 → total = 0.02235
        expected = Decimal("0.022350")
        assert cost == expected

    def test_zero_tokens(self):
        cost = estimate_cost(0, 0, 3.0, 15.0)
        assert cost == Decimal("0.000000")


class TestLogAiUsage:
    @pytest.mark.asyncio
    async def test_creates_log_entry(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        await log_ai_usage(
            session=mock_session,
            project_id="proj-123",
            user_id="user-456",
            source="chat",
            model="us.anthropic.claude-sonnet-4-6",
            input_tokens=3200,
            output_tokens=850,
        )

        mock_session.add.assert_called_once()
        log_entry = mock_session.add.call_args[0][0]
        assert log_entry.project_id == "proj-123"
        assert log_entry.source == "chat"
        assert log_entry.input_tokens == 3200
        assert log_entry.output_tokens == 850
        assert log_entry.estimated_cost_usd is not None
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_no_user_id(self):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        await log_ai_usage(
            session=mock_session,
            project_id="proj-123",
            user_id=None,
            source="mcp",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
        )

        log_entry = mock_session.add.call_args[0][0]
        assert log_entry.user_id is None

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self):
        """Usage logging should never break the main flow."""
        mock_session = AsyncMock()
        mock_session.commit.side_effect = Exception("DB error")

        # Should not raise
        await log_ai_usage(
            session=mock_session,
            project_id="proj-123",
            user_id="user-1",
            source="chat",
            model="model-1",
            input_tokens=100,
            output_tokens=50,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_usage_logging.py -v`
Expected: FAIL — `app.ai.usage_logging` not found.

- [ ] **Step 3: Implement the usage logging helper**

```python
# app/ai/usage_logging.py
"""AI usage logging — records token usage and estimated cost to PostgreSQL.

This module is intentionally fire-and-forget: logging failures are caught
and logged but never propagate to the caller. AI features should never
break because of usage tracking issues.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.db import AiUsageLog

logger = structlog.get_logger(__name__)


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    input_price_per_mtok: float,
    output_price_per_mtok: float,
) -> Decimal:
    """Estimate USD cost from token counts and per-million-token pricing.

    Returns a Decimal with 6 decimal places.
    """
    input_cost = Decimal(str(input_tokens)) / Decimal("1000000") * Decimal(str(input_price_per_mtok))
    output_cost = Decimal(str(output_tokens)) / Decimal("1000000") * Decimal(str(output_price_per_mtok))
    total = input_cost + output_cost
    return total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


async def log_ai_usage(
    project_id: str,
    user_id: str | None,
    source: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Record an AI usage entry to the database.

    Estimates cost using configured pricing. Silently catches and logs
    any errors — usage tracking must never break AI features.
    """
    try:
        settings = get_settings()
        cost = estimate_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_price_per_mtok=settings.ai_cost_input_per_mtok,
            output_price_per_mtok=settings.ai_cost_output_per_mtok,
        )

        # Use a separate session to avoid interfering with caller's transaction
        from app.services.postgres import get_background_session
        async with get_background_session() as usage_session:
            entry = AiUsageLog(
                project_id=project_id,
                user_id=user_id,
                source=source,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=cost,
            )
            usage_session.add(entry)
            await usage_session.commit()

        logger.info(
            "ai_usage_logged",
            project_id=project_id,
            source=source,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=str(cost),
        )
    except Exception as exc:
        logger.warning(
            "ai_usage_logging_failed",
            error=str(exc),
            project_id=project_id,
            source=source,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_usage_logging.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/ai/usage_logging.py tests/unit/test_usage_logging.py
git commit -m "feat(5b-m5): add AI usage logging helper with cost estimation"
```

---

## Task 6: Backend Lint + Full Test Pass

**Files:**
- No new files — verification only

- [ ] **Step 1: Run linting**

Run: `cd cast-clone-backend && uv run ruff check app/ai/usage_logging.py app/api/ai_usage.py app/schemas/ai_usage.py`
Expected: No errors.

- [ ] **Step 2: Run type checking**

Run: `cd cast-clone-backend && uv run mypy app/ai/usage_logging.py app/api/ai_usage.py app/schemas/ai_usage.py --ignore-missing-imports`
Expected: No errors (or only pre-existing ones).

- [ ] **Step 3: Run full unit test suite**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v --tb=short`
Expected: All tests pass.

---

## Task 7: Frontend — API Client Functions

**Files:**
- Modify: `cast-clone-frontend/lib/api.ts`
- Modify: `cast-clone-frontend/lib/types.ts`

- [ ] **Step 1: Add TypeScript types**

In `cast-clone-frontend/lib/types.ts`, add the following types:

```typescript
// ── API Keys (M4 endpoints) ──

export interface ApiKeyResponse {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  is_active: boolean;
}

export interface ApiKeyCreateResponse {
  id: string;
  name: string;
  raw_key: string;
}

// ── AI Usage (M5 endpoints) ──

export interface UsageBySourceItem {
  source: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  count: number;
}

export interface UsageByProjectItem {
  project_id: string;
  project_name: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  count: number;
}

export interface UsageSummaryResponse {
  total_input_tokens: number;
  total_output_tokens: number;
  total_estimated_cost_usd: number;
  by_source: UsageBySourceItem[];
  by_project: UsageByProjectItem[];
}
```

- [ ] **Step 2: Add API client functions**

In `cast-clone-frontend/lib/api.ts`, add the following functions:

```typescript
// ── API Keys (M4 endpoints, consumed by M5 UI) ──

export async function listApiKeys(): Promise<ApiKeyResponse[]> {
  return apiFetch<ApiKeyResponse[]>("/api/v1/api-keys");
}

export async function createApiKey(name: string): Promise<ApiKeyCreateResponse> {
  return apiFetch<ApiKeyCreateResponse>("/api/v1/api-keys", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function revokeApiKey(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/api-keys/${id}`, { method: "DELETE" });
}

// ── AI Usage (M5 endpoints) ──

export async function getAiUsageSummary(
  days: number = 30,
): Promise<UsageSummaryResponse> {
  return apiFetch<UsageSummaryResponse>(
    `/api/v1/admin/ai-usage?days=${days}`,
  );
}
```

Also add the new types to the import block at the top of `api.ts`:

```typescript
import type {
  // ... existing imports ...
  ApiKeyResponse,
  ApiKeyCreateResponse,
  UsageSummaryResponse,
} from "./types";
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No new errors.

- [ ] **Step 4: Commit**

```bash
cd cast-clone-frontend && git add lib/api.ts lib/types.ts
git commit -m "feat(5b-m5): add API key and AI usage client functions"
```

---

## Task 8: Frontend — ApiKeyTable Component

**Files:**
- Create: `cast-clone-frontend/components/settings/ApiKeyTable.tsx`

- [ ] **Step 1: Create the component**

```tsx
// cast-clone-frontend/components/settings/ApiKeyTable.tsx
"use client";

import { useState } from "react";
import type { ApiKeyResponse } from "@/lib/types";
import { revokeApiKey } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Trash2, Key } from "lucide-react";

interface ApiKeyTableProps {
  keys: ApiKeyResponse[];
  onKeyRevoked: () => void;
}

export function ApiKeyTable({ keys, onKeyRevoked }: ApiKeyTableProps) {
  const [revoking, setRevoking] = useState<string | null>(null);

  async function handleRevoke(id: string) {
    if (!confirm("Are you sure you want to revoke this API key? This action cannot be undone.")) {
      return;
    }
    setRevoking(id);
    try {
      await revokeApiKey(id);
      onKeyRevoked();
    } catch (err) {
      console.error("Failed to revoke key:", err);
    } finally {
      setRevoking(null);
    }
  }

  if (keys.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        <Key className="mx-auto mb-3 h-8 w-8 opacity-50" />
        <p>No API keys yet. Create one to connect external AI tools.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/50">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Name</th>
            <th className="px-4 py-3 text-left font-medium">Created</th>
            <th className="px-4 py-3 text-left font-medium">Last Used</th>
            <th className="px-4 py-3 text-left font-medium">Status</th>
            <th className="px-4 py-3 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key.id} className="border-b last:border-0">
              <td className="px-4 py-3 font-mono text-sm">{key.name}</td>
              <td className="px-4 py-3 text-muted-foreground">
                {new Date(key.created_at).toLocaleDateString()}
              </td>
              <td className="px-4 py-3 text-muted-foreground">
                {key.last_used_at
                  ? new Date(key.last_used_at).toLocaleDateString()
                  : "Never"}
              </td>
              <td className="px-4 py-3">
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                    key.is_active
                      ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                      : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                  }`}
                >
                  {key.is_active ? "Active" : "Revoked"}
                </span>
              </td>
              <td className="px-4 py-3 text-right">
                {key.is_active && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleRevoke(key.id)}
                    disabled={revoking === key.id}
                    className="text-red-600 hover:text-red-700"
                  >
                    <Trash2 className="mr-1 h-4 w-4" />
                    {revoking === key.id ? "Revoking..." : "Revoke"}
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No new errors.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/settings/ApiKeyTable.tsx
git commit -m "feat(5b-m5): add ApiKeyTable component"
```

---

## Task 9: Frontend — CreateKeyModal Component

**Files:**
- Create: `cast-clone-frontend/components/settings/CreateKeyModal.tsx`

- [ ] **Step 1: Create the component**

```tsx
// cast-clone-frontend/components/settings/CreateKeyModal.tsx
"use client";

import { useState } from "react";
import { createApiKey } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Copy, Check, AlertTriangle, X } from "lucide-react";

interface CreateKeyModalProps {
  open: boolean;
  onClose: () => void;
  onKeyCreated: () => void;
}

export function CreateKeyModal({ open, onClose, onKeyCreated }: CreateKeyModalProps) {
  const [name, setName] = useState("");
  const [rawKey, setRawKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const result = await createApiKey(name.trim());
      setRawKey(result.raw_key);
      onKeyCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create key");
    } finally {
      setCreating(false);
    }
  }

  async function handleCopy() {
    if (!rawKey) return;
    await navigator.clipboard.writeText(rawKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleClose() {
    setName("");
    setRawKey(null);
    setCopied(false);
    setError(null);
    onClose();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg bg-background p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {rawKey ? "API Key Created" : "Create API Key"}
          </h2>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        {rawKey ? (
          <div className="space-y-4">
            <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-950/30">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <p className="text-sm text-amber-800 dark:text-amber-300">
                Copy this key now. It will not be shown again.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 overflow-x-auto rounded border bg-muted p-3 font-mono text-sm">
                {rawKey}
              </code>
              <Button variant="outline" size="sm" onClick={handleCopy}>
                {copied ? (
                  <Check className="h-4 w-4 text-green-600" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
            <Button onClick={handleClose} className="w-full">
              Done
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label htmlFor="key-name" className="mb-1 block text-sm font-medium">
                Key Name
              </label>
              <input
                id="key-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Claude Code, Cursor, VS Code"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                autoFocus
              />
            </div>
            {error && (
              <p className="text-sm text-red-600">{error}</p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                onClick={handleCreate}
                disabled={!name.trim() || creating}
              >
                {creating ? "Creating..." : "Create Key"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No new errors.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/settings/CreateKeyModal.tsx
git commit -m "feat(5b-m5): add CreateKeyModal with one-time key display and copy"
```

---

## Task 10: Frontend — McpSetupGuide Component

**Files:**
- Create: `cast-clone-frontend/components/settings/McpSetupGuide.tsx`

- [ ] **Step 1: Create the component**

```tsx
// cast-clone-frontend/components/settings/McpSetupGuide.tsx
"use client";

import { useState } from "react";
import { Copy, Check, Terminal, Code, Wand2 } from "lucide-react";

const SETUP_SNIPPETS = [
  {
    id: "claude-code",
    name: "Claude Code",
    icon: Terminal,
    description: "Add CodeLens as an MCP server in Claude Code CLI.",
    command: `claude mcp add codelens -- http://localhost:8090/mcp`,
    note: "Run this in your terminal. You'll be prompted for the API key.",
  },
  {
    id: "vscode",
    name: "VS Code (Copilot)",
    icon: Code,
    description: "Add to your VS Code MCP configuration.",
    command: `{
  "servers": {
    "codelens": {
      "type": "sse",
      "url": "http://localhost:8090/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}`,
    note: "Add this to .vscode/mcp.json in your workspace.",
  },
  {
    id: "cursor",
    name: "Cursor",
    icon: Wand2,
    description: "Configure CodeLens MCP in Cursor settings.",
    command: `{
  "mcpServers": {
    "codelens": {
      "url": "http://localhost:8090/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}`,
    note: "Add to Cursor Settings > MCP > Add Server, or edit ~/.cursor/mcp.json.",
  },
];

export function McpSetupGuide() {
  const [copiedId, setCopiedId] = useState<string | null>(null);

  async function handleCopy(id: string, text: string) {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">MCP Setup Guide</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect external AI tools to CodeLens using the MCP protocol.
          Create an API key above, then use these snippets to configure your tool.
        </p>
      </div>

      <div className="space-y-3">
        {SETUP_SNIPPETS.map((snippet) => {
          const Icon = snippet.icon;
          return (
            <div
              key={snippet.id}
              className="rounded-lg border p-4"
            >
              <div className="mb-2 flex items-center gap-2">
                <Icon className="h-5 w-5 text-muted-foreground" />
                <h4 className="font-medium">{snippet.name}</h4>
              </div>
              <p className="mb-3 text-sm text-muted-foreground">
                {snippet.description}
              </p>
              <div className="relative">
                <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-sm">
                  {snippet.command}
                </pre>
                <button
                  onClick={() => handleCopy(snippet.id, snippet.command)}
                  className="absolute right-2 top-2 rounded p-1 hover:bg-background/80"
                  title="Copy to clipboard"
                >
                  {copiedId === snippet.id ? (
                    <Check className="h-4 w-4 text-green-600" />
                  ) : (
                    <Copy className="h-4 w-4 text-muted-foreground" />
                  )}
                </button>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">{snippet.note}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No new errors.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/settings/McpSetupGuide.tsx
git commit -m "feat(5b-m5): add McpSetupGuide with copy-paste snippets"
```

---

## Task 11: Frontend — API Keys Settings Page

**Files:**
- Create: `cast-clone-frontend/app/settings/api-keys/page.tsx`

- [ ] **Step 1: Create the page**

```tsx
// cast-clone-frontend/app/settings/api-keys/page.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { listApiKeys } from "@/lib/api";
import type { ApiKeyResponse } from "@/lib/types";
import { ApiKeyTable } from "@/components/settings/ApiKeyTable";
import { CreateKeyModal } from "@/components/settings/CreateKeyModal";
import { McpSetupGuide } from "@/components/settings/McpSetupGuide";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";

export default function ApiKeysSettingsPage() {
  const { user } = useAuth();
  const [keys, setKeys] = useState<ApiKeyResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);

  const loadKeys = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listApiKeys();
      setKeys(data);
    } catch {
      // User may not have access
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  const isAdmin = user?.role === "admin";

  return (
    <div className="space-y-8 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">API Keys</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage API keys for MCP server access by external AI tools.
          </p>
        </div>
        {isAdmin && (
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create Key
          </Button>
        )}
      </div>

      {loading ? (
        <div className="py-12 text-center text-muted-foreground">Loading...</div>
      ) : (
        <ApiKeyTable keys={keys} onKeyRevoked={loadKeys} />
      )}

      <hr className="my-8 border-border" />

      <McpSetupGuide />

      <CreateKeyModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onKeyCreated={loadKeys}
      />
    </div>
  );
}
```

- [ ] **Step 2: Add "API Keys" to the settings navigation**

The settings page navigation is in the layout or sidebar that renders the settings tabs. Find the navigation items (System, Team, Activity) and add an "API Keys" entry:

```typescript
{ label: "API Keys", href: "/settings/api-keys", icon: Key }
```

Add it after the "Team" entry. Import `Key` from `lucide-react`.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No new errors.

- [ ] **Step 4: Manual verification**

Start the dev server: `cd cast-clone-frontend && npm run dev`

Navigate to `http://localhost:3000/settings/api-keys`:
- The page should render with a header, empty state (no keys), and the MCP Setup Guide.
- The "Create Key" button should be visible (admin mode when auth disabled).
- The three setup snippets (Claude Code, VS Code, Cursor) should render with copy buttons.

- [ ] **Step 5: Commit**

```bash
cd cast-clone-frontend && git add app/settings/api-keys/page.tsx
git commit -m "feat(5b-m5): add API Keys settings page with key management and MCP guide"
```

---

## Task 12: Frontend — AiUsageDashboard Component

**Files:**
- Create: `cast-clone-frontend/components/admin/AiUsageDashboard.tsx`

- [ ] **Step 1: Create the component**

```tsx
// cast-clone-frontend/components/admin/AiUsageDashboard.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { getAiUsageSummary } from "@/lib/api";
import type { UsageSummaryResponse } from "@/lib/types";
import { Activity, DollarSign, Zap, BarChart3 } from "lucide-react";

function formatTokens(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
  return String(count);
}

function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    chat: "AI Chat",
    summary: "AI Summaries",
    pr_analysis: "PR Analysis",
    mcp: "MCP Server",
  };
  return labels[source] || source;
}

interface StatCardProps {
  label: string;
  value: string;
  icon: React.ReactNode;
}

function StatCard({ label, value, icon }: StatCardProps) {
  return (
    <div className="rounded-lg border p-4">
      <div className="flex items-center gap-2 text-muted-foreground">
        {icon}
        <span className="text-sm font-medium">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-bold">{value}</p>
    </div>
  );
}

interface AiUsageDashboardProps {
  className?: string;
}

export function AiUsageDashboard({ className }: AiUsageDashboardProps) {
  const [data, setData] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getAiUsageSummary(days);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load usage data");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return <div className="py-12 text-center text-muted-foreground">Loading usage data...</div>;
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
        {error}
      </div>
    );
  }

  if (!data) return null;

  const totalTokens = data.total_input_tokens + data.total_output_tokens;

  return (
    <div className={className}>
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold">AI Usage</h3>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded-md border bg-background px-2 py-1 text-sm"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      {/* Summary Cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard
          label="Total Tokens"
          value={formatTokens(totalTokens)}
          icon={<Zap className="h-4 w-4" />}
        />
        <StatCard
          label="Estimated Cost"
          value={formatCost(data.total_estimated_cost_usd)}
          icon={<DollarSign className="h-4 w-4" />}
        />
        <StatCard
          label="API Calls"
          value={String(data.by_source.reduce((sum, s) => sum + s.count, 0))}
          icon={<Activity className="h-4 w-4" />}
        />
      </div>

      {/* Breakdown by Source */}
      {data.by_source.length > 0 && (
        <div className="mb-6">
          <h4 className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <BarChart3 className="h-4 w-4" />
            Breakdown by Source
          </h4>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Source</th>
                  <th className="px-4 py-2 text-right font-medium">Calls</th>
                  <th className="px-4 py-2 text-right font-medium">Input Tokens</th>
                  <th className="px-4 py-2 text-right font-medium">Output Tokens</th>
                  <th className="px-4 py-2 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.by_source.map((s) => (
                  <tr key={s.source} className="border-b last:border-0">
                    <td className="px-4 py-2">{sourceLabel(s.source)}</td>
                    <td className="px-4 py-2 text-right">{s.count}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {formatTokens(s.input_tokens)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {formatTokens(s.output_tokens)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {formatCost(s.estimated_cost_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Breakdown by Project */}
      {data.by_project.length > 0 && (
        <div>
          <h4 className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <BarChart3 className="h-4 w-4" />
            Usage by Project
          </h4>
          <div className="space-y-2">
            {data.by_project.map((p) => {
              const pct =
                data.total_estimated_cost_usd > 0
                  ? (p.estimated_cost_usd / data.total_estimated_cost_usd) * 100
                  : 0;
              return (
                <div key={p.project_id} className="rounded-lg border p-3">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-sm font-medium">{p.project_name}</span>
                    <span className="text-sm font-mono text-muted-foreground">
                      {formatCost(p.estimated_cost_usd)}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-muted">
                    <div
                      className="h-2 rounded-full bg-primary"
                      style={{ width: `${Math.max(pct, 1)}%` }}
                    />
                  </div>
                  <div className="mt-1 flex justify-between text-xs text-muted-foreground">
                    <span>{p.count} calls</span>
                    <span>
                      {formatTokens(p.input_tokens)} in / {formatTokens(p.output_tokens)} out
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {data.by_source.length === 0 && data.by_project.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          No AI usage recorded in this time period.
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No new errors.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/admin/AiUsageDashboard.tsx
git commit -m "feat(5b-m5): add AiUsageDashboard with token/cost breakdown"
```

---

## Task 13: Frontend — Integrate Dashboard into API Keys Page

**Files:**
- Modify: `cast-clone-frontend/app/settings/api-keys/page.tsx`

- [ ] **Step 1: Add the dashboard to the API Keys page**

In `cast-clone-frontend/app/settings/api-keys/page.tsx`, add the import:

```typescript
import { AiUsageDashboard } from "@/components/admin/AiUsageDashboard";
```

Then add the dashboard section after the `McpSetupGuide` component and before the closing `</div>`:

```tsx
      {isAdmin && (
        <>
          <hr className="my-8 border-border" />
          <AiUsageDashboard />
        </>
      )}
```

- [ ] **Step 2: Manual verification**

Start the dev server: `cd cast-clone-frontend && npm run dev`

Navigate to `http://localhost:3000/settings/api-keys`:
- The API key table should render (empty state or with keys if M4 backend is running).
- The MCP Setup Guide section should show three tool configurations.
- The AI Usage dashboard should appear at the bottom (showing empty state or data).
- The time period selector (7/30/90 days) should work.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add app/settings/api-keys/page.tsx
git commit -m "feat(5b-m5): integrate AiUsageDashboard into API Keys settings page"
```

---

## Task 14: Integration Smoke Test

**Files:**
- No new files — verification only

- [ ] **Step 1: Run backend linting**

Run: `cd cast-clone-backend && uv run ruff check app/ai/usage_logging.py app/api/ai_usage.py app/schemas/ai_usage.py app/models/db.py`
Expected: No errors.

- [ ] **Step 2: Run backend type checking**

Run: `cd cast-clone-backend && uv run mypy app/ai/usage_logging.py app/api/ai_usage.py app/schemas/ai_usage.py --ignore-missing-imports`
Expected: No errors (or only pre-existing ones).

- [ ] **Step 3: Run full backend unit test suite**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v --tb=short`
Expected: All tests pass.

- [ ] **Step 4: Run frontend type check**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No new errors.

- [ ] **Step 5: Run frontend lint**

Run: `cd cast-clone-frontend && npm run lint`
Expected: No new errors.

- [ ] **Step 6: Verify usage endpoint with curl (requires running services)**

If services are running:

```bash
curl -s http://localhost:8000/api/v1/admin/ai-usage?days=30 | python3 -m json.tool
```

Expected: JSON response with `total_input_tokens`, `total_output_tokens`, `total_estimated_cost_usd`, `by_source`, `by_project` fields.

- [ ] **Step 7: Final commit with all files verified**

```bash
cd cast-clone-backend && git status
# Verify no uncommitted changes
```
