# PR Review — Architecture-Aware Pull Request Analysis

**Date:** 2026-04-27
**Status:** Draft
**Owner:** Backend + Frontend
**Phase target:** 5a (Collaboration & Integration)
**Related docs:** `00-PROJECT-OVERVIEW.md`, `03-PHASE-3-IMPACT-ANALYSIS.md`, `09-NEO4J-SCHEMA.md`

---

## 1. Summary

When a pull request is opened or updated against a configured branch, CAST Clone analyzes the diff against its architecture graph and produces an impact report: which graph nodes change, what the blast radius is, whether the PR introduces architectural drift, and a risk classification. Results are stored, surfaced in the dashboard, and posted back to the PR as a Markdown comment.

This is **not** a generic AI code reviewer. It is the architecture-graph product applied to a diff.

---

## 2. Goals

- Detect what graph nodes a PR changes and what depends on them (downstream blast radius) and what they depend on (upstream).
- Surface architectural drift: new cross-module dependencies, new circular dependencies, files added outside known modules.
- Classify each PR as `low | medium | high` risk based on objective graph signals.
- Produce a human-readable summary (Markdown) suitable for posting on the PR.
- Support GitHub at v1; provider abstraction so GitLab / Bitbucket / Gitea can be added without rewrites.
- Keep cost predictable: a typical PR analysis must complete in under 5 minutes and cost under $0.50 in AI tokens.

## 3. Non-Goals (v1)

- Line-level code review (style, bugs, security on diff lines). Out of scope.
- Blocking status checks (PR cannot merge until green). Advisory-only in v1.
- Automatic fix suggestions or code edits.
- Repos without a prior baseline analysis — PR analysis requires the target branch to already be analyzed.
- Mono-PR splitting / partial commit analysis.

---

## 4. User Journey

1. Admin connects a Git provider (GitHub) via the existing **Connectors** flow — OAuth or PAT, encrypted at rest.
2. Admin imports a repository and enables **PR Review** for one or more monitored branches (e.g., `main`, `develop`).
3. CAST registers a webhook on the repo (auto-register via API, or copy/paste setup if the token lacks scope).
4. A developer opens a PR targeting `main`. GitHub fires `pull_request.opened`.
5. CAST receives the webhook, verifies HMAC, ensures both `main` and the source branch have a fresh architecture graph (re-runs the pipeline if commits are stale), then runs PR analysis.
6. While analysis runs, the PR shows a "CAST Clone — analyzing…" comment.
7. On completion, the comment is updated with the impact report. The dashboard's `/repositories/{id}/pull-requests` list updates.
8. A reviewer can click into the PR detail page to see changed nodes, drift alerts, cross-tech impact, and a "View in graph" link that highlights affected nodes.

---

## 5. Architecture

```
            ┌─────────────────────────────┐
            │  Git platform (GitHub etc.) │
            └────────┬─────────┬──────────┘
        webhook POST │         │ REST: fetch diff, post comment
                     ▼         ▲
        ┌────────────────────────────────────┐
        │ FastAPI: /api/v1/webhooks/{pf}/{r} │  (HMAC verify, dedup, enqueue)
        └────────────────────────┬───────────┘
                                 │
                                 ▼
        ┌────────────────────────────────────┐
        │ PR analysis orchestrator           │
        │  1. ensure_branch_analyzed(target) │
        │  2. ensure_branch_analyzed(source) │
        │  3. fetch_diff()                   │
        │  4. map_diff_to_graph()            │
        │  5. aggregate_impact()  (Cypher)   │
        │  6. detect_drift()      (Cypher)   │
        │  7. classify_risk()                │
        │  8. ai_summarize()      (Bedrock)  │
        │  9. persist + post_comment()       │
        └────────────────────────┬───────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
        ┌──────────┐      ┌──────────┐       ┌──────────┐
        │ Postgres │      │  Neo4j   │       │ Frontend │
        │ pr_analy │      │ (graph)  │       │ /pull-…  │
        └──────────┘      └──────────┘       └──────────┘
```

The analysis pipeline reuses the existing 11-stage indexer (`app/orchestrator/pipeline.py`) for the graph build of each branch. PR-specific work is a new module `app/pr_analysis/` that runs after both graphs are ready.

---

## 6. Data Model

### 6.1 Postgres — new tables

