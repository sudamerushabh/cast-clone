# Python Plugin Completion — Design Spec

**Date**: 2026-04-22
**Scope**: Option B — harden existing Python plugins + fill obvious framework gaps
**Timeline**: 8 weeks across 4 milestones

## Problem

Python plugin support in `cast-clone-backend` is ~90% implemented but incomplete and untested at the framework-graph level:

- `DjangoSettingsPlugin.extract()` is stubbed
- Pydantic request/response schemas are not linked to FastAPI endpoints
- Async SQLAlchemy, Alembic migrations, Flask, and Celery are unsupported
- `scip-python` is wired in but SCIP→Python edge upgrades are not validated end-to-end
- Stage 2 parses Python dependency declarations but does not install them, which degrades all downstream SCIP output
- Only a trivial `python-sample` fixture exists; no realistic FastAPI / Django / Flask fixture validates the pipeline

Without this work, the Python side of the product advertises framework support that is not actually trustworthy for real codebases.

## Solution Shape

**Additive changes within the existing 10-stage pipeline.** No new stages. Three pipeline stages take work:

- **Stage 2 (dependencies)**: add sandboxed `uv venv` + `uv pip install` for Python projects, producing `ResolvedEnvironment.python_venv_path`
- **Stage 4 (SCIP)**: pin `sourcegraph/scip-python:v0.6.6`, pass `VIRTUAL_ENV` + `NODE_OPTIONS` env, handle partial-index success mode
- **Stage 5 (plugins)**: 3 new plugins (Flask, Celery, Alembic); 3 enhanced (FastAPI Pydantic-deep, SQLAlchemy async, Django Settings completion)

## Design Decisions

### DD-1: Venv resolution via sandboxed install
Stage 2 creates an isolated venv per project and runs `uv pip install -e . || uv pip install -r requirements.txt || true` inside a resource-limited subprocess before Stage 4 SCIP.

- Network namespace restricted to PyPI/configured index URLs
- 300s default timeout (configurable per project)
- 2 CPU / 4 GB memory limits
- Read-only source mount; ephemeral write-only venv dir
- **Fail-open**: install failure emits `warnings`, falls back to system Python; downstream plugins degrade via graph-only reads

Rationale: mirrors Sourcegraph's autoindex pattern (`local_steps: ["pip install . || true"]`). SCIP without installed deps produces unresolved imports and LOW-confidence edges — unacceptable for the "MRI for Software" pitch.

### DD-2: Pydantic deep extraction (Q2 option C)
FastAPI plugin links endpoints to Pydantic models, extracts field-level constraints, and fuzzy-matches Pydantic fields to ORM columns in the same project.

- Endpoint → model: `ACCEPTS` (request body), `RETURNS` (response_model)
- Field-level: constraints from `Field(ge=0, max_length=100, ...)` stored on FIELD node properties
- Validators: `@field_validator`, `@model_validator`, `@validator`, `@root_validator` tag enclosing functions with `is_validator: true`
- Pydantic→ORM link: `MAPS_TO` edge with MEDIUM confidence, gated behind `enable_pydantic_orm_linking` per-project setting (**default ON**)

### DD-3: Celery medium-depth plugin (Q3 option B)
Discover tasks AND link producers to consumers.

- Task discovery: `@celery.task`, `@shared_task`, `@app.task` → `EntryPoint(kind="message_consumer")`, layer="Business Logic"
- Queue extraction: `queue=` kwarg → `MESSAGE_TOPIC` node per unique queue name
- Producer linking: `.delay()`, `.apply_async()`, `.s()`, `.signature()` call sites → `CALLS` edge + `PRODUCES` edge to queue (leans on SCIP receiver resolution)
- Consumer linking: task → `CONSUMES` queue
- **Deferred to post-B**: Celery Canvas (chain/group/chord), beat schedules, retry/backoff metadata

### DD-4: Flask medium-depth plugin (Q4 option B)
Flask-core + Flask-SQLAlchemy adapter + Flask-RESTful.

- `@app.route()`, `@bp.route()`, `add_url_rule()` → `API_ENDPOINT` + `HANDLES`
- `Blueprint("name", url_prefix="/api")` → prefix-chain routes
- `MethodView` subclasses: each HTTP-method function → endpoint
- Flask-RESTful `Resource` + `api.add_resource(cls, "/path")` → endpoints per method
- Flask-SQLAlchemy: recognize `db = SQLAlchemy()` + `db.Model` pattern, reuse SQLAlchemy plugin's extraction

