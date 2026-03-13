# Implementation Plans — Master Index

Plans for all phases. Execute in dependency order shown below.

---

# Phase 1 — Core Analysis Engine

All plans for Phase 1 (Core Analysis Engine). Execute in dependency order shown below.

---

## Execution Order

```
M1 (foundation)
 ├─> M2 (API + orchestrator)     ── parallel ──┐
 └─> M3 (discovery + deps)       ── parallel ──┘
      └─> M4a (tree-sitter base)
           ├─> M4b (Java extractor)       ── parallel ──┐
           ├─> M4c (TypeScript extractor) ── parallel ──┤
           ├─> M4d (Python extractor)     ── parallel ──┤
           └─> M4e (C# extractor)         ── parallel ──┘
                └─> M5 (SCIP indexers)    ── parallel ──┐
                └─> M6a (plugin base)     ── parallel ──┘
                     ├─> M6b (Spring + Hibernate)  ── parallel ──┐
                     └─> M6c (SQL plugins)         ── parallel ──┘
                          ├─> M7a (cross-tech linker)   ── parallel ──┐
                          ├─> M7b (enricher)            ── parallel ──┤
                          ├─> M7c (Neo4j writer)        ── parallel ──┤
                          └─> M7d (transactions)        ── parallel ──┘
                               └─> M9 (integration wiring)
```

## Plan Files

| Milestone | File | Description | Depends On |
|-----------|------|-------------|------------|
| **M1** | `2026-03-12-phase1-m1-foundation.md` | Enums, GraphNode/Edge/SymbolGraph, ProjectManifest, AnalysisContext, DB models, services (postgres, neo4j GraphStore ABC, redis), config, lifespan wiring | — |
| **M2** | `2026-03-12-phase1-m2-api-orchestrator.md` | Pydantic schemas, WebSocket progress, subprocess utils, pipeline shell (9 no-op stubs), Project CRUD API, Analysis API, Graph Query API, router registration | M1 |
| **M3** | `2026-03-12-phase1-m3-discovery-dependencies.md` | Test fixtures, Stage 1 discovery (filesystem scan, language/framework detection), Stage 2 dependencies (Maven/Gradle/npm/Python/.NET parsers) | M1 |
| **M4a** | `2026-03-12-phase1-m4a-treesitter-base.md` | LanguageExtractor Protocol + registry, grammar loading, parallel file parsing (ProcessPoolExecutor), global symbol resolution | M1, M3 |
| **M4b** | `2026-03-12-phase1-m4b-java-extractor.md` | JavaExtractor: packages, imports, classes, interfaces, methods, constructors, fields, calls, object creation, SQL strings | M4a |
| **M4c** | `2026-03-12-phase1-m4c-typescript-extractor.md` | TypeScriptExtractor: ES6+CommonJS imports, classes, interfaces, functions, arrow functions, calls, decorators, JSX, exports | M4a |
| **M4d** | `2026-03-12-phase1-m4d-python-extractor.md` | PythonExtractor: classes with bases, methods with decorators/type hints, imports, calls, fields, SQL string tagging | M4a |
| **M4e** | `2026-03-12-phase1-m4e-csharp-extractor.md` | CSharpExtractor: namespaces, using directives, classes, interfaces, methods with attributes, properties, constructors with DI, calls | M4a |
| **M5** | `2026-03-12-phase1-m5-scip.md` | Protobuf parser, SCIP indexer runner (4 languages, asyncio.gather parallel), merger (definitions→references→relationships, confidence upgrade) | M4a |
| **M6a** | `2026-03-12-phase1-m6a-plugin-base.md` | FrameworkPlugin ABC, PluginResult, LayerRules, PluginRegistry with Kahn's algorithm topological sort, cascade-skip on failure | M1 |
| **M6b** | `2026-03-12-phase1-m6b-spring-hibernate-plugins.md` | Spring DI, Spring Web, Hibernate/JPA, Spring Data plugins | M6a, M4b |
| **M6c** | `2026-03-12-phase1-m6c-sql-plugins.md` | SQL Parser (sqlglot), SQL Migration (Flyway/Alembic DDL parsing, schema reconstruction) | M6a |
| **M7a** | `2026-03-12-phase1-m7a-linker.md` | HTTP Endpoint Matcher, MQ Matcher, Shared DB Matcher — Stage 6 cross-tech linker | M6b, M6c |
| **M7b** | `2026-03-12-phase1-m7b-enricher.md` | Fan-in/fan-out metrics, DEPENDS_ON aggregation, IMPORTS aggregation, layer assignment, community detection — Stage 7 | M1 |
| **M7c** | `2026-03-12-phase1-m7c-writer.md` | Neo4j batch writer (clear→indexes→App node→nodes→edges→fulltext index) — Stage 8 (CRITICAL) | M1 |
| **M7d** | `2026-03-12-phase1-m7d-transactions.md` | BFS from entry points, cycle detection, terminal classification, Transaction nodes — Stage 9 | M1 |
| **M9** | `2026-03-12-phase1-m9-integration.md` | Replace pipeline stubs with real calls, PipelineServices DI, Spring PetClinic fixture, integration tests (testcontainers), E2E test | ALL |

