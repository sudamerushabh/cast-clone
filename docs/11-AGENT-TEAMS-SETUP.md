# Claude Code Agent Teams — Phase 1 Development Plan

## Overview

This document provides everything needed to use Claude Code's experimental Agent Teams feature to parallelize Phase 1 development of the cast-clone project. It includes setup instructions, the CLAUDE.md project context file, and the orchestration prompts.

---

## 1. Prerequisites & Setup

### Enable Agent Teams

Add to your shell profile (~/.bashrc or ~/.zshrc):

```bash
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
```

Or add to your project's `.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### Install tmux (Recommended)

tmux gives each agent its own visible terminal pane so you can monitor all agents simultaneously:

```bash
# macOS
brew install tmux

# Ubuntu/Debian
sudo apt install tmux
```

### Actual Project Structure

```
cast-clone/
├── .claude/
│   └── settings.json
├── CLAUDE.md                              ← Project context (create this)
├── cast-clone-backend/
│   ├── .venv/
│   ├── app/                               ← Python package root
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── health.py                  ← Existing health endpoint
│   │   ├── models/
│   │   │   └── __init__.py
│   │   ├── services/
│   │   │   └── __init__.py
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── main.py                        ← FastAPI entrypoint
│   ├── .env.example
│   ├── .python-version
│   ├── pyproject.toml
│   └── uv.lock
├── cast-clone-frontend/
├── docs/                                  ← Architecture docs (00-11)
└── plans/
```

**Key observations from existing code:**
- Python package is `app` (not `src/codelens`)
- Package manager is `uv` (not pip)
- FastAPI app lives at `cast-clone-backend/app/main.py`
- Existing folders: `api/`, `models/`, `services/`
- Tests will go in `cast-clone-backend/tests/`

---

## 2. CLAUDE.md — Project Context File

Create this file at the project root (`cast-clone/CLAUDE.md`). Every agent reads it on startup.

