# Phase 5a — AI-Powered Pull Request Impact Analysis

**Timeline:** First milestone of Phase 5 (AI Integration)
**Goal:** When a PR is created, automatically analyze its blast radius against the existing architecture graph, detect drift, and generate an AI-powered impact summary
**Depends On:** Phases 1-4a (graph in Neo4j, impact analysis queries, JWT auth)
**Last Updated:** 2026-03-13

---

## Overview

Phase 5a is the first milestone of Phase 5 (AI Integration). It introduces the first AI-powered feature in CodeLens: automatic pull request impact analysis.

When a developer creates or updates a pull request on GitHub, GitLab, or Bitbucket, CodeLens captures the event via webhook, fetches the diff, maps changed files and lines to nodes in the existing architecture graph, computes upstream and downstream blast radius using the Phase 3 Cypher queries, detects architectural drift, and generates a natural-language AI summary via Claude Sonnet.

Results are surfaced exclusively in the CodeLens UI — a new "Pull Requests" dashboard within each project. No comments are posted back to the Git platform.

**Why Phase 5a and not Phase 6 (CI/CD)?** Phase 6's CI/CD integration is about architecture gate rules that block merges. Phase 5a is about _understanding_ — giving the team visibility into what a PR touches before they review it. It's a read-only, informational feature powered by AI, which makes it a natural entry point for Phase 5.

---

## What CodeLens Does Differently

Most AI code review tools (CodeRabbit, GitHub Copilot Review, Qodo) analyze the **diff in isolation** — they see changed lines but don't understand how those changes ripple through the architecture. CodeLens already has a **semantically rich, type-resolved dependency graph** in Neo4j with symbol-level nodes (functions, classes, tables, endpoints), cross-tech linking (API calls, message queues, shared DB tables), and pre-computed community/centrality metrics.

This means CodeLens can answer questions no diff-based tool can:

- "This PR changes `OrderService.createOrder()` — that function has a fan-in of 12 and is called by 3 API endpoints, a Kafka consumer, and a scheduled job. Blast radius: 47 nodes across 4 layers."
- "This PR introduces a new dependency from the `shipping` module to the `billing` module. That dependency didn't exist before — it crosses a module boundary."
- "The changed function sits on the critical path of the `POST /api/orders` transaction. The transaction touches the `orders` and `order_items` tables."

---

## 1. Git Platform Integration

### Provider Pattern

A `GitPlatformClient` abstract base class with concrete implementations per platform. Each implementation handles two responsibilities: (a) parsing inbound webhook payloads, and (b) fetching PR diffs via the platform's REST API.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class GitPlatform(str, Enum):
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"


@dataclass
class PullRequestEvent:
    """Normalized PR event — same structure regardless of Git platform."""
    platform: GitPlatform
    repo_url: str
    pr_number: int
    pr_title: str
    pr_description: str
    author: str
    source_branch: str
    target_branch: str
    action: str               # "opened", "updated", "closed", "merged"
    commit_sha: str
    created_at: str
    raw_payload: dict = field(default_factory=dict)


@dataclass
class FileDiff:
    """A single file's diff within a PR."""
    path: str
    status: str               # "added", "modified", "deleted", "renamed"
    old_path: str | None       # For renames
    additions: int
    deletions: int
    hunks: list["DiffHunk"]    # Line-level changes


@dataclass
class DiffHunk:
    """A contiguous block of changes within a file."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int


@dataclass
class PRDiff:
    """Full diff for a pull request."""
    files: list[FileDiff]
    total_additions: int
    total_deletions: int
    total_files_changed: int


class GitPlatformClient(ABC):
    """Abstract client for Git platform interactions."""

    @abstractmethod
    def parse_webhook(self, headers: dict, body: bytes) -> PullRequestEvent | None:
        """Parse a raw webhook payload into a normalized PullRequestEvent.
        Returns None if the event is not a PR event we care about."""
        ...

    @abstractmethod
    def verify_webhook_signature(self, headers: dict, body: bytes, secret: str) -> bool:
        """Verify the webhook signature for security."""
        ...

    @abstractmethod
    async def fetch_diff(self, repo_url: str, pr_number: int, token: str) -> PRDiff:
        """Fetch the file-level diff for a PR via the platform API."""
        ...

    @abstractmethod
    async def fetch_changed_file_content(
        self, repo_url: str, commit_sha: str, file_path: str, token: str
    ) -> str | None:
        """Fetch a single file's content at a specific commit (for context)."""
        ...
