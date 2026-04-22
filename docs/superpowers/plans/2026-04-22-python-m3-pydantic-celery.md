# Python M3 — Pydantic Deep + Celery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two new Python framework plugins — `FastAPIPydanticPlugin` (deep Pydantic v1/v2 extraction + endpoint↔model linking + Pydantic↔ORM mapping) and `CeleryPlugin` (task discovery + queue extraction + producer linking) — and validate the full `endpoint → Pydantic → column` chain on `fastapi-todo` and the `endpoint → producer → task → queue` chain on `django-blog`.

**Architecture:** Additive. Two new `FrameworkPlugin` subclasses, two new `EdgeKind` values (`ACCEPTS`, `RETURNS`), no new `NodeKind`. The Pydantic plugin depends on the existing FastAPI plugin (topological order) and reuses `INHERITS` edges emitted by the Python tree-sitter extractor to find `BaseModel` subclasses. The Celery plugin stands alone and reuses `MESSAGE_TOPIC` (already in the enum) for queues. Writer code does not change — `apoc.merge.relationship(from, e.type, ...)` in `app/services/neo4j.py:191` takes the edge type dynamically, so new `EdgeKind`s flow through without schema work.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2 (also supports v1 patterns), SQLAlchemy 2.0 async, Celery, structlog, pytest, pytest-asyncio, ruff, mypy, uv.

---

## Prerequisites

1. **Python M1 (`feat/python-m1-scip-foundation`) must be merged to `main`** before M3 starts. M3 relies on SCIP-resolved Python symbols (`FastAPIPlugin` + `SQLAlchemyPlugin` run against SCIP-upgraded FQNs) and on the three scratch-authored fixtures (`fastapi-todo`, `django-blog`, `flask-inventory`) authored during M1.
2. **Python M2 (`feat/python-m2-django-sqlalchemy-alembic`) must be merged to `main`** before M3 starts. M3 asserts endpoint→Pydantic→column chains, which require the enriched async SQLAlchemy column extraction and the Alembic migration plugin from M2.
3. Worktree for M3: create `.claude/worktrees/python-m3/` with branch `feat/python-m3-pydantic-celery` off `main`. Do not start M3 inside the M1 or M2 worktree.
4. Confirm before starting: `git log --oneline main -n 5` shows both M1 and M2 merge commits, and `ls cast-clone-backend/tests/fixtures/fastapi-todo cast-clone-backend/tests/fixtures/django-blog` both succeed.

---

## Context Summary

### Plugin classes already present on `main` (after M1 + M2)

| Plugin | File | Emits |
|---|---|---|
| `FastAPIPlugin` | `app/stages/plugins/fastapi_plugin/routes.py` | `APIEndpoint` nodes, `HANDLES` edges, `INJECTS` edges (Depends), layer assignments |
| `SQLAlchemyPlugin` | `app/stages/plugins/sqlalchemy_plugin/models.py` | `TABLE` nodes, `COLUMN` nodes, `HAS_COLUMN` edges (sync + async after M2) |
| `DjangoSettingsPlugin` | `app/stages/plugins/django/settings.py` | `CONFIG_FILE`, `CONFIG_ENTRY` nodes (structured properties after M2) |
| `AlembicPlugin` | `app/stages/plugins/alembic_plugin/migrations.py` | migration `FUNCTION` nodes, `INHERITS` revision DAG, `READS`/`WRITES` table ops |

### Tree-sitter Python extractor behavior

Relevant at `app/stages/treesitter/extractors/python.py`:

- Class base classes emit `INHERITS` edges with `target_fqn=<raw_identifier_text>` at `LOW` confidence (lines 341–354). For `class TodoCreate(BaseModel):` this emits `INHERITS (TodoCreate) -> (BaseModel)` where `BaseModel` is the raw identifier, not resolved. SCIP may later upgrade this edge's target to a resolved FQN.
- Function decorators are stored on the FUNCTION node as `properties["annotations"]: list[str]` (lines 471–476). Values are raw decorator source text including `@` and arguments, e.g., `'@shared_task(queue="notifications")'` or `'@field_validator("title")'`.
- Function params are stored as `properties["params"]: list[dict]`. Each dict has keys `name`, `type` (annotation source text or empty), `default` (source text or empty).
- Function return type is stored as `properties["return_type"]: str` (source text of the annotation after `->`).
- Class fields declared in the body are extracted by `_extract_class_body_fields` and emitted as `FIELD` nodes with `properties["value"]` containing the right-hand-side source text (e.g., `'Field(min_length=1, max_length=200)'`).

### GraphStore edge writing

Relevant at `app/services/neo4j.py:187-193`:

```python
cypher = """
UNWIND $batch AS e
MATCH (from {fqn: e.from_fqn, app_name: $app_name})
MATCH (to {fqn: e.to_fqn, app_name: $app_name})
CALL apoc.merge.relationship(from, e.type, {}, e.properties, to) YIELD rel
RETURN count(rel) AS cnt
"""
```

The edge type is dynamic (`e.type` sourced from `edge.kind.value`). Therefore **no writer code needs to change for M3** — adding `ACCEPTS` and `RETURNS` to the `EdgeKind` enum is sufficient for the edges to flow into Neo4j as `:ACCEPTS` and `:RETURNS` relationship types.

### Fixtures already authored during M1

- `tests/fixtures/fastapi-todo/app/schemas/todo.py` — Pydantic v2 models `TodoCreate`, `TodoRead`, `TodoUpdate` using class-body `Field(...)` form with `min_length`, `max_length`, `ge` constraints.
- `tests/fixtures/fastapi-todo/app/schemas/user.py` — analogous user schemas.
- `tests/fixtures/fastapi-todo/app/routes/todos.py` — endpoints using `response_model=TodoRead`, `data: TodoCreate` request-body pattern, `list[TodoRead]` return annotations.
- `tests/fixtures/django-blog/posts/tasks.py` — `@shared_task(queue="notifications")` and `@shared_task(queue="analytics")` tasks.
- `tests/fixtures/django-blog/posts/views.py` — producer call site `notify_post_published.delay(post.id)` inside `PostViewSet.perform_create`.
- `tests/fixtures/django-blog/blog_project/celery.py` — Celery app bootstrap.

**These fixtures already carry the exact patterns M3 plugins target. Do not re-author them. Extend only if a specific test reveals an unambiguous gap.**

### Coding conventions (from root `CLAUDE.md` and project `CLAUDE.md`)

- Python 3.12+, type hints everywhere, `async def` for I/O, `uv` (not `pip`).
- Dataclasses for internal models, Pydantic v2 for API boundaries.
- `ruff` for format and lint; `mypy` for typing.
- `structlog` JSON logging; log entry and exit per plugin with timing.
- Only stages 1 and 8 are fatal; every plugin's `extract()` must catch its own exceptions and surface them as warnings through `PluginResult.warnings`.
- Conventional commits scoped to the area: `feat(pydantic): ...`, `feat(celery): ...`, `test(integration): ...`, `docs(plans): ...`.

### Critical reviewer guidance

- **TDD:** every task writes the failing test first, runs it to confirm failure, then writes the minimum implementation. Commit boundaries are task boundaries — no multi-task commits.
- **Do not** touch existing Java / Spring / .NET plugin files. Any collateral change there is outside this plan and should be flagged.
- **Do not** add new `NodeKind` values. `FUNCTION`, `CLASS`, `FIELD`, `MESSAGE_TOPIC` already cover every concept M3 introduces.
- **Do not** introduce a config-service or "project settings" infrastructure for the per-project Pydantic↔ORM linking toggle. Use a module-level constant `ENABLE_PYDANTIC_ORM_LINKING = True` inside `pydantic.py`. Tests monkeypatch it. If the user later asks for per-project override, that is a follow-up milestone.

---

## File Structure

### New files

```
cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py
cast-clone-backend/app/stages/plugins/celery_plugin/__init__.py
cast-clone-backend/app/stages/plugins/celery_plugin/tasks.py
cast-clone-backend/app/stages/plugins/celery_plugin/producers.py
cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py
cast-clone-backend/tests/unit/test_celery_plugin.py
cast-clone-backend/tests/integration/test_python_m3_pipeline.py
```

### Modified files

```
cast-clone-backend/app/models/enums.py                     # +ACCEPTS, +RETURNS
cast-clone-backend/tests/unit/test_enums.py                # +enum coverage
cast-clone-backend/app/stages/plugins/fastapi_plugin/__init__.py  # export Pydantic plugin
cast-clone-backend/app/stages/plugins/__init__.py          # register both new plugins
cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md            # document new plugins
CLAUDE.md                                                  # Plugin Priority table: Python tier notes
```

### Not modified (by design)

- `app/services/neo4j.py` — edge type is dynamic via apoc; no writer branch change.
- `app/stages/writer.py` — passes through untouched.
- `app/models/context.py` — no new fields; per-plugin state lives in module-level constants or `PluginResult.warnings`.

---

## Test Strategy

### Unit tests

- `tests/unit/test_enums.py` — assert `EdgeKind.ACCEPTS == "ACCEPTS"` and `EdgeKind.RETURNS == "RETURNS"`.
- `tests/unit/test_pydantic_deep_plugin.py` — ~25 cases covering: detect positive/negative; Pydantic class tagging; class-body `Field` constraint extraction; `Annotated[...]` constraint extraction; validator tagging across all four decorator names; `ACCEPTS` edge emission; `RETURNS` edge emission; `MAPS_TO` matching (exact, ambiguous, disabled).
- `tests/unit/test_celery_plugin.py` — ~20 cases covering: detect positive/negative; task discovery across `@celery.task`, `@shared_task`, `@app.task`; queue extraction; `MESSAGE_TOPIC` node creation and dedup; `CONSUMES` edge; producer linking via `.delay()` / `.apply_async()` / `.s()` / `.signature()`; `PRODUCES` edge emission; entry-point emission with `kind="message_consumer"`.

Each unit test builds a synthetic `SymbolGraph` with pre-seeded nodes/edges (no file I/O, no subprocess). This keeps suite fast (<2 s total).

### Integration tests

- `tests/integration/test_python_m3_pipeline.py`:
  - `TestFastAPITodoPydanticChain` — runs Stages 1 through 5 on `tests/fixtures/fastapi-todo/`, skips writer, asserts the in-memory `SymbolGraph` contains: at least one `APIEndpoint`, `ACCEPTS` edge from that endpoint to a `TodoCreate`/`TodoUpdate`/similar CLASS node, `RETURNS` edge from that endpoint to a `TodoRead` CLASS node, `MAPS_TO` edge from a Pydantic FIELD (e.g., `TodoCreate.title`) to a SQLAlchemy COLUMN (e.g., `todos.title`).
  - `TestDjangoBlogCeleryChain` — runs Stages 1 through 5 on `tests/fixtures/django-blog/`, asserts: at least one `FUNCTION` node with `properties["framework"] == "celery"`, `MESSAGE_TOPIC` node named `"notifications"`, `CONSUMES` edge from `notify_post_published` → `notifications` topic, `PRODUCES` edge from the `PostViewSet.perform_create` caller → `notifications` topic.