```markdown
# cast-clone — Software Architecture Intelligence Platform

## What This Project Is
cast-clone is an on-premise software architecture intelligence platform that reverse-engineers,
visualizes, and analyzes complex codebases. It parses source code using tree-sitter and SCIP
indexers, stores architecture graphs in Neo4j, and serves an interactive visualization UI.
This is a clone/alternative to CAST Imaging.

## Repository Structure
- cast-clone-backend/ — Python backend (FastAPI, Celery, analysis engine)
  - app/ — Python package root (all source code lives here)
  - app/api/ — FastAPI route handlers
  - app/models/ — Pydantic models and dataclasses
  - app/services/ — Business logic and service layer
  - app/config.py — Application configuration
  - app/main.py — FastAPI application entrypoint
  - tests/ — All backend tests (pytest)
  - pyproject.toml — Python dependencies (managed with uv)
  - uv.lock — Locked dependencies
- cast-clone-frontend/ — React frontend (TypeScript, Cytoscape.js)
- docs/ — Architecture and design documentation
- plans/ — Implementation plans and specs
- docker-compose.yml — Full stack deployment

## Tech Stack
- **Backend:** Python 3.12+ with FastAPI, Celery, Redis
- **Package Manager:** uv (NOT pip — always use `uv add`, `uv run`, `uv sync`)
- **Graph Database:** Neo4j 5.x (Community Edition) with APOC + GDS plugins
- **Relational DB:** PostgreSQL 16 (users, projects, metadata)
- **Frontend:** React 18+ with TypeScript, Cytoscape.js, Monaco Editor
- **Deployment:** Docker Compose (on-premise)

## Key Architecture Decisions
- **SCIP over LSP:** We use Sourcegraph SCIP indexers (Apache 2.0) for compiler-accurate
  code resolution instead of LSP servers. SCIP runs as CLI subprocesses producing Protobuf
  index files. LSP is fallback only via lsp-client library.
- **Tree-sitter:** Base parser for structural extraction. py-tree-sitter with pre-compiled grammars.
- **Neo4j abstraction:** All graph DB operations go through a GraphStore abstract interface
  to allow future swap to Memgraph or Apache AGE.
- **Framework plugins:** Plugin system with detect/extract contract for Spring, Django, React, etc.
- **sqlglot:** For parsing embedded SQL strings and extracting table/column references.
- **ELK layout engine:** elkjs for hierarchical/layered graph layouts in the frontend.

## Project Documentation
All architecture and design documents are in /docs/:
- 00-PROJECT-OVERVIEW.md — Vision, differentiators, roadmap
- 01-PHASE-1-CORE-ENGINE.md — Phase 1 spec (REVISED with SCIP)
- 07-ANALYSIS-ORCHESTRATOR.md — Pipeline stages deep dive (REVISED with SCIP)
- 08-FRAMEWORK-PLUGINS.md — Plugin architecture
- 09-NEO4J-SCHEMA.md — Graph schema and queries

## Coding Conventions
- Python: Use type hints everywhere. Dataclasses for data structures. ABC for interfaces.
- Package manager: ALWAYS use uv. `uv add <package>` to add deps. `uv run pytest` to run tests.
- Async: Use async/await for I/O operations (FastAPI, Neo4j driver, subprocess calls).
- Testing: pytest with pytest-asyncio. Every module needs unit tests. Integration tests
  for pipeline stages. Use fixtures for Neo4j and Redis test instances.
- Naming: snake_case for Python, camelCase for TypeScript/React.
- Imports: Use absolute imports from `app.` root (e.g., `from app.models.graph import GraphNode`).
- Docstrings: Google style for all public functions and classes.
- Linting: ruff (already configured in project)

## File Ownership Rules (CRITICAL FOR AGENT TEAMS)
To prevent merge conflicts when multiple agents work simultaneously:
- cast-clone-backend/app/parsing/ → owned by Parsing Agent
- cast-clone-backend/app/scip/ → owned by SCIP Agent
- cast-clone-backend/app/plugins/ → owned by Plugin Agent
- cast-clone-backend/app/graph/ → owned by Graph Agent
- cast-clone-backend/app/pipeline/ → owned by Pipeline Agent
- cast-clone-backend/app/api/ → owned by API Agent
- cast-clone-backend/app/services/ → owned by Lead (shared service layer)
- cast-clone-frontend/src/ → owned by Frontend Agent
- Shared interfaces in cast-clone-backend/app/models/ → owned by Lead only
- Tests mirror source: cast-clone-backend/tests/parsing/, cast-clone-backend/tests/scip/, etc.

## Shared Data Models (All agents read these, only Lead modifies)
Core data models are in cast-clone-backend/app/models/:
- graph.py — GraphNode, GraphEdge, NodeKind, EdgeType, Confidence
- analysis.py — ProjectManifest, AnalysisContext, PluginResult, SymbolInfo
- api_schemas.py — API request/response schemas (Pydantic)
```

---

## 3. Development Waves

Phase 1 is decomposed into 4 sequential waves. Each wave uses a 3-agent team.

### Wave 1: Foundation (Data Models + Parsing + Graph Storage)
Core data pipeline — parse code → store graph. Everything else depends on these.

### Wave 2: Resolution (SCIP + Framework Plugins + SQL)
Adds compiler-accurate resolution and framework-specific analysis.

### Wave 3: Pipeline (Orchestrator + Worker Infrastructure)
Wires all components into the 9-stage analysis pipeline.

### Wave 4: API + Frontend
REST API, WebSocket progress, and the React graph visualization UI.

---

## 4. Agent Team Prompts

### WAVE 1 PROMPT — Foundation

Copy-paste this into Claude Code after enabling agent teams:

