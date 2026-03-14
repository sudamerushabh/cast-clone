# Phase 5b-M2: On-Demand AI Summaries

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver on-demand AI-generated explanations for any code object in the architecture graph, cached in PostgreSQL with graph-hash invalidation, exposed via both a REST endpoint and a shared tool for the chat agent.

**Architecture:** A summary service in `app/ai/summaries.py` assembles structured context about a node (details + source code from the shared tool layer), sends a single Claude Sonnet call to generate a 2-3 paragraph explanation, and caches the result in PostgreSQL keyed by `(project_id, node_fqn)`. A SHA-256 graph hash (`fan_in:fan_out:sorted_neighbor_fqns`) detects staleness after re-analysis. A REST endpoint at `GET /api/v1/projects/{project_id}/summary/{node_fqn}` serves the "Explain this" button. A `get_or_generate_summary` tool is added to the shared tool layer so the chat agent can use summaries.

**Tech Stack:** Python 3.12, FastAPI, Anthropic SDK (`AsyncAnthropicBedrock`), SQLAlchemy 2.0 async, Pydantic v2, structlog, pytest + pytest-asyncio.

**BLOCKER:** M1 (Shared Tool Layer) must be fully implemented before starting this plan. Tasks 1-3 (config, schema, ORM model) can be done in parallel with M1, but Tasks 4+ depend on `app/ai/tools.py` and `ChatToolContext` created by M1.

---

## File Structure

```
app/ai/
└── summaries.py               # NEW -- summary generation + cache logic

app/api/
└── summaries.py               # NEW -- REST endpoint

app/schemas/
└── summaries.py               # NEW -- SummaryResponse Pydantic model

app/models/
└── db.py                      # MODIFY -- add AiSummary ORM model

app/ai/
├── tools.py                   # MODIFY -- add get_or_generate_summary tool
├── tool_definitions.py        # MODIFY -- add get_or_generate_summary definition
└── chat.py                    # MODIFY -- register get_or_generate_summary in _TOOL_HANDLERS

app/config.py                  # MODIFY -- add summary_* settings

app/api/__init__.py            # MODIFY -- register summary_router
app/main.py                    # MODIFY -- include summary_router

tests/unit/
├── test_summary_schemas.py    # NEW -- schema validation tests
├── test_summary_service.py    # NEW -- generation + cache logic tests
└── test_summary_endpoint.py   # NEW -- API endpoint tests
```

---

## Task 1: Config Additions

**Files:**
- Modify: `app/config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py (append to existing file)
def test_summary_settings_defaults():
    s = Settings(database_url="postgresql+asyncpg://x", neo4j_uri="bolt://x")
    assert s.summary_model == "us.anthropic.claude-sonnet-4-6"
    assert s.summary_max_tokens == 512
    assert s.summary_source_line_cap == 200
    assert s.summary_neighbor_limit == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_config.py::test_summary_settings_defaults -v`
Expected: FAIL -- `Settings` has no `summary_model` attribute.

- [ ] **Step 3: Add summary settings to config**

In `app/config.py`, add after the chat settings block:

```python
    # Phase 5b-M2: AI summaries
    summary_model: str = "us.anthropic.claude-sonnet-4-6"
    summary_max_tokens: int = 512
    summary_source_line_cap: int = 200
    summary_neighbor_limit: int = 20
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_config.py::test_summary_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/config.py tests/unit/test_config.py
git commit -m "feat(5b-m2): add summary configuration settings"
```

---

## Task 2: Summary Schema (Pydantic v2)

**Files:**
- Create: `app/schemas/summaries.py`
- Create: `tests/unit/test_summary_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_summary_schemas.py
"""Tests for summary response schemas."""
from app.schemas.summaries import SummaryResponse


class TestSummaryResponse:
    def test_cached_response(self):
        resp = SummaryResponse(
            fqn="com.app.OrderService",
            summary="OrderService handles order processing...",
            cached=True,
            model="us.anthropic.claude-sonnet-4-6",
        )
        assert resp.fqn == "com.app.OrderService"
        assert resp.cached is True
        assert resp.model == "us.anthropic.claude-sonnet-4-6"

    def test_generated_response(self):
        resp = SummaryResponse(
            fqn="com.app.OrderService",
            summary="OrderService handles order processing...",
            cached=False,
            model="us.anthropic.claude-sonnet-4-6",
            tokens_used=350,
        )
        assert resp.cached is False
        assert resp.tokens_used == 350

    def test_tokens_used_optional(self):
        resp = SummaryResponse(
            fqn="com.app.X",
            summary="X does things.",
            cached=True,
            model="model-1",
        )
        assert resp.tokens_used is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_schemas.py -v`
