# CAST Clone — Software Architecture Intelligence Platform

## What Is This Project?

An on-premise "MRI for Software" that reverse-engineers codebases into interactive architecture maps. Users connect a git provider (GitHub/GitLab/Gitea/Bitbucket) or upload a project, the engine parses everything (Java, TypeScript, C#, Python), builds a graph in Neo4j, and exposes it through a Next.js visualization UI plus an AI chat that can query the graph via tool-calling. Think CAST Imaging but modern, AI-native, deployable with a single `docker compose up`.

## Repository Layout

This repository is a monorepo with several top-level projects:

```
cast-clone/
├── cast-clone-backend/      Python/FastAPI analysis engine + REST/WS API + MCP server
├── cast-clone-frontend/     Next.js 16 App Router visualization UI
├── license-infra/           AWS CDK app for license key issuance/validation (separate deploy)
├── docker-compose.yml       Root compose: postgres, neo4j, redis, minio, backend
├── Makefile                 Top-level helpers (up/down/*-dev/*-lint)
├── docs/                    Cross-project docs
└── tools/                   One-off scripts
```

> Backend architecture docs live under `cast-clone-backend/docs/` (`00-PROJECT-OVERVIEW.md` … `10-DEPLOYMENT.md`). Read these before touching any pipeline stage or plugin — they specify behavior the code is expected to honor.

## Tech Stack

### Backend (`cast-clone-backend/`)
- **Runtime:** Python 3.12+
- **Package manager:** `uv` (NOT pip — use `uv add`, `uv sync`, `uv run`). `uv.lock` is checked in.
- **Framework:** FastAPI, Pydantic v2 (+ `pydantic-settings`), uvicorn
- **Graph DB:** Neo4j 5 Community + APOC + Graph Data Science plugin (`graphdatascience` Python client + `neo4j` async driver)
- **Relational DB:** PostgreSQL 16 (`asyncpg` + `sqlalchemy[asyncio]` + Alembic)
- **Cache / pubsub:** Redis 7 (`redis[hiredis]`)
- **Object storage:** MinIO (S3-compatible) for uploaded archives
- **Parsing:** `tree-sitter` ≥0.25 + per-language grammars; SCIP indexers (subprocess); `sqlglot` ≥29 for embedded SQL
- **AI:** `anthropic[bedrock]` ≥0.40 + `openai` ≥2.32 (chat + summaries); `mcp[cli]` v1 (MCP server)
- **Auth:** `python-jose[cryptography]` + `passlib[bcrypt]` (JWT, can be bypassed in dev with `AUTH_DISABLED=true`)
- **Other:** `apscheduler` (scheduled jobs), `aiosmtplib` (email), `httpx`, `boto3`, `structlog`
- **Testing:** `pytest` + `pytest-asyncio` + `pytest-cov` ≥7 + `testcontainers` ≥4.14 + `respx`
- **Linting:** `ruff` (formatter + linter — no black/isort/flake8)

### Frontend (`cast-clone-frontend/`)
- **Framework:** Next.js 16.1.6 (App Router, Turbopack dev)
- **Runtime:** React 19.2.4, TypeScript 5.9.3 (strict)
- **Graph viz:** `cytoscape` 3.33 + `react-cytoscapejs` 2.0 + `cytoscape-dagre` (hierarchical), `cytoscape-fcose` (force), `cytoscape-expand-collapse` (drill-down compounds), `cytoscape-svg` (export)
- **Code viewer:** `@monaco-editor/react`
- **Styling:** Tailwind v4 (`@tailwindcss/postcss`) + `tw-animate-css` + `tailwind-merge`; ShadcnUI (`new-york`/`radix-mira` style via `components.json`) + `radix-ui` + `lucide-react`
- **State:** React hooks only — **no TanStack Query, no Zustand** (intentional; revisit if multi-user real-time becomes a pain point)
- **Markdown:** `react-markdown` + `remark-gfm`
- **Testing:** `vitest` + `@testing-library/react` (installed, sparsely used)

---

## Backend Layout (`cast-clone-backend/app/`)

```
app/
├── main.py                  FastAPI app, lifespan (init pg/neo4j/redis/license/scheduler)
├── config.py                Pydantic Settings (env-driven)
├── api/                     29 routers — see API surface below
├── ai/                      Anthropic + OpenAI chat, tool definitions, usage logging
├── mcp/                     FastMCP server (`server.py`) + auth middleware
├── git/                     Git provider clients (github/gitlab/gitea/bitbucket) + diff_parser
├── pr_analysis/             PR analyzer pipeline: diff_mapper → impact_aggregator → drift_detector → risk_scorer → commenter (+ `ai/` sub-package for AI comment generation)
├── orchestrator/
│   ├── pipeline.py          PIPELINE_STAGES list (11 stages) + run_analysis_pipeline()
│   ├── progress.py          WebSocketProgressReporter
│   └── subprocess_utils.py  Async subprocess + timeout
├── stages/
│   ├── discovery.py         Stage 1: filesystem scan, language/framework detection
│   ├── dependencies.py      Stage 2: build tool detection, venv setup (Python), Maven/Gradle/npm resolution
│   ├── treesitter/          Stage 3: extractors per language (java, typescript, csharp, python)
│   ├── scip/                Stage 4: per-language indexer subprocess + protobuf parser + merger
│   ├── plugins/             Stage 6: framework plugins (see Plugin Status below)
│   ├── linker.py            Stage 7: cross-tech HTTP/MQ matching
│   ├── enricher.py          Stage 8: metrics aggregation
│   ├── transactions.py      Stage 9: transaction subgraph discovery
│   ├── writer.py            Stage 10: Neo4j batch UNWIND+MERGE
│   └── gds_enricher.py      Stage 11: Louvain community detection via GDS
├── models/
│   ├── db.py                SQLAlchemy ORM (Project, AnalysisRun, User, License, …)
│   ├── graph.py             In-memory: GraphNode, GraphEdge, SymbolGraph
│   ├── context.py           AnalysisContext (shared pipeline state)
│   └── manifest.py          ProjectManifest (Stage 1 output)
├── schemas/                 Pydantic API DTOs (one file per resource: chat, graph, projects, …)
├── services/                15+ modules: postgres, neo4j, redis, ai_provider, auth, branch_manager,
│                             clone, crypto, deployment, email, license, loc_tracking, loc_usage,
│                             git_providers/{github,gitlab,gitea,bitbucket}.py
├── templates/               Email templates (Jinja)
└── tests/
    ├── unit/                ~140 files, ~1.6k tests
    ├── integration/         pipeline e2e + python M1–M4 + neo4j roundtrip + email
    ├── e2e/                 test_python_full_stack.py (smoke through Stages 1–7)
    └── fixtures/            spring-petclinic, raw-java, fastapi-todo, django-blog,
                              flask-inventory, python-sample, csharp, express-app,
                              sql-migrations
```

### API Surface (29 routers)

| Group | Routers |
|---|---|
| Core | `health`, `projects`, `analysis`, `analysis_views`, `graph`, `graph_views`, `dependencies`, `websocket` |
| Git / repos | `repositories`, `connectors`, `git_config`, `webhooks`, `pull_requests` |
| AI | `chat`, `summaries`, `ai_config`, `ai_usage` |
| Auth & users | `auth`, `users`, `api_keys` |
| Collaboration | `annotations`, `tags`, `saved_views`, `activity`, `export` |
| System | `email`, `license`, `system` |

> The MCP server is mounted separately under `app/mcp/server.py` (FastMCP). It re-uses the chat tool layer in `app/ai/tools.py`, so MCP and built-in chat share the same Neo4j query surface.

### Pipeline Stages (11, in order)

Defined in `app/orchestrator/pipeline.py:158` (`PIPELINE_STAGES`):

```
1. discovery        ★ critical    Scanning filesystem...
2. dependencies                   Resolving dependencies...
3. parsing                        Tree-sitter parallel parsing (ProcessPoolExecutor)
4. scip                           Per-language SCIP indexer subprocesses
5. lsp_fallback                   LSP fallback for unsupported languages (currently no-op)
6. plugins                        Framework plugin enrichment
7. linking                        Cross-tech HTTP endpoint / MQ matching
8. enrichment                     Metrics + community computation
9. transactions                   Transaction-flow subgraph discovery
10. writing         ★ critical    Neo4j UNWIND + MERGE
11. gds_enrichment                Louvain community detection via GDS
```

Only `discovery` and `writing` are critical; every other stage degrades to warnings on failure. Progress is reported per-stage over a WebSocket (`app/orchestrator/progress.py`).

### Plugin Status (`app/stages/plugins/`)

| Tier | Plugin pkg | Sub-modules | Status |
|---|---|---|---|
| 1 — Java | `spring/` | `di`, `web`, `data`, `events`, `messaging`, `scheduling` | ✅ |
| 1 — Java | `hibernate/` | `jpa` | ✅ |
| 1 — DB | `sql/` | `parser` (sqlglot), `migration` (Flyway/Liquibase/Alembic) | ✅ |
| 2b — .NET | `dotnet/` | DI, EF, middleware, SignalR, gRPC | ✅ |
| 4 — Python | `fastapi_plugin/` | `routes`, `pydantic` (deep, with Field/Annotated constraints) | ✅ M3 |
| 4 — Python | `django/` | `settings`, `urls`, `orm`, `drf` | ✅ M2 |
| 4 — Python | `flask_plugin/` | `routes`, `blueprints`, `restful`, `sqlalchemy_adapter` | ✅ M4 |
| 4 — Python | `sqlalchemy_plugin/` | `models` (sync + async style) | ✅ M2 |
| 4 — Python | `alembic_plugin/` | `migrations` (revision-chain DAG) | ✅ M2 |
| 4 — Python | `celery_plugin/` | `tasks`, `producers` (.delay/.apply_async/.s/.signature) | ✅ M3 |
| 2a — JS/TS | Express, NestJS, React+Router, HTTP matcher | — | ❌ deferred |

Plugin auto-discovery, detection, topological sort and execution live in `app/stages/plugins/registry.py`. Base contract is `app/stages/plugins/base.py`.

---

## Frontend Layout (`cast-clone-frontend/`)

```
app/
├── (root pages)             /, /login, /setup, /connectors, /connectors/new
├── repositories/            ★ primary IA — branch-parameterized
│   └── [repoId]/
│       ├── page.tsx                    overview
│       ├── [...branch]/                branch explorer
│       ├── graph/[...branch]/          ★ Cytoscape graph view
│       ├── dependencies/[...branch]/   dependency analysis
│       ├── impact/[...branch]/         impact / path / dead-code / community
│       ├── chat/[...branch]/           AI chat (tool-using Claude/OpenAI)
│       ├── search/[...branch]/         code search
│       ├── transactions/[...branch]/   transaction tracing
│       ├── views/[...branch]/          saved views
│       ├── settings/[...branch]/       repo settings
│       └── pull-requests/              PR list + /[analysisId] detail
├── projects/[id]/(graph)    legacy upload-based flow — kept for backward compat
└── settings/                /, /activity, /ai, /api-keys, /email, /license, /system, /team
components/
├── graph/                   GraphView, GraphToolbar, GraphExplorer, FilterPanel, NodeProperties,
│                             TransactionSelector, Breadcrumbs, ExportButtons
├── analysis/                ImpactPanel, PathFinderPanel, CircularDepsPanel, DeadCodePanel,
│                             PathGraphModal, TraceRouteModal, CommunityToggle
├── pull-requests/ (11)      PR drift / impact UI
├── chat/ (8)                AI chat components
├── layout/ (9)              AppLayout, GlobalShell, Sidebar, TopBar, IconRail, ContextPanel,
│                             ProjectContextNav, UserMenu, LicenseBanner
├── ui/ (11)                 shadcn primitives
└── (annotations, repositories, settings, search, users, views, connectors, code, activity, admin, export)
hooks/                       useGraph (drill-down + caching + perf-tier), 14 others
lib/
├── api.ts                   77+ typed API methods
├── cytoscape-setup.ts       extension registration (dagre/fcose/expand-collapse/svg)
├── cytoscape-elements.ts    API → Cytoscape element conversion
└── graph-styles.ts          stylesheet (KIND/LAYER coloring, edge styles, legend)
public/logos/                github.svg, gitlab.svg, gitea.svg, bitbucket.svg
```

### npm scripts
```
dev        next dev --turbopack
build      next build
start      next start
lint       eslint
format     prettier --write "**/*.{ts,tsx}"
typecheck  tsc --noEmit
```

There is no `tailwind.config.ts` (Tailwind v4 picks up everything via `@tailwindcss/postcss` + CSS imports). There is no `vitest.config.ts` despite vitest being installed.

---

## Commands

All commands assume you are at the repo root unless noted.

### Bring up infra + backend (Docker Compose)
```bash
docker compose up -d                 # postgres, neo4j, redis, minio, backend
docker compose ps                    # health
docker compose logs -f backend
docker compose down                  # stop + keep volumes
docker compose down -v               # nuke volumes (full reset)
```

Or via Makefile shortcuts:
```bash
make up                              # docker compose up -d
make down                            # docker compose down
make backend-dev                     # uv run uvicorn app.main:app --reload (host)
make frontend-dev                    # npm run dev
make backend-lint                    # uv run ruff check .
make frontend-lint                   # npm run lint
```

### Backend (host dev loop)
```bash
cd cast-clone-backend
uv sync                                          # install deps
uv run uvicorn app.main:app --reload             # API on :8000
uv run pytest tests/unit -v                      # unit tests
uv run pytest tests/integration -v               # uses testcontainers
uv run pytest tests/e2e -v                       # python full-stack smoke
uv run pytest --cov=app --cov-report=html        # coverage → htmlcov/
uv run ruff check app tests                      # lint
uv run ruff format app tests                     # format
uv run mypy app                                  # type check
uv run alembic upgrade head                      # apply DB migrations
uv run alembic revision --autogenerate -m "..."  # new migration
```

### Frontend
```bash
cd cast-clone-frontend
npm install
npm run dev          # Turbopack on :3000
npm run typecheck
npm run lint
npm run format
```

### Service ports (host-mapped)

| Service | Container | Host |
|---|---|---|
| Postgres | 5432 | **15432** |
| Neo4j Browser | 7474 | **17474** |
| Neo4j Bolt | 7687 | **17687** |
| Redis | 6379 | 6379 |
| MinIO API | 9000 | 9000 |
| MinIO Console | 9001 | 9001 |
| Backend | 8000 | 8000 |
| Frontend | 3000 | 3000 |

Default creds (dev only): postgres `codelens/codelens`, neo4j `neo4j/codelens`, MinIO `codelens/codelens123`.

---

## Coding Conventions

- **Type hints everywhere.** All function signatures, return types, dataclass fields. No `any` in TS unless unavoidable.
- **Pydantic v2** for API DTOs (`app/schemas/`) and config. Use `model_validator`, not `@validator`.
- **Async by default** for I/O (DB, files, subprocess). Sync only for CPU-bound work (tree-sitter is run in `ProcessPoolExecutor`).
- **Dataclasses** for internal models (`GraphNode`, `GraphEdge`, `AnalysisContext`); **Pydantic** for API boundaries.
- **No global state.** Pass dependencies explicitly via FastAPI `Depends()`.
- **Logging:** `structlog` with JSON output. Every stage logs entry/exit + timing.
- **Error handling:** Each pipeline stage catches its own exceptions. Only `discovery` and `writing` are fatal — everything else degrades with warnings. Never bare `except:`.
- **N+1 prevention:** Prefer `selectinload` / `joinedload` over lazy relationship loads.
- **Frontend state:** React hooks only. Do not introduce TanStack Query or Zustand without discussion.
- **Components:** Named exports, PascalCase components, camelCase functions. Prefer `interface` over `type` for object shapes.
- **Tests:** Every module has unit tests (`pytest` + `pytest-asyncio`). Integration tests use `testcontainers-python`.

### Git conventions
- Conventional commits: `feat|fix|refactor|docs|test|chore(scope): description`
- Scope derived from path: `agents`, `llm`, `knowledge`, `auth`, `billing`, `ui`, `api`, `pipeline`, `plugins`, `mcp`, `pr`, …
- Atomic — one logical change per commit
- Branches: `feat/short-description`, `fix/short-description`

---

## Key Technical Decisions

| Decision | Choice | Why |
|---|---|---|
| AST parsing | Tree-sitter | Fast C-based, 100+ languages, S-expression queries |
| Type resolution | SCIP (not LSP) | Purpose-built for batch indexing, ~10× faster than LSP |
| Graph DB | Neo4j Community | Best tooling, GDS bundled, abstract behind `GraphStore` interface |
| SQL parsing | sqlglot | 21+ dialects, zero deps, column-level lineage |
| Visualization | Cytoscape.js | Compound nodes, MIT, mature analytics |
| Layouts | Dagre + fCoSE | Two algorithms cover all views |
| MCP framework | FastMCP (official SDK) | Tools = decorated functions; protocol plumbing handled |
| AI providers | Claude (Anthropic + Bedrock) primary; OpenAI fallback | Tool-use is the routing mechanism |
| Auth | JWT + bcrypt | Sufficient for on-prem; bypassable via `AUTH_DISABLED` |
| Object storage | MinIO | S3-compatible, on-prem-friendly |
| Task queue | Celery (in plugin form for analysis); FastAPI BackgroundTask elsewhere | No standalone worker process yet |
| Package mgr (BE) | uv | Fast, deterministic lockfile |
| Bundler (FE) | Turbopack | Default in Next.js 16 |

---

## Architecture Docs

Detailed specs in `cast-clone-backend/docs/`. **Read the relevant doc before implementing.**

| Doc | Contents |
|---|---|
| `00-PROJECT-OVERVIEW.md` | Vision, differentiators, stack, full roadmap |
| `01-PHASE-1-CORE-ENGINE.md` | 4-layer parsing strategy, what each layer extracts |
| `02-PHASE-2-VISUALIZATION.md` | Cytoscape views, levels, lazy loading |
| `03-PHASE-3-IMPACT-ANALYSIS.md` | Cypher queries + GDS, 7 endpoints |
| `04-PHASE-4-COLLABORATION.md` | JWT auth, annotations, tags, saved views, export |
| `05-PHASE-5-AI-INTEGRATION.md` | MCP server + built-in chat |
| `06-PHASE-6-ENTERPRISE.md` | Advisors, portfolio, drift detection |
| `07-ANALYSIS-ORCHESTRATOR.md` | Pipeline wiring, subprocess management, error recovery |
| `08-FRAMEWORK-PLUGINS.md` | Plugin contract, tree-sitter query patterns, per-framework specs |
| `09-NEO4J-SCHEMA.md` | Node labels, edge types, Cypher patterns, indexing |
| `10-DEPLOYMENT.md` | Docker Compose stack, volumes, health checks |

---

## What's Shipped vs. In Flight

This project is far enough along that the original time-boxed phases (Months 1–18) have largely collapsed. Snapshot as of **2026-05-06**:

### Shipped & production-ready
- **Phase 1 — Core engine.** 11-stage pipeline. Tier-1 Java plugins (Spring/Hibernate/SQL), .NET (Tier 2b), all Python plugins (Django, FastAPI+Pydantic deep, Flask, SQLAlchemy, Alembic, Celery). 9 fixtures green through Stages 1–7.
- **Phase 2 — Visualization.** Cytoscape integration, 3 view modes (architecture/dependency/transaction), lazy drill-down (module → class → method), PNG/SVG export, performance tiers, breadcrumb navigation.
- **Phase 3 — Impact analysis.** Impact, path-finder, circular deps, dead code, Louvain communities — all backed by Cypher + GDS, surfaced through dedicated panels.
- **Phase 4 — Collaboration (partial).** JWT auth + bcrypt, users, API keys, annotations, tags, saved views, activity log, CSV/JSON export. Roles still minimal.
- **Phase 5 — AI integration.** MCP server (FastMCP, `app/mcp/server.py`) + built-in chat (Anthropic + OpenAI tool-calling). Chat & MCP share the tool layer in `app/ai/tools.py`.
- **Git connectors.** GitHub, GitLab, Gitea, Bitbucket clients (`app/git/`, `app/services/git_providers/`) — clone, webhook, PR fetch.
- **PR analysis.** `app/pr_analysis/` pipeline: diff_mapper → impact_aggregator → drift_detector → risk_scorer → AI commenter (`pr_analysis/ai/`).
- **Licensing.** `app/api/license.py` + `app/services/license.py` + the standalone `license-infra/` CDK app for offline license issuance.

### In flight / next up
- **Tier-2a JS/TS plugins** (Express, NestJS, React+Router, HTTP matcher).
- **Phase 6 advisors** (Cloud Readiness, DB Migration, Tech Debt / ISO 5055, Green/Sustainability, OSS risk).
- **Multi-app portfolio view.**
- **Architecture drift detection** (CI integration).
- **Mainframe support** (COBOL/JCL).

---

## Gotchas

- **`uv` only** — never run `pip install` in `cast-clone-backend/`; it will desync `uv.lock`. Use `uv add <pkg>`.
- **Auth bypass for local dev:** `AUTH_DISABLED=true` is set in `docker-compose.yml`. Don't ship that to any deployed env.
- **Repo clone path:** the backend container mounts `/home/ubuntu/repos:/home/ubuntu/repos`. If you change clone destinations, update the volume.
- **Non-default DB ports:** Postgres is on **15432**, Neo4j Browser on **17474**, Bolt on **17687** (avoiding clashes with anything else on the host). Connection strings in `docker-compose.yml` use the *internal* container ports (5432/7687); host-side tooling needs the mapped ports.
- **MinIO creds** in compose are `codelens/codelens123` (note the trailing `123` on the secret — easy to miss).
- **Branch-aware routing:** the canonical frontend path is `/repositories/[repoId]/<view>/[...branch]`. The legacy `/projects/[id]/...` routes still exist but new work should target the repositories tree.
- **No `tailwind.config.ts`** — Tailwind v4 reads everything from `@tailwindcss/postcss` and CSS `@import`s. Don't recreate the v3 config.
- **Tree-sitter parsing runs in a `ProcessPoolExecutor`** — anything passed in must be picklable. SCIP indexers run as `asyncio.gather`-parallel subprocesses, not in the pool.
- **Two AI providers:** `app/services/ai_provider.py` selects between Anthropic and OpenAI based on settings; chat tool-calling assumes Claude semantics — verify both paths when changing tools.
- **Stage failures usually don't abort the run.** Only `discovery` and `writing` are critical; check `app/orchestrator/pipeline.py` before assuming an exception will surface to the caller.
- **`AnalysisRun` lifecycle:** the trigger endpoint creates the run row first, then schedules a `BackgroundTask`. If you spawn the pipeline directly in tests, pass an existing `run_id`.

---

## Python Plugin Milestone History (preserved for context)

> These notes capture *why* the Python plugins behave the way they do — context that isn't derivable from the code alone. Keep them when editing plugins so future readers don't re-litigate decisions.

- **M1 (2026-04-22) — SCIP foundation.** Stage 2 builds a sandboxed venv; Stage 4 passes `VIRTUAL_ENV` + `NODE_OPTIONS` to `scip-python v0.6.6` with partial-index success.
- **M2 (2026-04-22) — Django + SQLAlchemy + Alembic.** Django settings enriched (structured `INSTALLED_APPS`/`DATABASES`/`MIDDLEWARE`/`AUTH_USER_MODEL`/`ROOT_URLCONF`/`DEFAULT_AUTO_FIELD`); SQLAlchemy 2.0 async style pinned; Alembic plugin reconstructs the revision-chain DAG.
- **M3 (2026-04-28) — FastAPI Pydantic deep + Celery.** `FastAPIPydanticPlugin` emits `ACCEPTS`/`RETURNS` edges from endpoints to Pydantic models, `MAPS_TO` from Pydantic FIELDs to SQLAlchemy COLUMNs (MEDIUM/LOW confidence), tags validators, extracts `Field(...)` constraints in class-body and `Annotated[...]` forms. `CeleryPlugin` discovers `@shared_task`/`@celery.task`/`@app.task`, dedupes `MESSAGE_TOPIC` per queue, emits `CONSUMES` + `PRODUCES` (`.delay`/`.apply_async`/`.s`/`.signature`). Two new edge kinds (`ACCEPTS`, `RETURNS`) flow through the writer via APOC dynamic edge type. SCIP merger hardened: parameter-descriptor leaks dropped, file:line fallback gated by descriptor kind to prevent FIELD↔CLASS cross-binding.
- **M4 (2026-05-04) — Flask.** Four sub-modules: `routes` (`@app.route`/`@bp.route`/`add_url_rule`), `blueprints` (registration-time prefix wins), `restful` (`Resource`/`MethodView` via `INHERITS`+`CONTAINS`, `Api(prefix=)` + `add_resource` binding), `sqlalchemy_adapter` (`db.Model`→TABLE, `db.Column`→COLUMN, `db.ForeignKey`→REFERENCES). Decorator regexes tolerate the `@`-prefix-stripped form `PythonExtractor` produces. `SQLAlchemyPlugin` cedes `db.Model` subclasses to `FlaskPlugin` to avoid duplicate TABLE nodes. E2e smoke runs all three Python fixtures (fastapi-todo, django-blog, flask-inventory) through Stages 1–7 in <5s each with 0 warnings.