```

### Platform Implementations

**GitHub:**
- Webhook: `X-GitHub-Event: pull_request`, signature via `X-Hub-Signature-256` (HMAC-SHA256)
- Diff API: `GET /repos/{owner}/{repo}/pulls/{pr_number}/files` — returns `filename`, `status`, `additions`, `deletions`, `patch`
- Patch parsing: GitHub returns unified diff in the `patch` field — parse hunk headers (`@@ -start,count +start,count @@`)

**GitLab:**
- Webhook: `X-Gitlab-Event: Merge Request Hook`, signature via `X-Gitlab-Token` (shared secret)
- Diff API: `GET /api/v4/projects/{id}/merge_requests/{mr_iid}/changes` — returns `changes[]` with `old_path`, `new_path`, `diff`
- Note: GitLab calls them "Merge Requests" — normalize to "Pull Request" in the CodeLens model

**Bitbucket:**
- Webhook: `X-Event-Key: pullrequest:created` / `pullrequest:updated`, signature via HMAC-SHA256
- Diff API: `GET /2.0/repositories/{workspace}/{repo}/pullrequests/{id}/diffstat` for file list, `GET .../diff` for patch content
- Note: Bitbucket's diff API is paginated — handle pagination

### Webhook Receiver Endpoints

```
POST /api/v1/webhooks/github/{project_id}      → GitHub webhook receiver
POST /api/v1/webhooks/gitlab/{project_id}       → GitLab webhook receiver
POST /api/v1/webhooks/bitbucket/{project_id}    → Bitbucket webhook receiver
```

These endpoints are **unauthenticated** (webhooks can't carry JWT tokens) but protected by webhook signature verification. The `project_id` in the URL maps the incoming event to a CodeLens project.

### Project Git Configuration

Stored in the existing `projects` table or a new `project_git_config` table:

```sql
CREATE TABLE project_git_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    platform VARCHAR(20) NOT NULL,          -- 'github', 'gitlab', 'bitbucket'
    repo_url VARCHAR(500) NOT NULL,         -- 'https://github.com/org/repo'
    api_token_encrypted TEXT NOT NULL,       -- Encrypted PAT or app token
    webhook_secret VARCHAR(255) NOT NULL,    -- For signature verification
    monitored_branches TEXT[] DEFAULT '{main,master,develop}',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    UNIQUE(project_id)
);
```

### Configuration UI Flow

1. User goes to Project Settings → "Git Integration" tab
2. Selects platform (GitHub / GitLab / Bitbucket)
3. Enters repo URL and API access token (PAT with repo/read scope)
4. CodeLens generates a unique webhook URL + webhook secret
5. User copies the webhook URL and secret, adds them in their Git platform's webhook settings
6. CodeLens displays "Waiting for first event..." until a webhook arrives
7. Optional: user configures which target branches to monitor (default: main, master, develop)

---

## 2. Diff-to-Graph Mapping

This is the core innovation — mapping a file-level diff to architecture graph nodes.

### How It Works

Every node in the Neo4j graph has `path`, `line`, and `end_line` properties (populated during the tree-sitter + SCIP analysis). When a PR changes lines 45-60 in `src/main/java/com/app/OrderService.java`, we query Neo4j for all nodes whose file path matches and whose line range overlaps with the changed lines.

### Cypher Query — Map Diff to Graph Nodes

```cypher
// For each changed file + hunk, find overlapping graph nodes
UNWIND $changedFiles AS cf
UNWIND cf.hunks AS hunk
MATCH (n)
WHERE n.path = cf.path
  AND n.line IS NOT NULL
  AND n.end_line IS NOT NULL
  AND n.line <= hunk.new_end
  AND n.end_line >= hunk.new_start
  AND labels(n)[0] IN ['Class', 'Function', 'Interface', 'Field', 'APIEndpoint']
RETURN DISTINCT n.fqn AS fqn,
       n.name AS name,
       labels(n)[0] AS type,
       n.path AS path,
       n.line AS line,
       n.end_line AS end_line,
       n.language AS language,
       cf.status AS change_type