Expected: FAIL -- `app.schemas.summaries` not found.

- [ ] **Step 3: Create the schema**

```python
# app/schemas/summaries.py
"""Request/response models for the AI summary endpoint."""
from __future__ import annotations

from pydantic import BaseModel


class SummaryResponse(BaseModel):
    """Response from the summary endpoint."""
    fqn: str
    summary: str
    cached: bool
    model: str
    tokens_used: int | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/schemas/summaries.py tests/unit/test_summary_schemas.py
git commit -m "feat(5b-m2): add SummaryResponse Pydantic schema"
```

---

## Task 3: AiSummary ORM Model

**Files:**
- Modify: `app/models/db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_summary_schemas.py (append to file)
from app.models.db import AiSummary


class TestAiSummaryModel:
    def test_create_instance(self):
        summary = AiSummary(
            project_id="proj-123",
            node_fqn="com.app.OrderService",
            summary="OrderService handles order processing...",
            model="us.anthropic.claude-sonnet-4-6",
            graph_hash="abc123",
            tokens_used=350,
        )
        assert summary.project_id == "proj-123"
        assert summary.node_fqn == "com.app.OrderService"
        assert summary.summary == "OrderService handles order processing..."
        assert summary.model == "us.anthropic.claude-sonnet-4-6"
        assert summary.graph_hash == "abc123"
        assert summary.tokens_used == 350

    def test_table_name(self):
        assert AiSummary.__tablename__ == "ai_summaries"

    def test_unique_constraint(self):
        constraints = AiSummary.__table_args__
        found = False
        for c in constraints:
            if hasattr(c, "name") and c.name == "uq_summary_project_node":
                found = True
        assert found, "Expected UniqueConstraint 'uq_summary_project_node'"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_schemas.py::TestAiSummaryModel -v`
Expected: FAIL -- `AiSummary` not found in `app.models.db`.

- [ ] **Step 3: Add AiSummary model to db.py**

In `app/models/db.py`, add after the `PrAnalysis` class:

```python
class AiSummary(Base):
    __tablename__ = "ai_summaries"
    __table_args__ = (
        UniqueConstraint("project_id", "node_fqn", name="uq_summary_project_node"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    node_fqn: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    graph_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped[Project] = relationship()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_schemas.py::TestAiSummaryModel -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/models/db.py tests/unit/test_summary_schemas.py
git commit -m "feat(5b-m2): add AiSummary ORM model"
```

**Note:** An Alembic migration should be generated after this step (`uv run alembic revision --autogenerate -m "add ai_summaries table"`). The migration file itself is environment-dependent and not included in this plan.

---

## Task 4: Summary Service -- Graph Hash + Cache Logic

**Files:**
- Create: `app/ai/summaries.py`
- Create: `tests/unit/test_summary_service.py`

This is the core logic: compute graph hash, check cache, generate if stale, upsert.

- [ ] **Step 1: Write the tests**