```python
# app/models/db.py (additions)

class PrAnalysis(Base):
    __tablename__ = "pr_analyses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str]                      # github | gitlab | bitbucket | gitea
    pr_number: Mapped[int]
    pr_title: Mapped[str]
    pr_description: Mapped[str | None]
    pr_author: Mapped[str]
    source_branch: Mapped[str]
    target_branch: Mapped[str]
    commit_sha: Mapped[str]                    # head sha at analysis time
    pr_url: Mapped[str]

    status: Mapped[str]                        # pending | analyzing | completed | failed | stale
    risk_level: Mapped[str | None]             # low | medium | high
    changed_node_count: Mapped[int | None]
    blast_radius_total: Mapped[int | None]
    files_changed: Mapped[int | None]
    additions: Mapped[int | None]
    deletions: Mapped[int | None]

    impact_summary: Mapped[dict | None] = mapped_column(JSONB)
    drift_report: Mapped[dict | None]   = mapped_column(JSONB)
    ai_summary: Mapped[str | None]
    ai_summary_tokens: Mapped[int | None]
    analysis_duration_ms: Mapped[int | None]

    comment_id: Mapped[str | None]             # platform comment ID (for updates)
    comment_url: Mapped[str | None]
    error_message: Mapped[str | None]

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("repository_id", "pr_number", "commit_sha", name="uq_pr_repo_commit"),
    )


class RepositoryGitConfig(Base):
    __tablename__ = "repository_git_configs"

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid_str)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), unique=True)
    platform: Mapped[str]
    repo_url: Mapped[str]
    api_token_encrypted: Mapped[bytes]         # Fernet(SECRET_KEY)
    webhook_secret: Mapped[bytes]              # Fernet
    monitored_branches: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(default=True)
    post_pr_comments: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

Re-uses existing `Project`, `AnalysisRun`, `Repository` models. A `Project` row exists per `(repository_id, branch)`; PR analysis ensures one exists for both source and target before proceeding.

### 6.2 In-memory dataclasses

```python
# app/pr_analysis/models.py

@dataclass
class DiffHunk:
    old_start: int; old_count: int
    new_start: int; new_count: int
    lines: list[str]

@dataclass
class FileDiff:
    path: str
    old_path: str | None       # None = added; != path = renamed
    change_type: Literal["added", "modified", "deleted", "renamed"]
    hunks: list[DiffHunk]
    additions: int
    deletions: int

@dataclass
class PRDiff:
    head_sha: str
    base_sha: str
    files: list[FileDiff]

@dataclass
class ChangedNode:
    fqn: str
    kind: str
    path: str
    change_type: Literal["added", "modified", "deleted"]
    lines_changed: int

@dataclass
class AffectedNode:
    fqn: str
    name: str
    kind: str
    layer: str | None
    depth: int                  # graph distance from a changed node
    direction: Literal["downstream", "upstream"]

@dataclass
class CrossTechImpact:
    edge_kind: str              # HTTP_CALL, MQ_PUBLISH, JDBC_QUERY, ...
    source_fqn: str
    target_fqn: str

@dataclass
class AggregatedImpact:
    changed_nodes: list[ChangedNode]
    affected_nodes: list[AffectedNode]
    by_type: dict[str, int]
    by_depth: dict[int, int]
    by_layer: dict[str, int]
    cross_tech: list[CrossTechImpact]
    transactions_affected: list[str]
    new_files: list[str]
    non_graph_files: list[str]
    blast_radius_total: int

@dataclass
class DriftReport:
    has_drift: bool
    new_module_dependencies: list[tuple[str, str]]
    circular_deps_introduced: list[list[str]]
    new_files_outside_modules: list[str]