## Totals

- **17 plans**, ~150 tasks, ~400 test cases
- Estimated: ~50 source files created, ~5 modified
- All plans follow TDD: write failing test → implement → verify → commit

---

# Phase 2 — Visualization & Navigation

Spec: `cast-clone-backend/docs/02-PHASE-2-VISUALIZATION.md`

## Execution Order

```
M1 (Backend APIs) ─────────────────────────┐
                                            ├──> M4 (Graph Visualization)
M2 (Frontend Foundation) ──> M3 (Pages) ───┤
                                            ├──> M5 (Panels + Search)  ── parallel ──┐
                                            └──> M6 (Transaction View) ── parallel ──┘
                                                      └──> M7 (Code Viewer + Export)
```

## Plan Files

| Milestone | File | Description | Depends On |
|-----------|------|-------------|------------|
| **M1** | `2026-03-12-phase2-m1-backend-api.md` | 7 new API endpoints: modules, classes-in-module, methods-in-class, aggregated edges, transaction list/detail, code viewer (with path traversal protection) | — |
| **M2** | `2026-03-12-phase2-m2-frontend-foundation.md` | TypeScript types (mirroring backend schemas), API client (fetch-based), AppLayout shell, Sidebar, shadcn components | — |
| **M3** | `2026-03-12-phase2-m3-frontend-pages.md` | Project list page (card grid + status badges), project dashboard (analysis trigger + status polling + "View Graph" link), landing redirect | M2 |
| **M4** | `2026-03-12-phase2-m4-graph-visualization.md` | Cytoscape.js integration, extension registration, graph styles, element converters, useGraph hook, GraphView wrapper, GraphToolbar, Architecture (dagre TB) + Dependency (fcose) views, compound node drill-down | M1, M3 |
| **M5** | `2026-03-12-phase2-m5-panels-search.md` | NodeProperties right sidebar, Cmd+K SearchDialog, useSearch hook, FilterPanel (client-side hide/show), Breadcrumbs | M4 |
| **M6** | `2026-03-12-phase2-m6-transaction-view.md` | TransactionSelector dropdown, useTransactions hook, transactionToElements converter, dagre LR layout, entry-point/terminal styling | M4 |
| **M7** | `2026-03-12-phase2-m7-code-viewer-export.md` | Monaco Editor code viewer (bottom panel, read-only, line highlight), PNG/SVG/JSON export buttons via Cytoscape built-ins | M5 |

## Totals

- **7 plans**, ~50 tasks
- Backend: ~3 new files, ~1 modified
- Frontend: ~20 new files, ~5 modified
- All backend tasks follow TDD; frontend verified via typecheck + manual testing

Python Plugin Plans — Index Addendum
These two plan files extend the Phase 1 plugin system with Python framework support (Tier 4).
Execution Order (extends M6 chain)
M6a (plugin base)
 ├─> M6b (Spring + Hibernate)       ── done ──
 ├─> M6c (SQL plugins)              ── done ──
 ├─> M6e (FastAPI + SQLAlchemy)     ── NEW ── parallel with M6e
 └─> M6f (Django plugins)           ── NEW ── parallel with M6d
      └─> M7a (cross-tech linker)   ── existing ──
M6d and M6e are independent of each other and can be built in parallel.
Within M6e, the dependency chain is: django-settings → django-urls + django-orm → django-drf.
Plan Files
MilestoneFileDescriptionDepends OnM6d2026-03-13-phase1-m6e-fastapi-sqlalchemy-plugins.mdFastAPI (routes, Depends() DI) + SQLAlchemy (declarative models, ForeignKey) — 2 independent pluginsM6a, M4dM6e2026-03-13-phase1-m6f-django-plugins.mdDjango Settings, URLs, ORM, DRF — 4 plugins with dependency chainM6a, M4d
Recommended Build Order