Both integration tests skip Neo4j (pass `write_to_neo4j=False` or equivalent); they assert on the `AnalysisContext.graph` directly. The M1 integration test harness (`test_python_pipeline.py`) is the template — mirror its style.

### Acceptance

- Unit test coverage on new files ≥85%.
- `uv run ruff check app/ tests/ --diff` exits clean for the M3 diff.
- `uv run mypy app/stages/plugins/fastapi_plugin/pydantic.py app/stages/plugins/celery_plugin/` exits with 0 errors.
- No pre-existing suite regression. Baseline is the M2 merge commit.

---

## Commit Convention

All commit messages follow conventional commits:
- `feat(enums): ...` for `EdgeKind` additions
- `feat(pydantic): ...` for Pydantic plugin work
- `feat(celery): ...` for Celery plugin work
- `test(unit): ...` for unit tests
- `test(integration): ...` for integration tests
- `docs(plugins): ...` for documentation

Every task ends with exactly one commit. No squash, no amend.

---

## Tasks

### Task 1: Preflight reconnaissance (read-only, no commit)

**Files:** (none written)

**Purpose:** Confirm prerequisites and the exact on-disk state of fixtures + plugin files before making any change. Catch drift early.

- [ ] **Step 1: Confirm M1 and M2 are merged**

Run: `git log --oneline main | grep -iE "M1|M2|python-m1|python-m2" | head -5`

Expected: at least one entry mentioning M1 merge and one mentioning M2 merge. If either is missing, STOP — the implementer must not proceed. Report back with the full `git log --oneline main -n 15` output so the controller can decide whether to unblock.

- [ ] **Step 2: Confirm fixtures exist on disk**

Run:

```bash
ls cast-clone-backend/tests/fixtures/fastapi-todo/app/schemas/ \
   cast-clone-backend/tests/fixtures/fastapi-todo/app/routes/ \
   cast-clone-backend/tests/fixtures/django-blog/posts/ \
   cast-clone-backend/tests/fixtures/django-blog/blog_project/
```

Expected: both `todo.py` and `user.py` under `schemas/`, both `todos.py` and `users.py` under `routes/`, `tasks.py` + `views.py` + `models.py` under `posts/`, `celery.py` + `settings.py` under `blog_project/`. If anything is missing, STOP and report.

- [ ] **Step 3: Confirm current `EdgeKind` enum lacks `ACCEPTS` / `RETURNS`**

Run: `grep -n "ACCEPTS\|RETURNS" cast-clone-backend/app/models/enums.py`

Expected: no match. If `ACCEPTS` or `RETURNS` is already present, STOP and report — Task 2 must be replaced with a verification test instead of an enum addition.

- [ ] **Step 4: Inspect one Pydantic schema and one Celery tasks file**

Run:

```bash
head -40 cast-clone-backend/tests/fixtures/fastapi-todo/app/schemas/todo.py
head -40 cast-clone-backend/tests/fixtures/django-blog/posts/tasks.py
```

Record the observed `Field(...)` argument list shape and the observed `@shared_task(queue="...")` decorator shape. These shapes determine the regex patterns in later tasks; if they differ materially from the shapes documented in the Context Summary above, STOP and report.

- [ ] **Step 5: Inspect existing FastAPIPlugin emissions**

Run:

```bash
grep -n "ACCEPTS\|RETURNS\|response_model\|BaseModel" cast-clone-backend/app/stages/plugins/fastapi_plugin/routes.py
```

Expected: no matches for `ACCEPTS` / `RETURNS` / `BaseModel`. The existing plugin does not do Pydantic work and M3 must not modify it (the Pydantic plugin is a separate class).

- [ ] **Step 6: Do not commit anything**

This task is purely read-only reconnaissance. No files written, no commits made. Report findings to the controller in your summary.

---

### Task 2: Add `ACCEPTS` and `RETURNS` to `EdgeKind`

**Files:**
- Modify: `cast-clone-backend/app/models/enums.py:28-52`
- Modify: `cast-clone-backend/tests/unit/test_enums.py`

- [ ] **Step 1: Write the failing test**

Open `cast-clone-backend/tests/unit/test_enums.py`. If a test function covering `EdgeKind` already exists, extend it. Otherwise, append:

```python
from app.models.enums import EdgeKind


def test_edge_kind_includes_pydantic_endpoint_edges():
    assert EdgeKind.ACCEPTS == "ACCEPTS"
    assert EdgeKind.RETURNS == "RETURNS"
    assert EdgeKind("ACCEPTS") is EdgeKind.ACCEPTS
    assert EdgeKind("RETURNS") is EdgeKind.RETURNS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_enums.py::test_edge_kind_includes_pydantic_endpoint_edges -v`

Expected: FAIL with `AttributeError: ACCEPTS` or `ValueError: 'ACCEPTS' is not a valid EdgeKind`.

- [ ] **Step 3: Add the enum values**

Edit `cast-clone-backend/app/models/enums.py`. Inside the `EdgeKind` class, after `MIDDLEWARE_CHAIN = "MIDDLEWARE_CHAIN"` on line 52, add:

```python
    ACCEPTS = "ACCEPTS"
    RETURNS = "RETURNS"
```

So the end of `EdgeKind` becomes:

```python
    MIDDLEWARE_CHAIN = "MIDDLEWARE_CHAIN"
    ACCEPTS = "ACCEPTS"
    RETURNS = "RETURNS"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_enums.py -v`

Expected: PASS. Full `test_enums.py` should pass with no regressions.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/models/enums.py cast-clone-backend/tests/unit/test_enums.py
git commit -m "feat(enums): add ACCEPTS + RETURNS EdgeKinds for endpoint↔Pydantic links"
```

---

### Task 3: Scaffold `FastAPIPydanticPlugin` class

**Files:**
- Create: `cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py`
- Create: `cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py`

- [ ] **Step 1: Write the failing test**

Create `cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py`:

```python
"""Unit tests for FastAPIPydanticPlugin (M3)."""

from __future__ import annotations

import pytest

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph


def _ctx() -> AnalysisContext:
    return AnalysisContext(project_id="test-project")


def test_plugin_class_is_importable():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    plugin = FastAPIPydanticPlugin()
    assert plugin.name == "fastapi_pydantic"
    assert "python" in plugin.supported_languages
    assert "fastapi" in plugin.depends_on


def test_detect_returns_not_detected_when_no_basemodel_inherits():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    plugin = FastAPIPydanticPlugin()
    result = plugin.detect(ctx)
    assert result.confidence is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.stages.plugins.fastapi_plugin.pydantic'`.

- [ ] **Step 3: Create the skeleton**

Create `cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py`:

```python
"""FastAPI Pydantic deep-extraction plugin (M3).

Tags Pydantic BaseModel subclasses, extracts Field constraints from
class-body and Annotated forms, tags validator functions, and links
FastAPI endpoints to their request/response Pydantic models via
ACCEPTS and RETURNS edges. Optionally fuzzy-matches Pydantic fields
to SQLAlchemy columns via MAPS_TO edges.

Depends on FastAPIPlugin (must run first so APIEndpoint nodes exist)
and is best paired with SQLAlchemyPlugin (for MAPS_TO targets).
"""

from __future__ import annotations

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Module-level toggle for Pydantic→ORM MAPS_TO linking. Default ON per DD-2.
# Tests monkeypatch this constant; production runs never mutate it.
ENABLE_PYDANTIC_ORM_LINKING = True


class FastAPIPydanticPlugin(FrameworkPlugin):
    name = "fastapi_pydantic"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = ["fastapi"]

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        return PluginResult()

    def get_layer_classification(self) -> LayerRules:
        return LayerRules.empty()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: PASS (both cases).

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py \
        cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py
git commit -m "feat(pydantic): scaffold FastAPIPydanticPlugin skeleton"
```

---

### Task 4: Implement `detect()` via `BaseModel` INHERITS scan

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py`
- Modify: `cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_pydantic_deep_plugin.py`:

```python
def test_detect_high_when_basemodel_inherits_edge_present():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoCreate",
        name="TodoCreate",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn="BaseModel",
            kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW,
            evidence="tree-sitter",
        )
    )

    result = FastAPIPydanticPlugin().detect(ctx)

    assert result.confidence == Confidence.HIGH
    assert "Pydantic" in result.reason


def test_detect_recognises_qualified_basemodel():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="pkg.schemas.User",
        name="User",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn="pydantic.BaseModel",
            kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW,
        )
    )

    result = FastAPIPydanticPlugin().detect(ctx)

    assert result.confidence == Confidence.HIGH
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: the two new tests FAIL with `confidence is None`.

- [ ] **Step 3: Implement `detect()`**

Replace the `detect()` method body in `pydantic.py` with:

```python
    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        for edge in context.graph.edges:
            if edge.kind != EdgeKind.INHERITS:
                continue
            target = edge.target_fqn
            if target == "BaseModel" or target.endswith(".BaseModel"):
                return PluginDetectionResult(
                    confidence=Confidence.HIGH,
                    reason="Pydantic BaseModel subclass found via INHERITS edge",
                )
        return PluginDetectionResult.not_detected()
```

Add `EdgeKind` to the existing `from app.models.enums import ...` line so it reads:

```python
from app.models.enums import Confidence, EdgeKind
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: all four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py \
        cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py
git commit -m "feat(pydantic): detect Pydantic models via BaseModel INHERITS edges"
```

---

### Task 5: Tag Pydantic model classes in `extract()`

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py`
- Modify: `cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pydantic_deep_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_tags_pydantic_model_classes():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoCreate",
        name="TodoCreate",
        kind=NodeKind.CLASS,
        language="python",
    )
    non_model = GraphNode(
        fqn="app.services.TodoService",
        name="TodoService",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(non_model)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn="BaseModel",
            kind=EdgeKind.INHERITS,
        )
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    # Plugin does not duplicate the class node — it mutates the existing one.
    updated = ctx.graph.get_node(model.fqn)
    assert updated is not None
    assert updated.properties.get("is_pydantic_model") is True
    other = ctx.graph.get_node(non_model.fqn)
    assert other is not None
    assert other.properties.get("is_pydantic_model") is not True
    assert result.warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py::test_extract_tags_pydantic_model_classes -v`

Expected: FAIL (the current `extract()` returns an empty `PluginResult` and never mutates nodes).

- [ ] **Step 3: Implement the tagging pass**

Replace the `extract()` method body in `pydantic.py` with:

```python
    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("fastapi_pydantic_extract_start")

        graph = context.graph
        model_fqns = self._find_pydantic_model_fqns(graph)

        for fqn in model_fqns:
            node = graph.get_node(fqn)
            if node is not None:
                node.properties["is_pydantic_model"] = True

        log.info(
            "fastapi_pydantic_extract_complete",
            pydantic_models=len(model_fqns),
        )
        return PluginResult(warnings=[])

    def _find_pydantic_model_fqns(self, graph) -> set[str]:
        """Return FQNs of classes whose INHERITS edge points at BaseModel."""
        model_fqns: set[str] = set()
        for edge in graph.edges:
            if edge.kind != EdgeKind.INHERITS:
                continue
            target = edge.target_fqn
            if target == "BaseModel" or target.endswith(".BaseModel"):
                model_fqns.add(edge.source_fqn)
        return model_fqns