### DD-5: Scratch-authored fixtures
Three realistic fixture projects in `tests/fixtures/`, authored inside this repo (not curated from upstream). Fully controlled, deterministic for CI, no upstream drift.

- `fastapi-todo/` — FastAPI + async SQLAlchemy + Alembic + Pydantic v2 (~2 KLOC)
- `django-blog/` — Django + DRF + Celery (~3 KLOC)
- `flask-inventory/` — Flask + Flask-SQLAlchemy + Flask-RESTful (~1.5 KLOC)

### DD-6: Milestone-based shipping (Q4 option ii)
Four independently mergeable milestones, each gated on integration tests passing. M1 is load-bearing — nothing downstream is trustworthy until SCIP→Python edge upgrades are validated end-to-end.

## Data Model Changes

### New EdgeKind values (2)

| Edge | Source → Target | Why new |
|---|---|---|
| `ACCEPTS` | API_ENDPOINT → CLASS | Transaction-flow queries need request-contract semantics distinct from `DEPENDS_ON` |
| `RETURNS` | API_ENDPOINT → CLASS | Mirror direction |

### Reused EdgeKinds

| Use case | Edge | Properties |
|---|---|---|
| Pydantic field → ORM column | `MAPS_TO` | `{source: "pydantic", confidence_reason: "name_and_type_match"}` |
| Celery producer → task | `CALLS` | `{async: true, queue, evidence: "celery-producer"}` |
| Celery producer → queue | `PRODUCES` | `{queue}` |
| Celery task → queue | `CONSUMES` | `{queue}` |
| Alembic migration → table | `WRITES` / `READS` | `{migration_id, operation}` |
| Alembic migration DAG | `INHERITS` | `{revision, down_revision}` |

### No new NodeKind values
All concepts map to existing kinds via properties:
- Celery tasks: `FUNCTION` + `{framework: "celery", task_name, queue, retries}`
- Alembic migrations: `FUNCTION` + `{is_migration: true, revision, down_revision}`
- Pydantic validators: `FUNCTION` + `{is_validator: true, validator_kind, target_field}`
- Pydantic field constraints: stored as `properties.constraints` on existing FIELD node
- Message queues: `MESSAGE_TOPIC` (already in enum)

### Writer impact
`app/stages/writer.py` gains 2 new UNWIND+MERGE branches for `ACCEPTS` and `RETURNS`. No schema migration for Neo4j (edge types are label-only, added lazily).

## Milestones

### M1 — SCIP Foundation (weeks 1–2) [LOAD-BEARING]

**Goal**: trustworthy SCIP Python output before any downstream plugin work.

1. `build_python_venv(manifest) -> Path | None` in `app/stages/dependencies.py` — sandboxed `uv venv` + `uv pip install` with resource limits
2. `ResolvedEnvironment.python_venv_path: Path | None` field
3. SCIP indexer config pinned to `sourcegraph/scip-python:v0.6.6` with `VIRTUAL_ENV` + `NODE_OPTIONS=--max-old-space-size=8192` env
4. Partial-index success handling: non-zero exit + `index.scip` > 0 bytes → merge anyway, emit warning
5. `scip_symbol_to_fqn` test cases for Python SCIP format (`scip-python python <pkg> <ver> <descriptors>`)
6. Three fixture projects authored (fastapi-todo, django-blog, flask-inventory)
7. Integration test: fastapi-todo end-to-end, assert ≥80% of CALLS edges from route handlers into service/model functions (i.e. edges that traverse the framework boundary) are HIGH confidence after SCIP merge

**Acceptance**: 3 fixtures analyze cleanly, Neo4j contains expected base graph, edge upgrades validated.

### M2 — Django Settings + Async SQLAlchemy + Alembic (weeks 3–4)

1. Finish `DjangoSettingsPlugin.extract()` — emit `CONFIG_FILE` + `CONFIG_ENTRY` children for INSTALLED_APPS, DATABASES, MIDDLEWARE, AUTH_USER_MODEL, ROOT_URLCONF, DEFAULT_AUTO_FIELD
2. Async SQLAlchemy recognition — `AsyncSession`, `async_sessionmaker`, `create_async_engine`; SQLAlchemy 2.0 `DeclarativeBase` / `Mapped[str]` / `mapped_column(...)` style
3. New `app/stages/plugins/alembic_plugin/` — mirrors `sql/migration.py` shape; parses `upgrade()`/`downgrade()` + `op.*` calls; emits migration chain via `INHERITS` edge between `revision` → `down_revision`

