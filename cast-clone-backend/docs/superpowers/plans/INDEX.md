# Phase 1 Implementation Plans — Master Index

All plans for Phase 1 (Core Analysis Engine). Execute in dependency order shown below.

---

## Execution Order

```
M1 (foundation)
 ├─> M2 (API + orchestrator)     ── parallel ──┐
 └─> M3 (discovery + deps)       ── parallel ──┘
      └─> M4a (tree-sitter base)
           ├─> M4b (Java extractor)       ── parallel ──┐
           ├─> M4c (TypeScript extractor)  ── parallel ──┤
           ├─> M4d (Python extractor)      ── parallel ──┤
           └─> M4e (C# extractor)         ── parallel ──┘
                └─> M5 (SCIP indexers)     ── parallel ──┐
                └─> M6a (plugin base)      ── parallel ──┘
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