```
I'm building cast-clone, a software architecture intelligence platform (a CAST Imaging clone).
Read CLAUDE.md and all docs in /docs/ (especially 01-PHASE-1-CORE-ENGINE.md,
07-ANALYSIS-ORCHESTRATOR.md, 08-FRAMEWORK-PLUGINS.md, and 09-NEO4J-SCHEMA.md) for full context.

The existing project structure has the Python package at cast-clone-backend/app/ with
existing files: app/api/health.py, app/models/__init__.py, app/services/__init__.py,
app/config.py, app/main.py. We use uv as the package manager (not pip).

We're starting Phase 1, Wave 1: Foundation. Create an agent team with the following structure.

## Team Structure

**You (Lead/Supervisor):**
- First, read ALL docs in /docs/ to understand the full architecture
- Create the shared data models in cast-clone-backend/app/models/ BEFORE spawning teammates:
  - app/models/graph.py — GraphNode, GraphEdge, NodeKind, EdgeType, Confidence enums and dataclasses
  - app/models/analysis.py — ProjectManifest, DetectedLanguage, DetectedFramework,
    AnalysisContext, ResolvedEnvironment, PluginResult, SymbolInfo
  - app/models/__init__.py — re-export all public types
  (Follow the specs in 07-ANALYSIS-ORCHESTRATOR.md for exact fields)
- Write model tests in cast-clone-backend/tests/test_models.py
- Install shared dependencies via uv: `cd cast-clone-backend && uv add tree-sitter tree-sitter-java tree-sitter-python tree-sitter-typescript tree-sitter-c-sharp sqlglot neo4j pytest pytest-asyncio pytest-cov ruff`
- After models are committed and deps installed, spawn the 3 teammates below
- Monitor teammates, review their work, resolve integration issues
- After all teammates finish, write integration tests that verify:
  parse a sample Java project with tree-sitter → store in Neo4j → query back
- DO NOT implement anything yourself beyond shared models and deps — delegate everything

**Teammate 1 — Parsing Agent:**
- Owns: cast-clone-backend/app/parsing/ and cast-clone-backend/tests/parsing/
- Read 01-PHASE-1-CORE-ENGINE.md sections 2-3 for full spec
- Implement:
  1. app/parsing/__init__.py
  2. app/parsing/grammar.py — LanguageGrammar registry (maps extensions → tree-sitter grammars)
  3. app/parsing/java_extractor.py — S-expression queries for Java (classes, methods, fields,
     calls, imports, annotations as specified in the doc)
  4. app/parsing/python_extractor.py — same for Python
  5. app/parsing/typescript_extractor.py — same for TypeScript
  6. app/parsing/symbol_resolver.py — GlobalSymbolResolver (FQN index, import resolution, inheritance)
  7. app/parsing/file_scanner.py — parallel file parsing with ProcessPoolExecutor
  8. app/parsing/string_tagger.py — identify SQL strings, URLs, Kafka topics in string literals
- All extractors must return list[GraphNode] and list[GraphEdge] using models from app.models.graph
- Write unit tests for each extractor with sample code snippets as test fixtures
- Write a test that parses a real multi-file Java project (create fixtures in tests/parsing/fixtures/)
- Test coverage target: >90%
- Message the Graph Agent when your output format is finalized

**Teammate 2 — Graph Agent:**
- Owns: cast-clone-backend/app/graph/ and cast-clone-backend/tests/graph/
- Read 09-NEO4J-SCHEMA.md for the complete schema
- Implement:
  1. app/graph/__init__.py
  2. app/graph/store.py — GraphStore abstract base class (the interface from 01-PHASE-1-CORE-ENGINE.md):
     write_nodes_batch, write_edges_batch, query_neighbors, query_path,
     query_level, search_fulltext, clear_application
  3. app/graph/neo4j_store.py — Neo4jGraphStore implementation:
     - UNWIND-based batch writes in groups of 5000
     - Cypher queries for neighbors, shortest path, multi-level navigation, full-text search
  4. app/graph/schema.py — Schema initialization (CREATE INDEX, CREATE FULLTEXT INDEX)
  5. app/graph/connection.py — Connection pool management and health checks
- Use async neo4j driver (neo4j[async])
- Write unit tests using testcontainers-python or a Neo4j test fixture
- Write performance test for batch writes (10K nodes, 50K edges)
- Test coverage target: >90%

**Teammate 3 — Project Discovery Agent:**
- Owns: cast-clone-backend/app/discovery/ and cast-clone-backend/tests/discovery/
- Read 07-ANALYSIS-ORCHESTRATOR.md Stage 1 and Stage 2
- Implement:
  1. app/discovery/__init__.py
  2. app/discovery/scanner.py — ProjectScanner (walk filesystem, ignore patterns, group by ext)
  3. app/discovery/build_system.py — BuildSystemDetector (Maven/Gradle/npm/pip/dotnet)
  4. app/discovery/framework.py — FrameworkDetector (two-pass: build file + code scanning)
  5. app/discovery/monorepo.py — MonorepoDetector (sub-projects, Lerna/Nx/Maven modules)
  6. app/discovery/config_collector.py — ConfigFileCollector (application.yml, settings.py, .env)
  7. app/discovery/db_artifacts.py — DatabaseArtifactFinder (Flyway, Liquibase, Alembic, EF)
  8. app/discovery/dependency_resolver.py — DependencyResolver (run Maven/npm/pip as subprocess)
  All of these produce ProjectManifest and ResolvedEnvironment from app.models.analysis
- Create test fixtures in tests/discovery/fixtures/ (a small Spring Boot + React project structure)
- Write unit tests for each detector with various project layouts
- Write integration test that scans the fixture and produces correct manifest
- Test coverage target: >90%

## Coordination Rules
- Lead creates shared models FIRST, installs deps, commits, THEN spawns teammates
- Teammates must import from app.models — never define their own GraphNode/GraphEdge
- Each teammate works ONLY in their owned directories (app/{module}/ and tests/{module}/)
- When a teammate finishes and tests pass, message the lead with a summary
- Lead runs the full integration test suite after all teammates complete
- If any teammate encounters a design question, message the lead — don't guess
- Use `uv run pytest` to run tests, `uv run ruff check` for linting

## Quality Gates
- ALL code must have type hints
- ALL public functions must have Google-style docstrings
- ALL modules must have >90% test coverage (use pytest-cov)
- Run `uv run ruff check` before marking any task complete
- Every teammate runs their own tests and confirms they pass before reporting done
```