M6e Task 2: SQLAlchemy (~2 days) — closest to existing Hibernate plugin
M6e Task 1: FastAPI (~2 days) — closest to existing Spring Web plugin
M6e Task 1: Django Settings (~1 day) — simple config extraction
M6f Task 3: Django ORM (~2 days) — similar to SQLAlchemy
M6f Task 2: Django URLs (~2 days) — include() recursion
M6f Task 4: Django DRF (~3 days) — most complex, multi-level indirection

---

# Phase 3 — Impact Analysis & Smart Features

Spec: `cast-clone-backend/docs/03-PHASE-3-IMPACT-ANALYSIS.md`

## Execution Order

```
M1 (GDS + Enricher) ──────────────────────────────┐
                                                    │
M2 (Backend Analysis APIs) ────────────────────────┤
                                                    ├──> M4 (Impact + Path Finder UI)
M3 (Frontend Foundation: types + API + hooks) ─────┤
                                                    ├──> M5 (Community + CircDeps + Dead Code)
                                                    │         └──> M7 (Enhanced Code Viewer)
                                                    └──> M6 (Metrics Dashboard)
```

M1, M2, and M3 are independent and can run in parallel.
M4 and M5 require M2 + M3. M6 requires M3. M7 requires M4/M5.

## Plan Files

| Milestone | File | Description | Depends On |
|-----------|------|-------------|------------|
| **M1** | `2026-03-13-phase3-m1-gds-enricher.md` | Add `graphdatascience` dep, GDS Louvain community detection as Stage 10 (post Neo4j write), remove BFS from enricher | — |
| **M2** | `2026-03-13-phase3-m2-analysis-api.md` | 7 new API endpoints: impact analysis, path finder, communities, circular deps, dead code, metrics, node details — all Cypher-backed | — |
| **M3** | `2026-03-13-phase3-m3-frontend-foundation.md` | TypeScript types for all Phase 3 responses, 7 API client functions, 3 hooks (useImpactAnalysis, usePathFinder, useAnalysisData) | — |
| **M4** | `2026-03-13-phase3-m4-impact-pathfinder.md` | ImpactPanel (color by depth, dim unaffected, summary), PathFinderPanel (select 2 nodes, highlight path), "Show Impact" button in NodeProperties, Cytoscape overlays | M2, M3 |
| **M5** | `2026-03-13-phase3-m5-community-circulardeps-deadcode.md` | CommunityToggle (palette coloring), CircularDepsPanel (cycle list + highlight), DeadCodePanel (sortable table), toolbar integration | M2, M3 |
| **M6** | `2026-03-13-phase3-m6-metrics-dashboard.md` | New `/projects/[id]/metrics` page: MetricCard (summary stats), TopTenTable (complexity, fan-in, fan-out), click-to-navigate | M2, M3 |
| **M7** | `2026-03-13-phase3-m7-enhanced-code-viewer.md` | Monaco Editor clickable references — function calls/class references navigate to graph nodes via deltaDecorations | M4, M5 |

## Totals

- **7 plans**, ~35 tasks
- Backend: ~3 new files, ~3 modified
- Frontend: ~12 new files, ~5 modified
- Backend tasks follow TDD; frontend verified via typecheck + manual testing

---

# Phase 4A — Product Shell, Git Connectors, Repo Onboarding

Spec: `cast-clone-backend/docs/12-PHASE-4A-FRONTEND-DESIGN-GITCONNECTOR-REPO-ONBOARDING.MD`

## Execution Order

```
M7a (Nav Shell) ← pure frontend, no backend changes
    │
    ▼
M7b (Git Connectors) ← needs M7a for /connectors route
    │               backend: GitConnector model, crypto, providers, API
    ▼
M7c (Repo Onboarding) ← needs M7b for connector + repo browsing
                    backend: Repository model, clone service, Project changes,
                             snapshot builder, evolution API
```