```

Parameters:
- `$changedFiles`: list of `{path, status, hunks: [{new_start, new_end}]}`

### Handling Edge Cases

**File renamed:** If `status = "renamed"`, search for nodes matching the `old_path` (since the graph reflects the last full analysis, before the rename).

**File deleted:** If `status = "deleted"`, all nodes in that file are "affected" — mark them with a special flag.

**File added:** New files won't exist in the graph (it reflects the pre-PR state). Flag these as "new code — not yet in architecture graph" and include them in the summary without impact analysis.

**No matching nodes:** Some files have no graph nodes (e.g., config files, README, tests). Report these as "non-graph changes" in the summary — useful context but no blast radius to compute.

### Neo4j Index for Path Lookup

Add a new index to support efficient path-based queries:

```cypher
CREATE INDEX idx_class_path FOR (n:Class) ON (n.path)
CREATE INDEX idx_function_path FOR (n:Function) ON (n.path)
CREATE INDEX idx_interface_path FOR (n:Interface) ON (n.path)
```

---

## 3. Impact Computation

Reuses the Phase 3 impact analysis queries exactly. For each changed graph node, run upstream and downstream traversals, then aggregate.

### Per-Node Impact

For each `changed_node_fqn`, run the existing queries:

```cypher
// Downstream: what does this node affect?
MATCH path = (start {fqn: $fqn})-[:CALLS|INJECTS|PRODUCES|WRITES*1..5]->(affected)
WITH affected, min(length(path)) AS depth
RETURN affected.fqn AS fqn, affected.name AS name,
       labels(affected)[0] AS type, affected.path AS file, depth

// Upstream: what depends on this node?
MATCH path = (dependent)-[:CALLS|INJECTS|CONSUMES|READS*1..5]->(start {fqn: $fqn})
WITH dependent, min(length(path)) AS depth
RETURN dependent.fqn AS fqn, dependent.name AS name,
       labels(dependent)[0] AS type, dependent.path AS file, depth
```

### Aggregated Impact

After running impact for all changed nodes, merge and deduplicate:

```python
@dataclass
class AggregatedImpact:
    """Combined impact across all changed nodes in a PR."""
    changed_nodes: list[ChangedNode]         # Directly modified by the PR
    downstream_affected: list[AffectedNode]  # What the changes affect
    upstream_dependents: list[AffectedNode]  # What depends on the changes
    total_blast_radius: int                  # Unique affected nodes (deduped)
    by_type: dict[str, int]                  # {"Function": 12, "Class": 5, ...}
    by_depth: dict[int, int]                 # {1: 5, 2: 8, 3: 4, ...}
    by_layer: dict[str, int]                 # {"Presentation": 3, "Business": 8, ...}
    by_module: dict[str, int]                # {"com.app.orders": 5, ...}
    cross_tech_impacts: list[CrossTechImpact]  # API endpoints, MQ topics, tables
    transactions_affected: list[str]         # Transaction names that include changed nodes
```

### Cross-Tech Impact Detection

Query which API endpoints, message topics, and database tables are in the blast radius:

```cypher
// API endpoints affected
MATCH (start {fqn: $fqn})-[:CALLS|INJECTS*1..5]->(fn:Function)-[:HANDLES]->(ep:APIEndpoint)
RETURN ep.method AS method, ep.path AS path, fn.fqn AS handler_fqn

// Message topics affected
MATCH (start {fqn: $fqn})-[:CALLS*1..5]->(fn:Function)-[:PRODUCES|CONSUMES]->(mt:MessageTopic)
RETURN mt.name AS topic, type(last(relationships(path))) AS direction

// Database tables affected
MATCH (start {fqn: $fqn})-[:CALLS*1..5]->(fn:Function)-[:READS|WRITES]->(t:Table)
RETURN t.name AS table_name, type(last(relationships(path))) AS access_type
```

### Transactions Affected

Check which pre-computed transactions include the changed nodes:

```cypher
UNWIND $changedFqns AS fqn
MATCH (t:Transaction)-[:INCLUDES]->(fn {fqn: fqn})
RETURN DISTINCT t.name AS transaction_name, t.http_method AS method,
       t.url_path AS url, t.node_count AS size