```

Remove the unused imports check. The final imports block in `pydantic.py` should read:

```python
from __future__ import annotations

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: all prior tests still PASS plus the new tagging test PASSES.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py \
        cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py
git commit -m "feat(pydantic): tag Pydantic model classes with is_pydantic_model=True"
```

---

### Task 6: Extract class-body `Field(...)` constraints

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py`
- Modify: `cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py`

**Background:** Tree-sitter Python extractor emits class-body fields as `FIELD` nodes with `properties["value"]` containing the RHS source text. For `title: str = Field(min_length=1, max_length=200)`, the `value` property is the literal string `'Field(min_length=1, max_length=200)'`. M3 parses that value with a tolerant regex.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pydantic_deep_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_parses_class_body_field_constraints():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoCreate",
        name="TodoCreate",
        kind=NodeKind.CLASS,
        language="python",
    )
    field_node = GraphNode(
        fqn="app.schemas.todo.TodoCreate.title",
        name="title",
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "type": "str",
            "value": "Field(min_length=1, max_length=200)",
        },
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(field_node)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn=field_node.fqn,
            kind=EdgeKind.CONTAINS,
        )
    )
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=model.fqn,
            target_fqn="BaseModel",
            kind=EdgeKind.INHERITS,
        )
    )

    await FastAPIPydanticPlugin().extract(ctx)

    updated = ctx.graph.get_node(field_node.fqn)
    assert updated is not None
    constraints = updated.properties.get("constraints")
    assert constraints == {"min_length": "1", "max_length": "200"}