```python
# tests/unit/test_summary_service.py
"""Tests for the AI summary service.

Mocks Anthropic client and database -- no external services needed.
"""
from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.summaries import (
    compute_graph_hash,
    assemble_node_context,
    generate_summary,
    get_or_create_summary,
)
from app.ai.tools import ChatToolContext


@pytest.fixture
def mock_graph_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def ctx(mock_graph_store: AsyncMock) -> ChatToolContext:
    return ChatToolContext(
        graph_store=mock_graph_store,
        app_name="test-app",
        project_id="proj-123",
        db_session=AsyncMock(),
    )


class TestComputeGraphHash:
    @pytest.mark.asyncio
    async def test_hash_deterministic(self, ctx: ChatToolContext):
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.Caller"}],  # callers
            [{"fqn": "com.app.Callee"}],  # callees
        ]
        h1 = await compute_graph_hash(ctx, "com.app.OrderService")

        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.Caller"}],
            [{"fqn": "com.app.Callee"}],
        ]
        h2 = await compute_graph_hash(ctx, "com.app.OrderService")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    @pytest.mark.asyncio
    async def test_hash_changes_on_neighbor_change(self, ctx: ChatToolContext):
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.A"}],
            [{"fqn": "com.app.B"}],
        ]
        h1 = await compute_graph_hash(ctx, "com.app.X")

        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.A"}, {"fqn": "com.app.C"}],  # new caller
            [{"fqn": "com.app.B"}],
        ]
        h2 = await compute_graph_hash(ctx, "com.app.X")
        assert h1 != h2

    @pytest.mark.asyncio
    async def test_hash_order_independent(self, ctx: ChatToolContext):
        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.B"}, {"fqn": "com.app.A"}],
            [],
        ]
        h1 = await compute_graph_hash(ctx, "com.app.X")

        ctx.graph_store.query.side_effect = [
            [{"fqn": "com.app.A"}, {"fqn": "com.app.B"}],
            [],
        ]
        h2 = await compute_graph_hash(ctx, "com.app.X")
        assert h1 == h2


class TestAssembleNodeContext:
    @pytest.mark.asyncio
    async def test_assembles_details_and_source(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = {
            "fqn": "com.app.OrderService", "name": "OrderService",
            "type": "Class", "language": "Java",
            "path": "src/OrderService.java", "line": 1, "end_line": 50, "loc": 50,
            "complexity": 5, "community_id": 1,
        }
        ctx.graph_store.query.side_effect = [
            [{"fqn": f"com.app.Caller{i}", "name": f"Caller{i}", "type": "Class"} for i in range(5)],
            [{"fqn": f"com.app.Callee{i}", "name": f"Callee{i}", "type": "Class"} for i in range(3)],
        ]
        result = await assemble_node_context(ctx, "com.app.OrderService")
        assert result["node"]["fqn"] == "com.app.OrderService"
        assert len(result["callers"]) == 5
        assert len(result["callees"]) == 3

    @pytest.mark.asyncio
    async def test_caps_callers_at_20(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = {
            "fqn": "com.app.X", "name": "X", "type": "Class",
            "language": "Java", "path": "X.java", "line": 1, "end_line": 10,
            "loc": 10, "complexity": 1, "community_id": None,
        }
        ctx.graph_store.query.side_effect = [
            [{"fqn": f"com.app.C{i}", "name": f"C{i}", "type": "Class"} for i in range(30)],
            [],
        ]
        result = await assemble_node_context(ctx, "com.app.X")
        assert len(result["callers"]) == 20

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_node(self, ctx: ChatToolContext):
        ctx.graph_store.query_single.return_value = None
        result = await assemble_node_context(ctx, "does.not.exist")
        assert result is None


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_calls_anthropic_and_returns_text(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="OrderService is responsible for...")]
        mock_response.usage.input_tokens = 500
        mock_response.usage.output_tokens = 200

        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response

        node_context = {
            "node": {"fqn": "com.app.OrderService", "name": "OrderService", "type": "Class"},
            "callers": [{"fqn": "com.app.A", "name": "A"}],
            "callees": [{"fqn": "com.app.B", "name": "B"}],
        }

        text, tokens = await generate_summary(
            client=mock_client,
            model="us.anthropic.claude-sonnet-4-6",
            max_tokens=512,
            node_context=node_context,
        )
        assert text == "OrderService is responsible for..."
        assert tokens == 700
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_includes_source_code_in_prompt(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Summary text")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response

        node_context = {
            "node": {"fqn": "com.app.X", "name": "X", "type": "Class"},
            "callers": [],
            "callees": [],
            "source_code": "1: public class X {\n2:   void run() {}\n3: }",
        }

        await generate_summary(
            client=mock_client,
            model="model-1",
            max_tokens=512,
            node_context=node_context,
        )
        call_args = mock_client.messages.create.call_args
        user_msg = call_args[1]["messages"][0]["content"]
        assert "public class X" in user_msg


class TestGetOrCreateSummary:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached(self, ctx: ChatToolContext):
        """When graph_hash matches, return cached summary without calling Anthropic."""
        mock_session = ctx.db_session
        mock_row = MagicMock()
        mock_row.summary = "Cached summary text"
        mock_row.model = "model-1"
        mock_row.graph_hash = "abc123"
        mock_row.tokens_used = 300

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_session.execute.return_value = mock_result

        with patch("app.ai.summaries.compute_graph_hash", return_value="abc123"):
            result = await get_or_create_summary(
                ctx=ctx,
                node_fqn="com.app.OrderService",
                client=AsyncMock(),
                model="model-1",
                max_tokens=512,
            )
        assert result["cached"] is True
        assert result["summary"] == "Cached summary text"

    @pytest.mark.asyncio
    async def test_cache_miss_generates_and_upserts(self, ctx: ChatToolContext):
        """When no cache exists, generate and upsert."""
        mock_session = ctx.db_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Generated summary")]
        mock_response.usage.input_tokens = 400
        mock_response.usage.output_tokens = 150
        mock_client.messages.create.return_value = mock_response

        with (
            patch("app.ai.summaries.compute_graph_hash", return_value="new_hash"),
            patch("app.ai.summaries.assemble_node_context", return_value={
                "node": {"fqn": "com.app.X", "name": "X", "type": "Class"},
                "callers": [], "callees": [],
            }),
        ):
            result = await get_or_create_summary(
                ctx=ctx,
                node_fqn="com.app.X",
                client=mock_client,
                model="model-1",
                max_tokens=512,
            )
        assert result["cached"] is False
        assert result["summary"] == "Generated summary"
        assert result["tokens_used"] == 550
        # Verify upsert was called
        assert mock_session.execute.call_count >= 2  # select + upsert

    @pytest.mark.asyncio
    async def test_stale_cache_regenerates(self, ctx: ChatToolContext):
        """When graph_hash differs, regenerate."""
        mock_session = ctx.db_session
        mock_row = MagicMock()
        mock_row.summary = "Old summary"
        mock_row.model = "model-1"
        mock_row.graph_hash = "old_hash"
        mock_row.tokens_used = 200

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_session.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Fresh summary")]
        mock_response.usage.input_tokens = 300
        mock_response.usage.output_tokens = 100
        mock_client.messages.create.return_value = mock_response

        with (
            patch("app.ai.summaries.compute_graph_hash", return_value="new_hash"),
            patch("app.ai.summaries.assemble_node_context", return_value={
                "node": {"fqn": "com.app.X", "name": "X", "type": "Class"},
                "callers": [], "callees": [],
            }),
        ):
            result = await get_or_create_summary(
                ctx=ctx,
                node_fqn="com.app.X",
                client=mock_client,
                model="model-1",
                max_tokens=512,
            )
        assert result["cached"] is False
        assert result["summary"] == "Fresh summary"

    @pytest.mark.asyncio
    async def test_missing_node_returns_error(self, ctx: ChatToolContext):
        """When node doesn't exist in graph, return error dict."""
        mock_session = ctx.db_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with (
            patch("app.ai.summaries.compute_graph_hash", return_value="hash"),
            patch("app.ai.summaries.assemble_node_context", return_value=None),
        ):
            result = await get_or_create_summary(
                ctx=ctx,
                node_fqn="does.not.exist",
                client=AsyncMock(),
                model="model-1",
                max_tokens=512,
            )
        assert "error" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_service.py -v`
