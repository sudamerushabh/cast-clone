# Python M4 — Flask + Integration Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `FlaskPlugin` (Flask-core routes + Blueprint prefix chaining + Flask-RESTful `Resource`/`MethodView` + Flask-SQLAlchemy `db.Model` adapter), wire it into the registry, and close Phase 1 Python support with an end-to-end smoke test that exercises all three scratch-authored fixtures (`fastapi-todo`, `django-blog`, `flask-inventory`) under a <5-minute-per-fixture budget and a ≤5-warnings-per-fixture quality gate.

**Architecture:** One `FlaskPlugin` class in `flask_plugin/routes.py` registered with `global_registry`. Three helper modules — `blueprints.py`, `restful.py`, `sqlalchemy_adapter.py` — expose pure functions the plugin's `extract()` composes. No new `NodeKind` or `EdgeKind` is introduced; Flask nodes and edges reuse `API_ENDPOINT`, `FUNCTION`, `CLASS`, `TABLE`, `COLUMN`, `HANDLES`, `REFERENCES`, `HAS_COLUMN`. The plugin is independent of `FastAPIPlugin` and `SQLAlchemyPlugin` (no `depends_on`), but benefits from SCIP-resolved FQNs emitted by M1.

**Tech Stack:** Python 3.12, Flask 2.x/3.x, Flask-RESTful, Flask-SQLAlchemy, SQLAlchemy 2.0, structlog, pytest, pytest-asyncio, ruff, mypy, uv.

---

## Prerequisites

1. **Python M1, M2, and M3 must be merged to `main`** before M4 starts. M4 reuses:
   - M1 SCIP foundation (resolved Python FQNs, `tests/fixtures/flask-inventory/` scaffold).
   - M2 async SQLAlchemy column extraction (nothing Flask-specific, but the e2e smoke runs SQLAlchemyPlugin against fastapi-todo).
   - M3 Pydantic + Celery plugins (the e2e smoke depends on them for the cross-fixture run).
2. Worktree for M4: `.claude/worktrees/python-m4/` on branch `feat/python-m4-flask-integration-polish` off `main`.
3. Preflight: `git log --oneline main -n 5` shows M1+M2+M3 merge commits; `ls cast-clone-backend/tests/fixtures/flask-inventory` shows `app/`, `wsgi.py`, `requirements.txt`.

---

## Context Summary

### `flask-inventory` fixture shape (already authored in M1)

Source tree (`cast-clone-backend/tests/fixtures/flask-inventory/`):

```
app/__init__.py              # Flask factory + db = SQLAlchemy() + register_blueprint()
app/models.py                # Warehouse + Item (db.Model subclasses)
app/resources.py             # ItemListResource, ItemResource (flask_restful.Resource)
app/blueprints/__init__.py   # empty
app/blueprints/items.py      # items_bp = Blueprint("items", __name__) + @items_bp.route
app/blueprints/warehouses.py # warehouses_bp = Blueprint(...) + @warehouses_bp.route
wsgi.py                      # from app import create_app; app = create_app()
```

Key patterns in the fixture (authoritative for M4 plugin matching):

| Pattern | Source (verbatim) | M4 plugin responsibility |
|---|---|---|
| Blueprint declaration | `items_bp = Blueprint("items", __name__)` | `blueprints.py` — record name + optional construction-time `url_prefix` |
| Blueprint-route decorator | `@items_bp.route("", methods=["GET"])` | `routes.py` — emit APIEndpoint per HTTP method with `blueprint="items"` tag |
| Blueprint-route with path converter | `@items_bp.route("/<int:item_id>/adjust", methods=["POST"])` | `routes.py` — keep the raw path including converter syntax |
| Registration-time prefix | `app.register_blueprint(items_bp, url_prefix="/items")` | `blueprints.py` — build blueprint_name→url_prefix map; `routes.py` applies it |
| Flask-RESTful resource | `class ItemListResource(Resource):` with `get`/`post` methods | `restful.py` — detect subclass of `Resource` (or `MethodView`), enumerate HTTP methods |
| Resource registration | `api.add_resource(ItemListResource, "/items")` + `Api(app, prefix="/api")` | `restful.py` — emit endpoint per HTTP method with combined prefix |
| Flask-SQLAlchemy model | `class Warehouse(db.Model):` with `db.Column(db.Integer, primary_key=True)` | `sqlalchemy_adapter.py` — emit TABLE + COLUMN + HAS_COLUMN |
| Flask-SQLAlchemy foreign key | `db.Column(db.Integer, db.ForeignKey("warehouses.id", ondelete="CASCADE"))` | `sqlalchemy_adapter.py` — emit REFERENCES edge |
| Flask-SQLAlchemy relationship | `db.relationship("Item", back_populates="warehouse")` | Out of scope for M4 — leave for a later milestone; do not emit a custom edge kind |

**Patterns mentioned in the spec but not present in this fixture:**

- `@app.route()` on the main Flask app (fixture uses only blueprints). M4 still implements recognition because `routes.py` has to handle both patterns.
- `add_url_rule()` direct call. Implement recognition; not exercised in the integration test (no synthetic fixture mutation).
- `MethodView` subclass. Implement recognition in `restful.py`; not exercised in the integration test.

### Existing plugin patterns to mirror

| Concern | Reference | How M4 reuses |
|---|---|---|
| `FrameworkPlugin` ABC + `PluginResult` | `app/stages/plugins/base.py` | Implement `detect()`, `async extract()`, `get_layer_classification()` |
| Route decorator regex | `app/stages/plugins/fastapi_plugin/routes.py:34-37` (`_ROUTE_DECORATOR_RE`) | Adapt for Flask's `@<var>.route("/path", methods=[...])` |
| Layer classification | `FastAPIPlugin.get_layer_classification()` | Presentation for routes; Data Access for db.Model; Business Logic default |
| Helpers split across modules | `app/stages/plugins/celery_plugin/` (tasks.py + producers.py from M3) | One plugin class in `routes.py`, helpers in `blueprints.py`/`restful.py`/`sqlalchemy_adapter.py` |
| SQLAlchemy column emission | `app/stages/plugins/sqlalchemy_plugin/models.py` | Adapt regex for `db.Column(db.Integer, ...)` instead of `mapped_column(Integer, ...)` |

### Tree-sitter Python extractor outputs M4 relies on

Every Flask/SQLAlchemy construct M4 cares about is already visible in the graph after Stage 3 completes:

- Class base classes emit `INHERITS` edges (`python.py:341-354`). `class Warehouse(db.Model)` → `INHERITS(Warehouse → db.Model)`. `class ItemResource(Resource)` → `INHERITS(ItemResource → Resource)`.
- Class fields emit `FIELD` nodes with `properties["value"]` containing the RHS source text. `id = db.Column(db.Integer, primary_key=True)` → field `id` with value `"db.Column(db.Integer, primary_key=True)"`.
- Method decorators stored on the FUNCTION node as `properties["annotations"]` (list of decorator source strings).
- Method parameters stored as `properties["params"]` list (each has `name`, `type`, `default`).

### GraphStore edge writing

Unchanged from M3: `app/services/neo4j.py:191` uses `apoc.merge.relationship(from, e.type, ...)`. No writer changes needed for M4 (all edge kinds reused).

### Coding conventions

- Python 3.12, type hints everywhere, `uv` commands.
- `ruff` format + lint; `mypy` strict on new modules.
- structlog JSON logging: entry + exit per plugin with timing and emission counts.
- Only Stage 1 + Stage 8 are fatal. Every helper catches its own exceptions; failures surface as `PluginResult.warnings` strings.
- Conventional commits: `feat(flask): ...`, `test(integration): ...`, `test(e2e): ...`, `docs(plugins): ...`.

### Critical reviewer guidance

- **TDD throughout.** Every task writes the failing test, runs it, implements the minimum, runs again, commits. No multi-task commits.
- **Do not mutate existing plugins.** `FastAPIPlugin`, `SQLAlchemyPlugin`, `DjangoORMPlugin`, `CeleryPlugin` (M3), `AlembicPlugin` (M2) all stay untouched.
- **Do not add `NodeKind` or `EdgeKind` values.** Every concept M4 introduces maps to an existing enum member.
- **Do not refactor the existing SQLAlchemy plugin to share code.** The `db.Column(...)` syntax differs enough from `mapped_column(...)` / `Column(...)` that shared regex would sacrifice clarity. M4 owns its adapter regex in `sqlalchemy_adapter.py`.
- **Do not couple FlaskPlugin to FastAPIPlugin or SQLAlchemyPlugin.** Keep `depends_on = []`.

---

## File Structure

### New files

```
cast-clone-backend/app/stages/plugins/flask_plugin/__init__.py
cast-clone-backend/app/stages/plugins/flask_plugin/routes.py
cast-clone-backend/app/stages/plugins/flask_plugin/blueprints.py
cast-clone-backend/app/stages/plugins/flask_plugin/restful.py
cast-clone-backend/app/stages/plugins/flask_plugin/sqlalchemy_adapter.py
cast-clone-backend/tests/unit/test_flask_plugin.py
cast-clone-backend/tests/integration/test_python_m4_pipeline.py
cast-clone-backend/tests/e2e/__init__.py
cast-clone-backend/tests/e2e/test_python_full_stack.py
```

### Modified files

```
cast-clone-backend/app/stages/plugins/__init__.py     # register FlaskPlugin
cast-clone-backend/app/stages/plugins/registry.py     # (no change expected; verify during Task 13)
cast-clone-backend/tests/unit/test_plugin_registry.py # +FlaskPlugin registration test
cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md       # Flask section
CLAUDE.md                                             # Tier table: Python tier 4 → production-ready
```

### Module responsibilities

| File | Owns |
|---|---|
| `routes.py` | `FlaskPlugin` class. `detect()` via Flask imports or `@*.route` annotations. `extract()` composes helpers and returns `PluginResult`. |
| `blueprints.py` | Parse Blueprint constructors + `register_blueprint()` calls; return blueprint_name→url_prefix map. |
| `restful.py` | Detect `Resource` / `MethodView` subclasses; enumerate HTTP methods; parse `Api(...)` prefix; parse `api.add_resource(cls, "/path")` calls. |
| `sqlalchemy_adapter.py` | Detect `db = SQLAlchemy()` pattern; find `db.Model` subclasses; extract `db.Column(...)` columns and `db.ForeignKey` references. |

---

## Test Strategy

### Unit tests (`tests/unit/test_flask_plugin.py`, ~400 lines)

- `detect()` positive/negative (routes annotation, `from flask import` manifest, empty graph).
- `@app.route()` → APIEndpoint + HANDLES; multiple HTTP methods in one decorator expand to N endpoints.
- `@bp.route()` → APIEndpoint tagged with `blueprint_name`; prefix unresolved until Task 6.
- Blueprint + `register_blueprint()` prefix chaining (both construction-time `url_prefix=` and registration-time `url_prefix=`).
- `add_url_rule(rule, endpoint=func, methods=[...])` → APIEndpoint.
- `Resource` subclass method enumeration.
- `api.add_resource(cls, "/path")` + `Api(app, prefix="/api")` combined prefix.
- `MethodView` subclass.
- `db.Model` subclass → TABLE node.
- `db.Column(db.Integer, primary_key=True, nullable=False)` → COLUMN with `primary_key=True`, `nullable=False`.
- `db.ForeignKey("warehouses.id")` → REFERENCES edge.

Every unit test seeds a synthetic `SymbolGraph` — no file I/O, no subprocess.

### Integration tests (`tests/integration/test_python_m4_pipeline.py`)

- `TestFlaskInventoryBlueprints` — run stages 1–5 on flask-inventory, assert:
  - 4 blueprint-scoped endpoints exist with correct paths: `GET /items`, `POST /items/<int:item_id>/adjust`, `GET /warehouses`, `GET /warehouses/<int:wh_id>/items`.
  - Each endpoint has a HANDLES edge from its handler function.
- `TestFlaskInventoryRestful` — same pipeline run, assert Resource-backed endpoints exist: `GET /api/items`, `POST /api/items`, `GET /api/items/<int:item_id>`, `DELETE /api/items/<int:item_id>`.
- `TestFlaskInventoryModels` — assert `warehouses` and `items` TABLE nodes exist with correct column coverage and the `items.warehouse_id → warehouses.id` REFERENCES edge.

### E2E smoke (`tests/e2e/test_python_full_stack.py`)

Single test that runs the full pipeline (stages 1–7, skipping stage 8 Neo4j write) sequentially across all three fixtures and asserts:

- Per-fixture wall-clock duration <5 minutes (measured via `time.monotonic()`).
- Per-fixture `len(context.warnings) <= 5`.
- Each fixture produces a non-empty graph (`context.graph.node_count > 0`).

No testcontainers-python, no Docker — the smoke runs purely in-process. This mirrors the integration tests but adds the timing + warning budget assertion across all three.

### Acceptance gates

- All unit + integration + e2e tests green.
- `ruff check app/stages/plugins/flask_plugin/ tests/` clean.
- `ruff format --check app/stages/plugins/flask_plugin/ tests/` clean.
- `mypy app/stages/plugins/flask_plugin/` reports 0 errors.
- No regression on M1/M2/M3 suites. Baseline is the M3 merge commit.

---

## Commit Convention

- `feat(flask): ...` for plugin source
- `test(unit): ...` for `test_flask_plugin.py`
- `test(integration): ...` for `test_python_m4_pipeline.py`
- `test(e2e): ...` for `test_python_full_stack.py`
- `docs(plugins): ...` for doc updates

One commit per task. No squash.

---

## Tasks

### Task 1: Preflight reconnaissance (read-only, no commit)

**Files:** (none written)

- [ ] **Step 1: Confirm M1, M2, M3 are merged to `main`**

Run: `git log --oneline main | head -15`

Expected: commits referencing M1 (`feat/python-m1-scip-foundation`), M2 (`feat/python-m2-django-sqlalchemy-alembic`), M3 (`feat/python-m3-pydantic-celery`) are all present. If any of the three merges is missing, STOP and report.

- [ ] **Step 2: Confirm flask-inventory fixture on-disk shape**

Run:

```bash
ls cast-clone-backend/tests/fixtures/flask-inventory/app/ \
   cast-clone-backend/tests/fixtures/flask-inventory/app/blueprints/
```

Expected: `__init__.py`, `models.py`, `resources.py` under `app/`; `__init__.py`, `items.py`, `warehouses.py` under `app/blueprints/`.

- [ ] **Step 3: Confirm no `flask_plugin/` package already exists**

Run: `ls cast-clone-backend/app/stages/plugins/flask_plugin/ 2>/dev/null || echo "absent (expected)"`

Expected: `absent (expected)`. If the directory already exists, STOP and report — an earlier partial run contaminated the tree.

- [ ] **Step 4: Confirm FlaskPlugin is not registered yet**

Run: `grep -n "FlaskPlugin" cast-clone-backend/app/stages/plugins/__init__.py`

Expected: no matches. If `FlaskPlugin` is already imported or registered, STOP and report.

- [ ] **Step 5: Verify canonical fixture source patterns**

Run:

```bash
head -25 cast-clone-backend/tests/fixtures/flask-inventory/app/__init__.py
head -20 cast-clone-backend/tests/fixtures/flask-inventory/app/blueprints/items.py
head -30 cast-clone-backend/tests/fixtures/flask-inventory/app/resources.py
head -20 cast-clone-backend/tests/fixtures/flask-inventory/app/models.py
```

Record whether the observed source matches the verbatim patterns in the Context Summary table above. Any deviation invalidates later task code blocks — STOP and report. Otherwise proceed.

- [ ] **Step 6: Do not commit anything**

Read-only reconnaissance. Report findings to the controller. Do NOT create any file or run any linter — that is the implementer's work in later tasks.

---

### Task 2: Scaffold `FlaskPlugin` + detection

**Files:**
- Create: `cast-clone-backend/app/stages/plugins/flask_plugin/__init__.py`
- Create: `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`
- Create: `cast-clone-backend/app/stages/plugins/flask_plugin/blueprints.py`
- Create: `cast-clone-backend/app/stages/plugins/flask_plugin/restful.py`
- Create: `cast-clone-backend/app/stages/plugins/flask_plugin/sqlalchemy_adapter.py`
- Create: `cast-clone-backend/tests/unit/test_flask_plugin.py`

- [ ] **Step 1: Write the failing tests**

Create `cast-clone-backend/tests/unit/test_flask_plugin.py`:

```python
"""Unit tests for FlaskPlugin (M4)."""

from __future__ import annotations

import pytest

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode


def _ctx() -> AnalysisContext:
    return AnalysisContext(project_id="test-project")


def test_plugin_class_is_importable():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    plugin = FlaskPlugin()
    assert plugin.name == "flask"
    assert "python" in plugin.supported_languages
    assert plugin.depends_on == []


def test_detect_not_detected_on_empty_graph():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    result = FlaskPlugin().detect(_ctx())
    assert result.confidence is None


def test_detect_high_when_flask_route_decorator_present():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="app.blueprints.items.list_items",
            name="list_items",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ['@items_bp.route("", methods=["GET"])']},
        )
    )
    result = FlaskPlugin().detect(ctx)
    assert result.confidence == Confidence.HIGH
    assert "Flask" in result.reason


def test_detect_high_from_manifest_framework():
    from app.models.manifest import DetectedFramework, ProjectManifest
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    ctx.manifest = ProjectManifest(
        project_root="/fake",
        detected_frameworks=[DetectedFramework(name="Flask", version="3.0")],
    )
    result = FlaskPlugin().detect(ctx)
    assert result.confidence == Confidence.HIGH
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.stages.plugins.flask_plugin'`.

- [ ] **Step 3: Create package skeleton**

Create `cast-clone-backend/app/stages/plugins/flask_plugin/__init__.py`:

```python
"""Flask framework plugin — routes, blueprints, Flask-RESTful, Flask-SQLAlchemy."""

from app.stages.plugins.flask_plugin.routes import FlaskPlugin

__all__ = ["FlaskPlugin"]
```

Create `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`:

```python
"""FlaskPlugin — entry point for Flask route/blueprint/restful/model extraction.

Composes helpers from blueprints.py, restful.py, and sqlalchemy_adapter.py.
"""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, NodeKind
from app.models.graph import SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Matches @<var>.route("/path", ...) including @app.route and @bp.route.
_ROUTE_DECORATOR_RE = re.compile(
    r"^@(\w+)\.route\(\s*[\"']([^\"']*)[\"']"
)


def _has_flask_route_annotation(graph: SymbolGraph) -> bool:
    for node in graph.nodes.values():
        if node.kind != NodeKind.FUNCTION or node.language != "python":
            continue
        for deco in node.properties.get("annotations", []):
            if _ROUTE_DECORATOR_RE.match(deco):
                return True
    return False


class FlaskPlugin(FrameworkPlugin):
    name = "flask"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest is not None:
            for fw in context.manifest.detected_frameworks:
                if "flask" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Flask framework '{fw.name}' detected in manifest",
                    )
        if _has_flask_route_annotation(context.graph):
            return PluginDetectionResult(
                confidence=Confidence.HIGH,
                reason="Flask route decorators found in graph",
            )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("flask_extract_start")
        log.info("flask_extract_complete")
        return PluginResult(warnings=[])

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(
            rules=[
                LayerRule(pattern="@app.route", layer="Presentation"),
                LayerRule(pattern="@.route", layer="Presentation"),
            ]
        )
```

Create three empty helper stubs to keep imports valid:

`cast-clone-backend/app/stages/plugins/flask_plugin/blueprints.py`:

```python
"""Blueprint parsing helpers (M4 Task 5)."""

from __future__ import annotations
```

`cast-clone-backend/app/stages/plugins/flask_plugin/restful.py`:

```python
"""Flask-RESTful and MethodView helpers (M4 Tasks 8-10)."""

from __future__ import annotations
```

`cast-clone-backend/app/stages/plugins/flask_plugin/sqlalchemy_adapter.py`:

```python
"""Flask-SQLAlchemy db.Model adapter (M4 Tasks 11-12)."""

from __future__ import annotations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: all four scaffolding tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/flask_plugin/ \
        cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "feat(flask): scaffold FlaskPlugin + detect via manifest or route decorator"
```

---

### Task 3: Extract `@app.route()` endpoints

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`
- Modify: `cast-clone-backend/tests/unit/test_flask_plugin.py`

**Background:** A Flask app-level decorator looks like `@app.route("/login", methods=["GET", "POST"])`. When `methods=` is absent, Flask defaults to `["GET"]`. Each HTTP method produces its own APIEndpoint node so consumers can reason per-method.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flask_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_emits_endpoint_from_app_route():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    handler = GraphNode(
        fqn="app.wsgi.login",
        name="login",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@app.route("/login", methods=["GET", "POST"])']},
    )
    ctx.graph.add_node(handler)

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert len(endpoints) == 2
    methods = sorted(ep.properties["method"] for ep in endpoints)
    assert methods == ["GET", "POST"]
    paths = {ep.properties["path"] for ep in endpoints}
    assert paths == {"/login"}

    handles = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
    assert len(handles) == 2
    assert all(e.source_fqn == handler.fqn for e in handles)


@pytest.mark.asyncio
async def test_extract_defaults_app_route_method_to_get():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="app.wsgi.home",
            name="home",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ['@app.route("/")']},
        )
    )

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert len(endpoints) == 1
    assert endpoints[0].properties["method"] == "GET"
    assert endpoints[0].properties["path"] == "/"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: the two new tests FAIL — `extract()` currently returns empty.

- [ ] **Step 3: Implement `@<var>.route(...)` extraction**

Replace the contents of `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py` with:

```python
"""FlaskPlugin — entry point for Flask route/blueprint/restful/model extraction.

Composes helpers from blueprints.py, restful.py, and sqlalchemy_adapter.py.
"""

from __future__ import annotations

import re

import structlog

from app.models.context import AnalysisContext, EntryPoint
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# @<var>.route("/path", methods=["GET", "POST"])
_ROUTE_DECORATOR_RE = re.compile(
    r"^@(\w+)\.route\(\s*[\"']([^\"']*)[\"']"
)
_METHODS_KWARG_RE = re.compile(
    r"methods\s*=\s*\[([^\]]*)\]"
)
_METHOD_STRING_RE = re.compile(r"[\"']([A-Z]+)[\"']")

APP_ROUTE_VARS: frozenset[str] = frozenset({"app"})


def _parse_methods(decorator: str) -> list[str]:
    match = _METHODS_KWARG_RE.search(decorator)
    if not match:
        return ["GET"]
    inner = match.group(1)
    methods = [m.group(1).upper() for m in _METHOD_STRING_RE.finditer(inner)]
    return methods or ["GET"]


def _has_flask_route_annotation(graph: SymbolGraph) -> bool:
    for node in graph.nodes.values():
        if node.kind != NodeKind.FUNCTION or node.language != "python":
            continue
        for deco in node.properties.get("annotations", []):
            if _ROUTE_DECORATOR_RE.match(deco):
                return True
    return False


def _make_endpoint(
    path: str,
    method: str,
    handler_fqn: str,
    framework_tag: str = "flask",
    blueprint: str | None = None,
) -> tuple[GraphNode, GraphEdge, EntryPoint]:
    endpoint_fqn = f"{method}:{path}"
    props: dict[str, object] = {
        "method": method,
        "path": path,
        "framework": framework_tag,
    }
    if blueprint is not None:
        props["blueprint"] = blueprint
    endpoint = GraphNode(
        fqn=endpoint_fqn,
        name=f"{method} {path}",
        kind=NodeKind.API_ENDPOINT,
        language="python",
        properties=props,
    )
    edge = GraphEdge(
        source_fqn=handler_fqn,
        target_fqn=endpoint_fqn,
        kind=EdgeKind.HANDLES,
        confidence=Confidence.HIGH,
        evidence="flask-decorator",
    )
    entry = EntryPoint(
        fqn=endpoint_fqn,
        kind="http_endpoint",
        metadata={"method": method, "path": path},
    )
    return endpoint, edge, entry