```

---

## 4. Risk Scoring

A simple **High / Medium / Low** classification. No complex numeric formula — just clear thresholds that are easy to explain and tune.

### Risk Factors

| Factor | Description | How It's Measured |
|--------|-------------|-------------------|
| Blast Radius Size | Total unique nodes affected (upstream + downstream) | Count from aggregated impact |
| Hub Node Changed | Whether any changed node has high centrality | PageRank or betweenness from GDS (already computed in Stage 7) |
| Cross-Tech Impact | Whether the blast radius touches API endpoints, MQ topics, or DB tables | Cross-tech impact query results |
| Fan-In | Maximum fan-in (incoming edges) of any changed node | `MATCH ()-[r]->(n {fqn: $fqn}) RETURN count(r)` |
| Layer Span | How many architectural layers the blast radius crosses | `by_layer` count from aggregated impact |

### Classification Logic

```python
def classify_risk(impact: AggregatedImpact) -> str:
    """Classify PR risk as High, Medium, or Low."""
    score = 0

    # Blast radius size
    if impact.total_blast_radius > 50:
        score += 3
    elif impact.total_blast_radius > 20:
        score += 2
    elif impact.total_blast_radius > 5:
        score += 1

    # Hub node changed (top 10% by PageRank)
    if any(n.is_hub for n in impact.changed_nodes):
        score += 3

    # Cross-tech impact
    cross_tech_count = len(impact.cross_tech_impacts)
    if cross_tech_count > 3:
        score += 2
    elif cross_tech_count > 0:
        score += 1

    # Fan-in of changed nodes
    max_fan_in = max((n.fan_in for n in impact.changed_nodes), default=0)
    if max_fan_in > 15:
        score += 2
    elif max_fan_in > 5:
        score += 1

    # Layer span
    if len(impact.by_layer) >= 3:
        score += 1

    # Classify
    if score >= 7:
        return "High"
    elif score >= 3:
        return "Medium"
    else:
        return "Low"
```

Thresholds are configurable per project in the future. For now, hardcode sensible defaults.

---

## 5. Architecture Drift Detection

Lightweight drift detection that adds value without complexity. We detect two things: **new circular dependencies** and **new cross-module dependencies** introduced by the PR.

### How It Works

The PR diff tells us which nodes changed. We check if those changes would create architectural problems by querying the existing graph plus the _implied_ new connections.

**Caveat:** Since we don't re-run the full analysis pipeline for a PR, we can't know the _exact_ new connections a PR introduces. What we can do is flag when:

1. **Changed nodes are in modules that didn't previously depend on each other** — a potential new cross-module dependency
2. **Changed nodes participate in existing circular dependencies** — making the cycle worse
3. **Changed nodes add new files to modules** — potential module boundary violation

### New Cross-Module Dependencies

For each changed node, check if the node's module has new imports or dependencies that didn't exist before:

```cypher
// Find modules of changed nodes
UNWIND $changedFqns AS fqn
MATCH (m:Module)-[:CONTAINS*1..3]->(n {fqn: fqn})
RETURN DISTINCT m.fqn AS module_fqn, m.name AS module_name, collect(fqn) AS changed_nodes_in_module
```

Then, for the changed files, check if any new import statements reference modules that the current module doesn't already depend on. This is a heuristic based on file paths — if a changed file in `com.app.orders` now imports from `com.app.billing`, and there's no existing `IMPORTS` or `DEPENDS_ON` edge between those modules, that's a potential new cross-module dependency.

### Existing Circular Dependencies Affected

```cypher
// Check if changed nodes participate in known cycles
UNWIND $changedFqns AS fqn
MATCH (n {fqn: fqn})<-[:CONTAINS*1..3]-(m:Module)
MATCH cyclePath = (m)-[:IMPORTS|DEPENDS_ON*2..6]->(m)
RETURN DISTINCT [node IN nodes(cyclePath) | node.name] AS cycle
```

### Drift Report

```python
@dataclass
class DriftReport:
    """Architecture drift detected in a PR."""
    potential_new_module_deps: list[ModuleDependency]  # Module A → Module B (new)
    circular_deps_affected: list[list[str]]            # Cycles that include changed modules
    new_files_outside_modules: list[str]               # Files added outside known module boundaries
    has_drift: bool                                     # True if any drift detected
```

---

## 6. AI Summary Generation

The first use of the Claude API in CodeLens. A single Claude Sonnet call that takes structured impact data and produces a natural-language summary.

### Implementation

```python
import anthropic
import json


SUMMARY_SYSTEM_PROMPT = """You are an expert software architect analyzing a pull request's impact on an application's architecture.

You will receive structured data about:
- The changed graph nodes (functions, classes, endpoints modified by the PR)
- The blast radius (upstream and downstream affected nodes)
- Cross-technology impacts (API endpoints, message queues, database tables)
- Affected transactions (end-to-end flows)
- Risk classification and factors
- Architecture drift signals

Generate a concise, actionable impact summary. Structure it as:
1. **One-sentence verdict** — What is the overall risk and scope of this PR?
2. **Key impacts** (2-4 bullets) — The most important things a reviewer should know
3. **Cross-tech concerns** — If the PR affects APIs, message queues, or DB tables that other systems depend on
4. **Architecture drift** — If the PR introduces new module dependencies or touches circular dependencies
5. **Recommendation** — One sentence on what the reviewer should focus on

Be specific — use actual class names, function names, and module names from the data.
Keep it under 300 words. Developers are busy."""