Expected: FAIL -- `app.ai.summaries` not found.

- [ ] **Step 3: Implement the summary service**

```python
# app/ai/summaries.py
"""AI summary generation with PostgreSQL caching.

Generates natural-language explanations of code objects using a single
Claude Sonnet call. Caches results with graph-hash invalidation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from anthropic import AsyncAnthropicBedrock
from sqlalchemy import select, text

from app.ai.tools import ChatToolContext, object_details, get_source_code
from app.models.db import AiSummary

logger = structlog.get_logger(__name__)

SUMMARY_SYSTEM_PROMPT = (
    "You are an expert software architect. Explain what this code object does, "
    "its role in the architecture, and its key dependencies.\n\n"
    "Be concise (2-3 paragraphs). Reference specific class/method names. "
    "Focus on: what it does, who calls it, what it calls, and why it matters."
)


async def compute_graph_hash(ctx: ChatToolContext, node_fqn: str) -> str:
    """Compute SHA-256 hash of a node's graph neighborhood.

    Hash = SHA-256(fan_in:fan_out:sorted_neighbor_fqns)
    Changes when callers/callees change, triggering summary regeneration.
    """
    callers = await ctx.graph_store.query(
        "MATCH (caller)-[:CALLS]->(n {fqn: $fqn, app_name: $app_name}) "
        "RETURN caller.fqn AS fqn",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )
    callees = await ctx.graph_store.query(
        "MATCH (n {fqn: $fqn, app_name: $app_name})-[:CALLS]->(callee) "
        "RETURN callee.fqn AS fqn",
        {"fqn": node_fqn, "app_name": ctx.app_name},
    )
    fan_in = len(callers)
    fan_out = len(callees)
    neighbor_fqns = sorted(
        [r["fqn"] for r in callers] + [r["fqn"] for r in callees]
    )
    raw = f"{fan_in}:{fan_out}:{','.join(neighbor_fqns)}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def assemble_node_context(
    ctx: ChatToolContext,
    node_fqn: str,
    neighbor_limit: int = 20,
) -> dict[str, Any] | None:
    """Assemble structured context about a node for the summary prompt.

    Uses shared tool functions to fetch details and source code.
    Caps callers/callees at neighbor_limit (default 20).
    """
    details = await object_details(ctx, node_fqn=node_fqn)
    if details["node"] is None:
        return None

    callers = details["callers"][:neighbor_limit]
    callees = details["callees"][:neighbor_limit]

    result: dict[str, Any] = {
        "node": details["node"],
        "callers": callers,
        "callees": callees,
    }

    # Fetch source code (may return metadata-only if no repo)
    source = await get_source_code(ctx, node_fqn=node_fqn)
    if source.get("code"):
        result["source_code"] = source["code"]

    return result


async def generate_summary(
    client: AsyncAnthropicBedrock,
    model: str,
    max_tokens: int,
    node_context: dict[str, Any],
) -> tuple[str, int]:
    """Make a single Claude call to generate a node summary.

    Returns (summary_text, total_tokens_used).
    """
    user_content = json.dumps(node_context, default=str)

    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    summary_text = response.content[0].text
    tokens_used = response.usage.input_tokens + response.usage.output_tokens
    return summary_text, tokens_used


async def get_or_create_summary(
    ctx: ChatToolContext,
    node_fqn: str,
    client: AsyncAnthropicBedrock,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    """Get cached summary or generate a new one.

    Cache invalidation: compares SHA-256 graph hash of the node's
    neighborhood. If hash matches cached value, returns cache.
    Otherwise regenerates and upserts.
    """
    session = ctx.db_session
    current_hash = await compute_graph_hash(ctx, node_fqn)

    # Check cache
    result = await session.execute(
        select(AiSummary).where(
            AiSummary.project_id == ctx.project_id,
            AiSummary.node_fqn == node_fqn,
        )
    )
    cached = result.scalar_one_or_none()

    if cached and cached.graph_hash == current_hash:
        logger.info("summary.cache_hit", node_fqn=node_fqn)
        return {
            "fqn": node_fqn,
            "summary": cached.summary,
            "cached": True,
            "model": cached.model,
            "tokens_used": cached.tokens_used,
        }

    # Cache miss or stale -- generate
    node_context = await assemble_node_context(ctx, node_fqn)
    if node_context is None:
        return {"fqn": node_fqn, "error": f"Node not found: {node_fqn}"}

    logger.info("summary.generating", node_fqn=node_fqn, reason="stale" if cached else "miss")
    summary_text, tokens_used = await generate_summary(
        client=client,
        model=model,
        max_tokens=max_tokens,
        node_context=node_context,
    )

    # Upsert via SQLAlchemy dialect-specific insert (consistent with ORM patterns)
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models.db import AiSummary

    stmt = pg_insert(AiSummary).values(
        project_id=ctx.project_id,
        node_fqn=node_fqn,
        summary=summary_text,
        model=model,
        graph_hash=current_hash,
        tokens_used=tokens_used,
    ).on_conflict_do_update(
        index_elements=["project_id", "node_fqn"],
        set_={
            "summary": summary_text,
            "model": model,
            "graph_hash": current_hash,
            "tokens_used": tokens_used,
        },
    )
    await session.execute(stmt)
    await session.commit()

    return {
        "fqn": node_fqn,
        "summary": summary_text,
        "cached": False,
        "model": model,
        "tokens_used": tokens_used,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/ai/summaries.py tests/unit/test_summary_service.py
git commit -m "feat(5b-m2): add summary service with graph-hash cache invalidation"
```