class FlaskPlugin(FrameworkPlugin):
    name = "flask"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest is not None:
            for fw in context.manifest.detected_frameworks:
                if "flask" in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Flask framework '{fw.name}' detected in manifest",
                    )
        if _has_flask_route_annotation(context.graph):
            return PluginDetectionResult(
                confidence=Confidence.HIGH,
                reason="Flask route decorators found in graph",
            )
        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("flask_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        layer_assignments: dict[str, str] = {}
        warnings: list[str] = []

        for func in graph.nodes.values():
            if func.kind != NodeKind.FUNCTION or func.language != "python":
                continue
            for deco in func.properties.get("annotations", []):
                match = _ROUTE_DECORATOR_RE.match(deco)
                if not match:
                    continue
                var_name, path = match.group(1), match.group(2)
                if var_name not in APP_ROUTE_VARS:
                    continue
                for method in _parse_methods(deco):
                    endpoint, edge, entry = _make_endpoint(
                        path=path,
                        method=method,
                        handler_fqn=func.fqn,
                    )
                    nodes.append(endpoint)
                    edges.append(edge)
                    entry_points.append(entry)
                    layer_assignments[func.fqn] = "Presentation"

        log.info(
            "flask_extract_complete",
            endpoints=len([n for n in nodes if n.kind == NodeKind.API_ENDPOINT]),
        )
        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments=layer_assignments,
            entry_points=entry_points,
            warnings=warnings,
        )

    def get_layer_classification(self) -> LayerRules:
        return LayerRules(
            rules=[
                LayerRule(pattern="@app.route", layer="Presentation"),
                LayerRule(pattern="@.route", layer="Presentation"),
            ]
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/flask_plugin/routes.py \
        cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "feat(flask): emit APIEndpoint + HANDLES for @app.route() decorators"
```

---

### Task 4: Extract `@bp.route()` with blueprint tagging (prefix deferred)

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`
- Modify: `cast-clone-backend/tests/unit/test_flask_plugin.py`

**Background:** `@items_bp.route("/foo")` is a blueprint-scoped route. The blueprint's `url_prefix` is not known yet (resolved in Task 5/6). For this task we emit the endpoint with the raw path and tag it `blueprint=<variable_name>` so Task 6 can rewrite the path in a second pass.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flask_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_emits_endpoint_from_blueprint_route():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    handler = GraphNode(
        fqn="app.blueprints.items.list_items",
        name="list_items",
        kind=NodeKind.FUNCTION,
        language="python",
        properties={"annotations": ['@items_bp.route("", methods=["GET"])']},
    )
    ctx.graph.add_node(handler)

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert len(endpoints) == 1
    ep = endpoints[0]
    assert ep.properties["method"] == "GET"
    assert ep.properties["path"] == ""
    assert ep.properties["blueprint"] == "items_bp"


@pytest.mark.asyncio
async def test_extract_blueprint_route_with_path_converter():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="app.blueprints.items.adjust_quantity",
            name="adjust_quantity",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={
                "annotations": ['@items_bp.route("/<int:item_id>/adjust", methods=["POST"])'],
            },
        )
    )

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert len(endpoints) == 1
    assert endpoints[0].properties["path"] == "/<int:item_id>/adjust"
    assert endpoints[0].properties["method"] == "POST"
    assert endpoints[0].properties["blueprint"] == "items_bp"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: the two new tests FAIL — current code skips non-`app` route decorators (`var_name not in APP_ROUTE_VARS`).

- [ ] **Step 3: Relax the filter and tag blueprint routes**

In `routes.py`, replace the inner loop in `extract()` that handles route decorators. Specifically, change the early-continue on `var_name not in APP_ROUTE_VARS` to instead flag the endpoint as blueprint-scoped when the variable is not `app`:

```python
        for func in graph.nodes.values():
            if func.kind != NodeKind.FUNCTION or func.language != "python":
                continue
            for deco in func.properties.get("annotations", []):
                match = _ROUTE_DECORATOR_RE.match(deco)
                if not match:
                    continue
                var_name, path = match.group(1), match.group(2)
                blueprint = None if var_name in APP_ROUTE_VARS else var_name
                for method in _parse_methods(deco):
                    endpoint, edge, entry = _make_endpoint(
                        path=path,
                        method=method,
                        handler_fqn=func.fqn,
                        blueprint=blueprint,
                    )
                    nodes.append(endpoint)
                    edges.append(edge)
                    entry_points.append(entry)
                    layer_assignments[func.fqn] = "Presentation"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/flask_plugin/routes.py \
        cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "feat(flask): tag blueprint-scoped endpoints (prefix resolution deferred)"
```

---

