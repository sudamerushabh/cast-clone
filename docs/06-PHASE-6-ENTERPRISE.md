# Phase 6 — Enterprise & Advisors

**Timeline:** Months 12–18
**Goal:** Go upmarket with modernization intelligence and enterprise features

---

## Overview

Phase 6 targets enterprise customers with large-scale modernization needs — cloud migration, mainframe modernization, technical debt remediation, and compliance. This phase adds "Advisors" (automated assessment engines), multi-application portfolio management, CI/CD integration, and architecture drift detection.

---

## 1. Advisors (Assessment Engines)

Advisors are automated analysis modules that scan the graph for specific patterns and produce actionable recommendations. Each Advisor has a specific modernization focus.

### Cloud / Container Readiness Advisor

**Purpose:** Assess whether an application can be containerized or migrated to cloud-native architecture.

**What it checks:**

| Category | Check | Blocker / Booster |
|----------|-------|-------------------|
| File System | Writes to local filesystem paths | Blocker — containers have ephemeral storage |
| Sessions | Uses sticky sessions or local session storage | Blocker — need distributed session |
| Configuration | Hardcoded hostnames, ports, file paths | Blocker — need externalized config |
| Database | Uses connection pooling correctly | Booster — cloud-ready |
| Database | Embedded database (H2, SQLite) | Blocker — need external DB |
| Logging | Writes logs to stdout/stderr | Booster — cloud-native logging |
| Logging | Writes logs to local files | Blocker — need log aggregation |
| State | Stores state in memory (static variables, singletons) | Blocker — need stateless design |
| Dependencies | Uses cloud-incompatible native libraries | Blocker — may not work in containers |
| Health | Exposes health/readiness endpoints | Booster — Kubernetes-ready |
| Configuration | Uses environment variables for config | Booster — 12-factor app |

**Detection approach:**
- Query the graph for specific patterns (e.g., `File.write()` calls, `HttpSession` usage)
- Parse configuration files for hardcoded values
- Check for known cloud-blocker libraries/APIs

**Output:**
- Readiness score (0-100)
- List of blockers with severity, location (file, line), and remediation guidance
- List of boosters (things already cloud-ready)
- Estimated effort to remediate all blockers

### Database Migration Advisor

**Purpose:** Assess the effort required to migrate from one database to another (e.g., Oracle → PostgreSQL, SQL Server → MySQL).

**What it checks:**

| Category | Check | Impact |
|----------|-------|--------|
| Proprietary SQL | Oracle-specific PL/SQL, `CONNECT BY`, `ROWNUM` | High — requires rewrite |
| Stored Procedures | Count and complexity of stored procedures | High — must be rewritten or ported |
| Data Types | Usage of vendor-specific data types | Medium — need type mapping |
| Functions | Vendor-specific SQL functions (`NVL`, `ISNULL`, `DECODE`) | Medium — need translation |
| Sequences | Sequence usage patterns | Low — PostgreSQL supports sequences |
| Triggers | Trigger complexity and count | Medium — syntax differs between DBs |
| Indexes | Vendor-specific index types (Oracle bitmap, SQL Server columnstore) | Medium — need equivalent |

**Detection approach:**
- Parse all SQL in the codebase (from SQL parser plugin)
- Parse migration files and DDL scripts
- Identify vendor-specific syntax using `sqlglot` dialect analysis
- Map each finding to the target database's equivalent (or flag as "no equivalent")

**Output:**
- Migration complexity score
- Count of SQL statements requiring modification, grouped by change type
- Auto-generated migration suggestions for common patterns
- List of stored procedures requiring manual rewrite

### Technical Debt Advisor (ISO 5055)

**Purpose:** Identify and prioritize critical structural flaws affecting resiliency, security, efficiency, and maintainability.

**ISO 5055 Categories:**