async def generate_pr_summary(
    pr_event: PullRequestEvent,
    impact: AggregatedImpact,
    drift: DriftReport,
    risk_level: str,
) -> str:
    """Generate AI summary for a PR using Claude Sonnet."""
    client = anthropic.AsyncAnthropic()

    context = {
        "pr_title": pr_event.pr_title,
        "pr_description": pr_event.pr_description[:500],
        "author": pr_event.author,
        "source_branch": pr_event.source_branch,
        "target_branch": pr_event.target_branch,
        "risk_level": risk_level,
        "changed_nodes": [
            {"fqn": n.fqn, "type": n.type, "name": n.name}
            for n in impact.changed_nodes[:20]
        ],
        "blast_radius": {
            "total": impact.total_blast_radius,
            "by_type": impact.by_type,
            "by_layer": impact.by_layer,
            "by_depth": impact.by_depth,
        },
        "cross_tech": [
            {"kind": ct.kind, "name": ct.name, "detail": ct.detail}
            for ct in impact.cross_tech_impacts[:10]
        ],
        "transactions_affected": impact.transactions_affected[:10],
        "drift": {
            "new_module_deps": [
                {"from": d.from_module, "to": d.to_module}
                for d in drift.potential_new_module_deps
            ],
            "circular_deps": drift.circular_deps_affected,
            "has_drift": drift.has_drift,
        },
    }

    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": json.dumps(context, indent=2)}
        ],
    )

    return response.content[0].text
```

### Caching

Cache AI summaries in PostgreSQL. Invalidate when the PR is updated (new commits pushed) or when the project is re-analyzed.

```sql
-- Stored in the pr_analyses table (see section 7), no separate cache table needed.
-- The ai_summary column holds the cached summary.
-- On PR update: re-run analysis, overwrite summary.
-- On project re-analysis: mark all PR analyses as "stale" (graph_version mismatch).
```

### Cost Control

- Use **Claude Sonnet** (not Opus) — fast, cheap, sufficient for structured-data-to-prose
- Cap context at ~2K tokens (truncate node lists, limit to top 20 changed nodes, top 10 cross-tech impacts)
- One API call per PR analysis run — no tool-use loop
- Store the summary — don't regenerate if the PR hasn't changed
- Track token usage in the activity log for admin visibility

---

## 7. Database Schema

### PR Analysis Records

```sql
CREATE TABLE pr_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- PR metadata (from webhook)
    platform VARCHAR(20) NOT NULL,
    pr_number INTEGER NOT NULL,
    pr_title VARCHAR(500) NOT NULL,
    pr_description TEXT,
    pr_author VARCHAR(200) NOT NULL,
    source_branch VARCHAR(200) NOT NULL,
    target_branch VARCHAR(200) NOT NULL,
    commit_sha VARCHAR(64) NOT NULL,
    pr_url VARCHAR(500),

    -- Analysis results
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, analyzing, completed, failed, stale
    risk_level VARCHAR(10),                          -- High, Medium, Low
    changed_node_count INTEGER,
    blast_radius_total INTEGER,
    impact_summary JSONB,                            -- Full AggregatedImpact as JSON
    drift_report JSONB,                              -- DriftReport as JSON
    ai_summary TEXT,                                 -- Claude-generated summary

    -- Diff metadata
    files_changed INTEGER,
    additions INTEGER,
    deletions INTEGER,

    -- Graph version tracking
    graph_analysis_run_id UUID REFERENCES analysis_runs(id),  -- Which analysis run this was computed against

    -- Timing
    analysis_duration_ms INTEGER,
    ai_summary_tokens INTEGER,                       -- Token usage for cost tracking
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),

    -- Unique constraint: one analysis per PR per commit
    UNIQUE(project_id, pr_number, commit_sha)
);

