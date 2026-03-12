# CodeLens — Software Architecture Intelligence Platform

## Project Overview

CodeLens is an on-premise software architecture intelligence platform that automatically reverse-engineers, visualizes, and analyzes the inner workings of complex software applications. It performs semantic analysis of source code, database scripts, and configuration files to produce interactive architecture maps — enabling software architects, engineers, and AI agents to understand, maintain, modernize, and migrate applications with speed and confidence.

---

## Vision

Build the most accurate, AI-native, developer-friendly alternative to CAST Imaging — positioning CodeLens as the "MRI for Software" that turns source code into actionable architectural intelligence.

---

## Key Differentiators vs. CAST Imaging

| Area | CAST Imaging | CodeLens (Target) |
|------|-------------|-------------------|
| Onboarding | Heavy "CAST Console" setup process | Paste a Git URL or point to a directory and wait |
| Learning Curve | Steep — users report difficulty at the start | Intuitive UI with guided exploration |
| Graph Clarity | Cluttered and hard to navigate at scale (user complaints) | Smart aggregation, decluttering, progressive disclosure |
| Export Options | Limited — SVG with zoom limits | Full export to SVG, PNG, JSON, CSV, PDF, XLSX |
| IDE Integration | None (users request it frequently) | VS Code extension + MCP server from early phases |
| AI Integration | MCP server added recently (2025) | AI-native from the ground up — built-in assistant + MCP |
| Deployment | Complex infrastructure | Single `docker-compose up` command |
| Pricing | Enterprise pricing, opaque | Transparent tier-based pricing |

---

## Target Market (Phased)

1. **Phase 1-3:** Developer teams who need to understand their own codebases (greenfield + brownfield)
2. **Phase 4-5:** AI agent ecosystem — feed architecture intelligence to LLMs for accurate code generation
3. **Phase 6+:** Enterprise legacy modernization — cloud migration, mainframe modernization, technical debt remediation

---

## Supported Technologies (Initial)

### Languages
- Java (8, 11, 17, 21)
- C# / .NET (6, 7, 8)
- TypeScript / JavaScript (ES2020+)
- Python (3.8+)
- SQL (PostgreSQL, MySQL, SQL Server, Oracle dialects)

### Frameworks
- **Java:** Spring Boot, Spring MVC, Spring Data, Spring Security, Hibernate/JPA, JAX-RS
- **Python:** Django, Django REST Framework, FastAPI, SQLAlchemy, Alembic
- **TypeScript/JS:** React, Angular, Next.js, Express, NestJS, React Router, Redux
- **.NET:** ASP.NET Core, Entity Framework Core, Blazor

### Databases
- PostgreSQL, MySQL, SQL Server, Oracle, MongoDB, Redis
- Migration tools: Flyway, Liquibase, Alembic, EF Migrations

---

## Tech Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Backend API | Python + FastAPI | Fast async API, great ecosystem for analysis tools |
| Analysis Engine | Python + Tree-sitter + LSP | Tree-sitter for fast AST parsing, LSP for deep resolution |
| Graph Database | Neo4j | Purpose-built for graph traversal, Cypher query language |
| Relational DB | PostgreSQL | Users, projects, configs, audit logs |
| Cache / Queue | Redis | Analysis job queues, query caching, session storage |
| Object Storage | MinIO (S3-compatible) | Source code archives, analysis artifacts |
| Frontend | React + TypeScript | Component-based UI, rich ecosystem |
| Graph Visualization | Cytoscape.js | Purpose-built for network graphs, compound nodes, WebGL |
| Code Viewer | Monaco Editor | VS Code's editor component, syntax highlighting |
| Deployment | Docker Compose | Single-command on-premise deployment |

---

## Phase Roadmap Summary

| Phase | Timeline | Focus | Key Deliverable |
|-------|----------|-------|----------------|
| Phase 1 | Months 1–3 | Foundation & Core Analysis Engine | Parse code → build graph → store → basic display |
| Phase 2 | Months 3–5 | Rich Visualization & Navigation | Multi-level drill-down, transaction flows, data model views |
| Phase 3 | Months 5–7 | Impact Analysis & Smart Features | Blast radius, modularity scoring, path finder |
| Phase 4 | Months 7–9 | Collaboration & Team Features | Annotations, saved views, user management, reporting |
| Phase 5 | Months 9–12 | AI Integration | Built-in AI assistant, MCP server for external agents |
| Phase 6 | Months 12–18 | Enterprise & Advisors | Cloud readiness, DB migration, tech debt scoring, CI/CD |

---

## System Architecture (High-Level)

```
┌─────────────────────────────────────────────────────────────┐
│                   User's Infrastructure                      │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              Docker Compose Stack                        │ │
│  │                                                           │ │
│  │  ┌───────────────────────────────────────────────────┐   │ │
│  │  │          React Frontend (Nginx)                    │   │ │
│  │  │  Cytoscape.js + Monaco Editor + Search UI          │   │ │
│  │  └──────────────────────┬────────────────────────────┘   │ │
│  │                         │ :443                            │ │
│  │  ┌──────────────────────▼────────────────────────────┐   │ │
│  │  │          FastAPI Backend                           │   │ │
│  │  │  REST API + WebSocket + Graph Query Service        │   │ │
│  │  └──────────────────────┬────────────────────────────┘   │ │
│  │                         │                                 │ │
│  │       ┌─────────────────┼─────────────────┐              │ │
│  │       ▼                 ▼                 ▼              │ │
│  │  ┌────────┐       ┌──────────┐      ┌──────────┐        │ │
│  │  │ Neo4j  │       │  Redis   │      │ Postgres │        │ │
│  │  │ (graph)│       │ (cache)  │      │ (meta)   │        │ │
│  │  └────────┘       └──────────┘      └──────────┘        │ │
│  │                                                           │ │
│  │  ┌───────────────────────────────────────────────────┐   │ │
│  │  │         Analysis Worker(s)                         │   │ │
│  │  │  Tree-sitter + LSP Harness + Framework Plugins     │   │ │
│  │  │  + Cross-Tech Linker + Graph Builder               │   │ │
│  │  └───────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  Source code stays on local disk — never leaves the machine   │
└─────────────────────────────────────────────────────────────┘
```

---

## Document Index

| Document | Description |
|----------|-------------|
| `01-PHASE-1-CORE-ENGINE.md` | Analysis engine, parsing, graph storage, minimal UI |
| `02-PHASE-2-VISUALIZATION.md` | Rich visualization, multi-level navigation, core views |
| `03-PHASE-3-IMPACT-ANALYSIS.md` | Impact analysis, modularity scoring, path finder |
| `04-PHASE-4-COLLABORATION.md` | Annotations, saved views, user management, reporting |
| `05-PHASE-5-AI-INTEGRATION.md` | AI assistant, MCP server, AI-powered summaries |
| `06-PHASE-6-ENTERPRISE.md` | Cloud readiness, DB migration, CI/CD, portfolio view |
| `07-ANALYSIS-ORCHESTRATOR.md` | Deep dive: pipeline stages, wiring, error recovery |
| `08-FRAMEWORK-PLUGINS.md` | Deep dive: plugin system architecture, all plugin specs |
| `09-NEO4J-SCHEMA.md` | Deep dive: graph data model, queries, aggregation |
| `10-DEPLOYMENT.md` | Docker Compose setup, on-premise installation guide |