```

---

## 7. API Surface

All under `/api/v1/`. Auth via JWT bearer (existing `get_current_user`); webhook endpoint is unauthenticated but HMAC-verified.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/webhooks/{platform}/{repo_id}` | Receive Git provider webhook; HMAC verify; enqueue analysis; return 202. |
| `GET`  | `/repositories/{repo_id}/pull-requests` | List PR analyses; filter by `status`, `risk`; paginated. |
| `GET`  | `/repositories/{repo_id}/pull-requests/{id}` | Full detail. |
| `GET`  | `/repositories/{repo_id}/pull-requests/{id}/impact` | Structured impact (`AggregatedImpact` JSON). |
| `GET`  | `/repositories/{repo_id}/pull-requests/{id}/drift` | Drift report. |
| `POST` | `/repositories/{repo_id}/pull-requests/{id}/reanalyze` | Re-queue; resets status to pending. |
| `DELETE` | `/repositories/{repo_id}/pull-requests/{id}` | Soft-delete record (does not delete PR). |
| `POST` | `/repositories/{repo_id}/git-config` | Create/update git config (token, secret, branches). |
| `GET`  | `/repositories/{repo_id}/git-config/webhook-url` | Returns the webhook URL + secret to paste into platform. |
| `POST` | `/repositories/{repo_id}/git-config/auto-register-webhook` | Calls platform API to register webhook. |

Pydantic response schemas live in `app/schemas/pull_requests.py`. Convention: `*Response` for output, never expose ORM models directly.

---

## 8. Pipeline / Control Flow

### 8.1 Webhook handler (`app/api/webhooks.py`)

```
POST /api/v1/webhooks/github/{repo_id}
  ├─ load RepositoryGitConfig; 404 if missing
  ├─ verify HMAC against config.webhook_secret  → 401 on mismatch
  ├─ parse event via GitPlatformClient.parse_webhook
  │   └─ returns PullRequestEvent | None  (None = ignored event type)
  ├─ if event.target_branch ∉ config.monitored_branches → 200 ignored
  ├─ upsert PrAnalysis row by (repo_id, pr_number, commit_sha)
  │   ├─ if exists & status ∈ {analyzing, completed} → 200 (idempotent)
  │   └─ else create/reset to status=pending
  ├─ enqueue BackgroundTask: _run_pr_analysis(repo_id, pr_analysis_id)
  └─ return 202 {pr_analysis_id}
```

Webhook body size cap: 10 MB. Event types ignored: `ping`, `synchronize` on draft PRs (configurable).

### 8.2 PR analysis orchestrator (`app/pr_analysis/analyzer.py`)

```python
async def run_pr_analysis(repo_id: str, pr_analysis_id: str, services: PipelineServices) -> None:
    """Top-level entry point. Owns lifecycle of pr_analyses row."""
    started = monotonic()
    async with get_background_session() as db:
        pr = await db.get(PrAnalysis, pr_analysis_id)
        pr.status = "analyzing"
        await db.commit()

    try:
        # 1. Ensure both branches have fresh graphs.
        target_project = await ensure_branch_analyzed(repo_id, pr.target_branch, services)
        source_project = await ensure_branch_analyzed(repo_id, pr.source_branch, services)

        # 2. Fetch diff.
        client = create_platform_client(pr.platform, config)
        diff = await client.fetch_diff(pr.pr_url, base_sha=target_project.last_analyzed_commit, head_sha=pr.commit_sha)

        # 3. Map diff to graph nodes (uses source_project's graph).
        mapper = DiffMapper(neo4j_driver, source_project.id)
        changed = await mapper.map(diff)

        # 4. Aggregate impact (BFS over Neo4j, depth ≤ 5).
        impact = await ImpactAggregator(neo4j_driver, source_project.id).aggregate(changed)

        # 5. Detect drift (target vs source).
        drift = await DriftDetector(neo4j_driver, target_project.id, source_project.id).detect(changed, impact)

        # 6. Risk classification (deterministic; no AI).
        risk = classify_risk(impact, drift)

        # 7. AI summary (Bedrock).
        summary = await generate_pr_summary(pr, diff, impact, drift, risk)

        # 8. Persist results.
        await persist_results(db, pr, impact, drift, risk, summary, duration_ms=int((monotonic()-started)*1000))

        # 9. Post comment back to PR.
        if config.post_pr_comments:
            comment = format_pr_comment(pr, impact, drift, risk, summary)
            result = await client.post_comment(pr.pr_url, comment, update_comment_id=pr.comment_id)
            await update_comment_link(db, pr, result)

    except Exception as e:
        await mark_failed(db, pr, str(e))
        log.exception("pr_analysis_failed", pr_id=pr_analysis_id)
```

`ensure_branch_analyzed` is the new helper that looks up `Project` by `(repository_id, branch)`, compares `last_analyzed_commit` with current branch HEAD, and either returns immediately (if fresh) or invokes `run_analysis_pipeline` and waits.