CREATE INDEX idx_pr_project ON pr_analyses(project_id, created_at DESC);
CREATE INDEX idx_pr_status ON pr_analyses(project_id, status);
CREATE INDEX idx_pr_risk ON pr_analyses(project_id, risk_level);
```

### Activity Log Entries

New action types for the existing `activity_log` table:

- `pr_analysis.started` — PR event received, analysis queued
- `pr_analysis.completed` — Analysis finished successfully
- `pr_analysis.failed` — Analysis failed (with error details)

---

## 8. API Endpoints

```
# Webhook receivers (unauthenticated, signature-verified)
POST /api/v1/webhooks/github/{project_id}
POST /api/v1/webhooks/gitlab/{project_id}
POST /api/v1/webhooks/bitbucket/{project_id}

# PR Analysis (authenticated, JWT required)
GET  /api/v1/projects/{project_id}/pull-requests
     ?status=completed&risk=High&limit=20&offset=0
     → Paginated list of PR analyses

GET  /api/v1/projects/{project_id}/pull-requests/{pr_analysis_id}
     → Full PR analysis detail (impact, drift, AI summary)

GET  /api/v1/projects/{project_id}/pull-requests/{pr_analysis_id}/impact
     → Detailed impact data (changed nodes, blast radius, cross-tech)

GET  /api/v1/projects/{project_id}/pull-requests/{pr_analysis_id}/drift
     → Drift report for this PR

POST /api/v1/projects/{project_id}/pull-requests/{pr_analysis_id}/reanalyze
     → Re-run analysis (e.g., after a new full project analysis)

# Git integration configuration (admin only)
POST /api/v1/projects/{project_id}/git-config
     → Configure Git platform, repo URL, token, webhook secret
GET  /api/v1/projects/{project_id}/git-config
     → Get current config (token masked)
PUT  /api/v1/projects/{project_id}/git-config
     → Update config
DELETE /api/v1/projects/{project_id}/git-config
     → Remove Git integration

# Webhook management
GET  /api/v1/projects/{project_id}/git-config/webhook-url
     → Get the webhook URL + secret for copy-paste setup
POST /api/v1/projects/{project_id}/git-config/test
     → Test the API token connectivity (verify we can reach the repo)
```

---

## 9. Analysis Pipeline

### Flow

```
Webhook arrives
    ↓
Signature verification
    ↓
Parse & normalize to PullRequestEvent
    ↓
Look up project by project_id in URL
    ↓
Check: is this a PR event for a monitored branch? If not, ignore.
    ↓
Create pr_analyses record (status: "pending")
    ↓
Queue background task: run_pr_analysis(pr_analysis_id)
    ↓
Background task:
    1. Fetch diff via Git platform API
    2. Map diff to graph nodes (Cypher query)
    3. Run impact analysis per changed node (reuse Phase 3 queries)
    4. Aggregate impact across all changed nodes
    5. Run drift detection queries
    6. Compute risk level
    7. Generate AI summary (Claude Sonnet API call)
    8. Store results in pr_analyses table
    9. Log to activity_log
    ↓