---

## Task 5: Shared Tool Layer Integration

**Files:**
- Modify: `app/ai/tools.py` -- add `get_or_generate_summary` function
- Modify: `app/ai/tool_definitions.py` -- add tool definition
- Modify: `app/ai/chat.py` -- register in `_TOOL_HANDLERS`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_summary_service.py (append to file)
from app.ai.tools import get_or_generate_summary as tool_get_or_generate_summary


class TestGetOrGenerateSummaryTool:
    @pytest.mark.asyncio
    async def test_tool_delegates_to_service(self, ctx: ChatToolContext):
        """The shared tool wraps the summary service."""
        with patch("app.ai.tools.summaries_get_or_create_summary") as mock_svc:
            mock_svc.return_value = {
                "fqn": "com.app.X",
                "summary": "X does things.",
                "cached": True,
                "model": "model-1",
                "tokens_used": 100,
            }
            result = await tool_get_or_generate_summary(ctx, node_fqn="com.app.X")
            assert result["summary"] == "X does things."
            mock_svc.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_service.py::TestGetOrGenerateSummaryTool -v`
Expected: FAIL -- `get_or_generate_summary` not found in `app.ai.tools`.

- [ ] **Step 3: Add the tool function to `app/ai/tools.py`**

Append to `app/ai/tools.py`:

```python
# ── Summary Tools ────────────────────────────────────────────
# Added in M2. Requires db_session on ChatToolContext.