1. **Reliability** — null pointer dereferences, unhandled exceptions, resource leaks
2. **Security** — SQL injection vectors, hardcoded credentials, insecure deserialization
3. **Performance** — N+1 queries, unnecessary object creation in loops, inefficient algorithms
4. **Maintainability** — god classes (too many methods), cyclomatic complexity > threshold, deep inheritance chains

**Detection approach:**
- Graph-based detection: circular dependencies, excessive coupling, god classes (fan-in + fan-out > threshold)
- AST-based detection: complexity metrics, code duplication heuristics, naming convention violations
- Pattern matching: known anti-patterns (service locator, singleton abuse, anemic domain model)

**Output:**
- Technical debt score per module, per application
- Ranked list of flaws by severity and remediation effort
- Remediation guidance for each flaw category
- Trend tracking over time (if re-analysis is run periodically)

### Green / Sustainability Advisor

**Purpose:** Identify code patterns that contribute to excessive resource usage and energy consumption.

**What it checks:**
- Inefficient database queries (full table scans, missing indexes)
- Unnecessary computation in hot paths
- Excessive logging in production
- Uncompressed data transfers
- Polling where event-driven would suffice
- Memory leaks (objects held in static collections)

### Open Source Risk Advisor

**Purpose:** Map security, legal, and obsolescence risks from open-source dependencies.

**What it checks:**
- Known vulnerabilities in dependencies (CVE scanning via integration with OSV or similar databases)
- License compatibility (GPL in a proprietary project, license conflicts)
- Abandoned/unmaintained dependencies (no commits in 2+ years, archived repos)
- Dependency age and version freshness

---

## 2. Multi-Application Portfolio View

### Dashboard

A portfolio dashboard showing all analyzed applications:

- Application cards with key metrics (LOC, languages, frameworks, last analyzed, health score)
- Sortable/filterable grid
- Quick comparison: select 2+ apps to compare metrics side-by-side

### Cross-Application Dependencies

- Visualize how applications connect to each other:
  - Shared databases (two apps write to the same table)
  - API calls between services
  - Message queue connections
  - Shared libraries/packages

- Dependency matrix: Application × Application showing dependency type and strength

### Portfolio-Level Metrics

- Total LOC across all applications
- Technology distribution (pie chart: Java 45%, TypeScript 30%, Python 25%)
- Framework usage distribution
- Average technical debt score
- Applications by cloud readiness tier
- Cross-application coupling score

---

## 3. CI/CD Integration

### GitHub Actions Integration

```yaml
# .github/workflows/codelens.yml
name: CodeLens Analysis
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run CodeLens Analysis
        uses: codelens/analyze-action@v1
        with:
          server_url: ${{ secrets.CODELENS_URL }}
          api_key: ${{ secrets.CODELENS_API_KEY }}
          project_id: ${{ vars.CODELENS_PROJECT_ID }}
      
      - name: Check Architecture Rules
        uses: codelens/gate-action@v1
        with:
          server_url: ${{ secrets.CODELENS_URL }}
          api_key: ${{ secrets.CODELENS_API_KEY }}
          rules: |
            no-circular-dependencies
            max-coupling: 0.6
            no-new-tech-debt: critical
```

### Architecture Gate Rules

Define rules that PRs must pass before merging:

| Rule | Description | Example |
|------|-------------|---------|
| `no-circular-dependencies` | No new circular dependencies introduced | Block if PR creates a new cycle |
| `max-coupling` | Module coupling must stay below threshold | Block if coupling > 0.6 |
| `no-new-tech-debt` | No new critical technical debt | Block if critical flaws increase |
| `no-new-cross-module-deps` | No new dependencies between specific modules | Block if A starts depending on B |
| `cloud-readiness-score` | Cloud readiness must stay above threshold | Block if score drops below 60 |

### Architecture Drift Detection

Compare the current analysis with the previous one to detect drift:

- **New dependencies** — modules that didn't depend on each other before now do
- **New circular dependencies** — cycles that didn't exist before
- **Coupling increase** — modules becoming more entangled
- **New technologies** — languages or frameworks that weren't present before
- **Dead code growth** — percentage of unreachable code increasing