**Acceptance**: Django fixture emits settings graph; fastapi-todo's Alembic migrations form a chained DAG; async SQLAlchemy models recognized.

### M3 — Pydantic Deep + Celery (weeks 5–6)

1. New `app/stages/plugins/fastapi_plugin/pydantic.py` — Pydantic v1+v2 BaseModel extraction, `Field(...)` constraints (class-body + `Annotated[...]` forms), validator tagging, `ACCEPTS`/`RETURNS` edges
2. Pydantic→ORM linking via `MAPS_TO` edge (MEDIUM confidence, ON by default, per-project override)
3. New `app/stages/plugins/celery_plugin/` — task discovery, queue extraction, producer linking via SCIP, `CONSUMES`/`PRODUCES` edges

**Acceptance**: fastapi-todo shows full endpoint→Pydantic→column chain; django-blog shows endpoint→producer→task→queue chain.

### M4 — Flask + Integration Polish (weeks 7–8)

1. New `app/stages/plugins/flask_plugin/` with sub-modules `routes.py`, `blueprints.py`, `restful.py`, `sqlalchemy_adapter.py`
2. End-to-end integration test exercising all 3 fixtures in sequence
3. Performance smoke: each fixture completes in <5 min on developer laptop
4. Documentation update: `docs/08-FRAMEWORK-PLUGINS.md` + `CLAUDE.md` Tier table

**Acceptance**: flask-inventory analyzes end-to-end; all 3 fixtures pass integration tests; no fixture emits >5 warnings.

## Error Handling & Degradation Matrix

Principle (from `CLAUDE.md`): only Stage 1 and Stage 8 are fatal. Everything else degrades with warnings.

| Failure | Behavior | Warning |
|---|---|---|
| `uv venv` creation fails | Skip install; `python_venv_path = None` | `"venv creation failed: <reason>"` |
| `uv pip install` times out | Abort install, keep empty venv | `"pip install timed out after 300s"` |
| `uv pip install` partial failure | Continue with installed subset | `"pip install partial: <failed packages>"` |
| No build file present | Skip install entirely | (silent — normal case) |
| scip-python non-zero exit + partial index | Merge partial index | `"scip-python exited non-zero; using partial index"` |
| scip-python crash (known decorator bug) | Same as above | `"scip-python crashed mid-run; index may be incomplete"` |
| Plugin `extract()` raises | Mark failed; skip dependents (existing registry logic) | `"plugin <name> failed: <reason>"` |
| Pydantic→ORM ambiguous match | LOW-confidence edges to all candidates | `"pydantic field <name> matches N ORM columns"` |
| Celery `.delay()` unresolvable | Name fallback, LOW confidence | debug log only |
| Alembic references unknown table | Create stub TABLE node | `"alembic migration <rev> references unknown table"` |

## Testing Strategy

### Unit tests (per new/changed module)
- `tests/unit/stages/test_dependencies.py` — `build_python_venv()` with mocked subprocess
- `tests/unit/stages/scip/test_merger.py` — Python SCIP symbol format cases
- `tests/unit/stages/plugins/test_flask_plugin.py` (~300–400 lines)
- `tests/unit/stages/plugins/test_celery_plugin.py` (~300–400 lines)
- `tests/unit/stages/plugins/test_alembic_plugin.py` (~250 lines)
- `tests/unit/stages/plugins/test_django_settings_plugin.py` (new)
- Extend `test_fastapi_plugin.py` with Pydantic-deep cases
- Create/extend `test_sqlalchemy_plugin.py` with async cases

### Integration tests (per milestone acceptance gate)
- `tests/integration/test_python_pipeline.py`:
  - `TestFastAPITodoPipeline` (M3 gate) — endpoint→Pydantic→column chain
  - `TestDjangoBlogPipeline` (M3 gate) — endpoint→producer→task→queue chain
  - `TestFlaskInventoryPipeline` (M4 gate) — blueprints + Flask-SQLAlchemy
- Uses `testcontainers-python` for Neo4j (existing pattern)

### End-to-end smoke (M4 acceptance)
- `tests/e2e/test_python_full_stack.py` — docker-compose, upload each fixture, query Neo4j
- Performance assertion: <5 min per fixture