from app.ai.summaries import get_or_create_summary as summaries_get_or_create_summary


async def get_or_generate_summary(ctx: ChatToolContext, node_fqn: str) -> dict:
    """Get AI summary for a node. Returns cached if available, generates if not."""
    from anthropic import AsyncAnthropicBedrock
    from app.config import get_settings

    settings = get_settings()
    client = AsyncAnthropicBedrock(aws_region=settings.aws_region)
    return await summaries_get_or_create_summary(
        ctx=ctx,
        node_fqn=node_fqn,
        client=client,
        model=settings.summary_model,
        max_tokens=settings.summary_max_tokens,
    )
```

- [ ] **Step 4: Add tool definition to `app/ai/tool_definitions.py`**

Append to the list returned by `get_chat_tool_definitions()`:

```python
        {
            "name": "get_or_generate_summary",
            "description": "Get an AI-generated explanation of a code object. Returns a cached summary if available, generates a new one if not. Use this when a user asks to explain or summarize a specific class, method, or module.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_fqn": {"type": "string", "description": "Fully qualified name of the node to summarize"},
                },
                "required": ["node_fqn"],
            },
        },
```

- [ ] **Step 5: Register in `_TOOL_HANDLERS` in `app/ai/chat.py`**

Add to the `_TOOL_HANDLERS` dict in `app/ai/chat.py`:

```python
    "get_or_generate_summary": lambda ctx, inp: get_or_generate_summary(ctx, node_fqn=inp["node_fqn"]),
```

And add the import at the top of `app/ai/chat.py`:

```python
from app.ai.tools import (
    # ... existing imports ...
    get_or_generate_summary,
)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_service.py::TestGetOrGenerateSummaryTool -v`
Expected: PASS

Also verify tool definitions still pass:

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_chat_tools.py::TestToolDefinitions -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd cast-clone-backend && git add app/ai/tools.py app/ai/tool_definitions.py app/ai/chat.py tests/unit/test_summary_service.py
git commit -m "feat(5b-m2): add get_or_generate_summary to shared tool layer"
```

---