Generate a "drift report" for each PR or periodic analysis:

```
Architecture Drift Report (vs. baseline from 2025-06-01)
========================================================

New Dependencies (3):
  + OrderModule → UserModule (via UserService.getUser() call in OrderProcessor)
  + AuthModule → NotificationModule (via NotificationService.sendOTP())
  + Frontend → new npm package: @tanstack/react-query

Removed Dependencies (1):
  - PaymentModule → LegacyGateway (removed in PR #456)

Coupling Changes:
  UserModule: 0.42 → 0.48 (+0.06) ⚠️ increasing
  OrderModule: 0.35 → 0.31 (-0.04) ✓ improving

New Circular Dependencies (0): ✓ Clean

Technical Debt:
  Critical flaws: 12 → 11 (-1) ✓ improving
  High flaws: 45 → 47 (+2) ⚠️ increasing
```

---

## 4. Mainframe Modernization Support

### Additional Language Support

- COBOL (via tree-sitter-cobol grammar)
- JCL (Job Control Language)
- PL/I
- Natural/ADABAS
- CICS transaction definitions
- IMS message definitions
- DB2 stored procedures

### Modernization Advisor

- Map COBOL programs to potential Java/C# equivalents
- Identify CICS transactions and their modern REST API equivalents
- Map IMS hierarchical data to relational database schemas
- Estimate conversion effort (LOC × complexity factor)
- Identify shared copybooks and their blast radius
- Trace batch job flows (JCL → COBOL program → DB2 tables)

---

## 5. API Endpoints (Phase 6 Additions)

```
// Advisors
GET  /api/v1/advisors/{project}/cloud-readiness
GET  /api/v1/advisors/{project}/db-migration
     ?source=oracle&target=postgresql
GET  /api/v1/advisors/{project}/tech-debt
GET  /api/v1/advisors/{project}/green
GET  /api/v1/advisors/{project}/open-source-risk

// Portfolio
GET  /api/v1/portfolio/dashboard
GET  /api/v1/portfolio/dependencies
GET  /api/v1/portfolio/metrics
GET  /api/v1/portfolio/compare?apps=app1,app2,app3

// CI/CD
POST /api/v1/ci/analyze
     {project_id, commit_sha, branch}
POST /api/v1/ci/gate-check
     {project_id, rules[]}
GET  /api/v1/ci/drift-report
     ?project_id=...&baseline=...&current=...

// Architecture Rules
POST /api/v1/projects/{id}/rules
     {name, type, config}
GET  /api/v1/projects/{id}/rules
GET  /api/v1/projects/{id}/rules/evaluate
```

---

## 6. Deliverables Checklist

- [ ] Cloud Readiness Advisor
- [ ] Database Migration Advisor
- [ ] Technical Debt Advisor (ISO 5055 alignment)
- [ ] Green / Sustainability Advisor
- [ ] Open Source Risk Advisor
- [ ] Portfolio dashboard with multi-app overview
- [ ] Cross-application dependency visualization
- [ ] Portfolio-level metrics and comparison
- [ ] GitHub Actions integration (analyze action + gate action)
- [ ] GitLab CI integration
- [ ] Architecture gate rules engine
- [ ] Architecture drift detection and reporting
- [ ] Drift comparison API
- [ ] COBOL/JCL/PL-I language support (if targeting mainframe market)
- [ ] Mainframe Modernization Advisor

---

## 7. Success Criteria

Phase 6 is complete when:

1. Cloud Readiness Advisor produces accurate assessments matching manual expert review
2. Database Migration Advisor correctly identifies > 95% of vendor-specific SQL patterns
3. CI/CD integration blocks PRs that violate defined architecture rules
4. Architecture drift reports accurately capture changes between analysis runs
5. Portfolio dashboard provides useful overview across 5+ analyzed applications