@pytest.mark.asyncio
async def test_extract_parses_ge_and_le_numeric_constraints():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoCreate",
        name="TodoCreate",
        kind=NodeKind.CLASS,
        language="python",
    )
    owner_id = GraphNode(
        fqn="app.schemas.todo.TodoCreate.owner_id",
        name="owner_id",
        kind=NodeKind.FIELD,
        language="python",
        properties={"type": "int", "value": "Field(ge=1, le=1000)"},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(owner_id)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn=owner_id.fqn, kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    constraints = ctx.graph.get_node(owner_id.fqn).properties.get("constraints")
    assert constraints == {"ge": "1", "le": "1000"}


@pytest.mark.asyncio
async def test_extract_ignores_non_field_value():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="M",
        name="M",
        kind=NodeKind.CLASS,
        language="python",
    )
    plain = GraphNode(
        fqn="M.x",
        name="x",
        kind=NodeKind.FIELD,
        language="python",
        properties={"type": "int", "value": "42"},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(plain)
    ctx.graph.add_edge(GraphEdge(source_fqn="M", target_fqn="M.x", kind=EdgeKind.CONTAINS))
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    assert "constraints" not in ctx.graph.get_node(plain.fqn).properties
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: the three new constraint tests FAIL (no `constraints` property is populated).

- [ ] **Step 3: Implement the constraint extractor**

Insert this near the top of `pydantic.py` (below the `import` block, above `ENABLE_PYDANTIC_ORM_LINKING`):

```python
import re

# Matches a single kwarg inside a Field(...) call. Captures name and raw value.
# Tolerant: values may be numbers, quoted strings, tuples, or function refs.
_FIELD_KWARG_RE = re.compile(
    r"(\w+)\s*=\s*"
    r"(\"[^\"]*\"|'[^']*'|\([^)]*\)|\[[^\]]*\]|[^,)\s]+)"
)

_RECOGNISED_CONSTRAINTS = frozenset(
    {
        "min_length",
        "max_length",
        "ge",
        "gt",
        "le",
        "lt",
        "multiple_of",
        "pattern",
        "default",
        "max_digits",
        "decimal_places",
    }
)


def _parse_field_constraints(raw_value: str) -> dict[str, str]:
    """Pull recognised Pydantic Field() constraints out of a raw RHS string.

    Accepts both ``Field(min_length=3)`` (class-body) and bare ``min_length=3``
    (already stripped of outer ``Field(``). Returns an empty dict if the value
    does not look like a Pydantic Field call.
    """
    if "Field(" not in raw_value and "=" not in raw_value:
        return {}

    inside = raw_value
    field_start = raw_value.find("Field(")
    if field_start != -1:
        open_paren = raw_value.find("(", field_start)
        # Find matching close paren respecting nesting.
        depth = 0
        end = -1
        for idx in range(open_paren, len(raw_value)):
            ch = raw_value[idx]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = idx
                    break
        if end == -1:
            return {}
        inside = raw_value[open_paren + 1 : end]

    constraints: dict[str, str] = {}
    for match in _FIELD_KWARG_RE.finditer(inside):
        name = match.group(1)
        if name not in _RECOGNISED_CONSTRAINTS:
            continue
        raw = match.group(2).strip()
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            raw = raw[1:-1]
        constraints[name] = raw
    return constraints
```

Then expand `extract()` so it also walks FIELD nodes contained by Pydantic classes:

```python
    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("fastapi_pydantic_extract_start")

        graph = context.graph
        model_fqns = self._find_pydantic_model_fqns(graph)

        for fqn in model_fqns:
            node = graph.get_node(fqn)
            if node is not None:
                node.properties["is_pydantic_model"] = True

        constraints_applied = self._apply_field_constraints(graph, model_fqns)

        log.info(
            "fastapi_pydantic_extract_complete",
            pydantic_models=len(model_fqns),
            field_constraints=constraints_applied,
        )
        return PluginResult(warnings=[])

    def _apply_field_constraints(self, graph, model_fqns: set[str]) -> int:
        applied = 0
        for edge in graph.edges:
            if edge.kind != EdgeKind.CONTAINS:
                continue
            if edge.source_fqn not in model_fqns:
                continue
            field_node = graph.get_node(edge.target_fqn)
            if field_node is None or field_node.kind != NodeKind.FIELD:
                continue
            raw = field_node.properties.get("value", "")
            constraints = _parse_field_constraints(raw)
            if constraints:
                field_node.properties["constraints"] = constraints
                applied += 1
        return applied
```

Also add `NodeKind` to the enum import at the top:

```python
from app.models.enums import Confidence, EdgeKind, NodeKind
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: all existing + new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py \
        cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py
git commit -m "feat(pydantic): extract Field(...) constraints from class-body form"
```

---

### Task 7: Extract `Annotated[type, Field(...)]` constraints

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py`
- Modify: `cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py`

**Background:** Pydantic v2 recommends the `Annotated[str, Field(min_length=1)]` form. When a field uses this form, the tree-sitter extractor stores the annotation in `properties["type"]` (because the RHS is either empty or a plain default like `None`). So we must also scan `type` for `Field(...)` calls.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pydantic_deep_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_parses_annotated_field_constraints():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.User",
        name="User",
        kind=NodeKind.CLASS,
        language="python",
    )
    email_field = GraphNode(
        fqn="app.schemas.User.email",
        name="email",
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "type": "Annotated[str, Field(min_length=3, max_length=254)]",
            "value": "",
        },
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(email_field)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn=email_field.fqn, kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    constraints = ctx.graph.get_node(email_field.fqn).properties.get("constraints")
    assert constraints == {"min_length": "3", "max_length": "254"}


@pytest.mark.asyncio
async def test_extract_merges_constraints_from_type_and_value():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    # Defensive case: both type and value carry Field() — should merge,
    # with value taking precedence on key collision.
    f = GraphNode(
        fqn="M.x",
        name="x",
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "type": "Annotated[int, Field(ge=0)]",
            "value": "Field(le=100)",
        },
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(f)
    ctx.graph.add_edge(GraphEdge(source_fqn="M", target_fqn="M.x", kind=EdgeKind.CONTAINS))
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    constraints = ctx.graph.get_node("M.x").properties.get("constraints")
    assert constraints == {"ge": "0", "le": "100"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: the two new tests FAIL (constraints missing or partial).

- [ ] **Step 3: Update `_apply_field_constraints` to also scan `type`**

Replace `_apply_field_constraints` in `pydantic.py` with:

```python
    def _apply_field_constraints(self, graph, model_fqns: set[str]) -> int:
        applied = 0
        for edge in graph.edges:
            if edge.kind != EdgeKind.CONTAINS:
                continue
            if edge.source_fqn not in model_fqns:
                continue
            field_node = graph.get_node(edge.target_fqn)
            if field_node is None or field_node.kind != NodeKind.FIELD:
                continue
            combined: dict[str, str] = {}
            type_source = field_node.properties.get("type", "")
            value_source = field_node.properties.get("value", "")
            combined.update(_parse_field_constraints(type_source))
            combined.update(_parse_field_constraints(value_source))
            if combined:
                field_node.properties["constraints"] = combined
                applied += 1
        return applied
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py \
        cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py
git commit -m "feat(pydantic): extract Field constraints from Annotated[...] form"
```

---

### Task 8: Tag validator functions

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py`
- Modify: `cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py`

**Background:** Validator decorators look like `@field_validator("title")`, `@model_validator(mode="after")`, `@validator("title", pre=True)` (v1), `@root_validator` (v1). The function is under a Pydantic model class, so we restrict the scan to FUNCTION nodes whose parent (via `CONTAINS` edge) is a `is_pydantic_model` class.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pydantic_deep_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_tags_field_validator_function():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.User",
        name="User",
        kind=NodeKind.CLASS,
        language="python",
    )
    validator = GraphNode(
        fqn="app.schemas.User.normalise_email",
        name="normalise_email",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@field_validator("email")']},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(validator)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn=validator.fqn, kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    updated = ctx.graph.get_node(validator.fqn)
    assert updated.properties.get("is_validator") is True
    assert updated.properties.get("validator_kind") == "field_validator"
    assert updated.properties.get("target_field") == "email"


@pytest.mark.asyncio
async def test_extract_tags_model_validator_without_target_field():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    mv = GraphNode(
        fqn="M.check",
        name="check",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@model_validator(mode="after")']},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(mv)
    ctx.graph.add_edge(GraphEdge(source_fqn="M", target_fqn="M.check", kind=EdgeKind.CONTAINS))
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    props = ctx.graph.get_node("M.check").properties
    assert props.get("is_validator") is True
    assert props.get("validator_kind") == "model_validator"
    assert "target_field" not in props


@pytest.mark.asyncio
async def test_extract_tags_v1_validator_and_root_validator():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    v1 = GraphNode(
        fqn="M.v1",
        name="v1",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@validator("x", pre=True)']},
    )
    root = GraphNode(
        fqn="M.root",
        name="root",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ["@root_validator"]},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(v1)
    ctx.graph.add_node(root)
    ctx.graph.add_edge(GraphEdge(source_fqn="M", target_fqn="M.v1", kind=EdgeKind.CONTAINS))
    ctx.graph.add_edge(GraphEdge(source_fqn="M", target_fqn="M.root", kind=EdgeKind.CONTAINS))
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    await FastAPIPydanticPlugin().extract(ctx)

    v1_props = ctx.graph.get_node("M.v1").properties
    assert v1_props.get("validator_kind") == "validator"
    assert v1_props.get("target_field") == "x"
    root_props = ctx.graph.get_node("M.root").properties
    assert root_props.get("validator_kind") == "root_validator"
    assert "target_field" not in root_props
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: the three new tests FAIL.

- [ ] **Step 3: Implement validator tagging**

Add at module level in `pydantic.py`, near `_FIELD_KWARG_RE`:

```python
_VALIDATOR_DECORATOR_RE = re.compile(
    r"^@(field_validator|model_validator|validator|root_validator)\b"
    r"(?:\(\s*\"([^\"]+)\"|\(\s*'([^']+)'|)"
)
```

Extend `extract()` to call a new `_tag_validators` method:

```python
    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("fastapi_pydantic_extract_start")

        graph = context.graph
        model_fqns = self._find_pydantic_model_fqns(graph)

        for fqn in model_fqns:
            node = graph.get_node(fqn)
            if node is not None:
                node.properties["is_pydantic_model"] = True

        constraints_applied = self._apply_field_constraints(graph, model_fqns)
        validators_tagged = self._tag_validators(graph, model_fqns)

        log.info(
            "fastapi_pydantic_extract_complete",
            pydantic_models=len(model_fqns),
            field_constraints=constraints_applied,
            validators=validators_tagged,
        )
        return PluginResult(warnings=[])

    def _tag_validators(self, graph, model_fqns: set[str]) -> int:
        tagged = 0
        for edge in graph.edges:
            if edge.kind != EdgeKind.CONTAINS:
                continue
            if edge.source_fqn not in model_fqns:
                continue
            func = graph.get_node(edge.target_fqn)
            if func is None or func.kind != NodeKind.FUNCTION:
                continue
            for deco in func.properties.get("annotations", []):
                match = _VALIDATOR_DECORATOR_RE.match(deco)
                if not match:
                    continue
                kind = match.group(1)
                target = match.group(2) or match.group(3)
                func.properties["is_validator"] = True
                func.properties["validator_kind"] = kind
                if target:
                    func.properties["target_field"] = target
                tagged += 1
                break
        return tagged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py \
        cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py
git commit -m "feat(pydantic): tag validator functions with is_validator/validator_kind/target_field"
```

---

### Task 9: Emit `ACCEPTS` edges from endpoints to request-body models

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py`
- Modify: `cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py`

**Background:** Endpoint functions are FUNCTION nodes with a `HANDLES` edge to an `API_ENDPOINT` node. Their params include Pydantic model types — e.g., `data: TodoCreate`. The `param` dict has `type="TodoCreate"`. We resolve the type name to a Pydantic CLASS FQN by: (1) exact FQN match in same module, (2) endswith-`.TypeName` search across `is_pydantic_model` classes. If the param type matches no Pydantic model, skip.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pydantic_deep_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_emits_accepts_edge_for_body_param():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    # Pydantic model
    model = GraphNode(
        fqn="app.schemas.todo.TodoCreate",
        name="TodoCreate",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )
    # FastAPI endpoint handler
    handler = GraphNode(
        fqn="app.routes.todos.create_todo",
        name="create_todo",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={
            "params": [
                {"name": "data", "type": "TodoCreate", "default": ""},
                {"name": "session", "type": "AsyncSession", "default": "Depends(get_session)"},
            ],
            "return_type": "TodoRead",
        },
    )
    endpoint = GraphNode(
        fqn="POST:/todos",
        name="POST /todos",
        kind=NodeKind.API_ENDPOINT,
        language="python",
        properties={"method": "POST", "path": "/todos"},
    )
    ctx.graph.add_node(handler)
    ctx.graph.add_node(endpoint)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=handler.fqn,
            target_fqn=endpoint.fqn,
            kind=EdgeKind.HANDLES,
            confidence=Confidence.HIGH,
        )
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    accepts = [e for e in result.edges if e.kind == EdgeKind.ACCEPTS]
    assert len(accepts) == 1
    assert accepts[0].source_fqn == endpoint.fqn
    assert accepts[0].target_fqn == model.fqn
    assert accepts[0].confidence == Confidence.HIGH


@pytest.mark.asyncio
async def test_extract_accepts_skips_non_pydantic_types():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    handler = GraphNode(
        fqn="m.h",
        name="h",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"params": [{"name": "q", "type": "str", "default": ""}]},
    )
    endpoint = GraphNode(
        fqn="GET:/q", name="GET /q", kind=NodeKind.API_ENDPOINT, language="python"
    )
    ctx.graph.add_node(handler)
    ctx.graph.add_node(endpoint)
    ctx.graph.add_edge(
        GraphEdge(source_fqn="m.h", target_fqn="GET:/q", kind=EdgeKind.HANDLES)
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    assert [e for e in result.edges if e.kind == EdgeKind.ACCEPTS] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: two new tests FAIL — no edges returned.

- [ ] **Step 3: Implement ACCEPTS emission**

In `pydantic.py`, add a helper that resolves a type-annotation source string to a Pydantic model FQN, and extend `extract()` to build and return `ACCEPTS` edges.

Add imports if missing:

```python
from app.models.graph import GraphEdge
```

Add helper method inside the class:

```python
    def _resolve_pydantic_type(
        self,
        graph,
        type_source: str,
        model_fqns: set[str],
        scope_module: str,
    ) -> str | None:
        """Resolve a type-annotation string (e.g., 'TodoCreate' or 'list[TodoRead]')
        to a Pydantic model FQN. Returns None if no match.
        """
        if not type_source:
            return None

        # Strip generic wrappers: list[X], List[X], Optional[X], Union[X, None] → X.
        inner = type_source.strip()
        for wrapper in ("list[", "List[", "Optional[", "Union["):
            if inner.startswith(wrapper) and inner.endswith("]"):
                inner = inner[len(wrapper) : -1]
                # Drop a trailing ", None" for Union[X, None].
                if inner.endswith(", None"):
                    inner = inner[: -len(", None")]
                break

        inner = inner.split("|")[0].strip()  # `X | None` → `X`
        if not inner:
            return None

        # Exact FQN match.
        if inner in model_fqns:
            return inner

        # Same-module FQN match.
        candidate = f"{scope_module}.{inner}" if scope_module else inner
        if candidate in model_fqns:
            return candidate

        # Fallback: endswith `.Name` search.
        for fqn in model_fqns:
            if fqn.endswith(f".{inner}"):
                return fqn

        return None
```

Extend `extract()` to emit ACCEPTS edges:

```python
    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("fastapi_pydantic_extract_start")

        graph = context.graph
        model_fqns = self._find_pydantic_model_fqns(graph)

        for fqn in model_fqns:
            node = graph.get_node(fqn)
            if node is not None:
                node.properties["is_pydantic_model"] = True

        constraints_applied = self._apply_field_constraints(graph, model_fqns)
        validators_tagged = self._tag_validators(graph, model_fqns)
        edges: list[GraphEdge] = []
        edges.extend(self._emit_accepts_edges(graph, model_fqns))

        log.info(
            "fastapi_pydantic_extract_complete",
            pydantic_models=len(model_fqns),
            field_constraints=constraints_applied,
            validators=validators_tagged,
            accepts_edges=sum(1 for e in edges if e.kind == EdgeKind.ACCEPTS),
        )
        return PluginResult(edges=edges, warnings=[])

    def _emit_accepts_edges(self, graph, model_fqns: set[str]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for handles_edge in graph.edges:
            if handles_edge.kind != EdgeKind.HANDLES:
                continue
            handler = graph.get_node(handles_edge.source_fqn)
            endpoint = graph.get_node(handles_edge.target_fqn)
            if (
                handler is None
                or endpoint is None
                or handler.kind != NodeKind.FUNCTION
                or endpoint.kind != NodeKind.API_ENDPOINT
            ):
                continue
            scope_module = handler.fqn.rsplit(".", 1)[0] if "." in handler.fqn else ""
            for param in handler.properties.get("params", []):
                type_source = param.get("type", "")
                target = self._resolve_pydantic_type(
                    graph, type_source, model_fqns, scope_module
                )
                if target is None:
                    continue
                edges.append(
                    GraphEdge(
                        source_fqn=endpoint.fqn,
                        target_fqn=target,
                        kind=EdgeKind.ACCEPTS,
                        confidence=Confidence.HIGH,
                        evidence="fastapi-body-param",
                    )
                )
        return edges
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py \
        cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py
git commit -m "feat(pydantic): emit ACCEPTS edges from FastAPI endpoints to body models"
```

---

### Task 10: Emit `RETURNS` edges from endpoints to response models

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py`
- Modify: `cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py`

**Background:** FastAPI exposes the response model in two places: `response_model=TodoRead` as a kwarg on the route decorator (stored on the FUNCTION node as part of `annotations` list), and the function's `return_type` annotation. We prefer `response_model` when present (it is authoritative in FastAPI semantics), else fall back to `return_type`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pydantic_deep_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_emits_returns_edge_from_response_model():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoRead",
        name="TodoRead",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )
    handler = GraphNode(
        fqn="app.routes.todos.create_todo",
        name="create_todo",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={
            "annotations": ['@router.post("", response_model=TodoRead, status_code=201)'],
            "return_type": "TodoRead",
            "params": [],
        },
    )
    endpoint = GraphNode(
        fqn="POST:/todos",
        name="POST /todos",
        kind=NodeKind.API_ENDPOINT,
        language="python",
    )
    ctx.graph.add_node(handler)
    ctx.graph.add_node(endpoint)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=handler.fqn, target_fqn=endpoint.fqn, kind=EdgeKind.HANDLES)
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    returns = [e for e in result.edges if e.kind == EdgeKind.RETURNS]
    assert len(returns) == 1
    assert returns[0].source_fqn == endpoint.fqn
    assert returns[0].target_fqn == model.fqn
    assert returns[0].evidence == "fastapi-response-model"


@pytest.mark.asyncio
async def test_extract_falls_back_to_return_type_when_no_response_model():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.todo.TodoRead",
        name="TodoRead",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(model)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )
    handler = GraphNode(
        fqn="app.routes.todos.list_todos",
        name="list_todos",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={
            "annotations": ['@router.get("/owner/{owner_id}")'],
            "return_type": "list[TodoRead]",
            "params": [],
        },
    )
    endpoint = GraphNode(
        fqn="GET:/owner/{owner_id}",
        name="GET /owner/{owner_id}",
        kind=NodeKind.API_ENDPOINT,
        language="python",
    )
    ctx.graph.add_node(handler)
    ctx.graph.add_node(endpoint)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=handler.fqn, target_fqn=endpoint.fqn, kind=EdgeKind.HANDLES)
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    returns = [e for e in result.edges if e.kind == EdgeKind.RETURNS]
    assert len(returns) == 1
    assert returns[0].target_fqn == model.fqn
    assert returns[0].evidence == "fastapi-return-annotation"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: two new tests FAIL (no RETURNS edges yet).

- [ ] **Step 3: Implement RETURNS emission**

Add to `pydantic.py` at module scope:

```python
_RESPONSE_MODEL_RE = re.compile(r"response_model\s*=\s*([A-Za-z_][\w\.\[\]|, ]*)")
```

Extend the plugin with a new method and call it from `extract()`:

