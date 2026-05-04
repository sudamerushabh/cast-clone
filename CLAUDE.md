# CAST Clone — Software Architecture Intelligence Platform

## What Is This Project?

An on-premise "MRI for Software" that reverse-engineers codebases into interactive architecture maps. Users point it at a codebase, it parses everything (Java, TypeScript, C#, Python), builds a graph in Neo4j, and provides visualization, impact analysis, and AI-powered querying. Think CAST Imaging but modern, AI-native, and deployable with a single `docker compose up`.

## Repositories

This is a monorepo-adjacent setup with two separate projects:
- **`cast-clone-backend/`** — Python/FastAPI analysis engine + API
- **`cast-clone-frontend/`** — Next.js (App Router) visualization UI

## Tech Stack

### Backend (`cast-clone-backend/`)
- **Runtime:** Python 3.12+
- **Package Manager:** `uv` (NOT pip — use `uv add`, `uv sync`, `uv run`)
- **Framework:** FastAPI, Pydantic v2, uvicorn
- **Graph DB:** Neo4j Community Edition + GDS plugin (via `neo4j` async driver)
- **Relational DB:** PostgreSQL (via `asyncpg` + SQLAlchemy async)
- **Cache/PubSub:** Redis
- **Parsing:** `py-tree-sitter` + language grammars, SCIP indexers (subprocess), `sqlglot`
- **Testing:** `pytest` + `pytest-asyncio` + `pytest-cov`
- **Linting:** `ruff`, `mypy`
- **Task Queue:** None for Phase 1-3 (single async pipeline). Celery for Phase 4+.

### Frontend (`cast-clone-frontend/`)
- **Framework:** Next.js 14+ (App Router)
- **Language:** TypeScript
- **Graph Visualization:** Cytoscape.js + `react-cytoscapejs` (Phase 2)
- **Layout Algorithms:** `cytoscape-dagre` (hierarchical), `cytoscape-fcose` (force-directed)
- **Styling:** Tailwind CSS
- **State:** React hooks only — no Redux/Zustand until Phase 4+

---

## Backend Project Structure

```
cast-clone-backend/
├── CLAUDE.md                    # This file
├── docs/                        # Architecture docs (read-only reference)
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app entry + lifespan
│   ├── config.py                # Pydantic Settings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── health.py            # GET /health
│   │   ├── projects.py          # Project CRUD
│   │   ├── analysis.py          # Trigger + status endpoints
│   │   ├── graph.py             # Graph query endpoints
│   │   └── websocket.py         # Analysis progress WebSocket
│   ├── models/
│   │   ├── __init__.py
│   │   ├── db.py                # SQLAlchemy ORM models (Project, AnalysisRun)
│   │   ├── graph.py             # In-memory graph: GraphNode, GraphEdge, SymbolGraph
│   │   ├── context.py           # AnalysisContext (shared pipeline state)
│   │   └── manifest.py          # ProjectManifest (discovery output)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── postgres.py          # Async SQLAlchemy engine + session
│   │   ├── neo4j.py             # Neo4j async driver + query helpers
│   │   └── redis.py             # Redis connection
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── pipeline.py          # run_analysis_pipeline() — main wiring
│   │   ├── subprocess_utils.py  # Async subprocess with timeout
│   │   └── progress.py          # WebSocketProgressReporter
│   └── stages/
│       ├── __init__.py
│       ├── discovery.py         # Stage 1: filesystem scan, language/framework detection
│       ├── dependencies.py      # Stage 2: build tool detection, dependency resolution
│       ├── treesitter/
│       │   ├── __init__.py
│       │   ├── parser.py        # Base tree-sitter wrapper + parallel parsing
│       │   └── extractors/
│       │       ├── __init__.py
│       │       ├── java.py
│       │       ├── typescript.py
│       │       ├── csharp.py
│       │       └── python.py
│       ├── scip/
│       │   ├── __init__.py
│       │   ├── indexer.py       # SCIP subprocess runner (parallel per language)
│       │   ├── protobuf_parser.py
│       │   └── merger.py        # Merge SCIP into SymbolGraph
│       ├── plugins/
│       │   ├── __init__.py
│       │   ├── base.py          # FrameworkPlugin ABC, PluginResult
│       │   ├── registry.py      # Auto-discovery, detection, topological sort, execution
│       │   ├── spring/
│       │   │   ├── __init__.py
│       │   │   ├── di.py        # @Component/@Autowired resolution
│       │   │   ├── web.py       # @GetMapping endpoint extraction
│       │   │   └── data.py      # Spring Data repository resolution
│       │   ├── hibernate/
│       │   │   └── jpa.py       # @Entity/@OneToMany relationship mapping
│       │   └── sql/
│       │       ├── parser.py    # Embedded SQL via sqlglot
│       │       └── migration.py # Flyway/Liquibase/Alembic schema reconstruction
│       ├── linker.py            # Stage 6: HTTP endpoint matcher, MQ matcher
│       ├── enricher.py          # Stage 7: metrics, Louvain communities via GDS
│       ├── writer.py            # Stage 8: Neo4j batch writer (UNWIND + MERGE)
│       └── transactions.py      # Stage 9: transaction flow discovery
├── tests/
│   ├── conftest.py
│   ├── fixtures/                # Sample source code for testing
│   │   ├── spring-petclinic/
│   │   ├── express-app/
│   │   └── raw-java/
│   ├── unit/
│   └── integration/
├── .env.example
├── .python-version
├── pyproject.toml
├── uv.lock
└── docker-compose.yml
```

### Frontend Project Structure

```
cast-clone-frontend/
├── app/                         # Next.js App Router pages
│   ├── layout.tsx
│   ├── page.tsx                 # Landing / project list
│   ├── projects/
│   │   └── [id]/
│   │       ├── page.tsx         # Project dashboard
│   │       └── graph/
│   │           └── page.tsx     # Graph explorer (Phase 2)
├── components/
│   ├── graph/                   # Cytoscape graph components (Phase 2)
│   │   ├── GraphView.tsx
│   │   ├── GraphToolbar.tsx
│   │   └── NodeProperties.tsx
│   ├── search/
│   ├── layout/
│   └── ui/                      # Shared UI primitives
├── hooks/
│   ├── useGraph.ts
│   └── useSearch.ts
├── lib/
│   ├── api.ts                   # API client
│   └── types.ts                 # Shared TypeScript types
├── public/
├── .gitignore
├── .prettierrc
├── .prettierignore
├── next.config.js
├── package.json
├── tailwind.config.ts
└── tsconfig.json
```

---

## Architecture Docs

Detailed specs live in `cast-clone-backend/docs/`. **READ these before implementing any component:**

| Doc | Contents |
|-----|----------|
| `00-PROJECT-OVERVIEW.md` | Vision, differentiators vs CAST, tech stack, full roadmap |
| `01-PHASE-1-CORE-ENGINE.md` | 4-layer parsing strategy (tree-sitter + SCIP + plugins + sqlglot), what each layer extracts |
| `02-PHASE-2-VISUALIZATION.md` | Cytoscape.js, 3 views (architecture/dependency/transaction), 3 levels (module/class/method), lazy loading |
| `03-PHASE-3-IMPACT-ANALYSIS.md` | Impact analysis = Cypher queries + one GDS call, 7 API endpoints |
| `04-PHASE-4-COLLABORATION.md` | JWT auth, 2 roles, annotations, tags, saved views, CSV/JSON export |
| `05-PHASE-5-AI-INTEGRATION.md` | MCP server (FastMCP ~200 lines), built-in chat (Claude Sonnet + tool use) |
| `06-PHASE-6-ENTERPRISE.md` | Advisors (cloud readiness, DB migration, tech debt), portfolio view, CI/CD, drift detection |
| `07-ANALYSIS-ORCHESTRATOR.md` | Pipeline wiring, subprocess management, WebSocket progress, error recovery table |
| `08-FRAMEWORK-PLUGINS.md` | Plugin contract, tree-sitter query patterns, per-framework specs (Spring, Hibernate, React, ASP.NET, Express, NestJS) |
| `09-NEO4J-SCHEMA.md` | Full graph schema (node labels, edge types), Cypher query patterns, indexing |
| `10-DEPLOYMENT.md` | Docker Compose stack, volumes, health checks, installation |

---

## Roadmap Summary

### Phase 1 — Core Analysis Engine (Months 1-3) ← COMPLETE
Parse code → build graph → store in Neo4j → expose via API.
- 4-layer parsing: tree-sitter (structure) + SCIP (type resolution) + framework plugins (invisible connections) + sqlglot (embedded SQL)
- 9-stage pipeline: discover → dependencies → tree-sitter → SCIP → plugins → cross-tech link → enrich → write Neo4j → transactions
- Tier 1 plugins: Spring DI/Web/Data, Hibernate/JPA, SQL Parser, SQL Migration
- REST API for triggering analysis and querying graph
- No frontend visualization yet — API returns JSON
- Python production-ready: FastAPI, Django, Flask, SQLAlchemy (sync+async), Alembic, Celery, Pydantic deep

### Phase 2 — Visualization & Navigation (Months 3-5)
Make the graph explorable via the Next.js frontend.
- Cytoscape.js with react-cytoscapejs wrapper
- 3 views: Architecture (dagre), Dependency (fcose), Transaction (dagre LR)
- 3 levels: Module → Class → Method (lazy-loaded on drill-down)
- cytoscape-expand-collapse for compound node drill-down
- Search (Cmd+K), node properties panel, source code viewer (Monaco)
- Export: PNG/SVG/JSON via Cytoscape built-ins

### Phase 3 — Impact Analysis (Months 5-7)
"What breaks if I change this?" — all backed by Cypher queries, no separate engine.
- Impact analysis: variable-length path query + color overlay
- Path finder: shortestPath() Cypher
- Community detection: Louvain via GDS (one-time during Stage 7)
- Dead code candidates, circular dependencies, metrics dashboard
- 7 new API endpoints, all single Cypher queries

### Phase 4 — Collaboration (Months 7-9)
Let a team use the tool — minimum viable multi-user.
- JWT auth with bcrypt (local accounts only, ~150 lines)
- 2 roles: admin + member (one `if` statement)
- Annotations (notes on nodes), tags (deprecated, critical-path, etc.)
- Saved views (serialize Cytoscape state to JSONB, shareable URLs)
- CSV + JSON export, activity log

### Phase 5 — AI Integration (Months 9-12)
AI agents query the architecture graph.
- MCP Server: FastMCP, ~200 lines, thin wrapper over Neo4j queries, SSE on port 8090
- Built-in Chat: Claude Sonnet + tool use (Claude IS the router, no custom classifier)
- Shared tool layer: same Python functions back both MCP and chat

### Phase 6 — Enterprise & Advisors (Months 12-18)
Go upmarket with modernization intelligence.
- Advisors: Cloud Readiness, DB Migration, Tech Debt (ISO 5055), Green/Sustainability, Open Source Risk
- Portfolio view (multi-application), CI/CD integration (GitHub Actions)
- Architecture drift detection, mainframe support (COBOL/JCL)

---

## Key Technical Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| AST parsing | Tree-sitter | Fast C-based, 100+ languages, S-expression queries, used by GitHub |
| Type resolution | SCIP (not LSP) | Purpose-built for batch indexing, Apache 2.0, 10x faster than LSP |
| Graph DB | Neo4j Community | Best tooling, GDS algorithms included, abstract behind GraphStore interface |
| SQL parsing | sqlglot | 21+ dialects, zero deps, MIT, column-level lineage support |
| Visualization | Cytoscape.js | Purpose-built for graph analysis, compound nodes, MIT |
| Layout engines | Dagre + fCoSE | Two algorithms cover all views |
| MCP framework | FastMCP (official SDK) | Tools = decorated functions, handles protocol plumbing |
| AI model | Claude Sonnet | Tool use for routing, cost-effective |
| Auth (Phase 4) | JWT + bcrypt | Simple, sufficient for on-prem |
| Task queue | None Phase 1-3; Celery Phase 4+ | Single async pipeline until multi-user |
| Package manager | uv | Fast, deterministic lockfile |

---

## Coding Conventions

- **Type hints everywhere.** All function signatures, return types, dataclass fields.
- **Pydantic v2** for API models and config. Use `model_validator` not `validator`.
- **Async by default** for I/O (DB, files, subprocess). Sync for CPU-bound (tree-sitter in ProcessPool).
- **Dataclasses** for internal models (GraphNode, GraphEdge, AnalysisContext). Pydantic for API boundaries.
- **No global state.** Pass dependencies explicitly. Use FastAPI's `Depends()`.
- **Logging:** `structlog` with JSON output. Every stage logs entry/exit + timing.
- **Error handling:** Each pipeline stage catches its own exceptions. Only Stage 1 (discovery) and Stage 8 (Neo4j write) are fatal. Everything else degrades gracefully with warnings.
- **Tests:** Every module has unit tests. `pytest` + `pytest-asyncio`. Integration tests use `testcontainers-python`.

## Commands

```bash
# Backend development
cd cast-clone-backend
uv sync                                      # Install dependencies
docker compose up -d neo4j postgres redis     # Start infrastructure
uv run uvicorn app.main:app --reload          # Start API server

# Testing
uv run pytest tests/unit/ -v                  # Unit tests
uv run pytest tests/integration/ -v           # Integration tests
uv run pytest --cov=app --cov-report=html     # Coverage

# Linting
uv run ruff check app/ tests/
uv run ruff format app/ tests/
uv run mypy app/

# Frontend development
cd cast-clone-frontend
npm install                                   # or pnpm install
npm run dev                                   # Start dev server
```

---

## Pipeline Architecture (Phase 1)

The analysis pipeline is a single `async` function that runs 9 stages in sequence:

```
Stage 1: discover_project()       → ProjectManifest (files, languages, frameworks)
Stage 2: resolve_dependencies()   → ResolvedEnvironment (needed by SCIP)
Stage 3: parse_with_treesitter()  → RawSymbolGraph (CPU-bound, ProcessPoolExecutor)
Stage 4: run_scip_indexers()      → ResolvedSymbolGraph (I/O-bound, asyncio.gather parallel)
Stage 4b: run_lsp_fallback()      → Only if SCIP fails for a language
Stage 5: run_framework_plugins()  → EnrichedGraph (invisible connections)
Stage 6: run_cross_tech_linker()  → LinkedGraph (HTTP endpoint matching, MQ matching)
Stage 7: enrich_graph()           → FinalGraph (metrics, Louvain communities)
Stage 8: write_to_neo4j()         → Database populated (batch UNWIND + MERGE)
Stage 9: discover_transactions()  → Transaction subgraphs
```

No Celery. No task chains. SCIP indexers run as parallel async subprocesses. Tree-sitter parsing uses ProcessPoolExecutor. Progress reported via WebSocket.

## Plugin Priority (Phase 1 Tier 1)

| Priority | Plugins | Languages |
|----------|---------|-----------|
| Tier 1 | Spring DI + Web + Data, Hibernate/JPA, SQL Parser + Migration | Java + Database |
| Tier 2a | React + Router, Express, NestJS, HTTP Endpoint Matcher | JS/TS |
| Tier 2b | ASP.NET Core + Entity Framework | C#/.NET |
| Tier 4 | Django (Settings, ORM, URLs, DRF), FastAPI (Routes, Pydantic Deep), SQLAlchemy (sync+async), Alembic, Celery, Flask (Routes, Blueprints, RESTful, SQLAlchemy adapter) | Python |

> **Python status (M1 complete, 2026-04-22):** SCIP foundation landed. Stage 2 builds a sandboxed venv; Stage 4 passes VIRTUAL_ENV + NODE_OPTIONS to `scip-python v0.6.6` with partial-index success. Framework plugins scheduled for M2–M4.

> **Python status (M2 complete, 2026-04-22):** Django settings enriched (structured INSTALLED_APPS/DATABASES/MIDDLEWARE/AUTH_USER_MODEL/ROOT_URLCONF/DEFAULT_AUTO_FIELD); SQLAlchemy 2.0 async style pinned with tests; Alembic plugin landed with revision-chain DAG. M3 scheduled: Pydantic deep + Celery.

> **Python status (M3 complete, 2026-04-28):** FastAPIPydanticPlugin emits ACCEPTS/RETURNS edges from endpoints to Pydantic models, MAPS_TO edges from Pydantic FIELDs to SQLAlchemy COLUMNs (MEDIUM/LOW confidence), tags validator functions, extracts Field(...) constraints in class-body and Annotated[...] forms. CeleryPlugin discovers @shared_task/@celery.task/@app.task tasks, dedupes MESSAGE_TOPIC nodes per queue, emits CONSUMES + PRODUCES (.delay/.apply_async/.s/.signature). Two new EdgeKinds (ACCEPTS, RETURNS) flow through writer unchanged via apoc dynamic edge type. SCIP merger hardened: parameter-descriptor leaks dropped, file:line fallback now gated by descriptor kind to prevent FIELD↔CLASS cross-binding.

> **Python status (M4 complete, 2026-05-04):** FlaskPlugin landed with four sub-modules — routes (`@app.route`/`@bp.route`/`add_url_rule`), blueprints (registration-time prefix wins), restful (Resource/MethodView via INHERITS+CONTAINS, `Api(prefix=)` + `add_resource` binding), sqlalchemy_adapter (`db.Model` → TABLE, `db.Column` → COLUMN, `db.ForeignKey` → REFERENCES). Decorator regexes tolerate the @-prefix-stripped form PythonExtractor produces. M2 SQLAlchemyPlugin now cedes `db.Model` subclasses to FlaskPlugin to avoid duplicate TABLE nodes. Phase 1 Python is production-ready: e2e smoke runs all three fixtures (fastapi-todo, django-blog, flask-inventory) through Stages 1-7 in <5s each with 0 warnings.