### Coverage targets
- New modules: ≥85% line coverage
- Modified modules: no regression
- Each new EdgeKind (`ACCEPTS`, `RETURNS`) exercised ≥1 time

## Risks

| Risk | Prob | Impact | Mitigation |
|---|---|---|---|
| scip-python crashes on fixtures | Med | Med | Fixtures pinned to SCIP-clean patterns; partial-index fallback |
| Pydantic→ORM noisy false positives | Med | Low | Conservative match (exact name + type); per-project flag; LOW confidence on ambiguous |
| Sandboxed pip install security | Med | High | Docker netns restricted to PyPI; timeout + resource limits; "trusted code only" for on-prem Phase 1 |
| linux/amd64-only scip-python breaks arm64 devs | High | Low | Document `docker buildx` recipe; M1 test includes arm64 build step |
| Celery `.delay()` resolution misses | Med | Low | Name fallback at LOW confidence |
| Timeline slips on fixtures | High | Med | Budget 3 days for M1 fixtures; if M1 slips, author only `fastapi-todo` + `django-blog` in M1 and defer `flask-inventory` to the start of M4 (Flask plugin milestone) |

## Rollout

- Per-milestone PRs, each gated on integration tests
- Feature flag: `python.enable_venv_install` (default ON)
- Rollback: revert the milestone PR (additive changes, registry-level opt-in)
- Docs update lands with each milestone

## Explicit Non-Goals

Deferred beyond Option B:
- Flask-Smorest / APIFlask / Marshmallow schemas
- GraphQL (strawberry / graphene)
- pytest fixtures as entry points
- Python 3.12+ features (match, PEP 695)
- DRF serializer field-level AST walking
- Celery Canvas (chain/group/chord/beat)
- Custom Django M2M `through=`
- Type stub (`.pyi`) merging
- Poetry lockfile resolution beyond `uv pip install`

## File-Level Impact

**New files**:
```
app/stages/plugins/alembic_plugin/__init__.py
app/stages/plugins/alembic_plugin/migrations.py
app/stages/plugins/celery_plugin/__init__.py
app/stages/plugins/celery_plugin/tasks.py
app/stages/plugins/celery_plugin/producers.py
app/stages/plugins/flask_plugin/__init__.py
app/stages/plugins/flask_plugin/routes.py
app/stages/plugins/flask_plugin/blueprints.py
app/stages/plugins/flask_plugin/restful.py
app/stages/plugins/flask_plugin/sqlalchemy_adapter.py
app/stages/plugins/fastapi_plugin/pydantic.py
tests/fixtures/fastapi-todo/                   # ~2 KLOC scratch-authored
tests/fixtures/django-blog/                    # ~3 KLOC scratch-authored
tests/fixtures/flask-inventory/                # ~1.5 KLOC scratch-authored
tests/unit/stages/plugins/test_flask_plugin.py
tests/unit/stages/plugins/test_celery_plugin.py
tests/unit/stages/plugins/test_alembic_plugin.py
tests/unit/stages/plugins/test_django_settings_plugin.py
tests/integration/test_python_pipeline.py
tests/e2e/test_python_full_stack.py
```

**Modified files**:
```
app/models/enums.py                            # +ACCEPTS, +RETURNS EdgeKind
app/stages/dependencies.py                     # +build_python_venv()
app/stages/scip/indexer.py                     # pin v0.6.6, VIRTUAL_ENV env, NODE_OPTIONS
app/stages/scip/merger.py                      # +Python SCIP symbol handling
app/stages/writer.py                           # +ACCEPTS/+RETURNS UNWIND branches
app/stages/plugins/__init__.py                 # register new plugins
app/stages/plugins/django/settings.py          # finish extract()
app/stages/plugins/sqlalchemy_plugin/models.py # +async recognition
app/stages/plugins/fastapi_plugin/__init__.py  # register pydantic sub-plugin
app/stages/plugins/fastapi_plugin/routes.py    # +ACCEPTS/+RETURNS emission
app/models/context.py                          # ResolvedEnvironment.python_venv_path
docs/08-FRAMEWORK-PLUGINS.md                   # document new plugins
CLAUDE.md                                      # Tier table reflects Python production-ready
```

## Open Questions (resolved)

1. ✅ Pydantic→ORM linking default: **ON** (gated by `enable_pydantic_orm_linking` per-project override)
2. ✅ Fixtures: **scratch-authored inside this repo** (not curated from upstream) for determinism