```python
    def _emit_returns_edges(self, graph, model_fqns: set[str]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for handles_edge in graph.edges:
            if handles_edge.kind != EdgeKind.HANDLES:
                continue
            handler = graph.get_node(handles_edge.source_fqn)
            endpoint = graph.get_node(handles_edge.target_fqn)
            if (
                handler is None
                or endpoint is None
                or handler.kind != NodeKind.FUNCTION
                or endpoint.kind != NodeKind.API_ENDPOINT
            ):
                continue
            scope_module = handler.fqn.rsplit(".", 1)[0] if "." in handler.fqn else ""

            target: str | None = None
            evidence = "fastapi-response-model"
            for deco in handler.properties.get("annotations", []):
                match = _RESPONSE_MODEL_RE.search(deco)
                if match:
                    target = self._resolve_pydantic_type(
                        graph, match.group(1), model_fqns, scope_module
                    )
                    if target is not None:
                        break
            if target is None:
                return_type = handler.properties.get("return_type", "")
                target = self._resolve_pydantic_type(
                    graph, return_type, model_fqns, scope_module
                )
                evidence = "fastapi-return-annotation"
            if target is None:
                continue

            edges.append(
                GraphEdge(
                    source_fqn=endpoint.fqn,
                    target_fqn=target,
                    kind=EdgeKind.RETURNS,
                    confidence=Confidence.HIGH,
                    evidence=evidence,
                )
            )
        return edges
```

And update `extract()` to extend `edges`:

```python
        edges: list[GraphEdge] = []
        edges.extend(self._emit_accepts_edges(graph, model_fqns))
        edges.extend(self._emit_returns_edges(graph, model_fqns))
```

Update the `log.info("fastapi_pydantic_extract_complete", ...)` call to include `returns_edges=sum(1 for e in edges if e.kind == EdgeKind.RETURNS)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py \
        cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py
git commit -m "feat(pydantic): emit RETURNS edges from endpoints via response_model + return annotation"
```

---

### Task 11: Pydantic → ORM `MAPS_TO` linking

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py`
- Modify: `cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py`

**Background:** For each Pydantic FIELD whose parent class has `is_pydantic_model=True`, we search COLUMN nodes (produced by SQLAlchemyPlugin). A match requires: identical column name AND compatible types. Python `str` ↔ SQL `VARCHAR`/`TEXT`/`CHAR`/`STRING`; Python `int` ↔ `INTEGER`/`BIGINT`/`SMALLINT`; Python `bool` ↔ `BOOLEAN`/`BOOL`; Python `float` ↔ `REAL`/`FLOAT`/`DOUBLE`/`NUMERIC`/`DECIMAL`; Python `datetime` ↔ `TIMESTAMP`/`DATETIME`.

Confidence: MEDIUM for a unique match. LOW if multiple COLUMN nodes match (one edge per candidate with LOW).

Gated by `ENABLE_PYDANTIC_ORM_LINKING` module constant (default True). Tests monkeypatch the constant.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pydantic_deep_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_emits_maps_to_for_unique_column_match():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(
        fqn="app.schemas.User",
        name="User",
        kind=NodeKind.CLASS,
        language="python",
    )
    email_field = GraphNode(
        fqn="app.schemas.User.email",
        name="email",
        kind=NodeKind.FIELD,
        language="python",
        properties={"type": "str", "value": ""},
    )
    users_table = GraphNode(
        fqn="app.db.users",
        name="users",
        kind=NodeKind.TABLE,
        language="python",
    )
    email_column = GraphNode(
        fqn="app.db.users.email",
        name="email",
        kind=NodeKind.COLUMN,
        language="python",
        properties={"type": "VARCHAR"},
    )
    ctx.graph.add_node(model)
    ctx.graph.add_node(email_field)
    ctx.graph.add_node(users_table)
    ctx.graph.add_node(email_column)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn=email_field.fqn, kind=EdgeKind.CONTAINS)
    )
    ctx.graph.add_edge(
        GraphEdge(source_fqn=model.fqn, target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=users_table.fqn,
            target_fqn=email_column.fqn,
            kind=EdgeKind.HAS_COLUMN,
        )
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    maps = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
    assert len(maps) == 1
    assert maps[0].source_fqn == email_field.fqn
    assert maps[0].target_fqn == email_column.fqn
    assert maps[0].confidence == Confidence.MEDIUM
    assert maps[0].properties.get("source") == "pydantic"
    assert maps[0].properties.get("confidence_reason") == "name_and_type_match"


@pytest.mark.asyncio
async def test_extract_uses_low_confidence_on_ambiguous_matches():
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    field = GraphNode(
        fqn="M.email",
        name="email",
        kind=NodeKind.FIELD,
        language="python",
        properties={"type": "str"},
    )
    col1 = GraphNode(
        fqn="t1.email",
        name="email",
        kind=NodeKind.COLUMN,
        language="python",
        properties={"type": "VARCHAR"},
    )
    col2 = GraphNode(
        fqn="t2.email",
        name="email",
        kind=NodeKind.COLUMN,
        language="python",
        properties={"type": "TEXT"},
    )
    for n in (model, field, col1, col2):
        ctx.graph.add_node(n)
    ctx.graph.add_edge(GraphEdge(source_fqn="M", target_fqn="M.email", kind=EdgeKind.CONTAINS))
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    result = await FastAPIPydanticPlugin().extract(ctx)

    maps = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
    assert len(maps) == 2
    assert all(e.confidence == Confidence.LOW for e in maps)


@pytest.mark.asyncio
async def test_extract_skips_maps_to_when_flag_disabled(monkeypatch):
    import app.stages.plugins.fastapi_plugin.pydantic as mod

    monkeypatch.setattr(mod, "ENABLE_PYDANTIC_ORM_LINKING", False)

    ctx = _ctx()
    model = GraphNode(fqn="M", name="M", kind=NodeKind.CLASS, language="python")
    field = GraphNode(
        fqn="M.email",
        name="email",
        kind=NodeKind.FIELD,
        language="python",
        properties={"type": "str"},
    )
    col = GraphNode(
        fqn="t.email",
        name="email",
        kind=NodeKind.COLUMN,
        language="python",
        properties={"type": "VARCHAR"},
    )
    for n in (model, field, col):
        ctx.graph.add_node(n)
    ctx.graph.add_edge(GraphEdge(source_fqn="M", target_fqn="M.email", kind=EdgeKind.CONTAINS))
    ctx.graph.add_edge(
        GraphEdge(source_fqn="M", target_fqn="BaseModel", kind=EdgeKind.INHERITS)
    )

    result = await mod.FastAPIPydanticPlugin().extract(ctx)

    assert [e for e in result.edges if e.kind == EdgeKind.MAPS_TO] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: three new tests FAIL.

- [ ] **Step 3: Implement MAPS_TO linking**

Add to `pydantic.py`:

```python
_PY_TO_SQL_TYPES: dict[str, frozenset[str]] = {
    "str": frozenset({"VARCHAR", "TEXT", "CHAR", "STRING", "CITEXT"}),
    "int": frozenset({"INTEGER", "BIGINT", "SMALLINT", "INT"}),
    "bool": frozenset({"BOOLEAN", "BOOL"}),
    "float": frozenset({"REAL", "FLOAT", "DOUBLE", "DOUBLE PRECISION", "NUMERIC", "DECIMAL"}),
    "datetime": frozenset({"TIMESTAMP", "DATETIME", "TIMESTAMPTZ"}),
    "date": frozenset({"DATE"}),
}


def _python_type_compatible(py_type: str, sql_type: str) -> bool:
    """Return True if a Python type annotation looks compatible with a SQL column type."""
    if not py_type or not sql_type:
        return False
    py_norm = py_type.strip().split("[")[0].split("|")[0].strip()
    sql_norm = sql_type.strip().upper().split("(")[0].strip()
    allowed = _PY_TO_SQL_TYPES.get(py_norm, frozenset())
    return sql_norm in allowed
```

Extend the plugin class with a method and call it from `extract()`:

```python
    def _emit_maps_to_edges(self, graph, model_fqns: set[str]) -> list[GraphEdge]:
        if not ENABLE_PYDANTIC_ORM_LINKING:
            return []

        columns_by_name: dict[str, list] = {}
        for node in graph.nodes.values():
            if node.kind == NodeKind.COLUMN:
                columns_by_name.setdefault(node.name, []).append(node)

        edges: list[GraphEdge] = []
        for edge in graph.edges:
            if edge.kind != EdgeKind.CONTAINS:
                continue
            if edge.source_fqn not in model_fqns:
                continue
            field_node = graph.get_node(edge.target_fqn)
            if field_node is None or field_node.kind != NodeKind.FIELD:
                continue
            candidates = columns_by_name.get(field_node.name, [])
            compatible = [
                c
                for c in candidates
                if _python_type_compatible(
                    field_node.properties.get("type", ""),
                    c.properties.get("type", ""),
                )
            ]
            if not compatible:
                continue
            confidence = Confidence.MEDIUM if len(compatible) == 1 else Confidence.LOW
            for col in compatible:
                edges.append(
                    GraphEdge(
                        source_fqn=field_node.fqn,
                        target_fqn=col.fqn,
                        kind=EdgeKind.MAPS_TO,
                        confidence=confidence,
                        evidence="pydantic-orm-link",
                        properties={
                            "source": "pydantic",
                            "confidence_reason": "name_and_type_match",
                        },
                    )
                )
        return edges
```

Append the call to `extract()`:

```python
        edges.extend(self._emit_maps_to_edges(graph, model_fqns))
```

And include `maps_to_edges=sum(1 for e in edges if e.kind == EdgeKind.MAPS_TO)` in the final `log.info` block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pydantic_deep_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/fastapi_plugin/pydantic.py \
        cast-clone-backend/tests/unit/test_pydantic_deep_plugin.py
git commit -m "feat(pydantic): fuzzy-match Pydantic fields to SQLAlchemy columns via MAPS_TO"
```

---

### Task 12: Export and register `FastAPIPydanticPlugin`

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/fastapi_plugin/__init__.py`
- Modify: `cast-clone-backend/app/stages/plugins/__init__.py`
- Modify: `cast-clone-backend/tests/unit/test_plugin_registry.py` (extend if appropriate — otherwise add a new regression test)

- [ ] **Step 1: Write the failing test**

Open `cast-clone-backend/tests/unit/test_plugin_registry.py`. Find a test that iterates `global_registry.plugin_classes` and append a targeted check (if no such test exists, add one):

```python
def test_fastapi_pydantic_plugin_is_registered():
    from app.stages.plugins import global_registry
    from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin

    assert FastAPIPydanticPlugin in global_registry.plugin_classes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_registry.py::test_fastapi_pydantic_plugin_is_registered -v`

Expected: FAIL (the plugin is not yet registered).

- [ ] **Step 3: Export from sub-package**

Replace `cast-clone-backend/app/stages/plugins/fastapi_plugin/__init__.py` with:

```python
"""FastAPI framework plugins — route extraction, Depends() DI, Pydantic deep."""

from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin
from app.stages.plugins.fastapi_plugin.routes import FastAPIPlugin