### WAVE 2 PROMPT — Resolution

Run this after Wave 1 is complete and all tests pass:

```
Read CLAUDE.md and all docs in /docs/. Wave 1 (parsing + graph storage + discovery) is
complete. We're now building Wave 2: Resolution — adding SCIP indexing, framework plugins,
and SQL parsing on top of the foundation.

Create an agent team. Use Sonnet for teammates.

**You (Lead/Supervisor):**
- Verify Wave 1 code exists and tests pass: run `cd cast-clone-backend && uv run pytest tests/ -v`
- Review existing models in app/models/ and add any new ones needed:
  - app/models/scip.py — SCIPIndexerConfig, SCIPDocument, SCIPOccurrence, SCIPSymbolInfo
  - app/models/plugin.py — FrameworkPlugin ABC, LayerRules, EntryPoint, EndPoint
  Update app/models/__init__.py with new exports
- Install new deps: `uv add protobuf lsp-client`
- After model updates committed, spawn teammates
- After all teammates finish, write integration tests in cast-clone-backend/tests/test_integration_wave2.py:
  Test 1: Parse Spring Boot project → run SCIP → merge → verify resolved edges in Neo4j
  Test 2: Parse same project → run Spring DI plugin → verify INJECTS edges
  Test 3: Parse project with embedded SQL → verify READS/WRITES edges to tables

**Teammate 1 — SCIP Agent:**
- Owns: cast-clone-backend/app/scip/ and cast-clone-backend/tests/scip/
- Read 01-PHASE-1-CORE-ENGINE.md section 3 and 07-ANALYSIS-ORCHESTRATOR.md Stage 4
- Implement:
  1. app/scip/registry.py — SCIPIndexerRegistry (configs for scip-java, scip-typescript, scip-python, scip-dotnet)
  2. app/scip/runner.py — SCIPRunner (async subprocess execution with timeout)
  3. app/scip/parser.py — SCIPProtobufParser (parse index.scip files)
  4. app/scip/normalizer.py — SCIPSymbolNormalizer (SCIP symbol strings → internal FQN)
  5. app/scip/merger.py — SCIPMerger (merge SCIP into AnalysisContext, upgrade UNRESOLVED → RESOLVED)
  6. app/scip/lsp_fallback.py — LSPFallback (thin wrapper for when SCIP unavailable)
- Write unit tests with mock SCIP index fixtures
- Test coverage target: >90%

**Teammate 2 — Plugin Agent:**
- Owns: cast-clone-backend/app/plugins/ and cast-clone-backend/tests/plugins/
- Read 08-FRAMEWORK-PLUGINS.md for full plugin architecture
- Implement:
  1. app/plugins/base.py — FrameworkPlugin ABC (detect, extract, get_layer_classification)
  2. app/plugins/loader.py — PluginLoader (auto-discover from plugins directory)
  3. app/plugins/resolver.py — PluginDependencyResolver (topological sort on depends_on)
  4. app/plugins/executor.py — PluginExecutor (run in order, merge results, handle failures)
  5. app/plugins/java/spring_di.py — SpringDIPlugin (detect Spring, resolve @Autowired)
  6. app/plugins/java/hibernate.py — HibernatePlugin (@Entity → @Table mapping)
  7. app/plugins/layer_classifier.py — framework rules + folder-name heuristic fallback
- Create test fixtures with sample Spring Boot classes
- Test coverage target: >90%

**Teammate 3 — SQL Agent:**
- Owns: cast-clone-backend/app/sql/ and cast-clone-backend/tests/sql/
- Implement:
  1. app/sql/detector.py — SQLStringDetector (identify SQL from tree-sitter tagged strings)
  2. app/sql/parser.py — SQLParser (sqlglot → extract tables, columns, query type)
  3. app/sql/migration_parser.py — parse Flyway/Liquibase/Alembic migrations
  4. app/sql/schema_builder.py — build Table/Column/FK nodes from migrations
  5. app/sql/cross_tech.py — HTTPEndpointMatcher + MessageQueueMatcher
- Write unit tests with sample SQL in various dialects
- Test coverage target: >90%

## Coordination Rules
- Lead creates/updates shared models first, teammates import from app.models
- Each teammate works ONLY in their owned directories
- Use `uv run pytest` and `uv run ruff check`
```