Status: "completed" (or "failed" with error)
```

### Execution Model

Same as the main analysis pipeline — `BackgroundTasks` from FastAPI. PR analysis is much lighter than a full 9-stage pipeline run (no tree-sitter, no SCIP, no Neo4j writes). A typical PR analysis should complete in **5-15 seconds** including the Claude API call.

### Stale Graph Handling

When a project is re-analyzed (full pipeline run), all existing PR analyses for that project are marked as `status: "stale"`. The UI shows a banner: "This analysis was computed against an older version of the architecture graph. Click to re-analyze."

The `graph_analysis_run_id` column tracks which analysis run each PR analysis was computed against, enabling this staleness detection.

---

## 10. File Structure

```
cast-clone-backend/
├── app/
│   ├── api/
│   │   ├── webhooks.py              # CREATE — Webhook receiver endpoints
│   │   ├── pull_requests.py         # CREATE — PR analysis CRUD endpoints
│   │   └── git_config.py            # CREATE — Git integration config endpoints
│   ├── schemas/
│   │   ├── webhooks.py              # CREATE — Webhook payload models
│   │   ├── pull_requests.py         # CREATE — PR analysis request/response models
│   │   └── git_config.py            # CREATE — Git config request/response models
│   ├── git/
│   │   ├── __init__.py              # CREATE
│   │   ├── base.py                  # CREATE — GitPlatformClient ABC, shared models
│   │   ├── github.py                # CREATE — GitHub webhook parser + API client
│   │   ├── gitlab.py                # CREATE — GitLab webhook parser + API client
│   │   ├── bitbucket.py             # CREATE — Bitbucket webhook parser + API client
│   │   └── diff_parser.py           # CREATE — Unified diff → DiffHunk parser
│   ├── pr_analysis/
│   │   ├── __init__.py              # CREATE
│   │   ├── analyzer.py              # CREATE — Main PR analysis orchestrator
│   │   ├── diff_mapper.py           # CREATE — Map diffs to graph nodes (Neo4j queries)
│   │   ├── impact_aggregator.py     # CREATE — Aggregate per-node impacts
│   │   ├── risk_scorer.py           # CREATE — Risk classification logic
│   │   ├── drift_detector.py        # CREATE — Circular dep + module dep drift checks
│   │   └── ai_summary.py            # CREATE — Claude Sonnet summary generation
│   └── models/
│       └── db.py                    # MODIFY — Add PrAnalysis, ProjectGitConfig models
├── tests/
│   └── unit/
│       ├── test_webhook_parsing.py  # CREATE — Per-platform webhook parsing tests
│       ├── test_diff_mapper.py      # CREATE — Diff-to-graph mapping tests
│       ├── test_risk_scorer.py      # CREATE — Risk classification tests
│       ├── test_drift_detector.py   # CREATE — Drift detection tests
│       └── test_ai_summary.py       # CREATE — AI summary generation tests (mocked)
```

---

## 11. Frontend — PR Dashboard

### Navigation

Add "Pull Requests" as a new item in the project sidebar navigation, below "Impact Analysis" and above "Settings."

### PR List View (`/projects/{id}/pull-requests`)

A table/card view showing all captured PRs:

| Column | Content |
|--------|---------|
| PR # | PR number + title (clickable → detail view) |
| Author | PR author name |
| Branch | `source → target` branch |
| Risk | Badge: 🔴 High, 🟡 Medium, 🟢 Low |
| Blast Radius | "47 nodes affected" |
| Changed Nodes | "5 functions, 2 classes" |
| Status | Analyzing / Completed / Stale / Failed |
| Time | "3 minutes ago" |

Filters: by risk level, by status, by branch. Sort by: created date, risk level, blast radius size.

### PR Detail View (`/projects/{id}/pull-requests/{analysis_id}`)

**Header section:**
- PR title, number, author, branches, commit SHA
- Risk level badge (prominent)
- "Re-analyze" button (if stale)
- Link to PR on the Git platform (opens in new tab)

**AI Summary card:**
- Claude-generated natural language summary
- Rendered as formatted text (markdown → HTML)
- "Regenerate" button to re-run AI summary

**Statistics row (cards):**
- Changed Nodes: count + type breakdown
- Blast Radius: total affected nodes
- Layers Affected: count + names
- Transactions Affected: count

**Changed Nodes table:**
- FQN, name, type, file path, line range
- Each row clickable → navigates to the node in the architecture graph view
- Change type indicator: modified / deleted / renamed

**Impact Visualization:**
- Reuse the existing Cytoscape graph view with the Phase 3 impact overlay
- Pre-select all changed nodes as the "impact source"
- Color by depth: red (depth 1) → orange (depth 2) → yellow (depth 3+)
- Changed nodes highlighted with a distinct border/icon
- Unaffected nodes dimmed

**Cross-Tech Impact panel:**
- API Endpoints affected (method + path)
- Message Topics affected (name + produce/consume)
- Database Tables affected (name + read/write)
- Each item clickable → navigate to that node in the graph

**Drift Alerts panel (only shown if drift detected):**
- "⚠️ Potential new dependency: `orders` module → `billing` module"
- "⚠️ Changed code participates in circular dependency: `A → B → C → A`"
- Clear, actionable descriptions

---

## 12. Dependencies

### Python Packages (add to pyproject.toml)

```toml
# Phase 5a additions
"httpx>=0.27",              # Already in dev deps — move to main for Git API calls
"anthropic>=0.40",          # Claude API client
"cryptography>=44.0",       # For encrypting/decrypting API tokens at rest
```

### Environment Variables

```bash
# Claude API (required for AI summaries)
ANTHROPIC_API_KEY=sk-ant-...

