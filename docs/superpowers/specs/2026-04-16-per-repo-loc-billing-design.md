# Per-Repository Max-Branch LOC Billing

**Date:** 2026-04-16
**Status:** Approved
**Scope:** Backend (loc_usage, license, pipeline, API), Frontend (license page, repo list), DB migration

## Problem

The current LOC billing model sums `total_loc` across **all** completed `AnalysisRun` records:

```sql
SELECT COALESCE(SUM(total_loc), 0) FROM analysis_runs WHERE status = 'completed'
```

This causes LOC to inflate unfairly:
- Re-analyzing the same branch doubles the count.
- Analyzing multiple branches of the same repo sums them all, even though the underlying codebase is largely the same.
- Customers hit license limits far sooner than their actual codebase size warrants.

## Solution

Replace cumulative LOC billing with **per-repository max-branch** billing:

```
Billable LOC = SUM over all repositories [ MAX over all branches ( latest_completed_run.total_loc ) ]
```

### Rules

1. **Per branch:** Only the latest completed scan's `total_loc` counts (not historical scans).
2. **Per repo:** Only the branch with the highest LOC counts toward billing (not all branches summed).
3. **Global:** Total billable LOC = sum of each repository's max-branch LOC.
4. **Deletion:** When a branch (Project) is deleted, the repo's billable LOC is recalculated. If the deleted branch was the max, the next-highest branch becomes the new max.
5. **Re-scans:** Re-analyzing a branch replaces its LOC value (latest run wins), then the repo max is recalculated.
6. **Standalone projects:** Projects with no `repository_id` (legacy/standalone) are treated as individual "repos" — their latest completed run's LOC counts directly.

### Example

| Repository | Branch | Latest LOC | Max? |
|------------|--------|-----------|------|
| org/backend | main | 10,000 | |
| org/backend | develop | 12,000 | Yes |
| org/backend | feature-x | 8,000 | |
| org/frontend | main | 5,000 | Yes |

**Billable LOC = 12,000 + 5,000 = 17,000** (regardless of how many scans were run)

## Architecture

### New Database Table: `repository_loc_tracking`

One row per repository. Acts as a materialized aggregate of billing state.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| `id` | UUID | PK, default uuid4 | Row ID |
| `repository_id` | String(36) | FK → repositories.id, UNIQUE, CASCADE delete | Which repo |
| `billable_loc` | Integer | NOT NULL, default 0 | max(latest LOC) across branches |
| `max_loc_project_id` | String(36) | FK → projects.id, SET NULL on delete | Which branch (Project) is the max |
| `max_loc_branch_name` | String(255) | nullable | Denormalized branch name for display |
| `breakdown` | JSONB | NOT NULL, default {} | `{"branch_name": loc, ...}` for all branches |
| `last_recalculated_at` | DateTime(tz) | NOT NULL | When this row was last computed |
| `created_at` | DateTime(tz) | server_default=now() | Row creation time |

**Indexes:**
- Unique index on `repository_id` (implicit from UNIQUE constraint)
- No additional indexes needed (table is tiny — one row per repo)

### Recalculation Function

New module: `app/services/loc_tracking.py`

```python
async def recalculate_repo_loc(repository_id: str, session: AsyncSession) -> RepositoryLocTracking:
    """Recompute billable LOC for a repository from its branches' latest completed runs.

    1. Query all Projects for repository_id
    2. For each Project with a completed run, get the latest run's total_loc
    3. Build breakdown: {branch_name: loc}
    4. Pick the max -> billable_loc, max_loc_project_id, max_loc_branch_name
    5. Upsert into repository_loc_tracking
    6. Invalidate cumulative LOC cache
    """
```

**Query strategy:** Single query with window function to get each branch's latest completed run:

```sql
SELECT DISTINCT ON (p.id)
    p.id as project_id,
    p.branch,
    ar.total_loc
FROM projects p
JOIN analysis_runs ar ON ar.project_id = p.id
WHERE p.repository_id = :repo_id
  AND ar.status = 'completed'
  AND ar.total_loc IS NOT NULL
ORDER BY p.id, ar.completed_at DESC
```

### Updated `cumulative_loc()`

Replace the query in `app/services/loc_usage.py`:

```python
# NEW: sum of per-repo maximums from tracking table
result = await s.execute(
    select(func.coalesce(func.sum(RepositoryLocTracking.billable_loc), 0))
)

# PLUS: standalone projects (no repository_id) — latest run each
standalone = await s.execute(
    select(func.coalesce(func.sum(latest_standalone.c.total_loc), 0))
    # subquery: latest completed run per project where repository_id IS NULL
)

return int(result.scalar_one()) + int(standalone.scalar_one())
```

Same caching strategy: 60-second TTL, explicit invalidation.

### Trigger Points

| Event | Location | Action |
|-------|----------|--------|
| Analysis pipeline completes | `orchestrator/pipeline.py` (after status="completed") | `await recalculate_repo_loc(repo_id, session)` |
| Branch (Project) deleted | `api/repositories.py` (delete branch endpoint) | `await recalculate_repo_loc(repo_id, session)` |
| Repository deleted | Automatic | CASCADE delete removes tracking row |
| Branch added (no scan yet) | N/A | No tracking row change needed |

### API Changes