### Task 5: Blueprint prefix resolution in `blueprints.py`

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/blueprints.py`
- Modify: `cast-clone-backend/tests/unit/test_flask_plugin.py`

**Background:** Flask exposes two places where a blueprint can get a url prefix:
1. Construction: `items_bp = Blueprint("items", __name__, url_prefix="/items-ctor")`
2. Registration: `app.register_blueprint(items_bp, url_prefix="/items")`

Registration-time prefix wins if both are present. The helper `resolve_blueprint_prefixes()` scans FIELD nodes (Blueprint constructors stored as class-level/module-level assignments) and FUNCTION bodies (register_blueprint calls — represented as `CALLS` edges). In practice, tree-sitter captures the constructor arguments as the FIELD's `value` property and we cannot easily see the register_blueprint arguments without SCIP-level resolution; for M4 we rely on regex over the raw source value.

Our fixture in flask-inventory does not pass `url_prefix` to the constructor, so registration-time resolution is what matters. We parse register_blueprint calls by scanning FIELD nodes whose `value` property starts with `register_blueprint(` OR by reading module source text if the tree-sitter data is insufficient — since that escalates scope, M4 uses a simpler approach: locate FIELD nodes whose `value` contains `register_blueprint(` and parse them with a regex.

The cleanest hook is `app/__init__.py`'s `create_app()` body, where the fixture's `register_blueprint` calls live. The tree-sitter extractor stores bodies as FUNCTION nodes with a `body_source` property... actually it does not. Therefore we fall back to **module file re-reading** for Flask app factories. Since the pipeline already knows `context.manifest.project_root`, `blueprints.py` can open the file that defined each blueprint variable and regex the register_blueprint calls out of it.

To keep this deterministic and simple for M4: `resolve_blueprint_prefixes()` takes `(graph, project_root)` and:
1. Finds every FIELD node whose `value` contains `Blueprint(`. Records `(name, file_path, ctor_prefix)`.
2. For each source file referenced, re-opens the file and regex-scans for `register_blueprint(<name>, url_prefix="/...")`. Records `(name, reg_prefix)`.
3. Returns a map `{bp_variable_name: effective_prefix}` where effective = reg_prefix or ctor_prefix or `""`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flask_plugin.py`:

```python
def test_resolve_blueprint_prefixes_from_registration(tmp_path):
    from app.stages.plugins.flask_plugin.blueprints import resolve_blueprint_prefixes

    # Simulate an app/__init__.py that registers items_bp and warehouses_bp.
    app_init = tmp_path / "app" / "__init__.py"
    app_init.parent.mkdir(parents=True)
    app_init.write_text(
        'from flask import Flask\n'
        'from app.blueprints.items import items_bp\n'
        'from app.blueprints.warehouses import warehouses_bp\n'
        'def create_app():\n'
        '    app = Flask(__name__)\n'
        '    app.register_blueprint(items_bp, url_prefix="/items")\n'
        '    app.register_blueprint(warehouses_bp, url_prefix="/warehouses")\n'
        '    return app\n'
    )

    # Also simulate the blueprint module files with ctor declarations.
    items_file = tmp_path / "app" / "blueprints" / "items.py"
    items_file.parent.mkdir(parents=True)
    items_file.write_text('items_bp = Blueprint("items", __name__)\n')

    warehouses_file = tmp_path / "app" / "blueprints" / "warehouses.py"
    warehouses_file.write_text('warehouses_bp = Blueprint("warehouses", __name__)\n')

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    # Field nodes that the tree-sitter extractor would produce
    graph.add_node(
        GraphNode(
            fqn="app.blueprints.items.items_bp",
            name="items_bp",
            kind=NodeKind.FIELD,
            language="python",
            path=str(items_file),
            properties={"value": 'Blueprint("items", __name__)'},
        )
    )
    graph.add_node(
        GraphNode(
            fqn="app.blueprints.warehouses.warehouses_bp",
            name="warehouses_bp",
            kind=NodeKind.FIELD,
            language="python",
            path=str(warehouses_file),
            properties={"value": 'Blueprint("warehouses", __name__)'},
        )
    )

    result = resolve_blueprint_prefixes(graph, project_root=str(tmp_path))

    assert result == {"items_bp": "/items", "warehouses_bp": "/warehouses"}


def test_resolve_blueprint_prefixes_prefers_registration_over_constructor(tmp_path):
    from app.stages.plugins.flask_plugin.blueprints import resolve_blueprint_prefixes

    app_init = tmp_path / "app" / "__init__.py"
    app_init.parent.mkdir(parents=True)
    app_init.write_text(
        'app.register_blueprint(items_bp, url_prefix="/v2/items")\n'
    )
    items_file = tmp_path / "app" / "items.py"
    items_file.write_text('items_bp = Blueprint("items", __name__, url_prefix="/v1")\n')

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    graph.add_node(
        GraphNode(
            fqn="app.items.items_bp",
            name="items_bp",
            kind=NodeKind.FIELD,
            language="python",
            path=str(items_file),
            properties={"value": 'Blueprint("items", __name__, url_prefix="/v1")'},
        )
    )

    result = resolve_blueprint_prefixes(graph, project_root=str(tmp_path))

    assert result["items_bp"] == "/v2/items"


def test_resolve_blueprint_prefixes_falls_back_to_constructor(tmp_path):
    from app.stages.plugins.flask_plugin.blueprints import resolve_blueprint_prefixes

    # No register_blueprint calls anywhere in the tree.
    items_file = tmp_path / "app" / "items.py"
    items_file.parent.mkdir(parents=True)
    items_file.write_text('bp = Blueprint("x", __name__, url_prefix="/only")\n')

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    graph.add_node(
        GraphNode(
            fqn="app.items.bp",
            name="bp",
            kind=NodeKind.FIELD,
            language="python",
            path=str(items_file),
            properties={"value": 'Blueprint("x", __name__, url_prefix="/only")'},
        )
    )

    result = resolve_blueprint_prefixes(graph, project_root=str(tmp_path))

    assert result == {"bp": "/only"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: FAIL with `ImportError: cannot import name 'resolve_blueprint_prefixes'`.

- [ ] **Step 3: Implement the helper**

Replace `cast-clone-backend/app/stages/plugins/flask_plugin/blueprints.py` with:

```python
"""Blueprint prefix resolution helpers (M4 Task 5)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from app.models.enums import NodeKind
from app.models.graph import SymbolGraph

# Blueprint("name", __name__, url_prefix="/x")
_BLUEPRINT_CTOR_RE = re.compile(
    r"Blueprint\([^)]*?url_prefix\s*=\s*[\"']([^\"']+)[\"']"
)
# register_blueprint(bp_var, url_prefix="/x")
_REGISTER_RE = re.compile(
    r"register_blueprint\(\s*(\w+)\s*(?:,[^)]*?url_prefix\s*=\s*[\"']([^\"']+)[\"'])?"
)


def _extract_constructor_prefix(raw_value: str) -> str | None:
    match = _BLUEPRINT_CTOR_RE.search(raw_value)
    return match.group(1) if match else None


def _scan_registration_calls(project_root: str) -> dict[str, str]:
    """Walk every .py file under project_root and collect register_blueprint calls.

    Returns a map of blueprint variable name → registration-time url_prefix.
    Silently skips files we cannot read.
    """
    registrations: dict[str, str] = {}
    root = Path(project_root)
    if not root.exists():
        return registrations
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(dirpath) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in _REGISTER_RE.finditer(text):
                var_name = match.group(1)
                prefix = match.group(2)
                if prefix is not None:
                    registrations[var_name] = prefix
    return registrations


def resolve_blueprint_prefixes(
    graph: SymbolGraph, project_root: str
) -> dict[str, str]:
    """Return `{blueprint_variable_name: effective_url_prefix}`.

    Registration-time prefix wins over construction-time prefix. Blueprints
    with no prefix at all are omitted from the map (callers treat this as "").
    """
    constructor_prefixes: dict[str, str] = {}
    for node in graph.nodes.values():
        if node.kind != NodeKind.FIELD or node.language != "python":
            continue
        raw = node.properties.get("value", "")
        if "Blueprint(" not in raw:
            continue
        ctor_prefix = _extract_constructor_prefix(raw)
        if ctor_prefix is not None:
            constructor_prefixes[node.name] = ctor_prefix

    registration_prefixes = _scan_registration_calls(project_root)

    merged: dict[str, str] = {}
    for var in set(constructor_prefixes) | set(registration_prefixes):
        if var in registration_prefixes:
            merged[var] = registration_prefixes[var]
        else:
            merged[var] = constructor_prefixes[var]
    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/flask_plugin/blueprints.py \
        cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "feat(flask): resolve blueprint url_prefix from registration or constructor"
```

---

### Task 6: Apply blueprint prefixes in `FlaskPlugin.extract()`

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`
- Modify: `cast-clone-backend/tests/unit/test_flask_plugin.py`

**Background:** After Task 5 we have a `{bp_var: prefix}` map. We need to rewrite the `path` of every blueprint-tagged APIEndpoint node we emit in Task 4 so that the final path is `prefix + raw_path`. The endpoint's `fqn` (`{method}:{path}`) must also reflect the full path, otherwise Neo4j will create duplicate nodes.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_flask_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_applies_blueprint_prefix_to_endpoint(tmp_path):
    from app.models.manifest import ProjectManifest
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    # Simulate the flask-inventory structure.
    app_init = tmp_path / "app" / "__init__.py"
    app_init.parent.mkdir(parents=True)
    app_init.write_text(
        'app.register_blueprint(items_bp, url_prefix="/items")\n'
    )
    items_file = tmp_path / "app" / "blueprints" / "items.py"
    items_file.parent.mkdir(parents=True)
    items_file.write_text('items_bp = Blueprint("items", __name__)\n')

    ctx = _ctx()
    ctx.manifest = ProjectManifest(project_root=str(tmp_path))
    # Blueprint FIELD node
    ctx.graph.add_node(
        GraphNode(
            fqn="app.blueprints.items.items_bp",
            name="items_bp",
            kind=NodeKind.FIELD,
            language="python",
            path=str(items_file),
            properties={"value": 'Blueprint("items", __name__)'},
        )
    )
    # Handler with @items_bp.route
    ctx.graph.add_node(
        GraphNode(
            fqn="app.blueprints.items.list_items",
            name="list_items",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"annotations": ['@items_bp.route("", methods=["GET"])']},
        )
    )

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert len(endpoints) == 1
    assert endpoints[0].properties["path"] == "/items"
    assert endpoints[0].fqn == "GET:/items"


@pytest.mark.asyncio
async def test_extract_joins_blueprint_prefix_and_path_with_single_slash(tmp_path):
    from app.models.manifest import ProjectManifest
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    app_init = tmp_path / "app" / "__init__.py"
    app_init.parent.mkdir(parents=True)
    app_init.write_text(
        'app.register_blueprint(items_bp, url_prefix="/items")\n'
    )
    items_file = tmp_path / "app" / "blueprints" / "items.py"
    items_file.parent.mkdir(parents=True)
    items_file.write_text('items_bp = Blueprint("items", __name__)\n')

    ctx = _ctx()
    ctx.manifest = ProjectManifest(project_root=str(tmp_path))
    ctx.graph.add_node(
        GraphNode(
            fqn="app.blueprints.items.items_bp",
            name="items_bp",
            kind=NodeKind.FIELD,
            language="python",
            path=str(items_file),
            properties={"value": 'Blueprint("items", __name__)'},
        )
    )
    ctx.graph.add_node(
        GraphNode(
            fqn="app.blueprints.items.adjust",
            name="adjust",
            kind=NodeKind.FUNCTION,
            language="python",
            properties={
                "annotations": ['@items_bp.route("/<int:item_id>/adjust", methods=["POST"])']
            },
        )
    )

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert endpoints[0].properties["path"] == "/items/<int:item_id>/adjust"
    assert endpoints[0].fqn == "POST:/items/<int:item_id>/adjust"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: the two new tests FAIL (current path is `""` / `"/<int:item_id>/adjust"` without prefix).

- [ ] **Step 3: Wire the prefix resolver into `extract()`**

In `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`, add the import at the top:

```python
from app.stages.plugins.flask_plugin.blueprints import resolve_blueprint_prefixes
```

Add a helper at module scope:

```python
def _join_prefix_and_path(prefix: str, path: str) -> str:
    """Join a Flask url_prefix with a route path using exactly one slash."""
    if not prefix:
        return path
    if not path:
        return prefix
    if prefix.endswith("/") and path.startswith("/"):
        return prefix + path[1:]
    if not prefix.endswith("/") and not path.startswith("/"):
        return f"{prefix}/{path}"
    return prefix + path
```

Replace the `extract()` body so blueprint-tagged endpoints have their paths rewritten before the endpoint node is built. Replace the decorator loop with:

```python
        project_root = (
            context.manifest.project_root if context.manifest is not None else ""
        )
        bp_prefixes = resolve_blueprint_prefixes(graph, project_root) if project_root else {}

        for func in graph.nodes.values():
            if func.kind != NodeKind.FUNCTION or func.language != "python":
                continue
            for deco in func.properties.get("annotations", []):
                match = _ROUTE_DECORATOR_RE.match(deco)
                if not match:
                    continue
                var_name, raw_path = match.group(1), match.group(2)
                blueprint = None if var_name in APP_ROUTE_VARS else var_name
                prefix = bp_prefixes.get(var_name, "") if blueprint else ""
                full_path = _join_prefix_and_path(prefix, raw_path)
                for method in _parse_methods(deco):
                    endpoint, edge, entry = _make_endpoint(
                        path=full_path,
                        method=method,
                        handler_fqn=func.fqn,
                        blueprint=blueprint,
                    )
                    nodes.append(endpoint)
                    edges.append(edge)
                    entry_points.append(entry)
                    layer_assignments[func.fqn] = "Presentation"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/flask_plugin/routes.py \
        cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "feat(flask): apply blueprint url_prefix to endpoint paths"
```

---

### Task 7: Recognize `add_url_rule()` calls

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`
- Modify: `cast-clone-backend/tests/unit/test_flask_plugin.py`

**Background:** Some Flask apps use `app.add_url_rule("/path", endpoint="name", view_func=handler, methods=[...])` instead of (or in addition to) `@app.route`. We scan FIELD nodes whose `value` starts with `add_url_rule(` and reconstruct the endpoint. We can only resolve the view_func when its name matches a FUNCTION FQN in the same module. Unresolvable rules get a warning, not an error.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flask_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_emits_endpoint_from_add_url_rule():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    # Handler exists
    ctx.graph.add_node(
        GraphNode(
            fqn="app.main.healthcheck",
            name="healthcheck",
            kind=NodeKind.FUNCTION,
            language="python",
        )
    )
    # A FIELD whose value is the add_url_rule call. The tree-sitter extractor
    # can emit such nodes for top-level expression statements stored as side effects;
    # for this test we seed the FIELD directly.
    ctx.graph.add_node(
        GraphNode(
            fqn="app.main.__add_url_rule_0",
            name="__add_url_rule_0",
            kind=NodeKind.FIELD,
            language="python",
            properties={
                "value": 'add_url_rule("/healthz", endpoint="hc", view_func=healthcheck, methods=["GET"])'
            },
        )
    )

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    assert any(ep.properties["path"] == "/healthz" for ep in endpoints)
    handles = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
    assert any(
        e.source_fqn == "app.main.healthcheck"
        and e.target_fqn.startswith("GET:/healthz")
        for e in handles
    )


@pytest.mark.asyncio
async def test_extract_warns_on_unresolvable_add_url_rule_view_func():
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    ctx = _ctx()
    ctx.graph.add_node(
        GraphNode(
            fqn="app.main.__add_url_rule_0",
            name="__add_url_rule_0",
            kind=NodeKind.FIELD,
            language="python",
            properties={
                "value": 'add_url_rule("/x", view_func=ghost, methods=["GET"])'
            },
        )
    )

    result = await FlaskPlugin().extract(ctx)

    assert any("ghost" in w for w in result.warnings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: the two new tests FAIL.

- [ ] **Step 3: Implement `add_url_rule` scanning**

In `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`, add at module scope:

```python
_ADD_URL_RULE_RE = re.compile(
    r"^add_url_rule\(\s*[\"']([^\"']+)[\"'].*?view_func\s*=\s*(\w+)",
    re.DOTALL,
)
```

Add a helper method inside `FlaskPlugin`:

```python
    def _extract_add_url_rule_endpoints(
        self, graph: SymbolGraph
    ) -> tuple[list[GraphNode], list[GraphEdge], list[EntryPoint], list[str]]:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        warnings: list[str] = []

        for node in graph.nodes.values():
            if node.kind != NodeKind.FIELD or node.language != "python":
                continue
            raw = node.properties.get("value", "")
            if not raw.startswith("add_url_rule("):
                continue
            match = _ADD_URL_RULE_RE.match(raw)
            if not match:
                continue
            path, view_func = match.group(1), match.group(2)
            methods = _parse_methods(raw)

            handler_fqn = None
            parent_module = node.fqn.rsplit(".", 1)[0]
            candidate = f"{parent_module}.{view_func}"
            if candidate in graph.nodes:
                handler_fqn = candidate
            elif view_func in graph.nodes:
                handler_fqn = view_func
            else:
                for fqn in graph.nodes:
                    if fqn.endswith(f".{view_func}"):
                        handler_fqn = fqn
                        break

            if handler_fqn is None:
                warnings.append(
                    f"add_url_rule view_func '{view_func}' at path '{path}' unresolved"
                )
                continue

            for method in methods:
                endpoint, edge, entry = _make_endpoint(
                    path=path,
                    method=method,
                    handler_fqn=handler_fqn,
                )
                nodes.append(endpoint)
                edges.append(edge)
                entry_points.append(entry)
        return nodes, edges, entry_points, warnings
```

Call the helper from `extract()` right after the decorator loop:

```python
        rule_nodes, rule_edges, rule_entries, rule_warnings = (
            self._extract_add_url_rule_endpoints(graph)
        )
        nodes.extend(rule_nodes)
        edges.extend(rule_edges)
        entry_points.extend(rule_entries)
        warnings.extend(rule_warnings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/flask_plugin/routes.py \
        cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "feat(flask): emit endpoints from add_url_rule() + warn on unresolved view_func"
```

---

### Task 8: Flask-RESTful Resource + MethodView method enumeration

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/restful.py`
- Modify: `cast-clone-backend/tests/unit/test_flask_plugin.py`

**Background:** A `Resource` (or `MethodView`) subclass may define any of `get`, `post`, `put`, `patch`, `delete`, `head`, `options`. Each defined method becomes an endpoint when the class is later registered via `api.add_resource(cls, "/path")`. This task extracts the method list; Task 9 binds it to paths.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flask_plugin.py`:

```python
def test_enumerate_resource_methods_finds_defined_http_methods():
    from app.stages.plugins.flask_plugin.restful import (
        enumerate_resource_methods,
    )

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    resource_class = GraphNode(
        fqn="app.resources.ItemListResource",
        name="ItemListResource",
        kind=NodeKind.CLASS,
        language="python",
    )
    graph.add_node(resource_class)
    graph.add_edge(
        GraphEdge(
            source_fqn=resource_class.fqn,
            target_fqn="Resource",
            kind=EdgeKind.INHERITS,
        )
    )
    for method_name in ("get", "post"):
        m = GraphNode(
            fqn=f"{resource_class.fqn}.{method_name}",
            name=method_name,
            kind=NodeKind.FUNCTION,
            language="python",
            properties={"is_method": True},
        )
        graph.add_node(m)
        graph.add_edge(
            GraphEdge(source_fqn=resource_class.fqn, target_fqn=m.fqn, kind=EdgeKind.CONTAINS)
        )
    # Non-HTTP method should not be picked up
    helper = GraphNode(
        fqn=f"{resource_class.fqn}.internal",
        name="internal",
        kind=NodeKind.FUNCTION,
        language="python",
    )
    graph.add_node(helper)
    graph.add_edge(
        GraphEdge(source_fqn=resource_class.fqn, target_fqn=helper.fqn, kind=EdgeKind.CONTAINS)
    )

    result = enumerate_resource_methods(graph, base_classes=frozenset({"Resource"}))

    assert resource_class.fqn in result
    methods = result[resource_class.fqn]
    assert sorted(methods) == [
        ("GET", f"{resource_class.fqn}.get"),
        ("POST", f"{resource_class.fqn}.post"),
    ]


def test_enumerate_resource_methods_ignores_unrelated_classes():
    from app.stages.plugins.flask_plugin.restful import enumerate_resource_methods

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    graph.add_node(
        GraphNode(
            fqn="app.services.TodoService",
            name="TodoService",
            kind=NodeKind.CLASS,
            language="python",
        )
    )
    # Note: no INHERITS edge targeting Resource/MethodView

    assert enumerate_resource_methods(graph, base_classes=frozenset({"Resource"})) == {}


def test_enumerate_resource_methods_supports_methodview():
    from app.stages.plugins.flask_plugin.restful import enumerate_resource_methods

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    cls = GraphNode(
        fqn="app.views.UserView",
        name="UserView",
        kind=NodeKind.CLASS,
        language="python",
    )
    graph.add_node(cls)
    graph.add_edge(
        GraphEdge(source_fqn=cls.fqn, target_fqn="MethodView", kind=EdgeKind.INHERITS)
    )
    m = GraphNode(
        fqn=f"{cls.fqn}.delete",
        name="delete",
        kind=NodeKind.FUNCTION,
        language="python",
    )
    graph.add_node(m)
    graph.add_edge(GraphEdge(source_fqn=cls.fqn, target_fqn=m.fqn, kind=EdgeKind.CONTAINS))

    result = enumerate_resource_methods(
        graph, base_classes=frozenset({"Resource", "MethodView"})
    )

    assert result == {cls.fqn: [("DELETE", f"{cls.fqn}.delete")]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the helper**

Replace `cast-clone-backend/app/stages/plugins/flask_plugin/restful.py` with:

```python
"""Flask-RESTful Resource + MethodView helpers (M4 Tasks 8-10)."""

from __future__ import annotations

from app.models.enums import EdgeKind, NodeKind
from app.models.graph import SymbolGraph

_HTTP_METHOD_NAMES: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options"}
)


def _class_inherits_from(graph: SymbolGraph, class_fqn: str, bases: frozenset[str]) -> bool:
    """Return True if the class has an INHERITS edge whose target matches any base.

    Matches the raw base name or any FQN ending in `.<base>` (accommodates
    'flask_restful.Resource' etc.).
    """
    for edge in graph.edges:
        if edge.kind != EdgeKind.INHERITS or edge.source_fqn != class_fqn:
            continue
        target = edge.target_fqn
        if target in bases:
            return True
        for base in bases:
            if target.endswith(f".{base}"):
                return True
    return False


def enumerate_resource_methods(
    graph: SymbolGraph, base_classes: frozenset[str]
) -> dict[str, list[tuple[str, str]]]:
    """Return `{class_fqn: [(HTTP_METHOD, method_fqn), ...]}` for every class that
    inherits (directly) from any of the given base class names and defines at least
    one HTTP-named method.
    """
    # class_fqn → list of (child_name, child_fqn) via CONTAINS
    contained: dict[str, list[tuple[str, str]]] = {}
    for edge in graph.edges:
        if edge.kind != EdgeKind.CONTAINS:
            continue
        child = graph.get_node(edge.target_fqn)
        if child is None or child.kind != NodeKind.FUNCTION:
            continue
        contained.setdefault(edge.source_fqn, []).append((child.name, child.fqn))

    result: dict[str, list[tuple[str, str]]] = {}
    for node in graph.nodes.values():
        if node.kind != NodeKind.CLASS or node.language != "python":
            continue
        if not _class_inherits_from(graph, node.fqn, base_classes):
            continue
        methods: list[tuple[str, str]] = []
        for child_name, child_fqn in contained.get(node.fqn, []):
            if child_name.lower() in _HTTP_METHOD_NAMES:
                methods.append((child_name.upper(), child_fqn))
        if methods:
            result[node.fqn] = methods
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/flask_plugin/restful.py \
        cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "feat(flask): enumerate Resource/MethodView HTTP methods via INHERITS+CONTAINS"
```

---

### Task 9: `api.add_resource()` + `Api(prefix=...)` binding

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/restful.py`
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`
- Modify: `cast-clone-backend/tests/unit/test_flask_plugin.py`

**Background:** `Api(app, prefix="/api")` sets a global prefix for every resource registered via `api.add_resource(cls, "/items")`. The Api construction and add_resource calls live in the factory/app-init module. We scan `.py` files under the project root (same technique as Task 5's registration scan).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flask_plugin.py`:

```python
def test_resolve_restful_bindings_reads_api_prefix_and_add_resource(tmp_path):
    from app.stages.plugins.flask_plugin.restful import resolve_restful_bindings

    app_init = tmp_path / "app" / "__init__.py"
    app_init.parent.mkdir(parents=True)
    app_init.write_text(
        'api = Api(app, prefix="/api")\n'
        'api.add_resource(ItemListResource, "/items")\n'
        'api.add_resource(ItemResource, "/items/<int:item_id>")\n'
    )

    bindings = resolve_restful_bindings(project_root=str(tmp_path))

    assert bindings == {
        "ItemListResource": "/api/items",
        "ItemResource": "/api/items/<int:item_id>",
    }


def test_resolve_restful_bindings_no_api_prefix(tmp_path):
    from app.stages.plugins.flask_plugin.restful import resolve_restful_bindings

    app_init = tmp_path / "app" / "__init__.py"
    app_init.parent.mkdir(parents=True)
    app_init.write_text(
        'api = Api(app)\n'
        'api.add_resource(HealthResource, "/healthz")\n'
    )

    bindings = resolve_restful_bindings(project_root=str(tmp_path))

    assert bindings == {"HealthResource": "/healthz"}


@pytest.mark.asyncio
async def test_extract_emits_endpoints_per_resource_method(tmp_path):
    from app.models.manifest import ProjectManifest
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    app_init = tmp_path / "app" / "__init__.py"
    app_init.parent.mkdir(parents=True)
    app_init.write_text(
        'api = Api(app, prefix="/api")\n'
        'api.add_resource(ItemListResource, "/items")\n'
    )

    ctx = _ctx()
    ctx.manifest = ProjectManifest(project_root=str(tmp_path))
    cls = GraphNode(
        fqn="app.resources.ItemListResource",
        name="ItemListResource",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(cls)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=cls.fqn, target_fqn="Resource", kind=EdgeKind.INHERITS)
    )
    for method_name in ("get", "post"):
        m = GraphNode(
            fqn=f"{cls.fqn}.{method_name}",
            name=method_name,
            kind=NodeKind.FUNCTION,
            language="python",
        )
        ctx.graph.add_node(m)
        ctx.graph.add_edge(
            GraphEdge(source_fqn=cls.fqn, target_fqn=m.fqn, kind=EdgeKind.CONTAINS)
        )

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    ep_map = {(ep.properties["method"], ep.properties["path"]): ep for ep in endpoints}
    assert ("GET", "/api/items") in ep_map
    assert ("POST", "/api/items") in ep_map

    handles = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
    assert any(
        e.source_fqn == f"{cls.fqn}.get" and e.target_fqn == "GET:/api/items"
        for e in handles
    )
    assert any(
        e.source_fqn == f"{cls.fqn}.post" and e.target_fqn == "POST:/api/items"
        for e in handles
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement `resolve_restful_bindings` and wire into `extract()`**

Append to `cast-clone-backend/app/stages/plugins/flask_plugin/restful.py`:

```python
import os
import re
from pathlib import Path

_API_CTOR_RE = re.compile(r"Api\([^)]*?prefix\s*=\s*[\"']([^\"']+)[\"']")
_ADD_RESOURCE_RE = re.compile(
    r"add_resource\(\s*(\w+)\s*,\s*[\"']([^\"']+)[\"']"
)


def _join_prefix(prefix: str, path: str) -> str:
    if not prefix:
        return path
    if not path:
        return prefix
    if prefix.endswith("/") and path.startswith("/"):
        return prefix + path[1:]
    if not prefix.endswith("/") and not path.startswith("/"):
        return f"{prefix}/{path}"
    return prefix + path


def resolve_restful_bindings(project_root: str) -> dict[str, str]:
    """Return `{resource_class_name: effective_path}` by scanning .py files.

    Resolves the Api(prefix=...) global prefix and joins it with every
    api.add_resource(cls, "/path") call. When no Api prefix is present,
    the path is used as-is.
    """
    bindings: dict[str, str] = {}
    root = Path(project_root)
    if not root.exists():
        return bindings

    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(dirpath) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            api_prefix_match = _API_CTOR_RE.search(text)
            api_prefix = api_prefix_match.group(1) if api_prefix_match else ""
            for match in _ADD_RESOURCE_RE.finditer(text):
                cls_name = match.group(1)
                path = match.group(2)
                bindings[cls_name] = _join_prefix(api_prefix, path)
    return bindings
```

Extend `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`. Add imports:

```python
from app.stages.plugins.flask_plugin.restful import (
    enumerate_resource_methods,
    resolve_restful_bindings,
)

_RESTFUL_BASE_CLASSES: frozenset[str] = frozenset({"Resource", "MethodView"})
```

Add a helper method:

```python
    def _extract_restful_endpoints(
        self, graph: SymbolGraph, project_root: str
    ) -> tuple[list[GraphNode], list[GraphEdge], list[EntryPoint], list[str]]:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        entry_points: list[EntryPoint] = []
        warnings: list[str] = []

        bindings = resolve_restful_bindings(project_root) if project_root else {}
        methods_by_class = enumerate_resource_methods(graph, _RESTFUL_BASE_CLASSES)

        for class_fqn, methods in methods_by_class.items():
            class_node = graph.get_node(class_fqn)
            if class_node is None:
                continue
            path = bindings.get(class_node.name)
            if path is None:
                warnings.append(
                    f"restful resource {class_node.name} has no add_resource binding"
                )
                continue
            for http_method, handler_fqn in methods:
                endpoint, edge, entry = _make_endpoint(
                    path=path,
                    method=http_method,
                    handler_fqn=handler_fqn,
                )
                nodes.append(endpoint)
                edges.append(edge)
                entry_points.append(entry)
        return nodes, edges, entry_points, warnings
```

Call it from `extract()` after the `add_url_rule` helper:

```python
        rest_nodes, rest_edges, rest_entries, rest_warnings = (
            self._extract_restful_endpoints(graph, project_root)
        )
        nodes.extend(rest_nodes)
        edges.extend(rest_edges)
        entry_points.extend(rest_entries)
        warnings.extend(rest_warnings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/flask_plugin/restful.py \
        cast-clone-backend/app/stages/plugins/flask_plugin/routes.py \
        cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "feat(flask): bind Flask-RESTful Resource classes to endpoints via api.add_resource"
```

---

### Task 10: `MethodView` subclass coverage in integration surface

**Files:**
- Modify: `cast-clone-backend/tests/unit/test_flask_plugin.py`

**Background:** Task 8 already supports `MethodView` via `_RESTFUL_BASE_CLASSES`. This task adds an end-to-end coverage assertion at the plugin level to lock the behavior against future regression. The mechanism for binding MethodView to a URL differs (`app.add_url_rule("/path", view_func=UserView.as_view("user"))`) but is rare enough in practice that we accept the limitation: MethodView endpoints are recognized when registered via `add_resource` (via Flask-RESTful) OR when the factory uses `as_view` which our Task 7 regex does not match. We document the limitation and ship.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_flask_plugin.py`:

```python
@pytest.mark.asyncio
async def test_extract_endpoints_for_methodview_registered_via_add_resource(tmp_path):
    from app.models.manifest import ProjectManifest
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    app_init = tmp_path / "app" / "__init__.py"
    app_init.parent.mkdir(parents=True)
    app_init.write_text(
        'api = Api(app)\n'
        'api.add_resource(UserView, "/users/<int:user_id>")\n'
    )

    ctx = _ctx()
    ctx.manifest = ProjectManifest(project_root=str(tmp_path))
    cls = GraphNode(
        fqn="app.views.UserView",
        name="UserView",
        kind=NodeKind.CLASS,
        language="python",
    )
    ctx.graph.add_node(cls)
    ctx.graph.add_edge(
        GraphEdge(source_fqn=cls.fqn, target_fqn="MethodView", kind=EdgeKind.INHERITS)
    )
    for method_name in ("get", "delete"):
        m = GraphNode(
            fqn=f"{cls.fqn}.{method_name}",
            name=method_name,
            kind=NodeKind.FUNCTION,
            language="python",
        )
        ctx.graph.add_node(m)
        ctx.graph.add_edge(
            GraphEdge(source_fqn=cls.fqn, target_fqn=m.fqn, kind=EdgeKind.CONTAINS)
        )

    result = await FlaskPlugin().extract(ctx)

    endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
    paths = {(ep.properties["method"], ep.properties["path"]) for ep in endpoints}
    assert ("GET", "/users/<int:user_id>") in paths
    assert ("DELETE", "/users/<int:user_id>") in paths
```

- [ ] **Step 2: Run test to verify it PASSES immediately**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py::test_extract_endpoints_for_methodview_registered_via_add_resource -v`

Expected: PASS — Task 8's `_RESTFUL_BASE_CLASSES = frozenset({"Resource", "MethodView"})` already covers this path, so the test should succeed without new implementation code.

If the test FAILS, investigate: either the helper doesn't include `MethodView` in its base set (fix in Task 8's frozenset) or the `enumerate_resource_methods` filter drops a class incorrectly. Do not introduce new plugin logic — this task exists to lock the coverage guarantee.

- [ ] **Step 3: Commit the regression lock**

```bash
git add cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "test(unit): lock MethodView→add_resource coverage"
```

---

### Task 11: `sqlalchemy_adapter.py` — TABLE nodes from `db.Model` subclasses

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/sqlalchemy_adapter.py`
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`
- Modify: `cast-clone-backend/tests/unit/test_flask_plugin.py`

**Background:** Flask-SQLAlchemy pattern: `class Warehouse(db.Model):` with `__tablename__ = "warehouses"`. We detect classes that INHERITS from `db.Model` (or ends in `.Model` with the `db.` namespace). The `__tablename__` FIELD value (stripped of quotes) becomes the TABLE node's `name`; fallback is the snake_case of the class name.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flask_plugin.py`:

```python
def test_extract_flask_sqlalchemy_tables_uses_tablename_field():
    from app.stages.plugins.flask_plugin.sqlalchemy_adapter import (
        extract_flask_sqlalchemy_tables,
    )

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    cls = GraphNode(
        fqn="app.models.Warehouse",
        name="Warehouse",
        kind=NodeKind.CLASS,
        language="python",
    )
    graph.add_node(cls)
    graph.add_edge(
        GraphEdge(source_fqn=cls.fqn, target_fqn="db.Model", kind=EdgeKind.INHERITS)
    )
    tablename = GraphNode(
        fqn=f"{cls.fqn}.__tablename__",
        name="__tablename__",
        kind=NodeKind.FIELD,
        language="python",
        properties={"value": '"warehouses"'},
    )
    graph.add_node(tablename)
    graph.add_edge(
        GraphEdge(source_fqn=cls.fqn, target_fqn=tablename.fqn, kind=EdgeKind.CONTAINS)
    )

    tables = extract_flask_sqlalchemy_tables(graph)

    assert len(tables) == 1
    table_node, class_fqn = tables[0]
    assert table_node.kind == NodeKind.TABLE
    assert table_node.name == "warehouses"
    assert class_fqn == cls.fqn


def test_extract_flask_sqlalchemy_tables_falls_back_to_snakecased_class_name():
    from app.stages.plugins.flask_plugin.sqlalchemy_adapter import (
        extract_flask_sqlalchemy_tables,
    )

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    cls = GraphNode(
        fqn="app.models.PriceTier",
        name="PriceTier",
        kind=NodeKind.CLASS,
        language="python",
    )
    graph.add_node(cls)
    graph.add_edge(
        GraphEdge(source_fqn=cls.fqn, target_fqn="db.Model", kind=EdgeKind.INHERITS)
    )

    tables = extract_flask_sqlalchemy_tables(graph)

    assert len(tables) == 1
    assert tables[0][0].name == "price_tier"


def test_extract_flask_sqlalchemy_tables_skips_non_model_classes():
    from app.stages.plugins.flask_plugin.sqlalchemy_adapter import (
        extract_flask_sqlalchemy_tables,
    )

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    cls = GraphNode(
        fqn="app.services.TodoService",
        name="TodoService",
        kind=NodeKind.CLASS,
        language="python",
    )
    graph.add_node(cls)

    assert extract_flask_sqlalchemy_tables(graph) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the extractor**

Replace `cast-clone-backend/app/stages/plugins/flask_plugin/sqlalchemy_adapter.py` with:

```python
"""Flask-SQLAlchemy db.Model adapter (M4 Tasks 11-12)."""

from __future__ import annotations

import re

from app.models.enums import EdgeKind, NodeKind
from app.models.graph import GraphNode, SymbolGraph

_DB_MODEL_BASES: frozenset[str] = frozenset({"db.Model", "Model"})
_SNAKECASE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _to_snake_case(name: str) -> str:
    return _SNAKECASE_RE.sub("_", name).lower()


def _class_is_flask_model(graph: SymbolGraph, class_fqn: str) -> bool:
    for edge in graph.edges:
        if edge.kind != EdgeKind.INHERITS or edge.source_fqn != class_fqn:
            continue
        target = edge.target_fqn
        if target in _DB_MODEL_BASES:
            return True
        for base in _DB_MODEL_BASES:
            if target.endswith(f".{base}"):
                return True
    return False


def _find_tablename(graph: SymbolGraph, class_fqn: str) -> str | None:
    for edge in graph.edges:
        if edge.kind != EdgeKind.CONTAINS or edge.source_fqn != class_fqn:
            continue
        child = graph.get_node(edge.target_fqn)
        if (
            child is not None
            and child.kind == NodeKind.FIELD
            and child.name == "__tablename__"
        ):
            raw = child.properties.get("value", "").strip()
            if (raw.startswith('"') and raw.endswith('"')) or (
                raw.startswith("'") and raw.endswith("'")
            ):
                return raw[1:-1]
    return None


def extract_flask_sqlalchemy_tables(
    graph: SymbolGraph,
) -> list[tuple[GraphNode, str]]:
    """Return [(TableNode, source_class_fqn), ...] for every Flask-SQLAlchemy model class."""
    results: list[tuple[GraphNode, str]] = []
    for node in graph.nodes.values():
        if node.kind != NodeKind.CLASS or node.language != "python":
            continue
        if not _class_is_flask_model(graph, node.fqn):
            continue
        table_name = _find_tablename(graph, node.fqn) or _to_snake_case(node.name)
        table = GraphNode(
            fqn=f"table::{table_name}",
            name=table_name,
            kind=NodeKind.TABLE,
            language="python",
            properties={"framework": "flask-sqlalchemy"},
        )
        results.append((table, node.fqn))
    return results
```

Extend `FlaskPlugin.extract()` in `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`. Add the import:

```python
from app.stages.plugins.flask_plugin.sqlalchemy_adapter import (
    extract_flask_sqlalchemy_tables,
)
```

Append to `extract()` just before the final `log.info`:

```python
        for table_node, class_fqn in extract_flask_sqlalchemy_tables(graph):
            nodes.append(table_node)
            layer_assignments[class_fqn] = "Data Access"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/flask_plugin/sqlalchemy_adapter.py \
        cast-clone-backend/app/stages/plugins/flask_plugin/routes.py \
        cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "feat(flask): emit TABLE nodes for Flask-SQLAlchemy db.Model subclasses"
```

---

### Task 12: `db.Column` → COLUMN + `db.ForeignKey` → REFERENCES

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/sqlalchemy_adapter.py`
- Modify: `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`
- Modify: `cast-clone-backend/tests/unit/test_flask_plugin.py`

**Background:** FIELD nodes under a `db.Model` class whose `value` matches `db.Column(...)` are columns. Column properties: first positional arg is the SQL type (`db.Integer`, `db.String(100)`, etc.); `primary_key=True`, `nullable=False`, `unique=True` are recognized kwargs. `db.ForeignKey("warehouses.id")` inside a column definition produces a REFERENCES edge from that column FQN to the referenced `warehouses.id` column FQN.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_flask_plugin.py`:

```python
def test_extract_flask_sqlalchemy_columns():
    from app.stages.plugins.flask_plugin.sqlalchemy_adapter import (
        extract_flask_sqlalchemy_columns,
    )

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    cls = GraphNode(
        fqn="app.models.Item",
        name="Item",
        kind=NodeKind.CLASS,
        language="python",
    )
    graph.add_node(cls)
    graph.add_edge(
        GraphEdge(source_fqn=cls.fqn, target_fqn="db.Model", kind=EdgeKind.INHERITS)
    )
    graph.add_node(
        GraphNode(
            fqn=f"{cls.fqn}.__tablename__",
            name="__tablename__",
            kind=NodeKind.FIELD,
            language="python",
            properties={"value": '"items"'},
        )
    )
    graph.add_edge(
        GraphEdge(
            source_fqn=cls.fqn,
            target_fqn=f"{cls.fqn}.__tablename__",
            kind=EdgeKind.CONTAINS,
        )
    )
    id_field = GraphNode(
        fqn=f"{cls.fqn}.id",
        name="id",
        kind=NodeKind.FIELD,
        language="python",
        properties={"value": "db.Column(db.Integer, primary_key=True)"},
    )
    sku_field = GraphNode(
        fqn=f"{cls.fqn}.sku",
        name="sku",
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "value": "db.Column(db.String(64), unique=True, nullable=False)"
        },
    )
    graph.add_node(id_field)
    graph.add_node(sku_field)
    graph.add_edge(GraphEdge(source_fqn=cls.fqn, target_fqn=id_field.fqn, kind=EdgeKind.CONTAINS))
    graph.add_edge(
        GraphEdge(source_fqn=cls.fqn, target_fqn=sku_field.fqn, kind=EdgeKind.CONTAINS)
    )

    columns, has_column_edges, references = extract_flask_sqlalchemy_columns(graph)

    by_name = {col.name: col for col in columns}
    assert set(by_name) == {"id", "sku"}
    assert by_name["id"].properties["type"] == "INTEGER"
    assert by_name["id"].properties["primary_key"] is True
    assert by_name["sku"].properties["type"] == "VARCHAR(64)"
    assert by_name["sku"].properties["unique"] is True
    assert by_name["sku"].properties["nullable"] is False

    assert len(has_column_edges) == 2
    assert all(e.kind == EdgeKind.HAS_COLUMN for e in has_column_edges)
    table_fqn = "table::items"
    assert all(e.source_fqn == table_fqn for e in has_column_edges)
    assert references == []


def test_extract_flask_sqlalchemy_columns_emits_foreignkey_reference():
    from app.stages.plugins.flask_plugin.sqlalchemy_adapter import (
        extract_flask_sqlalchemy_columns,
    )

    from app.models.graph import SymbolGraph
    graph = SymbolGraph()
    item_cls = GraphNode(
        fqn="app.models.Item",
        name="Item",
        kind=NodeKind.CLASS,
        language="python",
    )
    graph.add_node(item_cls)
    graph.add_edge(
        GraphEdge(source_fqn=item_cls.fqn, target_fqn="db.Model", kind=EdgeKind.INHERITS)
    )
    graph.add_node(
        GraphNode(
            fqn=f"{item_cls.fqn}.__tablename__",
            name="__tablename__",
            kind=NodeKind.FIELD,
            language="python",
            properties={"value": '"items"'},
        )
    )
    graph.add_edge(
        GraphEdge(
            source_fqn=item_cls.fqn,
            target_fqn=f"{item_cls.fqn}.__tablename__",
            kind=EdgeKind.CONTAINS,
        )
    )
    fk_field = GraphNode(
        fqn=f"{item_cls.fqn}.warehouse_id",
        name="warehouse_id",
        kind=NodeKind.FIELD,
        language="python",
        properties={
            "value": (
                'db.Column(db.Integer, '
                'db.ForeignKey("warehouses.id", ondelete="CASCADE"), '
                'nullable=False)'
            )
        },
    )
    graph.add_node(fk_field)
    graph.add_edge(
        GraphEdge(source_fqn=item_cls.fqn, target_fqn=fk_field.fqn, kind=EdgeKind.CONTAINS)
    )

    _columns, _has, references = extract_flask_sqlalchemy_columns(graph)

    assert len(references) == 1
    ref = references[0]
    assert ref.kind == EdgeKind.REFERENCES
    assert ref.source_fqn == "column::items.warehouse_id"
    assert ref.target_fqn == "column::warehouses.id"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: FAIL with `ImportError: cannot import name 'extract_flask_sqlalchemy_columns'`.

- [ ] **Step 3: Implement column + foreign-key extraction**

Append to `cast-clone-backend/app/stages/plugins/flask_plugin/sqlalchemy_adapter.py`:

```python
from app.models.enums import Confidence
from app.models.graph import GraphEdge

_DB_COLUMN_CALL_RE = re.compile(r"^db\.Column\(")
_DB_TYPE_SIMPLE_RE = re.compile(r"db\.(Integer|BigInteger|SmallInteger|Boolean|Float|Numeric|Date|DateTime|Text)")
_DB_TYPE_STRING_RE = re.compile(r"db\.String\(\s*(\d+)\s*\)")
_FOREIGN_KEY_RE = re.compile(
    r"db\.ForeignKey\(\s*[\"']([^\"']+)[\"']"
)
_TRUE_KWARG_RE = re.compile(r"(primary_key|unique|nullable)\s*=\s*(True|False)")

_DB_TYPE_TO_SQL: dict[str, str] = {
    "Integer": "INTEGER",
    "BigInteger": "BIGINT",
    "SmallInteger": "SMALLINT",
    "Boolean": "BOOLEAN",
    "Float": "FLOAT",
    "Numeric": "NUMERIC",
    "Date": "DATE",
    "DateTime": "TIMESTAMP",
    "Text": "TEXT",
}


def _parse_column_type(raw: str) -> str:
    str_match = _DB_TYPE_STRING_RE.search(raw)
    if str_match:
        return f"VARCHAR({str_match.group(1)})"
    simple_match = _DB_TYPE_SIMPLE_RE.search(raw)
    if simple_match:
        return _DB_TYPE_TO_SQL[simple_match.group(1)]
    return "UNKNOWN"


def _parse_column_flags(raw: str) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for match in _TRUE_KWARG_RE.finditer(raw):
        flags[match.group(1)] = match.group(2) == "True"
    return flags


def extract_flask_sqlalchemy_columns(
    graph: SymbolGraph,
) -> tuple[list[GraphNode], list[GraphEdge], list[GraphEdge]]:
    """Return `(column_nodes, has_column_edges, reference_edges)` for every Flask-
    SQLAlchemy model class.
    """
    columns: list[GraphNode] = []
    has_column: list[GraphEdge] = []
    references: list[GraphEdge] = []

    for cls_node in graph.nodes.values():
        if cls_node.kind != NodeKind.CLASS or cls_node.language != "python":
            continue
        if not _class_is_flask_model(graph, cls_node.fqn):
            continue
        table_name = _find_tablename(graph, cls_node.fqn) or _to_snake_case(cls_node.name)
        table_fqn = f"table::{table_name}"

        for edge in graph.edges:
            if edge.kind != EdgeKind.CONTAINS or edge.source_fqn != cls_node.fqn:
                continue
            child = graph.get_node(edge.target_fqn)
            if child is None or child.kind != NodeKind.FIELD:
                continue
            if child.name == "__tablename__":
                continue
            raw = child.properties.get("value", "").strip()
            if not _DB_COLUMN_CALL_RE.match(raw):
                continue

            col_fqn = f"column::{table_name}.{child.name}"
            flags = _parse_column_flags(raw)
            column = GraphNode(
                fqn=col_fqn,
                name=child.name,
                kind=NodeKind.COLUMN,
                language="python",
                properties={
                    "type": _parse_column_type(raw),
                    "primary_key": flags.get("primary_key", False),
                    "nullable": flags.get("nullable", True),
                    "unique": flags.get("unique", False),
                    "framework": "flask-sqlalchemy",
                },
            )
            columns.append(column)
            has_column.append(
                GraphEdge(
                    source_fqn=table_fqn,
                    target_fqn=col_fqn,
                    kind=EdgeKind.HAS_COLUMN,
                    confidence=Confidence.HIGH,
                    evidence="flask-sqlalchemy",
                )
            )
            fk_match = _FOREIGN_KEY_RE.search(raw)
            if fk_match:
                target_spec = fk_match.group(1)
                # target_spec like "warehouses.id"
                references.append(
                    GraphEdge(
                        source_fqn=col_fqn,
                        target_fqn=f"column::{target_spec}",
                        kind=EdgeKind.REFERENCES,
                        confidence=Confidence.HIGH,
                        evidence="flask-sqlalchemy-foreignkey",
                    )
                )
    return columns, has_column, references
```

Extend `FlaskPlugin.extract()` in `cast-clone-backend/app/stages/plugins/flask_plugin/routes.py`. Replace the existing `for table_node, class_fqn in extract_flask_sqlalchemy_tables(graph):` block with:

```python
        for table_node, class_fqn in extract_flask_sqlalchemy_tables(graph):
            nodes.append(table_node)
            layer_assignments[class_fqn] = "Data Access"

        col_nodes, has_column_edges, ref_edges = extract_flask_sqlalchemy_columns(graph)
        nodes.extend(col_nodes)
        edges.extend(has_column_edges)
        edges.extend(ref_edges)
```

Also add the import:

```python
from app.stages.plugins.flask_plugin.sqlalchemy_adapter import (
    extract_flask_sqlalchemy_columns,
    extract_flask_sqlalchemy_tables,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_flask_plugin.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/flask_plugin/sqlalchemy_adapter.py \
        cast-clone-backend/app/stages/plugins/flask_plugin/routes.py \
        cast-clone-backend/tests/unit/test_flask_plugin.py
git commit -m "feat(flask): extract db.Column → COLUMN + db.ForeignKey → REFERENCES edges"
```

---

### Task 13: Register `FlaskPlugin` with the global registry

**Files:**
- Modify: `cast-clone-backend/app/stages/plugins/__init__.py`
- Modify: `cast-clone-backend/tests/unit/test_plugin_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `cast-clone-backend/tests/unit/test_plugin_registry.py`:

```python
def test_flask_plugin_is_registered():
    from app.stages.plugins import global_registry
    from app.stages.plugins.flask_plugin.routes import FlaskPlugin

    assert FlaskPlugin in global_registry.plugin_classes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_registry.py::test_flask_plugin_is_registered -v`

Expected: FAIL.

- [ ] **Step 3: Register**

Edit `cast-clone-backend/app/stages/plugins/__init__.py`. Near the other plugin imports, add:

```python
from app.stages.plugins.flask_plugin.routes import FlaskPlugin
```

Near the registry registrations (after the last `global_registry.register(...)` call), add:

```python
global_registry.register(FlaskPlugin)
```

Also update `__all__` to include `"FlaskPlugin"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_plugin_registry.py -v`

Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/stages/plugins/__init__.py \
        cast-clone-backend/tests/unit/test_plugin_registry.py
git commit -m "feat(flask): register FlaskPlugin with global registry"
```

---

### Task 14: Integration — `flask-inventory` blueprint endpoints

**Files:**
- Create: `cast-clone-backend/tests/integration/test_python_m4_pipeline.py`

- [ ] **Step 1: Write the failing test**

Create `cast-clone-backend/tests/integration/test_python_m4_pipeline.py`:

```python
"""M4 integration tests — Flask plugin end-to-end chains against flask-inventory."""

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
    """Run discovery → dependencies → treesitter → SCIP → plugins."""
    from app.stages.dependencies import resolve_dependencies
    from app.stages.discovery import discover_project
    from app.stages.plugins.registry import run_framework_plugins
    from app.stages.scip.indexer import run_scip_indexers
    from app.stages.treesitter.parser import parse_with_treesitter

    ctx = AnalysisContext(project_id=project_id)
    ctx.manifest = await discover_project(fixture_root)
    ctx.environment = await resolve_dependencies(ctx.manifest)
    await parse_with_treesitter(ctx)
    await run_scip_indexers(ctx)
    await run_framework_plugins(ctx)
    return ctx


class TestFlaskInventoryBlueprints:
    """Acceptance: blueprint routes produce endpoints with the correct prefix."""

    @pytest.fixture(scope="class")
    async def ctx(self) -> AnalysisContext:
        return await _run_pipeline_stages_1_to_5(
            FIXTURES_ROOT / "flask-inventory", "flask-inventory-m4"
        )

    async def test_items_list_endpoint_exists(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/items"
            and n.properties.get("method") == "GET"
        ]
        assert len(eps) >= 1, "expected GET /items endpoint from items_bp"

    async def test_items_adjust_endpoint_includes_path_converter(
        self, ctx: AnalysisContext
    ) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/items/<int:item_id>/adjust"
            and n.properties.get("method") == "POST"
        ]
        assert len(eps) == 1

    async def test_warehouses_list_endpoint_exists(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/warehouses"
            and n.properties.get("method") == "GET"
        ]
        assert len(eps) >= 1

    async def test_warehouses_items_nested_endpoint_exists(
        self, ctx: AnalysisContext
    ) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/warehouses/<int:wh_id>/items"
            and n.properties.get("method") == "GET"
        ]
        assert len(eps) == 1

    async def test_blueprint_endpoint_has_handles_edge(
        self, ctx: AnalysisContext
    ) -> None:
        handles = [e for e in ctx.graph.edges if e.kind == EdgeKind.HANDLES]
        assert any(
            e.target_fqn == "GET:/items"
            and e.source_fqn.endswith("list_items")
            for e in handles
        ), "expected HANDLES edge from list_items → GET:/items"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/integration/test_python_m4_pipeline.py::TestFlaskInventoryBlueprints -v`

Expected: PASS. If the harness import fails (`_run_pipeline_stages_1_to_5`), mirror M3's test file (`tests/integration/test_python_m3_pipeline.py`) exactly — it uses the same helper signature.

- [ ] **Step 3: Commit**

```bash
git add cast-clone-backend/tests/integration/test_python_m4_pipeline.py
git commit -m "test(integration): flask-inventory blueprint endpoints + prefix resolution"
```

---

### Task 15: Integration — `flask-inventory` Flask-RESTful Resource endpoints

**Files:**
- Modify: `cast-clone-backend/tests/integration/test_python_m4_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_python_m4_pipeline.py`:

```python
class TestFlaskInventoryRestful:
    """Acceptance: Flask-RESTful resources produce endpoints with Api prefix applied."""

    @pytest.fixture(scope="class")
    async def ctx(self) -> AnalysisContext:
        return await _run_pipeline_stages_1_to_5(
            FIXTURES_ROOT / "flask-inventory", "flask-inventory-m4-restful"
        )

    async def test_api_items_list_get(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/api/items"
            and n.properties.get("method") == "GET"
        ]
        assert len(eps) == 1

    async def test_api_items_list_post(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/api/items"
            and n.properties.get("method") == "POST"
        ]
        assert len(eps) == 1

    async def test_api_items_detail_get(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/api/items/<int:item_id>"
            and n.properties.get("method") == "GET"
        ]
        assert len(eps) == 1

    async def test_api_items_detail_delete(self, ctx: AnalysisContext) -> None:
        eps = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.API_ENDPOINT
            and n.properties.get("path") == "/api/items/<int:item_id>"
            and n.properties.get("method") == "DELETE"
        ]
        assert len(eps) == 1

    async def test_resource_method_has_handles_edge(
        self, ctx: AnalysisContext
    ) -> None:
        handles = [e for e in ctx.graph.edges if e.kind == EdgeKind.HANDLES]
        assert any(
            e.target_fqn == "DELETE:/api/items/<int:item_id>"
            and e.source_fqn.endswith("ItemResource.delete")
            for e in handles
        )
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/integration/test_python_m4_pipeline.py::TestFlaskInventoryRestful -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add cast-clone-backend/tests/integration/test_python_m4_pipeline.py
git commit -m "test(integration): flask-inventory Flask-RESTful endpoints + Api prefix"
```

---

### Task 16: Integration — `flask-inventory` Flask-SQLAlchemy tables

**Files:**
- Modify: `cast-clone-backend/tests/integration/test_python_m4_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_python_m4_pipeline.py`:

```python
class TestFlaskInventoryModels:
    """Acceptance: Flask-SQLAlchemy db.Model subclasses produce TABLE + COLUMN + REFERENCES."""

    @pytest.fixture(scope="class")
    async def ctx(self) -> AnalysisContext:
        return await _run_pipeline_stages_1_to_5(
            FIXTURES_ROOT / "flask-inventory", "flask-inventory-m4-models"
        )

    async def test_warehouses_table_exists(self, ctx: AnalysisContext) -> None:
        tables = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.TABLE and n.name == "warehouses"
        ]
        assert len(tables) == 1

    async def test_items_table_exists(self, ctx: AnalysisContext) -> None:
        tables = [
            n
            for n in ctx.graph.nodes.values()
            if n.kind == NodeKind.TABLE and n.name == "items"
        ]
        assert len(tables) == 1

    async def test_items_has_expected_columns(self, ctx: AnalysisContext) -> None:
        has_columns = [
            e
            for e in ctx.graph.edges
            if e.kind == EdgeKind.HAS_COLUMN and e.source_fqn == "table::items"
        ]
        col_names = {
            ctx.graph.get_node(e.target_fqn).name
            for e in has_columns
            if ctx.graph.get_node(e.target_fqn) is not None
        }
        assert {"id", "sku", "name", "quantity", "warehouse_id"} <= col_names

    async def test_items_warehouse_id_references_warehouses_id(
        self, ctx: AnalysisContext
    ) -> None:
        refs = [
            e
            for e in ctx.graph.edges
            if e.kind == EdgeKind.REFERENCES
            and e.source_fqn == "column::items.warehouse_id"
            and e.target_fqn == "column::warehouses.id"
        ]
        assert len(refs) == 1
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/integration/test_python_m4_pipeline.py::TestFlaskInventoryModels -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add cast-clone-backend/tests/integration/test_python_m4_pipeline.py
git commit -m "test(integration): flask-inventory Flask-SQLAlchemy tables + columns + FK"
```

---

### Task 17: End-to-end smoke — all three fixtures, <5 min, ≤5 warnings each

**Files:**
- Create: `cast-clone-backend/tests/e2e/__init__.py`
- Create: `cast-clone-backend/tests/e2e/test_python_full_stack.py`

**Background:** Spec M4 acceptance: "no fixture emits >5 warnings" and "each fixture completes in <5 min on developer laptop." We enforce both as a smoke test that runs in-process across all three fixtures. No Neo4j write (stage 8 skipped) — the gate is on graph size, warning count, and wall time.

- [ ] **Step 1: Write the failing test**

Create `cast-clone-backend/tests/e2e/__init__.py` (empty file).

Create `cast-clone-backend/tests/e2e/test_python_full_stack.py`:

```python
"""Python Phase 1 end-to-end smoke — runs all three fixtures in sequence.

Acceptance gates:
- Each fixture completes in <5 minutes (wall clock)
- Each fixture surfaces at most 5 warnings
- Each fixture produces a non-empty graph
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.models.context import AnalysisContext

FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures"

FIXTURES: list[tuple[str, str]] = [
    ("fastapi-todo", "e2e-fastapi-todo"),
    ("django-blog", "e2e-django-blog"),
    ("flask-inventory", "e2e-flask-inventory"),
]

MAX_DURATION_SECONDS: float = 300.0  # 5 minutes
MAX_WARNINGS: int = 5


pytestmark = [pytest.mark.e2e, pytest.mark.scip_python]


async def _run_full_pipeline(
    fixture_root: Path, project_id: str
) -> tuple[AnalysisContext, float]:
    """Run stages 1–7 (skipping the Neo4j writer). Returns (context, duration_s)."""
    from app.stages.dependencies import resolve_dependencies
    from app.stages.discovery import discover_project
    from app.stages.enricher import enrich_graph
    from app.stages.linker import run_cross_tech_linker
    from app.stages.plugins.registry import run_framework_plugins
    from app.stages.scip.indexer import run_scip_indexers
    from app.stages.treesitter.parser import parse_with_treesitter

    ctx = AnalysisContext(project_id=project_id)
    start = time.monotonic()
    ctx.manifest = await discover_project(fixture_root)
    ctx.environment = await resolve_dependencies(ctx.manifest)
    await parse_with_treesitter(ctx)
    await run_scip_indexers(ctx)
    await run_framework_plugins(ctx)
    await run_cross_tech_linker(ctx)
    await enrich_graph(ctx)
    return ctx, time.monotonic() - start


@pytest.mark.parametrize("fixture_name,project_id", FIXTURES)
async def test_fixture_meets_phase1_acceptance_gates(
    fixture_name: str, project_id: str
) -> None:
    fixture = FIXTURES_ROOT / fixture_name
    assert fixture.is_dir(), f"fixture dir missing: {fixture}"

    ctx, duration = await _run_full_pipeline(fixture, project_id)

    assert duration < MAX_DURATION_SECONDS, (
        f"{fixture_name} pipeline took {duration:.1f}s "
        f"(budget {MAX_DURATION_SECONDS}s)"
    )
    assert len(ctx.warnings) <= MAX_WARNINGS, (
        f"{fixture_name} emitted {len(ctx.warnings)} warnings (budget {MAX_WARNINGS}): "
        f"{ctx.warnings}"
    )
    assert ctx.graph.node_count > 0, f"{fixture_name} produced an empty graph"
    assert ctx.graph.edge_count > 0, f"{fixture_name} produced no edges"
```

- [ ] **Step 2: Update pytest configuration to include the new `e2e` marker**

Check `cast-clone-backend/pyproject.toml` (the `[tool.pytest.ini_options]` block). If the `markers` list exists and does NOT include `e2e`, add it:

```toml
markers = [
    "integration: integration tests",
    "scip_python: requires scip-python",
    "e2e: end-to-end smoke tests",
]
```

If no `markers` list is configured, leave pytest defaults (unregistered markers produce a warning but do not fail). If the M3 runbook added `scip_python` inline, mirror the same registration style.

- [ ] **Step 3: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/e2e/test_python_full_stack.py -v -m e2e`

Expected: three parameterised test cases PASS. If any fixture's duration or warning count exceeds the budget, do NOT relax the budget — instead investigate the plugin producing the warnings and fix the cause. Typical culprits: Task 7's `add_url_rule` warning on an unmatched `view_func`, or M3's `resolve_producer_edges` hitting an unexpected trigger-method suffix.

If `stages` imports fail (e.g. `enricher`, `linker` module paths differ), adjust the harness to match actual exports. The M3 integration harness is a correct template — reuse its imports verbatim if available.

- [ ] **Step 4: Commit**

```bash
git add cast-clone-backend/tests/e2e/__init__.py \
        cast-clone-backend/tests/e2e/test_python_full_stack.py \
        cast-clone-backend/pyproject.toml
git commit -m "test(e2e): Phase 1 Python smoke — all 3 fixtures, <5min, ≤5 warnings each"
```

---

### Task 18: Docs update + full regression sweep

**Files:**
- Modify: `cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `08-FRAMEWORK-PLUGINS.md`**

Open `cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md`. Append a new section after the Celery documentation added in M3:

````markdown
### FlaskPlugin (M4)

Covers Flask-core routes, Blueprint prefix chaining, Flask-RESTful `Resource`/`MethodView`, and the Flask-SQLAlchemy `db.Model` pattern.

**Detection:** `Flask` framework in manifest, or any `@<var>.route(...)` decorator in the graph.

**Routes & blueprints:**

| Pattern | Emits |
|---|---|
| `@app.route("/path", methods=[...])` | `APIEndpoint` + `HANDLES` per method (default `GET`) |
| `@bp.route("/path", methods=[...])` | `APIEndpoint` tagged `blueprint=<var>`; path includes registered prefix |
| `Blueprint("name", __name__, url_prefix="/x")` | Recorded as construction-time prefix |
| `app.register_blueprint(bp, url_prefix="/x")` | Recorded as registration-time prefix (wins over constructor) |
| `add_url_rule("/path", view_func=f, methods=[...])` | `APIEndpoint` + `HANDLES`; warns if `view_func` is unresolved |

**Flask-RESTful + MethodView:**

| Pattern | Emits |
|---|---|
| `class X(Resource):` with `get`/`post`/etc. methods | One `APIEndpoint` per HTTP method per registered path |
| `class X(MethodView):` with HTTP methods | Same, when registered via `api.add_resource` |
| `Api(app, prefix="/api")` | Global prefix applied to every `api.add_resource(...)` path |
| `api.add_resource(X, "/path")` | Binds X's HTTP methods to the combined path |

**Flask-SQLAlchemy adapter:**

| Pattern | Emits |
|---|---|
| `class X(db.Model):` | `TABLE` node (name from `__tablename__` or snake_cased class name) |
| `db.Column(db.Integer, ...)` | `COLUMN` + `HAS_COLUMN` edge with `type`, `primary_key`, `nullable`, `unique` |
| `db.Column(db.String(N))` | COLUMN type `VARCHAR(N)` |
| `db.ForeignKey("other_table.col")` | `REFERENCES` edge column → referenced column |

**Known limitations:**

- `MethodView` registered via `app.add_url_rule("/p", view_func=V.as_view("name"))` is not recognized (the `as_view()` call is not parsed). Use `api.add_resource()` to register MethodView subclasses if discovery is required.
- `db.relationship(...)` ORM relationships are not emitted; `REFERENCES` is the only cross-table edge M4 produces.
- Blueprint chaining of more than one level (`app.register_blueprint(outer_bp)` where `outer_bp` itself contains `register_blueprint(inner_bp, ...)`) collapses to the outer-most prefix only.
````

- [ ] **Step 2: Update root `CLAUDE.md`**

Open `CLAUDE.md` at the repo root. Find the "Plugin Priority" table. Replace the `Tier 4` row with:

```markdown
| Tier 4 | Django (Settings, ORM, URLs, DRF), FastAPI (Routes, Pydantic Deep), SQLAlchemy (sync+async), Alembic, Celery, Flask (Routes, Blueprints, RESTful, SQLAlchemy adapter) | Python |
```

Also, under "Phase 1 — Core Analysis Engine (Months 1-3)", update the "← CURRENT" marker to "← COMPLETE" and append a one-line note:

```markdown
- Python production-ready: FastAPI, Django, Flask, SQLAlchemy (sync+async), Alembic, Celery, Pydantic deep
```

- [ ] **Step 3: Full regression sweep**

```bash
cd cast-clone-backend
uv run pytest tests/unit/ -q
uv run pytest tests/integration/ -q -m "integration and not e2e"
uv run pytest tests/e2e/ -q -m e2e
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run mypy app/stages/plugins/flask_plugin/
```

Expected:
- Unit tests: at or above M3 baseline. No new failures.
- Integration tests: M4 adds 14 new test methods (5 + 5 + 4); total green.
- E2E: 3 parametrized cases green.
- `ruff check` — 0 new errors versus M3 baseline.
- `ruff format --check` — clean.
- `mypy` on `flask_plugin/` — 0 errors.

Fix any failures at the root cause before committing. Do not relax test expectations.

- [ ] **Step 4: Commit the docs update**

```bash
git add cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md CLAUDE.md
git commit -m "docs(plugins): document FlaskPlugin and mark Python Phase 1 complete"
```

---

## Self-Review Checklist

### Spec coverage

| Spec M4 requirement | Task |
|---|---|
| `app/stages/plugins/flask_plugin/` with 4 sub-modules | Task 2 |
| `@app.route()`, `@bp.route()` → `API_ENDPOINT` + `HANDLES` | Tasks 3, 4 |
| `add_url_rule()` recognition | Task 7 |
| `Blueprint("name", url_prefix=...)` prefix chaining | Tasks 5, 6 |
| `MethodView` subclass → per-method endpoint | Tasks 8, 10 |
| Flask-RESTful `Resource` + `api.add_resource()` | Tasks 8, 9 |
| Flask-SQLAlchemy `db = SQLAlchemy()` + `db.Model` | Tasks 11, 12 |
| End-to-end integration test exercising all 3 fixtures | Task 17 |
| Performance smoke: each fixture <5 min | Task 17 |
| flask-inventory analyzes end-to-end | Tasks 14, 15, 16 |
| No fixture emits >5 warnings | Task 17 (enforced) |
| Doc updates (`08-FRAMEWORK-PLUGINS.md` + CLAUDE.md) | Task 18 |

### Placeholder scan

```bash
grep -nE "TBD|TODO|implement later|fill in details|Similar to Task" \
  docs/superpowers/plans/2026-04-22-python-m4-flask-integration-polish.md || echo "clean"
```

Expected: `clean` (the grep command itself is the only match, and that's self-referential tooling, not a placeholder).

### Type consistency

- `FlaskPlugin.name` is `"flask"` everywhere (Tasks 2, 13).
- Helper names: `resolve_blueprint_prefixes` (Task 5), `enumerate_resource_methods` (Task 8), `resolve_restful_bindings` (Task 9), `extract_flask_sqlalchemy_tables` (Task 11), `extract_flask_sqlalchemy_columns` (Task 12). All referenced in Task 3/4/6/9/11/12 with consistent spellings.
- TABLE fqn format `table::<name>` (Task 11) matches COLUMN owner reference in Task 12.
- COLUMN fqn format `column::<table>.<col>` (Task 12) matches REFERENCES target format and integration assertions (Task 16).
- `APP_ROUTE_VARS` and `_RESTFUL_BASE_CLASSES` frozensets defined at module scope; no local shadowing.

---

## Execution Handoff

Plan complete and ready to save to `docs/superpowers/plans/2026-04-22-python-m4-flask-integration-polish.md`. Two execution options when M1/M2/M3 are merged and the user authorizes M4:

**1. Subagent-Driven (recommended)** — Opus implementer + Sonnet reviewers per task bundle, two-stage gate (spec compliance + code quality) between tasks. Same pattern as M1–M3.

**2. Inline Execution** — Drive tasks in a single session with checkpoints via `superpowers:executing-plans`.

**Which approach?** — Awaiting user direction.