### 8.3 Diff-to-graph mapping (`app/pr_analysis/diff_mapper.py`)

For each `FileDiff`:
- Look up nodes in Neo4j with `path = $path` (or `old_path` for renames/deletes), filter by `project_id`.
- If file maps to nodes, mark each node `change_type` based on hunk overlap: a node whose `[line, end_line]` intersects any hunk's `new_start..new_start+new_count` is `modified`; nodes only present in source = `added`; only in target = `deleted`.
- If file matches no node:
  - extension is parseable code (e.g., `.java`, `.ts`, `.py`) → `new_files`. Listed in the report as additive; impact aggregation cannot expand from these until the next full source-branch reanalysis.
  - extension not parseable (e.g., `.md`, `.json`, `.png`, `.lock`) → `non_graph_files`. Surface in the report (file count, lines) but exclude from blast radius.

### 8.4 Impact aggregation (`app/pr_analysis/impact_aggregator.py`)

Two Cypher queries (downstream + upstream), parameterized by changed FQNs and depth cap (default 5). Sketch — final form determined during M4:

```cypher
// downstream: who depends on the changed node (depth path needed for aggregation)
UNWIND $changed_fqns AS fqn
MATCH (start {fqn: fqn, project_id: $project_id})
MATCH path = (start)-[*1..$depth]->(reached)
WHERE NOT reached:Community
RETURN start.fqn AS source_fqn,
       reached AS node,
       length(path) AS depth,
       last(relationships(path)).kind AS edge_kind
```

Upstream is the same with reversed direction. Aggregations (`by_type`, `by_depth`, `by_layer`) computed in Python from the result set; a node reached by multiple paths is collapsed to the minimum depth. Cross-tech edges identified by `edge.kind ∈ {HTTP_CALL, MQ_PUBLISH, JDBC_QUERY, GRPC_CALL}`. Transactions found by joining affected nodes against `Transaction` nodes via `INVOLVES`.

### 8.5 Drift detection (`app/pr_analysis/drift_detector.py`)

Three signals (each its own Cypher pair, target vs source):
1. **New module dependencies:** modules in source connected by `DEPENDS_ON` that are not connected in target.
2. **Circular dependencies introduced:** strongly-connected components in source's module graph that don't exist in target.
3. **Files outside modules:** new files whose containing directory isn't a module in source.

### 8.6 Risk scoring (`app/pr_analysis/risk_scorer.py`)

Deterministic score function (no AI):

| Signal | Threshold → contribution |
|---|---|
| `blast_radius_total` | `< 10`: 0 · `< 50`: 1 · `< 200`: 2 · `≥ 200`: 3 |
| Hub node touched (fan-in ≥ 20) | per node: 1 (cap 3) |
| Cross-tech edges affected | per edge: 1 (cap 2) |
| Layers spanned | `≤ 1`: 0 · `2`: 1 · `≥ 3`: 2 |
| Drift signals | per signal: 1 (cap 3) |

Total `≥ 6` = high · `3–5` = medium · `≤ 2` = low. Thresholds tunable in `config.py`.

### 8.7 AI summarization (`app/pr_analysis/ai/`)

**Pattern:** supervisor + targeted subagents using Bedrock Claude Sonnet 4.6 (already in `pyproject.toml` as `anthropic[bedrock]`).

- **Triage** (`triage.py`): classify changed files into categories (`code`, `config`, `migration`, `test`, `docs`).
- **Subagents** (`subagents.py`): one per category, each runs an Anthropic agentic loop with bounded tool use over `read_file`, `grep_content`, `query_graph_node`, `get_node_impact`. Hard caps: 10 tool calls per subagent, 50,000 tokens per subagent.
- **Supervisor** (`supervisor.py`): receives subagent JSON reports + structured impact/drift, produces final 5-section Markdown summary: `Overview · Architectural Impact · Risk Assessment · Recommendations · Reviewer Checklist`.

Global budget caps from `config.py`: `PR_ANALYSIS_MAX_SUBAGENTS=15`, `PR_ANALYSIS_MAX_TOTAL_TOKENS=500_000`. Hard timeout: 4 minutes for the whole AI step. If the budget or timeout is hit, fall back to a deterministic-only Markdown summary built from impact/drift fields — analysis still completes.

---

## 9. Frontend

Routes (Next.js App Router, scoped under `/repositories/[repoId]/`):