M7a is a frontend-only prerequisite. M7b and M7c are sequential (M7c depends on M7b's connector model and provider adapters).

## Plan Files

| Milestone | File | Description | Depends On |
|-----------|------|-------------|------------|
| **M7a** | `2026-03-13-phase4a-m7a-nav-shell.md` | GlobalShell (IconRail + ContextPanel + TopBar), route restructuring (/repositories, /connectors, /settings), project-level nav, legacy /projects compat | Phase 2 M2 |
| **M7b** | `2026-03-13-phase4a-m7b-git-connectors.md` | Fernet crypto, GitProvider ABC + 4 implementations (GitHub/GitLab/Gitea/Bitbucket), GitConnector model, connector CRUD + test + repo browsing API, frontend connector pages | M7a |
| **M7c** | `2026-03-13-phase4a-m7c-repo-onboarding.md` | Repository model, Project branch fields + neo4j_app_name, git clone service, repository CRUD + clone + sync + evolution API, AddSourceModal, RepoCard, CloneProgress | M7b |

## Totals

- **3 plans**, ~36 tasks
- Backend: ~12 new files, ~4 modified
- Frontend: ~18 new files, ~5 modified
- Backend tasks follow TDD; frontend verified via typecheck + manual testing

---

# Phase 4 — Collaboration & Team Features

Spec: `cast-clone-backend/docs/04-PHASE-4-COLLABORATION.md`

## Execution Order

```
M1 (Auth Foundation) ─────────────────────────────┐
    │                                               │
    └──> M2 (Auth Frontend + User Management) ─────┤
              │                                     │
              ├──> M3 (Annotations & Tags)  ── parallel ──┐
              ├──> M4 (Saved Views)         ── parallel ──┤
              └──> M5 (Export & Activity)   ── parallel ──┘
```

M1 is the backend foundation. M2 adds frontend auth + user management.
M3, M4, M5 are independent and can run in parallel after M2 (frontend auth needed for all UI work).

## Plan Files

| Milestone | File | Description | Depends On |
|-----------|------|-------------|------------|
| **M1** | `2026-03-13-phase4-m1-auth-foundation.md` | User model, bcrypt password hashing, JWT creation/validation (python-jose), login/me/setup endpoints, get_current_user + require_admin FastAPI dependencies | — |
| **M2** | `2026-03-13-phase4-m2-auth-frontend-usermgmt.md` | User CRUD API (admin only), AuthContext provider, login page, first-run setup page, UserMenu in TopBar, admin user management page (/settings/team) | M1 |
| **M3** | `2026-03-13-phase4-m3-annotations-tags.md` | Annotation + Tag models (PostgreSQL), CRUD APIs with auth, useAnnotations hook, AnnotationList/AddAnnotation/TagBadges components, NodeProperties integration, graph visual indicators | M2 |
| **M4** | `2026-03-13-phase4-m4-saved-views.md` | SavedView model (JSONB state), CRUD API, useSavedViews hook, SaveViewModal, ViewsList, toolbar Save button, Cytoscape state capture/restore, shareable URLs | M2 |
| **M5** | `2026-03-13-phase4-m5-export-activity.md` | CSV/JSON streaming export (nodes, edges, graph, impact), ActivityLog model, fire-and-forget logging service, activity feed API (admin only), ExportMenu component, admin activity page | M2 |

## Parallelism Notes

M3, M4, M5 are logically independent but all modify `app/models/db.py` (adding models) and `app/api/__init__.py` (registering routers). If run in parallel by multiple agents, coordinate `db.py` and `__init__.py` changes to avoid merge conflicts.

## Deferred from Phase 4 Plans

Two spec §7 items are deferred — they are enhancements to the existing project pages, not new collaboration features:
- **Project settings page** (editable name/description, re-analyze button, analysis config, delete with confirmation)
- **Project dashboard cards** (last analyzed date, languages, node/edge counts, sort options)

These can be added as a standalone M6 plan or folded into a Phase 4 polish pass.

## Totals

- **5 plans**, ~40 tasks
- Backend: ~12 new files, ~5 modified (main.py, db.py, api/__init__.py, etc.)
- Frontend: ~18 new files, ~6 modified
- Backend tasks follow TDD; frontend verified via typecheck + manual testing
- New dependencies: python-jose[cryptography], passlib[bcrypt], python-multipart

---

# Phase 5a — AI-Powered Pull Request Impact Analysis

Spec: `cast-clone-backend/docs/05a-PHASE-5A-PR-IMPACT-ANALYSIS.md`

## Execution Order

```
M1 (Foundation: models, config, schemas)
    ↓
M2 (Git Platform Clients: webhook parsing + diff fetching)
    ↓
M3 (Webhook Receivers + Git Config API)
    ↓
M4 (Diff-to-Graph Mapper) ←── M5 (Risk Scorer + Drift Detector) [parallel]
    ↓                                 ↓
M6 (Impact Aggregator) ──────────────┘
    ↓
M7a (AI Pipeline Foundation) → M7b (Tools + Runner + Prompts) → M7c (Supervisor + API)
    ↓
M8 (PR Analysis Orchestrator)
    ↓
M9 (PR Analysis API Endpoints)
    ↓
M10 (Frontend — PR Dashboard)
```

M1 → M2 → M3 are sequential (each depends on the previous).
M4 and M5 can run in parallel (both depend only on M1).
M6 depends on M4. M7 depends on M1/M5/M6.
M8 wires M2-M7 together. M9 exposes API. M10 builds UI.

## Plan Files

| Milestone | File | Description | Depends On |
|-----------|------|-------------|------------|
| **M1** | `2026-03-13-phase5a-m1-foundation.md` | ProjectGitConfig + PrAnalysis ORM models, anthropic_api_key config, Pydantic schemas (webhooks, pull_requests, git_config), PR analysis pipeline dataclasses (PullRequestEvent, PRDiff, FileDiff, DiffHunk, AggregatedImpact, DriftReport) | — |
| **M2** | `2026-03-13-phase5a-m2-git-platform-clients.md` | GitPlatformClient ABC, unified diff parser, GitHub/GitLab/Bitbucket/Gitea webhook parsing + signature verification + diff fetching, platform client factory | M1 |
| **M3** | `2026-03-13-phase5a-m3-webhook-receivers-git-config-api.md` | Webhook receiver endpoints (unauthenticated, signature-verified), git config CRUD (admin-only), webhook URL generation, connectivity test, router registration | M1, M2 |
| **M4** | `2026-03-13-phase5a-m4-diff-to-graph-mapper.md` | DiffMapper: Neo4j path+line range queries, handles modified/added/deleted/renamed files, Neo4j path indexes | M1 |
| **M5** | `2026-03-13-phase5a-m5-risk-scorer-drift-detector.md` | Risk classification (High/Medium/Low scoring), drift detection (circular deps, new module deps), pure logic + Neo4j queries | M1 |
| **M6** | `2026-03-13-phase5a-m6-impact-aggregator.md` | Per-node impact (reuse Phase 3 Cypher), cross-tech detection (API/MQ/DB), transaction detection, dedup + aggregation, node enrichment (fan-in, hub status) | M1, M4 |
| **M7a** | `2026-03-13-phase5a-m7a-ai-pipeline-foundation.md` | anthropic[bedrock] dep, Bedrock config (aws_region, model IDs, circuit breakers), SummaryResult, report types, ToolContext, deterministic triage (file categorization + module batching) | M1 |
| **M7b** | `2026-03-13-phase5a-m7b-ai-pipeline-tools-runner-prompts.md` | 8 tool handlers (read_file, search_files, grep_content, list_directory, query_graph_node, get_node_impact, find_path, dispatch_subagent), shared agentic loop runner (run_agent), system prompts for all 5 roles | M7a |
| **M7c** | `2026-03-13-phase5a-m7c-ai-pipeline-supervisor-api.md` | Supervisor agent (50 tool calls, ad-hoc subagent dispatch), generate_pr_summary() public API, triage→parallel subagents→supervisor pipeline, single-call fallback, M8 orchestrator integration, old ai_summary.py removal | M7a, M7b |
| **M8** | `2026-03-13-phase5a-m8-orchestrator.md` | run_pr_analysis() pipeline: fetch diff → map → impact → drift → risk → AI → store. BackgroundTasks execution, stale analysis detection, activity logging | M2-M7 |
| **M9** | `2026-03-13-phase5a-m9-pr-analysis-api.md` | PR list (paginated, filterable), detail, impact detail, drift report, re-analyze endpoints. JWT auth required | M1, M3, M8 |
| **M10** | `2026-03-13-phase5a-m10-frontend-pr-dashboard.md` | TypeScript types + API client + hooks, PR list page (table + filters + badges), PR detail page (AI summary, stats, changed nodes, cross-tech, drift alerts), Git Integration settings page, project nav links | M9 |

## Totals

- **12 plans**, ~45 tasks, ~80 test cases
- Backend: ~22 new files, ~6 modified (config.py, db.py, neo4j.py, main.py, api/__init__.py, analyzer.py)
- Frontend: ~15 new files, ~3 modified (types.ts, api.ts, nav component)
- Backend tasks follow TDD; frontend verified via typecheck + manual testing
- New dependencies: anthropic[bedrock]>=0.40
- AI pipeline: multi-agent architecture with Bedrock (supervisor + specialist subagents)
- Spec: `docs/superpowers/specs/2026-03-13-pr-ai-agent-pipeline-design.md`