## Task 6: REST Endpoint

**Files:**
- Create: `app/api/summaries.py`
- Create: `tests/unit/test_summary_endpoint.py`
- Modify: `app/api/__init__.py` -- register router
- Modify: `app/main.py` -- include router

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_summary_endpoint.py
"""Tests for the summary REST endpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def mock_dependencies():
    """Mock out DB session, auth, GraphStore, and Anthropic client."""
    with (
        patch("app.api.summaries.get_session") as mock_get_session,
        patch("app.api.summaries.get_current_user") as mock_auth,
        patch("app.api.summaries.get_or_create_summary") as mock_summary,
        patch("app.api.summaries.Neo4jGraphStore") as mock_gs_cls,
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value = mock_session

        mock_user = MagicMock()
        mock_user.id = "user-1"
        mock_auth.return_value = mock_user

        # Mock project lookup
        mock_project = MagicMock()
        mock_project.id = "proj-123"
        mock_project.neo4j_app_name = "test-app"
        mock_project.repository = MagicMock()
        mock_project.repository.local_path = "/tmp/repo"

        mock_proj_result = MagicMock()
        mock_proj_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_proj_result

        mock_gs.return_value = AsyncMock()

        yield {
            "session": mock_session,
            "auth": mock_auth,
            "summary": mock_summary,
            "project": mock_project,
            "graph_store": mock_gs,
        }


class TestSummaryEndpoint:
    @pytest.mark.asyncio
    async def test_get_summary_cached(self, mock_dependencies):
        mock_dependencies["summary"].return_value = {
            "fqn": "com.app.OrderService",
            "summary": "OrderService handles orders...",
            "cached": True,
            "model": "model-1",
            "tokens_used": 300,
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/projects/proj-123/summary/com.app.OrderService")

        assert resp.status_code == 200
        data = resp.json()
        assert data["fqn"] == "com.app.OrderService"
        assert data["cached"] is True

    @pytest.mark.asyncio
    async def test_get_summary_generated(self, mock_dependencies):
        mock_dependencies["summary"].return_value = {
            "fqn": "com.app.X",
            "summary": "Freshly generated",
            "cached": False,
            "model": "model-1",
            "tokens_used": 500,
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/projects/proj-123/summary/com.app.X")

        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] is False

    @pytest.mark.asyncio
    async def test_project_not_found(self, mock_dependencies):
        mock_proj_result = MagicMock()
        mock_proj_result.scalar_one_or_none.return_value = None
        mock_dependencies["session"].execute.return_value = mock_proj_result

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/projects/not-real/summary/com.app.X")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_node_not_found(self, mock_dependencies):
        mock_dependencies["summary"].return_value = {
            "fqn": "does.not.exist",
            "error": "Node not found: does.not.exist",
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/projects/proj-123/summary/does.not.exist")

        assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_endpoint.py -v`
Expected: FAIL -- `app.api.summaries` not found or route not registered.

- [ ] **Step 3: Implement the endpoint**

```python
# app/api/summaries.py
"""REST endpoint for on-demand AI summaries."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.summaries import get_or_create_summary
from app.ai.tools import ChatToolContext
from app.api.dependencies import get_current_user
from app.config import get_settings
from app.models.db import Project, User
from app.schemas.summaries import SummaryResponse
from app.services.neo4j import Neo4jGraphStore, get_driver
from app.services.postgres import get_session

router = APIRouter(prefix="/api/v1/projects", tags=["summaries"])


@router.get(
    "/{project_id}/summary/{node_fqn:path}",
    response_model=SummaryResponse,
    summary="Get AI summary for a code object",
)
async def get_summary(
    project_id: str,
    node_fqn: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SummaryResponse:
    """Get or generate an AI summary for a specific code object.

    Returns cached summary if the graph neighborhood hasn't changed.
    Generates a fresh summary otherwise via a single Claude Sonnet call.
    """
    # Look up project
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {project_id}",
        )

    settings = get_settings()
    graph_store = Neo4jGraphStore(get_driver())

    repo_path = None
    if project.repository and project.repository.local_path:
        repo_path = project.repository.local_path

    ctx = ChatToolContext(
        graph_store=graph_store,
        app_name=project.neo4j_app_name,
        project_id=project_id,
        repo_path=repo_path,
        db_session=session,
    )

    from anthropic import AsyncAnthropicBedrock

    client = AsyncAnthropicBedrock(aws_region=settings.aws_region)

    summary_result = await get_or_create_summary(
        ctx=ctx,
        node_fqn=node_fqn,
        client=client,
        model=settings.summary_model,
        max_tokens=settings.summary_max_tokens,
    )

    if "error" in summary_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=summary_result["error"],
        )

    return SummaryResponse(
        fqn=summary_result["fqn"],
        summary=summary_result["summary"],
        cached=summary_result["cached"],
        model=summary_result["model"],
        tokens_used=summary_result.get("tokens_used"),
    )