| Route | Purpose |
|---|---|
| `/pull-requests` | List with filters (`status`, `risk`), paginated |
| `/pull-requests/[id]` | Detail: AI summary, stats, changed nodes, drift alerts, cross-tech, "View in graph" link, "Re-analyze" button |
| `/settings/.../git-config` | Connect/disconnect, monitored branches, `post_pr_comments` toggle, webhook setup modal |

Components under `components/pull-requests/`: `PrListTable`, `PrSummaryCard`, `PrStatsRow`, `PrChangedNodesTable`, `PrCrossTechPanel`, `PrDriftAlerts`, `PrRiskBadge`, `PrStatusBadge`, `WebhookSetupModal`, `GitIntegrationForm`.

Hook: `usePullRequests.ts` — `useRepoPrAnalyses(repoId, filters)` polls every 5s when any row's status is `pending` or `analyzing`; `useRepoPrDetail(repoId, id)` parallel-fetches detail + impact + drift.

Detail page **must** auto-refresh when status is `analyzing`. Stats row uses tile layout already shipped in the codebase. Drift alerts render as amber banners. Risk badge color: `low=emerald`, `medium=amber`, `high=red` (using existing OKLCH design tokens).

---

## 10. Security

- **Webhook auth:** HMAC-SHA256 signature verification per platform. Constant-time comparison. Reject if missing or invalid → 401.
- **Tokens:** API tokens and webhook secrets encrypted with Fernet (key = `SECRET_KEY`). Never logged. Never returned to the frontend (only `webhook_url` is returned, the secret is shown once on creation and cached client-side).
- **Webhook body size cap:** 10 MB. Reject larger payloads with 413.
- **Rate limit on webhook endpoint:** 60/min per repo (Redis token bucket).
- **Tenant isolation:** Every Cypher query filters by `project_id`. The graph store has unique constraint on `(project_id, fqn)` — already in place.
- **AI tool use sandboxing:** subagents' `read_file` and `grep_content` are confined to the cloned repo path (`config.repo_storage_path` rooted). Path traversal rejected.
- **License enforcement:** PR analysis is a write operation; `require_license_writable` dependency must gate the manual reanalyze and git-config endpoints. Webhook ingestion still records (so we don't lose events) but skips the analysis step when license is blocked.

---

## 11. Configuration

New env vars (all in `app/config.py`):

| Var | Default | Purpose |
|---|---|---|
| `PR_ANALYSIS_MODEL` | `us.anthropic.claude-sonnet-4-6` | Bedrock model for subagents |
| `PR_ANALYSIS_SUPERVISOR_MODEL` | `us.anthropic.claude-sonnet-4-6` | Bedrock model for supervisor |
| `PR_ANALYSIS_MAX_SUBAGENTS` | `15` | Fan-out cap |
| `PR_ANALYSIS_MAX_TOTAL_TOKENS` | `500_000` | Token budget per analysis |
| `PR_ANALYSIS_DEPTH_CAP` | `5` | BFS depth for impact aggregation |
| `PR_ANALYSIS_TIMEOUT_SEC` | `240` | Hard timeout for AI step |
| `PR_WEBHOOK_BODY_LIMIT_MB` | `10` | Webhook payload cap |
| `PR_WEBHOOK_RATE_PER_MIN` | `60` | Per-repo webhook rate limit |

---

## 12. Testing Strategy

Following project conventions (`pytest-asyncio` auto mode, `aiosqlite` for unit tests, real Docker services for integration).

**Unit (`tests/unit/`):**
- `test_diff_parser.py` — unified diff parsing edge cases (renames, binary files, empty hunks)
- `test_diff_mapper.py` — node lookup with renames, hunk-line overlap, file-extension routing
- `test_impact_aggregator.py` — Cypher path mocked; aggregation math
- `test_drift_detector.py` — module dep diff, circular SCC, files-outside-modules
- `test_risk_scorer.py` — every threshold boundary
- `test_pr_analyzer.py` — orchestration with mocked stages
- `test_comment_formatter.py` — Markdown rendering, emoji-free, length cap (65k chars)
- `test_webhook_parsing.py` — per-platform fixtures (GitHub, GitLab, Bitbucket, Gitea)
- `test_webhook_signature.py` — HMAC validation positive + negative
- `test_pull_requests_api.py` — list/detail/reanalyze/delete via `app_client`
- `test_ai_triage.py`, `test_ai_subagents.py`, `test_ai_supervisor.py`, `test_ai_tools.py` — mocked Anthropic client

**Integration (`tests/integration/`, marked `@pytest.mark.integration`):**
- `test_pr_analysis_e2e.py` — clone the local `spring-petclinic` fixture, simulate a synthetic PR diff, run `run_pr_analysis`, assert PrAnalysis row populated with non-empty impact/drift, no AI call (use deterministic fallback path).
- `test_webhook_to_completion.py` — POST a fixture webhook payload, wait for `status=completed`.

**Coverage gate:** new modules ≥ 85%.

---

## 13. Milestones

Each milestone ships independently; later ones layer on earlier ones. PR-by-PR review and merge.

| # | Title | Outcome | Cost (rough) |
|---|---|---|---|
| **M1** | DB models + git provider abstraction | `PrAnalysis`, `RepositoryGitConfig` tables; Alembic migration; `GitPlatformClient` ABC + GitHub impl; HMAC verification utility. Unit tests for signature + parser. | 2–3 days |
| **M2** | Webhook receiver + idempotent enqueue | `POST /api/v1/webhooks/{platform}/{repo_id}` end-to-end; rate limit; body size cap; row upserted; background task stub fires. | 1–2 days |
| **M3** | Branch lifecycle + diff mapper | `ensure_branch_analyzed` helper (per-branch Project + cached commit-sha skip); `DiffMapper` with renames/hunk-line overlap. | 2–3 days |
| **M4** | Impact aggregator + drift detector + risk scorer | Cypher-driven analysis; deterministic Markdown summary as fallback. End-to-end works without AI. | 3 days |
| **M5** | AI pipeline (triage + subagents + supervisor) | Bedrock-backed supervisor; tool-use loop; budget + timeout caps; fallback to deterministic on failure. | 3–4 days |
| **M6** | Comment poster + idempotent updates | Markdown formatter; `post_comment` per platform; comment ID tracked for updates on PR sync. | 1–2 days |
| **M7** | REST endpoints | Full CRUD for `pr_analyses`; pagination; impact/drift sub-resources; `reanalyze`. | 2 days |
| **M8** | Frontend list page | Route, table, filters, polling. | 2 days |
| **M9** | Frontend detail page | Stats row, summary card, changed nodes, drift alerts, cross-tech panel, reanalyze button, export (MD/JSON). | 3 days |
| **M10** | Webhook setup UX | Auto-register webhook flow; copy/paste fallback modal; integration form; per-branch toggle. | 2 days |

Total: ~22–26 working days.

---

## 14. Risks & Open Questions

| Risk | Mitigation |
|---|---|
| Source-branch analysis dominates latency for large repos | Cache by `last_analyzed_commit`. Allow `monitored_branches` to keep target branch hot. |
| AI tokens balloon | Per-subagent and global token caps; deterministic fallback summary always works. |
| Webhook redelivery causes duplicate analyses | Unique constraint `(repo_id, pr_number, commit_sha)` + idempotent upsert. |
| Renamed files break path lookup | `DiffMapper` checks both `path` and `old_path` against graph. |
| Generated/vendored files in PR inflate impact | Add `pr_path_excludes` regex list to `RepositoryGitConfig` (M3). |
| Comment edit token expires | Re-create comment if PATCH 404; record new `comment_id`. |
| Stale analysis (PR updates land mid-analysis) | New webhook with new `commit_sha` supersedes; old row marked `stale`. |

**Open questions** (decide before M1):
- Provider order after GitHub: GitLab vs Bitbucket first? Both have webhook contract differences worth knowing early.
- Do we want a `github-app` install path in v1, or stay PAT-only? App = better scopes, more setup work.
- Should we expose the analysis as a GitHub status check (in addition to a comment) in v1, or wait? Status check requires the `checks:write` scope.

---

## 15. Out-of-scope Follow-ups

- Status check / merge gating (Phase 5b).
- GitLab MR / Bitbucket PR / Gitea support (Phase 5b — provider abstraction makes this incremental).
- Inline file annotations on the PR diff (requires line-level mapping, larger UI lift).
- Time-series view of risk across PRs over a release window.
- Slack / Teams notifications on high-risk PRs.