__all__ = ["FastAPIPlugin", "FastAPIPydanticPlugin"]
```

- [ ] **Step 4: Register with global registry**

Edit `cast-clone-backend/app/stages/plugins/__init__.py`. Find the existing import for `FastAPIPlugin`:

```python
from app.stages.plugins.fastapi_plugin.routes import FastAPIPlugin
```

Add the Pydantic import alongside it (either replace with a consolidated import or add a second line):

```python
from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin
from app.stages.plugins.fastapi_plugin.routes import FastAPIPlugin
```

Find the `global_registry.register(FastAPIPlugin)` line and add immediately after it:

```python
global_registry.register(FastAPIPydanticPlugin)
```

Also update the `__all__` list at the bottom of the file to include `"FastAPIPydanticPlugin"`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_registry.py -v`

Expected: PASS, no regressions in the registry suite.

- [ ] **Step 6: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/fastapi_plugin/__init__.py \
        cast-clone-backend/app/stages/plugins/__init__.py \
        cast-clone-backend/tests/unit/test_plugin_registry.py
git commit -m "feat(pydantic): register FastAPIPydanticPlugin with global registry"
```

---

### Task 13: Scaffold `CeleryPlugin`

**Files:**
- Create: `cast-clone-backend/app/stages/plugins/celery_plugin/__init__.py`
- Create: `cast-clone-backend/app/stages/plugins/celery_plugin/tasks.py`
- Create: `cast-clone-backend/app/stages/plugins/celery_plugin/producers.py`
- Create: `cast-clone-backend/tests/unit/test_celery_plugin.py`

- [ ] **Step 1: Write the failing test**

Create `cast-clone-backend/tests/unit/test_celery_plugin.py`:

```python
"""Unit tests for CeleryPlugin (M3)."""

from __future__ import annotations

import pytest

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode


def _ctx() -> AnalysisContext:
    return AnalysisContext(project_id="test-project")


def test_plugin_class_is_importable():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    plugin = CeleryPlugin()
    assert plugin.name == "celery"
    assert "python" in plugin.supported_languages
    assert plugin.depends_on == []


def test_detect_returns_not_detected_when_no_celery_decorator_present():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    plugin = CeleryPlugin()
    result = plugin.detect(ctx)
    assert result.confidence is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_celery_plugin.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.stages.plugins.celery_plugin'`.

- [ ] **Step 3: Create package files**

Create `cast-clone-backend/app/stages/plugins/celery_plugin/__init__.py`:

```python
"""Celery plugin — task discovery, queue extraction, producer linking."""

from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

__all__ = ["CeleryPlugin"]
```

Create `cast-clone-backend/app/stages/plugins/celery_plugin/tasks.py`:

```python
"""Celery task discovery and queue extraction (M3).

Discovers Celery tasks via @celery.task, @shared_task, and @app.task
decorators; extracts the ``queue=`` kwarg; emits MESSAGE_TOPIC nodes and
CONSUMES edges from each task to its queue; registers each task as a
message-consumer EntryPoint.

Producer linking lives in producers.py.
"""

from __future__ import annotations

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()


class CeleryPlugin(FrameworkPlugin):
    name = "celery"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        return PluginResult()

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(rules=[])
```

Create `cast-clone-backend/app/stages/plugins/celery_plugin/producers.py`:

```python
"""Celery producer-site resolution helpers (M3).

Given a SymbolGraph plus the map of task FQN → queue name (built by
CeleryPlugin), find CALLS edges whose target is a Celery trigger method
(``.delay``, ``.apply_async``, ``.s``, ``.signature``), resolve the
producing caller, and emit PRODUCES edges from the caller to the queue.
"""

from __future__ import annotations

from app.models.enums import Confidence, EdgeKind
from app.models.graph import GraphEdge

_TRIGGER_METHODS: tuple[str, ...] = (".delay", ".apply_async", ".s", ".signature")


def resolve_producer_edges(graph, task_to_queue: dict[str, str]) -> list[GraphEdge]:
    """Return PRODUCES edges for each CALLS edge that hits a Celery trigger method."""
    edges: list[GraphEdge] = []
    for call in graph.edges:
        if call.kind != EdgeKind.CALLS:
            continue
        target = call.target_fqn
        base_fqn: str | None = None
        for suffix in _TRIGGER_METHODS:
            if target.endswith(suffix):
                base_fqn = target[: -len(suffix)]
                break
        if base_fqn is None:
            continue
        queue = task_to_queue.get(base_fqn)
        if queue is None:
            continue
        edges.append(
            GraphEdge(
                source_fqn=call.source_fqn,
                target_fqn=f"queue::{queue}",
                kind=EdgeKind.PRODUCES,
                confidence=Confidence.HIGH,
                evidence="celery-producer",
                properties={"queue": queue},
            )
        )
    return edges
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_celery_plugin.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/celery_plugin/ \
        cast-clone-backend/tests/unit/test_celery_plugin.py
git commit -m "feat(celery): scaffold CeleryPlugin + producers helper module"
```

---

### Task 14: Discover Celery tasks via decorator scan

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/celery_plugin/tasks.py`
- Modify: `cast-clone-backend/tests/unit/test_celery_plugin.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_celery_plugin.py`:

```python
def test_detect_high_when_shared_task_decorator_present():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    task = GraphNode(
        fqn="posts.tasks.notify",
        name="notify",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@shared_task(queue="notifications")']},
    )
    ctx.graph.add_node(task)

    result = CeleryPlugin().detect(ctx)

    assert result.confidence == Confidence.HIGH


def test_detect_high_for_app_task_and_celery_task_variants():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="a.b",
            name="b",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ["@app.task"]},
        )
    )

    assert CeleryPlugin().detect(ctx).confidence == Confidence.HIGH

    ctx2 = _ctx()
    ctx2.graph.add_node(
        GraphNode(
            fqn="c.d",
            name="d",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ["@celery.task(bind=True)"]},
        )
    )

    assert CeleryPlugin().detect(ctx2).confidence == Confidence.HIGH


@pytest.mark.asyncio
async def test_extract_tags_task_functions_and_emits_entry_points():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    task = GraphNode(
        fqn="posts.tasks.notify_post_published",
        name="notify_post_published",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@shared_task(queue="notifications")']},
    )
    non_task = GraphNode(
        fqn="posts.tasks.helper",
        name="helper",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": []},
    )
    ctx.graph.add_node(task)
    ctx.graph.add_node(non_task)

    result = await CeleryPlugin().extract(ctx)

    updated = ctx.graph.get_node(task.fqn)
    assert updated.properties.get("framework") == "celery"
    assert updated.properties.get("is_message_consumer") is True
    assert updated.properties.get("task_name") == "notify_post_published"

    other = ctx.graph.get_node(non_task.fqn)
    assert other.properties.get("framework") != "celery"

    assert any(
        ep.fqn == task.fqn and ep.kind == "message_consumer"
        for ep in result.entry_points
    )
    assert result.layer_assignments.get(task.fqn) == "Business Logic"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_celery_plugin.py -v`

Expected: new tests FAIL.

- [ ] **Step 3: Implement task discovery**

Replace `tasks.py` content:

```python
"""Celery task discovery and queue extraction (M3)."""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, NodeKind
from app.models.graph import GraphNode, SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

_TASK_DECORATOR_RE = re.compile(
    r"^@(?:shared_task|celery\.task|app\.task)\b"
)


def _find_task_functions(graph: SymbolGraph) -> list[GraphNode]:
    """Return FUNCTION nodes whose annotations include a Celery task decorator."""
    results: list[GraphNode] = []
    for node in graph.nodes.values():
        if node.kind != NodeKind.FUNCTION or node.language != "python":
            continue
        for deco in node.properties.get("annotations", []):
            if _TASK_DECORATOR_RE.match(deco):
                results.append(node)
                break
    return results