# Encryption key for API tokens stored in DB
TOKEN_ENCRYPTION_KEY=...     # Generated by setup script, Fernet key
```

---

## 13. What's Explicitly Deferred

| Feature | Deferred To | Why |
|---------|------------|-----|
| Post PR comments back to Git platform | Phase 6 (CI/CD) | Requires GitHub App / GitLab bot setup, more complex auth |
| GitHub Check Runs / status checks | Phase 6 (CI/CD) | Requires GitHub App, not just webhook + PAT |
| Architecture gate rules (block merge) | Phase 6 (CI/CD) | Requires posting back + CI integration |
| Full re-analysis per PR (run 9-stage pipeline on PR branch) | Phase 6 | Too slow, too heavy — graph-based analysis is sufficient |
| Azure DevOps support | Phase 6 | Lower priority platform, enterprise-focused |
| PR comparison (compare two PRs) | Later | Nice-to-have, not MVP |
| PR trend analytics (risk over time) | Phase 6 | Needs historical data accumulation |
| Slack/Teams notifications for high-risk PRs | Phase 6 | Notification system is a separate concern |
| Tool-use loop for AI summary (Claude calls graph tools) | Phase 5b | Single API call is sufficient for summaries |

---

## 14. Deliverables Checklist

### Git Platform Integration
- [ ] `GitPlatformClient` ABC with shared models (`PullRequestEvent`, `PRDiff`, `FileDiff`, `DiffHunk`)
- [ ] GitHub implementation (webhook parser + diff API client)
- [ ] GitLab implementation (webhook parser + diff API client)
- [ ] Bitbucket implementation (webhook parser + diff API client)
- [ ] Webhook signature verification per platform
- [ ] Webhook receiver endpoints (3 routes)
- [ ] Project Git configuration CRUD (API + DB)
- [ ] API token encryption at rest

### PR Analysis Engine
- [ ] Diff-to-graph mapping (Neo4j path/line range queries)
- [ ] Per-node impact computation (reuse Phase 3 Cypher queries)
- [ ] Impact aggregation across all changed nodes
- [ ] Cross-tech impact detection (API endpoints, MQ topics, DB tables)
- [ ] Transaction impact detection
- [ ] Risk classification (High / Medium / Low)
- [ ] Drift detection: new cross-module dependencies
- [ ] Drift detection: circular dependency involvement
- [ ] AI summary generation (Claude Sonnet)
- [ ] Background task orchestration
- [ ] Stale analysis detection (graph version tracking)

### API Endpoints
- [ ] PR analysis list endpoint (paginated, filterable)
- [ ] PR analysis detail endpoint
- [ ] PR impact detail endpoint
- [ ] PR drift report endpoint
- [ ] PR re-analyze endpoint
- [ ] Git config CRUD endpoints
- [ ] Webhook URL generation endpoint
- [ ] Git connectivity test endpoint

### Database
- [ ] `project_git_config` table + model
- [ ] `pr_analyses` table + model
- [ ] Neo4j path indexes for efficient diff mapping
- [ ] Activity log integration

### Frontend
- [ ] Git Integration setup page in Project Settings
- [ ] PR List view (table with filters and sorting)
- [ ] PR Detail view with AI summary card
- [ ] PR statistics cards (changed nodes, blast radius, layers, transactions)
- [ ] Changed nodes table (clickable → graph navigation)
- [ ] Impact visualization (Cytoscape overlay, reuse Phase 3)
- [ ] Cross-tech impact panel
- [ ] Drift alerts panel
- [ ] Stale analysis banner + re-analyze button
- [ ] PR risk level badges

### Testing
- [ ] Webhook parsing tests (per platform, including edge cases)
- [ ] Webhook signature verification tests
- [ ] Diff-to-graph mapping tests (with various change types)
- [ ] Risk classification tests (boundary conditions)
- [ ] Drift detection tests
- [ ] AI summary tests (mocked Claude API)
- [ ] Integration test: webhook → analysis → stored results

---

## 15. Success Criteria

Phase 5a is complete when:

1. A PR created on GitHub/GitLab/Bitbucket triggers an analysis within 5 seconds of webhook receipt
2. The diff-to-graph mapping correctly identifies >90% of changed graph nodes (validated manually on test PRs)
3. Blast radius computation completes within 10 seconds for a typical PR (< 20 changed files)
4. AI summary accurately reflects the impact data (no hallucinated node names or relationships)
5. Risk classification matches manual expert assessment on 5+ test PRs
6. Drift detection correctly flags new cross-module dependencies on test PRs that introduce them
7. The PR dashboard loads within 2 seconds and displays all analysis data
8. End-to-end latency from webhook receipt to completed analysis is under 30 seconds
9. Stale analyses are correctly detected after a full project re-analysis