```

- [ ] **Step 4: Register the router**

In `app/api/__init__.py`, add:

```python
from app.api.summaries import router as summary_router
```

In `app/main.py`, add:

```python
app.include_router(summary_router)
```

(Follow the same pattern as existing router registrations in these files.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_endpoint.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/api/summaries.py app/api/__init__.py app/main.py tests/unit/test_summary_endpoint.py
git commit -m "feat(5b-m2): add GET /api/v1/projects/{id}/summary/{fqn} endpoint"
```

---

## Task 7: Full Integration Test

**Files:**
- Append to: `tests/unit/test_summary_service.py`

- [ ] **Step 1: Write an end-to-end test covering the full flow**

```python
# tests/unit/test_summary_service.py (append to file)

class TestFullFlow:
    @pytest.mark.asyncio
    async def test_miss_then_hit(self, ctx: ChatToolContext):
        """First call generates, second call returns cache."""
        mock_session = ctx.db_session

        # First call: cache miss
        mock_result_miss = MagicMock()
        mock_result_miss.scalar_one_or_none.return_value = None

        # Second call: cache hit
        mock_cached = MagicMock()
        mock_cached.summary = "Generated summary"
        mock_cached.model = "model-1"
        mock_cached.graph_hash = "hash123"
        mock_cached.tokens_used = 500
        mock_result_hit = MagicMock()
        mock_result_hit.scalar_one_or_none.return_value = mock_cached

        mock_session.execute.side_effect = [
            mock_result_miss,   # First select (miss)
            MagicMock(),        # First upsert
            mock_result_hit,    # Second select (hit)
        ]

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Generated summary")]
        mock_response.usage.input_tokens = 300
        mock_response.usage.output_tokens = 200
        mock_client.messages.create.return_value = mock_response

        with (
            patch("app.ai.summaries.compute_graph_hash", return_value="hash123"),
            patch("app.ai.summaries.assemble_node_context", return_value={
                "node": {"fqn": "com.app.X", "name": "X", "type": "Class"},
                "callers": [], "callees": [],
            }),
        ):
            # First call -- generates
            r1 = await get_or_create_summary(
                ctx=ctx, node_fqn="com.app.X",
                client=mock_client, model="model-1", max_tokens=512,
            )
            assert r1["cached"] is False
            assert mock_client.messages.create.call_count == 1

            # Second call -- cached
            r2 = await get_or_create_summary(
                ctx=ctx, node_fqn="com.app.X",
                client=mock_client, model="model-1", max_tokens=512,
            )
            assert r2["cached"] is True
            # Anthropic should NOT have been called again
            assert mock_client.messages.create.call_count == 1
```

- [ ] **Step 2: Run all summary tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_summary_service.py tests/unit/test_summary_schemas.py tests/unit/test_summary_endpoint.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add tests/unit/test_summary_service.py
git commit -m "test(5b-m2): add full-flow integration test for summary cache"
```

---

## Task 8: Run Full Test Suite

- [ ] **Step 1: Run all tests to verify nothing is broken**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v --tb=short`
Expected: ALL PASS -- no regressions.

- [ ] **Step 2: Run linting**

Run: `cd cast-clone-backend && uv run ruff check app/ai/summaries.py app/api/summaries.py app/schemas/summaries.py`
Expected: No errors.

Run: `cd cast-clone-backend && uv run ruff format --check app/ai/summaries.py app/api/summaries.py app/schemas/summaries.py`
Expected: No formatting issues.