#### GET /api/v1/license/status — add `loc_breakdown` field

```python
class RepoLocBreakdown(BaseModel):
    repository_id: str
    repo_full_name: str
    billable_loc: int
    max_branch: str | None
    branches: dict[str, int]  # {branch_name: loc}

class LicenseStatusResponse(BaseModel):
    # ... existing fields ...
    loc_used: int | None
    loc_limit: int | None
    loc_breakdown: list[RepoLocBreakdown]  # NEW
```

#### GET /api/v1/repositories — add LOC fields to response

```python
class RepositoryResponse(BaseModel):
    # ... existing fields ...
    billable_loc: int | None          # NEW: max-branch LOC for this repo
    max_loc_branch: str | None        # NEW: which branch is the max
```

### Frontend Changes

#### License Page (`/settings/license`)

Add a "LOC by Repository" section below the existing progress bar:

```
Usage
Lines of Code                    17,000 / 500,000 (3.4%)
[=========                                              ]

LOC by Repository
┌──────────────────┬─────────────┬─────────┬──────────┐
│ Repository       │ Max Branch  │ LOC     │ % Total  │
├──────────────────┼─────────────┼─────────┼──────────┤
│ org/backend      │ develop     │ 12,000  │ 70.6%    │
│ org/frontend     │ main        │  5,000  │ 29.4%    │
├──────────────────┼─────────────┼─────────┼──────────┤
│ Total            │             │ 17,000  │          │
└──────────────────┴─────────────┴─────────┴──────────┘
```

Each row is expandable to show all branches:
```
▼ org/backend                develop    12,000   70.6%
    main                                10,000
    develop                             12,000  ← max
    feature-x                            8,000
```

#### Repository List Page (`/repositories`)

Add a small LOC badge to each RepoCard:
```
[org/backend]
  3 branches · cloned
  Billable: 12,000 LOC (develop)
```

### Data Migration

Alembic migration with two steps:

1. **Schema:** Create `repository_loc_tracking` table.
2. **Backfill:** For each existing repository, compute the breakdown from completed AnalysisRuns and insert a tracking row.

```python
# Backfill pseudo-code (runs inside migration)
for repo in all_repositories:
    for project in repo.projects:
        latest_run = latest_completed_run(project.id)
        if latest_run and latest_run.total_loc:
            breakdown[project.branch] = latest_run.total_loc
    if breakdown:
        max_branch = max(breakdown, key=breakdown.get)
        insert repository_loc_tracking(
            repository_id=repo.id,
            billable_loc=breakdown[max_branch],
            max_loc_branch_name=max_branch,
            breakdown=breakdown,
            ...
        )
```

After migration, existing customers see their LOC usage **drop** to the correct value.

### Edge Cases

| Edge Case | Handling |
|-----------|----------|
| Project with no `repository_id` (standalone) | Counted separately: latest completed run's LOC added to global total |
| Branch deleted while scan is running | Recalc triggers on scan complete; if project gone by then, it's excluded from breakdown |
| All branches deleted from a repo | Tracking row stays with `billable_loc = 0`; cleaned up on repo delete |
| Repository with zero completed scans | Tracking row with `billable_loc = 0`, empty breakdown |
| Two scans complete simultaneously for same repo | Both call `recalculate_repo_loc`; second one overwrites first with same correct result (idempotent) |
| Scan completes but `total_loc` is NULL | Branch excluded from breakdown (only non-null LOC counted) |
| License state recalculation on background refresh | Uses `cumulative_loc()` which reads from tracking table — always reflects latest recalc |

### Files to Create

| File | Purpose |
|------|---------|
| `app/services/loc_tracking.py` | `recalculate_repo_loc()` function |
| `alembic/versions/xxxx_add_repository_loc_tracking.py` | Migration: create table + backfill |

### Files to Modify

| File | Change |
|------|--------|
| `app/models/db.py` | Add `RepositoryLocTracking` model |
| `app/services/loc_usage.py` | Rewrite `cumulative_loc()` to query tracking table + standalone projects |
| `app/orchestrator/pipeline.py` | Call `recalculate_repo_loc()` after scan completes |
| `app/api/repositories.py` | Add `billable_loc`, `max_loc_branch` to response; call recalc on branch delete |
| `app/api/license.py` | Add `loc_breakdown` to status response |
| `cast-clone-frontend/lib/types.ts` | Add `RepoLocBreakdown` interface, update `LicenseStatusResponse` and `RepositoryResponse` |
| `cast-clone-frontend/lib/api.ts` | No changes needed (types flow through existing endpoints) |
| `cast-clone-frontend/app/settings/license/page.tsx` | Add LOC breakdown table |
| `cast-clone-frontend/app/repositories/page.tsx` | Add LOC badge to RepoCard |
| `cast-clone-frontend/components/connectors/ConnectorCard.tsx` | Add LOC display if repo data available |

### Non-Goals

- Historical LOC tracking / trending graphs (future work)
- Per-file LOC breakdown (overkill for billing)
- Changes to the license JWT structure (loc_limit stays the same)
- Changes to the operator UI (tiers and limits unchanged)
- Changes to the license state machine logic (evaluate_state stays the same, just gets a different cumulative number)
- Changes to email templates (they already use `loc.used` which will reflect the new calculation)