### WAVE 3 PROMPT — Pipeline

```
Read CLAUDE.md and all docs. Waves 1 and 2 complete. Building Wave 3: the Analysis Pipeline
Orchestrator that wires all components into the 9-stage pipeline.

Create an agent team. Use Sonnet for teammates.

**You (Lead/Supervisor):**
- Verify Waves 1-2 pass: `cd cast-clone-backend && uv run pytest tests/ -v`
- Read 07-ANALYSIS-ORCHESTRATOR.md — this wave implements it
- Write end-to-end integration test after teammates finish:
  Given a real Spring Boot + React project, run full pipeline and verify complete graph

**Teammate 1 — Pipeline Agent:**
- Owns: cast-clone-backend/app/pipeline/ and cast-clone-backend/tests/pipeline/
- Implement:
  1. app/pipeline/orchestrator.py — AnalysisOrchestrator sequencing all 9 stages
  2. app/pipeline/stages.py — Individual stage runner functions
  3. app/pipeline/progress.py — Progress event emitter (dict events for now)
  4. app/pipeline/errors.py — Error recovery and graceful degradation logic
- Each stage calls components from Waves 1-2
- Write unit tests for sequencing, error handling, degradation paths

**Teammate 2 — Enrichment Agent:**
- Owns: cast-clone-backend/app/enrichment/ and cast-clone-backend/tests/enrichment/
- Implement Stage 7 (GraphEnricher):
  1. app/enrichment/complexity.py — cyclomatic complexity from AST
  2. app/enrichment/metrics.py — fan-in/fan-out counter
  3. app/enrichment/community.py — Neo4j GDS Louvain community detection
  4. app/enrichment/coupling.py — coupling/cohesion scorer
  5. app/enrichment/aggregation.py — 5-level hierarchy builder
- Implement Stage 9 (TransactionDiscovery):
  6. app/enrichment/transactions.py — entry point finder, BFS traversal, subgraph writer
- Write tests with pre-populated Neo4j data

**Teammate 3 — Worker Agent:**
- Owns: cast-clone-backend/app/worker/ and cast-clone-backend/tests/worker/
- Install deps: `uv add celery[redis]`
- Implement:
  1. app/worker/celery_app.py — Celery configuration (Redis broker)
  2. app/worker/tasks.py — Analysis task (calls AnalysisOrchestrator)
  3. app/worker/progress.py — Progress reporting via Redis pub/sub
  4. app/worker/status.py — Task status tracking (pending, running, complete, failed)
- Write Docker Compose services for Redis + Celery worker
- Write integration tests for task lifecycle
```

### WAVE 4 PROMPT — API + Frontend