class CeleryPlugin(FrameworkPlugin):
    name = "celery"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        tasks = _find_task_functions(context.graph)
        if tasks:
            return PluginDetectionResult(
                confidence=Confidence.HIGH,
                reason=f"Celery task decorators found ({len(tasks)} tasks)",
            )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("celery_extract_start")

        graph = context.graph
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}

        tasks = _find_task_functions(graph)
        for task in tasks:
            task.properties["framework"] = "celery"
            task.properties["is_message_consumer"] = True
            task.properties["task_name"] = task.name
            entry_points.append(
                EntryPoint(
                    fqn=task.fqn,
                    kind="message_consumer",
                    metadata={"task_name": task.name},
                )
            )
            layer_assignments[task.fqn] = "Business Logic"

        log.info("celery_extract_complete", tasks=len(tasks))
        return PluginResult(
            entry_points=entry_points,
            layer_assignments=layer_assignments,
            warnings=[],
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(
            rules=[
                LayerRule(pattern="@shared_task", layer="Business Logic"),
                LayerRule(pattern="@celery.task", layer="Business Logic"),
                LayerRule(pattern="@app.task", layer="Business Logic"),
            ]
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_celery_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/celery_plugin/tasks.py \
        cast-clone-backend/tests/unit/test_celery_plugin.py
git commit -m "feat(celery): discover tasks via @shared_task/@celery.task/@app.task and tag consumers"
```

---

### Task 15: Extract queue names and emit `CONSUMES` edges

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/celery_plugin/tasks.py`
- Modify: `cast-clone-backend/tests/unit/test_celery_plugin.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_celery_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_creates_message_topic_and_consumes_edge():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="posts.tasks.notify",
            name="notify",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ['@shared_task(queue="notifications")']},
        )
    )

    result = await CeleryPlugin().extract(ctx)

    topics = [n for n in result.nodes if n.kind == NodeKind.MESSAGE_TOPIC]
    assert len(topics) == 1
    assert topics[0].fqn == "queue::notifications"
    assert topics[0].name == "notifications"

    consumes = [e for e in result.edges if e.kind == EdgeKind.CONSUMES]
    assert len(consumes) == 1
    assert consumes[0].source_fqn == "posts.tasks.notify"
    assert consumes[0].target_fqn == "queue::notifications"
    assert consumes[0].properties.get("queue") == "notifications"


@pytest.mark.asyncio
async def test_extract_dedupes_queue_nodes_across_tasks():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="a",
            name="a",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ['@shared_task(queue="q1")']},
        )
    )
    ctx.graph.add_node(
        GraphNode(
            fqn="b",
            name="b",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ['@shared_task(queue="q1")']},
        )
    )

    result = await CeleryPlugin().extract(ctx)

    topics = [n for n in result.nodes if n.kind == NodeKind.MESSAGE_TOPIC]
    assert len(topics) == 1
    assert topics[0].fqn == "queue::q1"

    consumes = [e for e in result.edges if e.kind == EdgeKind.CONSUMES]
    assert len(consumes) == 2


@pytest.mark.asyncio
async def test_extract_defaults_queue_to_celery_when_kwarg_missing():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="a",
            name="a",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ["@shared_task"]},
        )
    )

    result = await CeleryPlugin().extract(ctx)

    topics = [n for n in result.nodes if n.kind == NodeKind.MESSAGE_TOPIC]
    assert len(topics) == 1
    assert topics[0].name == "celery"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_celery_plugin.py -v`

Expected: new tests FAIL.

- [ ] **Step 3: Implement queue extraction**

Replace the body of `tasks.py` (inside `CeleryPlugin`) with the extended version. Add a module-level regex near `_TASK_DECORATOR_RE`:

```python
_QUEUE_KWARG_RE = re.compile(r"""queue\s*=\s*["']([^"']+)["']""")
_DEFAULT_QUEUE = "celery"
```

Replace the `extract()` body:

```python
    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("celery_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}
        queue_nodes: dict[str, GraphNode] = {}

        tasks = _find_task_functions(graph)
        for task in tasks:
            queue_name = _DEFAULT_QUEUE
            for deco in task.properties.get("annotations", []):
                if not _TASK_DECORATOR_RE.match(deco):
                    continue
                q_match = _QUEUE_KWARG_RE.search(deco)
                if q_match:
                    queue_name = q_match.group(1)
                break

            task.properties["framework"] = "celery"
            task.properties["is_message_consumer"] = True
            task.properties["task_name"] = task.name
            task.properties["queue"] = queue_name

            topic_fqn = f"queue::{queue_name}"
            if topic_fqn not in queue_nodes:
                queue_nodes[topic_fqn] = GraphNode(
                    fqn=topic_fqn,
                    name=queue_name,
                    kind=NodeKind.MESSAGE_TOPIC,
                    properties={"transport": "celery"},
                )

            from app.models.graph import GraphEdge  # local import avoids cycle
            edges.append(
                GraphEdge(
                    source_fqn=task.fqn,
                    target_fqn=topic_fqn,
                    kind=EdgeKind.CONSUMES,
                    confidence=Confidence.HIGH,
                    evidence="celery-task-decorator",
                    properties={"queue": queue_name},
                )
            )

            entry_points.append(
                EntryPoint(
                    fqn=task.fqn,
                    kind="message_consumer",
                    metadata={"task_name": task.name, "queue": queue_name},
                )
            )
            layer_assignments[task.fqn] = "Business Logic"

        nodes.extend(queue_nodes.values())

        log.info(
            "celery_extract_complete",
            tasks=len(tasks),
            queues=len(queue_nodes),
        )
        return PluginResult(
            nodes=nodes,
            edges=edges,
            entry_points=entry_points,
            layer_assignments=layer_assignments,
            warnings=[],
        )
```

Ensure `EdgeKind` is imported at the top of the file:

```python
from app.models.enums import Confidence, EdgeKind, NodeKind
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_celery_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/celery_plugin/tasks.py \
        cast-clone-backend/tests/unit/test_celery_plugin.py
git commit -m "feat(celery): extract queue= kwarg, emit MESSAGE_TOPIC + CONSUMES edges"
```

---

### Task 16: Wire producer linking into `CeleryPlugin`

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/celery_plugin/tasks.py`
- Modify: `cast-clone-backend/tests/unit/test_celery_plugin.py`

**Background:** `producers.py` already has the resolver helper (Task 13). This task builds the task→queue map inside `extract()` and calls `resolve_producer_edges`, folding the resulting edges into `PluginResult.edges`. The producer-side `MESSAGE_TOPIC` target FQN (`queue::<name>`) matches the one emitted in Task 15, so Neo4j will dedupe on MERGE.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_celery_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_emits_produces_edge_from_delay_caller():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="posts.tasks.notify",
            name="notify",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ['@shared_task(queue="notifications")']},
        )
    )
    # Producer caller with a CALLS edge to posts.tasks.notify.delay
    caller = GraphNode(
        fqn="posts.views.PostViewSet.perform_create",
        name="perform_create",
        kind=NodeKind.FUNCTION,
        language="python",
    )
    ctx.graph.add_node(caller)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=caller.fqn,
            target_fqn="posts.tasks.notify.delay",
            kind=EdgeKind.CALLS,
            confidence=Confidence.MEDIUM,
        )
    )

    result = await CeleryPlugin().extract(ctx)

    produces = [e for e in result.edges if e.kind == EdgeKind.PRODUCES]
    assert len(produces) == 1
    assert produces[0].source_fqn == caller.fqn
    assert produces[0].target_fqn == "queue::notifications"
    assert produces[0].properties.get("queue") == "notifications"


@pytest.mark.asyncio
async def test_extract_emits_produces_for_apply_async_and_signature():
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="t.run",
            name="run",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ['@shared_task(queue="q")']},
        )
    )
    caller = GraphNode(
        fqn="svc.enqueue",
        name="enqueue",
        kind=NodeKind.FUNCTION,
        language="python",
    )
    ctx.graph.add_node(caller)
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=caller.fqn,
            target_fqn="t.run.apply_async",
            kind=EdgeKind.CALLS,
        )
    )
    ctx.graph.add_edge(
        GraphEdge(
            source_fqn=caller.fqn,
            target_fqn="t.run.s",
            kind=EdgeKind.CALLS,
        )
    )

    result = await CeleryPlugin().extract(ctx)

    produces = [e for e in result.edges if e.kind == EdgeKind.PRODUCES]
    assert len(produces) == 2
    for e in produces:
        assert e.target_fqn == "queue::q"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_celery_plugin.py -v`

Expected: new tests FAIL.

- [ ] **Step 3: Wire producer resolution into `extract()`**

In `cast-clone-backend/app/stages/plugins/celery_plugin/tasks.py`, add the import near the top:

```python
from app.stages.plugins.celery_plugin.producers import resolve_producer_edges
```

Inside `extract()`, after the `nodes.extend(queue_nodes.values())` line and before the final `log.info`, add:

```python
        task_to_queue: dict[str, str] = {
            task.fqn: task.properties["queue"] for task in tasks
        }
        producer_edges = resolve_producer_edges(graph, task_to_queue)
        edges.extend(producer_edges)
```

Add `producers=len(producer_edges)` to the `log.info` keyword list:

```python
        log.info(
            "celery_extract_complete",
            tasks=len(tasks),
            queues=len(queue_nodes),
            producers=len(producer_edges),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_celery_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/celery_plugin/tasks.py \
        cast-clone-backend/tests/unit/test_celery_plugin.py
git commit -m "feat(celery): link producers via .delay/.apply_async/.s/.signature → PRODUCES"
```

---

### Task 17: Register `CeleryPlugin` with the global registry

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/__init__.py`
- Modify: `cast-clone-backend/tests/unit/test_plugin_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `cast-clone-backend/tests/unit/test_plugin_registry.py`:

```python
def test_celery_plugin_is_registered():
    from app.stages.plugins import global_registry
    from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

    assert CeleryPlugin in global_registry.plugin_classes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_registry.py::test_celery_plugin_is_registered -v`

Expected: FAIL.

- [ ] **Step 3: Register**

Edit `cast-clone-backend/app/stages/plugins/__init__.py`. Near the other plugin imports, add:

```python
from app.stages.plugins.celery_plugin.tasks import CeleryPlugin
```

Near the registry registrations (after `global_registry.register(DjangoDRFPlugin)`), add:

```python
global_registry.register(CeleryPlugin)
```

Also update `__all__` to include `"CeleryPlugin"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_registry.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/__init__.py \
        cast-clone-backend/tests/unit/test_plugin_registry.py
git commit -m "feat(celery): register CeleryPlugin with global registry"
```

---

### Task 18: Integration test — `fastapi-todo` endpoint→Pydantic→column chain

**Files:**
- Create: `cast-clone-backend/tests/integration/test_python_m3_pipeline.py`

**Background:** Follow the M1 integration pattern — use the existing `run_analysis_pipeline` helper (or its test harness) to drive stages 1–5 against `tests/fixtures/fastapi-todo/`, skip the Neo4j writer, and assert on `context.graph`. If the exact helper function name differs from M1's test, open `tests/integration/test_python_pipeline.py` (authored in M1) and mirror its setup verbatim.

- [ ] **Step 1: Write the failing test**

Create `cast-clone-backend/tests/integration/test_python_m3_pipeline.py`:

```python
"""M3 integration tests — Pydantic + Celery plugin end-to-end chains."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.context import AnalysisContext
from app.models.enums import EdgeKind, NodeKind

FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures"


pytestmark = [pytest.mark.integration, pytest.mark.scip_python]


async def _run_pipeline_stages_1_to_5(
    fixture_root: Path, project_id: str
) -> AnalysisContext:
    """Run discovery → dependencies → treesitter → SCIP → plugins.

    Skips Stage 6 (cross-tech linker), Stage 7 (enricher), Stage 8 (writer).
    Mirrors the harness used by tests/integration/test_python_pipeline.py.
    If that harness exposes a shared helper, prefer that import over this
    inline version.
    """
    from app.stages.discovery import discover_project
    from app.stages.dependencies import resolve_dependencies
    from app.stages.treesitter.parser import parse_with_treesitter
    from app.stages.scip.indexer import run_scip_indexers
    from app.stages.plugins.registry import run_framework_plugins

    ctx = AnalysisContext(project_id=project_id)
    ctx.manifest = await discover_project(fixture_root)
    ctx.environment = await resolve_dependencies(ctx.manifest)
    await parse_with_treesitter(ctx)
    await run_scip_indexers(ctx)
    await run_framework_plugins(ctx)
    return ctx


class TestFastAPITodoPydanticChain:
    """Acceptance: endpoint → Pydantic model → SQLAlchemy column via MAPS_TO."""

    @pytest.fixture(scope="class")
    async def ctx(self) -> AnalysisContext:
        fixture = FIXTURES_ROOT / "fastapi-todo"
        return await _run_pipeline_stages_1_to_5(fixture, "fastapi-todo-m3")

    async def test_api_endpoint_nodes_exist(self, ctx: AnalysisContext) -> None:
        endpoints = [n for n in ctx.graph.nodes.values() if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoints) >= 1, (
            f"expected ≥1 APIEndpoint; got {len(endpoints)}"
        )

    async def test_accepts_edge_points_to_pydantic_model(
        self, ctx: AnalysisContext
    ) -> None:
        accepts = [e for e in ctx.graph.edges if e.kind == EdgeKind.ACCEPTS]
        assert len(accepts) >= 1, "expected ≥1 ACCEPTS edge from endpoint to body model"
        # Each ACCEPTS target must be a Pydantic-flagged CLASS.
        for edge in accepts:
            target = ctx.graph.get_node(edge.target_fqn)
            assert target is not None, f"ACCEPTS target missing: {edge.target_fqn}"
            assert target.kind == NodeKind.CLASS
            assert target.properties.get("is_pydantic_model") is True

    async def test_returns_edge_points_to_pydantic_model(
        self, ctx: AnalysisContext
    ) -> None:
        returns = [e for e in ctx.graph.edges if e.kind == EdgeKind.RETURNS]
        assert len(returns) >= 1
        for edge in returns:
            target = ctx.graph.get_node(edge.target_fqn)
            assert target is not None
            assert target.properties.get("is_pydantic_model") is True

    async def test_pydantic_field_maps_to_column(
        self, ctx: AnalysisContext
    ) -> None:
        maps = [e for e in ctx.graph.edges if e.kind == EdgeKind.MAPS_TO]
        pydantic_maps = [
            e
            for e in maps
            if (src := ctx.graph.get_node(e.source_fqn)) is not None
            and src.kind == NodeKind.FIELD
            and (tgt := ctx.graph.get_node(e.target_fqn)) is not None
            and tgt.kind == NodeKind.COLUMN
        ]
        assert len(pydantic_maps) >= 1, (
            "expected ≥1 Pydantic field → SQLAlchemy column MAPS_TO edge"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/integration/test_python_m3_pipeline.py::TestFastAPITodoPydanticChain -v`

Expected: PASS if M1 + M2 + prior M3 tasks are correct; FAIL otherwise. If it FAILS with an import error on `_run_pipeline_stages_1_to_5`, open the M1 integration test file and adapt the harness name accordingly.

- [ ] **Step 3: Fix any harness mismatch**

If step 2 fails on imports, update the helper in this file to match M1's actual exported helper (look in `tests/integration/test_python_pipeline.py` for `_run_pipeline` or `run_pipeline_for_fixture` style names).

- [ ] **Step 4: Re-run test**

Run: `cd cast-clone-backend && uv run pytest tests/integration/test_python_m3_pipeline.py::TestFastAPITodoPydanticChain -v`

Expected: PASS (all four test methods).

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/tests/integration/test_python_m3_pipeline.py
git commit -m "test(integration): M3 fastapi-todo endpoint→Pydantic→column chain"
```

---

### Task 19: Integration test — `django-blog` endpoint→producer→task→queue chain

**Files:**
- Modify: `cast-clone-backend/tests/integration/test_python_m3_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to the existing `test_python_m3_pipeline.py` file:

```python
class TestDjangoBlogCeleryChain:
    """Acceptance: endpoint → producer function → Celery task → queue topic."""

    @pytest.fixture(scope="class")
    async def ctx(self) -> AnalysisContext:
        fixture = FIXTURES_ROOT / "django-blog"
        return await _run_pipeline_stages_1_to_5(fixture, "django-blog-m3")

    async def test_task_nodes_tagged_with_celery_framework(
        self, ctx: AnalysisContext
    ) -> None:
        tasks = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.FUNCTION
            and n.properties.get("framework") == "celery"
        ]
        assert len(tasks) >= 2, f"expected ≥2 Celery tasks in django-blog; got {len(tasks)}"

    async def test_message_topic_exists_for_notifications(
        self, ctx: AnalysisContext
    ) -> None:
        topics = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.MESSAGE_TOPIC and n.name == "notifications"
        ]
        assert len(topics) == 1, (
            f"expected exactly one 'notifications' MESSAGE_TOPIC; got {len(topics)}"
        )

    async def test_consumes_edge_from_task_to_topic(
        self, ctx: AnalysisContext
    ) -> None:
        consumes = [e for e in ctx.graph.edges if e.kind == EdgeKind.CONSUMES]
        assert any(
            e.target_fqn == "queue::notifications" for e in consumes
        ), "expected CONSUMES edge pointing to queue::notifications"

    async def test_produces_edge_from_view_caller_to_topic(
        self, ctx: AnalysisContext
    ) -> None:
        produces = [e for e in ctx.graph.edges if e.kind == EdgeKind.PRODUCES]
        assert any(
            e.target_fqn == "queue::notifications"
            and e.source_fqn.endswith("perform_create")
            for e in produces
        ), (
            "expected PRODUCES edge from PostViewSet.perform_create to queue::notifications"
        )
```

- [ ] **Step 2: Run test to verify it fails (or passes)**

Run: `cd cast-clone-backend && uv run pytest tests/integration/test_python_m3_pipeline.py::TestDjangoBlogCeleryChain -v`

Expected: PASS if Tasks 13-17 are correct against the real fixture; FAIL if the fixture's decorator source text differs from the unit-test assumptions.

- [ ] **Step 3: If failing, debug by printing the graph**

If any test case fails, temporarily add at the top of the failing test:

```python
        import json
        print(json.dumps([
            {"fqn": n.fqn, "kind": n.kind.value, "name": n.name}
            for n in ctx.graph.nodes.values()
            if n.kind in (NodeKind.FUNCTION, NodeKind.MESSAGE_TOPIC)
        ], indent=2))
```

Run the single failing test with `-s` to see output. Fix the root cause in the plugin (not the test). Remove the debug print before committing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/integration/test_python_m3_pipeline.py -v`

Expected: all eight integration test methods across both classes PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/tests/integration/test_python_m3_pipeline.py
git commit -m "test(integration): M3 django-blog endpoint→producer→task→queue chain"
```

---

### Task 20: Docs update + full regression sweep

**Files:**
- Modify: `cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `08-FRAMEWORK-PLUGINS.md`**

Open `cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md`. Locate the section describing Python / FastAPI plugins (search for "FastAPI" heading). Below that section, add:

````markdown
### FastAPIPydanticPlugin (M3)

Deep extraction of Pydantic v1 and v2 models used as FastAPI request and response bodies.

**Emits:**

| Output | Kind | Condition |
|---|---|---|
| Tag on CLASS node | `properties.is_pydantic_model = True` | Class has INHERITS edge to `BaseModel` |
| Field constraints | `properties.constraints` dict on FIELD | `Field(...)` call present in class-body or `Annotated[...]` |
| Validator tags | `is_validator`, `validator_kind`, `target_field` on FUNCTION | Decorated with `@field_validator`, `@model_validator`, `@validator`, `@root_validator` |
| ACCEPTS edge | `APIEndpoint → CLASS` | Endpoint param type is a Pydantic model |
| RETURNS edge | `APIEndpoint → CLASS` | `response_model=` kwarg or function return annotation is a Pydantic model |
| MAPS_TO edge | `FIELD → COLUMN` | Field name equals column name and Python↔SQL type is compatible |

**MAPS_TO confidence:**

- `MEDIUM` — unique candidate column.
- `LOW` — multiple candidate columns (one edge per candidate).

**Toggle:** `ENABLE_PYDANTIC_ORM_LINKING` module-level constant in `pydantic.py`. Default `True`. Disable for projects where field-name collisions are common.

### CeleryPlugin (M3)

Celery task discovery, queue extraction, and producer linking.

**Emits:**

| Output | Kind | Condition |
|---|---|---|
| Task tags | `framework="celery"`, `is_message_consumer=True`, `task_name`, `queue` on FUNCTION | Decorated with `@shared_task`, `@celery.task`, or `@app.task` |
| MESSAGE_TOPIC node | `fqn="queue::<name>"` | One per unique `queue=` kwarg value |
| CONSUMES edge | `FUNCTION → MESSAGE_TOPIC` | Task function to its queue topic |
| PRODUCES edge | `FUNCTION → MESSAGE_TOPIC` | Caller of `.delay()`, `.apply_async()`, `.s()`, `.signature()` |
| Entry point | `kind="message_consumer"` | Added to `context.entry_points` |

**Default queue:** `"celery"` when no `queue=` kwarg is present (matches Celery default).

**Deferred to a later milestone:** Celery Canvas (`chain`, `group`, `chord`), beat schedules, retry/backoff metadata.
````

- [ ] **Step 2: Update root `CLAUDE.md` Plugin Priority table**

Open `CLAUDE.md` at the repo root. Find the "Plugin Priority (Phase 1 Tier 1)" table. Update the "Tier 4" row, replacing its current text with:

```markdown
| Tier 4 | Django (Settings, ORM, URLs, DRF), FastAPI (Routes, Pydantic Deep), SQLAlchemy (sync+async), Alembic, Celery, Flask | Python |
```

- [ ] **Step 3: Full regression sweep**

Run each command sequentially. Record output counts in the commit description.

```bash
cd cast-clone-backend
uv run pytest tests/unit/ -q
uv run pytest tests/integration/ -q -m "integration and not e2e"
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run mypy app/stages/plugins/fastapi_plugin/pydantic.py app/stages/plugins/celery_plugin/
```

Expected:
- Unit test count at or above M2 baseline. No new failures.
- Integration test count increased by 8 (the new M3 cases). No new failures.
- `ruff check` — 0 new errors versus M2 baseline.
- `ruff format --check` — clean.
- `mypy` — 0 errors on the two new modules.

If any of these fail, STOP and fix root cause in the relevant plugin before committing Task 20.

- [ ] **Step 4: Commit docs update**

```bash
git add cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md CLAUDE.md
git commit -m "docs(plugins): document FastAPIPydanticPlugin + CeleryPlugin for M3"
```

---

## Self-Review Checklist

Run this after all 20 tasks commit. Fix any issue inline — no new review subagent required.

### Spec coverage

| Spec requirement | Task(s) |
|---|---|
| `ACCEPTS` EdgeKind for request body | Task 2, 9 |
| `RETURNS` EdgeKind for response model | Task 2, 10 |
| Pydantic v1 + v2 BaseModel extraction | Task 4, 5 |
| `Field(...)` constraints (class-body) | Task 6 |
| `Field(...)` constraints (Annotated) | Task 7 |
| `@field_validator` / `@model_validator` tagging | Task 8 |
| `@validator` / `@root_validator` (v1) tagging | Task 8 |
| Endpoint → Pydantic ACCEPTS emission | Task 9 |
| Endpoint → Pydantic RETURNS emission | Task 10 |
| Pydantic → ORM `MAPS_TO` with MEDIUM confidence default | Task 11 |
| `enable_pydantic_orm_linking` per-project override (default ON) | Task 11 (module constant) |
| Celery task discovery `@celery.task`, `@shared_task`, `@app.task` | Task 14 |
| Queue extraction via `queue=` kwarg | Task 15 |
| `MESSAGE_TOPIC` nodes per unique queue | Task 15 |
| `CONSUMES` edge task → queue | Task 15 |
| Entry point with `kind="message_consumer"`, `layer="Business Logic"` | Task 14 |
| Producer linking via `.delay()`, `.apply_async()`, `.s()`, `.signature()` | Task 13, 16 |
| `PRODUCES` edge producer → queue | Task 13, 16 |
| fastapi-todo acceptance chain | Task 18 |
| django-blog acceptance chain | Task 19 |
| Docs updated | Task 20 |

### Placeholder scan

Search for disallowed markers inside this plan:

```bash
grep -nE "TBD|TODO|implement later|fill in details|Similar to Task|appropriate error handling" \
  docs/superpowers/plans/2026-04-22-python-m3-pydantic-celery.md || echo "clean"
```

Expected: `clean`.

### Type consistency

- `FastAPIPydanticPlugin.name` is `"fastapi_pydantic"` everywhere (Tasks 3, 12).
- `CeleryPlugin.name` is `"celery"` everywhere (Tasks 13, 17).
- `MESSAGE_TOPIC` FQN format is `queue::<name>` in both consumer emission (Task 15) and producer resolution (Task 13). Changing one without the other breaks MERGE deduplication.
- Module constant `ENABLE_PYDANTIC_ORM_LINKING` referenced consistently (Task 11 + unit-test monkeypatch).

---

## Execution Handoff

Plan complete and ready to save to `docs/superpowers/plans/2026-04-22-python-m3-pydantic-celery.md`. Two execution options when the user authorizes M3 start:

**1. Subagent-Driven (recommended)** — Opus implementer per task bundle, Sonnet reviewer per spec + code review, two-stage gate between tasks. Same pattern as M1/M2.

**2. Inline Execution** — Drive tasks in a single session using `superpowers:executing-plans`, checkpoint between tasks for review.

**Which approach?** — Awaiting user direction.