```
Read CLAUDE.md and all docs. Waves 1-3 complete — full analysis pipeline works.
Building Wave 4: REST API and frontend UI.

Create an agent team. Use Sonnet for teammates.

**You (Lead/Supervisor):**
- Verify all waves pass: `cd cast-clone-backend && uv run pytest tests/ -v`
- Coordinate API contract between backend and frontend teammates
- Write end-to-end test after teammates finish

**Teammate 1 — API Agent:**
- Owns: cast-clone-backend/app/api/ and cast-clone-backend/tests/api/
- NOTE: app/api/ already has health.py and __init__.py — extend, don't overwrite
- Implement FastAPI routes (see 01-PHASE-1-CORE-ENGINE.md section 6):
  1. app/api/projects.py — POST /api/v1/projects, POST /api/v1/projects/{id}/analyze,
     GET /api/v1/projects/{id}/status
  2. app/api/graphs.py — GET nodes, edges, node/{fqn}, neighbors/{fqn}
  3. app/api/search.py — GET /api/v1/search/{project_id}
  4. app/api/websocket.py — WS /api/v1/projects/{id}/progress
  5. Update app/main.py to register all new routers
- Write API tests with httpx AsyncClient
- Write WebSocket test for progress streaming

**Teammate 2 — Frontend Agent:**
- Owns: cast-clone-frontend/src/ and cast-clone-frontend/tests/
- Implement React + TypeScript:
  1. Project list page
  2. Project upload page (ZIP upload or directory path)
  3. Analysis progress page (WebSocket, stage-by-stage progress bars)
  4. Graph view page (Cytoscape.js force-directed layout)
  5. Node properties panel (click → sidebar with details)
  6. Search bar with autocomplete
  7. Node type filter checkboxes
- Use react-cytoscapejs, Zustand for state
- Write component tests with React Testing Library
- Message API Agent to agree on response shapes first

**Teammate 3 — DevOps Agent:**
- Owns: docker-compose.yml, Dockerfiles, scripts/
- Implement:
  1. Dockerfile for backend (Python + uv + tree-sitter + SCIP indexers)
  2. Dockerfile for frontend (Node + nginx)
  3. Dockerfile for worker (backend base + Celery entrypoint)
  4. docker-compose.yml (nginx, api, worker, neo4j, postgres, redis)
  5. .env.example with all required variables
  6. setup.sh (generate passwords, validate prereqs, start stack)
  7. Health check script
- Test: `docker compose up` starts everything, all health checks pass
```

---

## 5. Best Practices & Tips

### Before Each Wave
1. Make sure previous wave tests all pass: `cd cast-clone-backend && uv run pytest tests/ -v`
2. Commit and tag: `git tag wave-1-complete`
3. Review shared models — update if needed before spawning teammates

### During a Wave
- Use tmux to monitor all agents in split panes
- If lead starts implementing instead of delegating, tell it:
  "Wait for your teammates to complete their tasks before proceeding. Only delegate."
- If a teammate gets stuck, interact directly (Shift+Down in tmux)
- If a teammate finishes early, tell the lead to assign it review duties

### Error Recovery
- Teammate crashes: tell the lead to spawn a replacement
- Tests fail after teammates finish: tell the lead to investigate
- Agents edit same file: `git diff`, manually resolve, then continue

### Permission Pre-Approval
Add to `.claude/settings.json` to reduce prompts:

```json
{
  "permissions": {
    "allow": [
      "Bash(uv *)",
      "Bash(pytest*)",
      "Bash(ruff*)",
      "Bash(docker*)",
      "Read(*)",
      "Write(cast-clone-backend/app/**)",
      "Write(cast-clone-backend/tests/**)",
      "Write(cast-clone-frontend/src/**)",
      "Write(cast-clone-frontend/tests/**)",
      "Write(plans/**)",
      "Write(docker-compose.yml)",
      "Write(Dockerfile*)"
    ]
  }
}
```

---

## 6. Verification Checklist (After All Waves)

```bash
# 1. All tests pass
cd cast-clone-backend && uv run pytest tests/ -v --cov=app --cov-report=term-missing

# 2. Coverage threshold
uv run pytest tests/ --cov=app --cov-fail-under=85

# 3. Linting
uv run ruff check app/ tests/

# 4. Type checking
uv run mypy app/

# 5. Docker stack
docker compose up -d
docker compose ps  # all services "healthy"

# 6. End-to-end
# Upload sample project via API → trigger analysis → poll → query graph → verify

# 7. Frontend
# Open http://localhost → create project → trigger analysis → view graph
```