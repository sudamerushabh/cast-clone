# PR AI Agent Pipeline — Design Spec

## Overview

Replace the single-shot LLM call in Phase 5a M7 with a full multi-agent pipeline for PR impact analysis. A **Supervisor Agent** orchestrates **specialist subagents** that independently explore the codebase, then synthesizes their findings into a comprehensive, production-safety-focused narrative summary.

**North star:** Prevent production breakage. The summary must trace every change through its full impact chain — direct callers, transitive dependents, API consumers, database writes, message queue consumers — and explicitly call out what will break if the PR is merged as-is.

**Scope note:** The Phase 5a parent spec (section 13) defers "Tool-use loop for AI summary" to Phase 5b. This design pulls that feature forward into M7, superseding the deferral decision. The single-call approach is retained only as a fallback.

---

## Prerequisites

### Repo Access

The agent pipeline requires full file access to the cloned repository. Projects analyzed via Phase 4a's repo onboarding flow already have a cloned repo on disk at `Repository.local_path`. The M8 orchestrator must resolve the repo path from the project's `Repository` record and pass it to `generate_pr_summary()`. If the repo is not cloned (e.g., local-path-only projects), the pipeline falls back to the single-call approach (no file-reading tools available).

### Config Additions

The following fields must be added to `app/config.py` `Settings`:

```python
# Phase 5a: AI agent pipeline
pr_analysis_model: str = "claude-sonnet-4-20250514"        # Model for subagents
pr_analysis_supervisor_model: str = "claude-sonnet-4-20250514"  # Model for supervisor (can be set to opus)
pr_analysis_max_subagents: int = 15                        # Circuit breaker: max total subagents
pr_analysis_max_total_tokens: int = 500_000                # Circuit breaker: max tokens across all agents
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PR Analysis AI Pipeline                           │
│                                                                     │
│  STAGE 1: TRIAGE (deterministic Python, no LLM)                     │
│    Input:  PRDiff, cloned repo path, graph impact data              │
│    Output: Categorized file groups + subagent dispatch plan          │
│                                                                     │
│  STAGE 2: PARALLEL SUBAGENT DISPATCH (asyncio.gather)               │
│                                                                     │
│   ┌────────────────┐ ┌────────────────┐ ┌────────────────┐         │
│   │ Code Change    │ │ Code Change    │ │ Code Change    │  ...     │
│   │ Analyst #1     │ │ Analyst #2     │ │ Analyst #3     │         │
│   │ (orders/)      │ │ (billing/)     │ │ (api/)         │         │
│   │                │ │                │ │                │         │
│   │ Agentic loop   │ │ Agentic loop   │ │ Agentic loop   │         │
│   │ 25 tool calls  │ │ 25 tool calls  │ │ 25 tool calls  │         │
│   │ Full context   │ │ Full context   │ │ Full context   │         │
│   └───────┬────────┘ └───────┬────────┘ └───────┬────────┘         │
│           ↓                  ↓                  ↓                   │
│       mini-report        mini-report        mini-report             │
│                                                                     │
│   ┌────────────────┐ ┌────────────────┐ ┌────────────────┐         │
│   │ Architecture   │ │ Infra &        │ │ Test Gap       │         │
│   │ Impact Analyst │ │ Config Analyst │ │ Analyst        │         │
│   │                │ │                │ │                │         │
│   │ Agentic loop   │ │ Agentic loop   │ │ Agentic loop   │         │
│   │ 25 tool calls  │ │ 25 tool calls  │ │ 25 tool calls  │         │
│   │ Full context   │ │ Full context   │ │ Full context   │         │
│   └───────┬────────┘ └───────┬────────┘ └───────┬────────┘         │
│           ↓                  ↓                  ↓                   │
│       arch-report        infra-report       test-report             │
│                                                                     │
│  STAGE 3: SUPERVISOR AGENTIC LOOP                                   │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────┐       │
│   │ SUPERVISOR AGENT                                         │       │
│   │                                                         │       │
│   │ Input: all subagent reports + impact + drift + risk     │       │
│   │ Tools: read_file, search_files, list_directory,         │       │
│   │        query_graph_node, get_node_impact, find_path,    │       │
│   │        dispatch_subagent                                │       │
│   │ Max tool calls: 50                                      │       │
│   │ Full context window                                     │       │
│   │                                                         │       │
│   │ Can dispatch ad-hoc subagents for follow-up             │       │
│   │ investigations (each gets 25 tool calls, full context)  │       │
│   │                                                         │       │
│   │ Output: comprehensive narrative summary                 │       │
│   └─────────────────────────────────────────────────────────┘       │
│                                                                     │
│  FALLBACK: If pipeline fails, fall back to single-call summary      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Agent Roles

### 1. Code Change Analyst (N instances, 1 per module batch)

**Purpose:** Read actual changed files, understand semantic meaning, spot issues.

**Seed context:** List of changed files in its batch + their graph node FQNs.

**Tools:** `read_file`, `search_files`, `grep_content`, `list_directory`, `query_graph_node`

**What it does:**
- Reads each changed file in its batch
- Follows references it discovers (e.g., a called method not in the PR)
- Greps for usages of changed methods/classes across the codebase
- Queries graph nodes to understand the call context
- Identifies semantic meaning of changes beyond just "lines added/removed"
- Spots potential issues: null safety, missing validation, contract changes

**System prompt guidance:**
> You are a senior code reviewer analyzing a batch of changed files. Read each file, understand what changed semantically, and follow any references that seem important. Use your tools to explore — don't guess about code you haven't read. For each change, explain what it does differently now and what could go wrong.

**Output:** Structured JSON mini-report:
```json
{
  "role": "code_change_analyst",
  "batch_id": "<module-name>",
  "files_analyzed": ["<paths>"],
  "semantic_summary": "<what the changes do as a whole>",
  "changes": [
    {
      "node_fqn": "<fqn>",
      "what_changed": "<semantic description>",
      "why_it_matters": "<impact context>",
      "risk": "high|medium|low",
      "concerns": ["<specific issues>"]
    }
  ],
  "cross_references_discovered": ["<things this code calls/uses that aren't in the PR>"],
  "config_dependencies_found": ["<env vars, config keys read by this code>"],
  "potential_issues": ["<bugs, missing checks, contract changes>"]
}
```

### 2. Architecture Impact Analyst (1 instance)

**Purpose:** Follow graph paths, understand blast radius deeply, identify critical chains and hub impacts.

**Seed context:** Aggregate `AggregatedImpact` data + changed node FQNs + transaction list + community membership.

**Tools:** `query_graph_node`, `get_node_impact`, `find_path`, `read_file`, `search_files`, `grep_content`

**What it does:**
- For each high-fan-in changed node, traces downstream impact chains
- Identifies critical transaction flows that pass through changed code
- Checks for hub nodes (high PageRank) in the blast radius
- Reads source code of critical downstream nodes to understand if they'll handle the change
- Identifies cross-module dependency changes

**System prompt guidance:**
> You are a software architect analyzing the structural impact of code changes on the architecture graph. Trace every changed node through its dependency chains. Focus on critical paths: high-traffic transaction flows, hub nodes, and cross-technology boundaries (API endpoints, message queues, database tables). For each impact chain, explain specifically what breaks and why. Use your tools to follow graph paths and read downstream code.

**Output:** Structured JSON:
```json
{
  "role": "architecture_impact_analyst",
  "critical_paths": [
    {
      "description": "<human-readable path description>",
      "nodes_in_path": ["<fqn chain>"],
      "risk": "high|medium|low",
      "reason": "<why this path is risky>"
    }
  ],
  "hub_nodes_affected": [
    {
      "fqn": "<fqn>",
      "fan_in": "<count>",
      "why": "<why this hub matters>"
    }
  ],
  "layer_analysis": "<which architectural layers are affected and how>",
  "transaction_impact": ["<affected end-to-end flows>"],
  "cross_tech_impact": [
    {
      "kind": "api_endpoint|message_topic|database_table",
      "name": "<identifier>",
      "impact": "<what changes for consumers>"
    }
  ],
  "module_coupling_observations": "<new dependencies, removed dependencies, coupling changes>"
}
```

### 3. Infrastructure & Config Analyst (1 instance)

**Purpose:** Read Dockerfiles, .env files, CI configs, app configs, migration files. Identify gaps between code changes and infrastructure.

**Seed context:** List of config/infra/migration files detected by triage + env vars/config keys referenced by changed code.

**Tools:** `read_file`, `search_files`, `grep_content`, `list_directory`

**What it does:**
- Reads all config and infrastructure files in the repository
- Checks if new env vars referenced in code exist in .env.example, docker-compose, CI
- Checks if new dependencies need Dockerfile changes
- Reads migration files to verify schema changes match code expectations
- Checks CI pipeline for impacts (new test steps needed, deploy changes)

**System prompt guidance:**
> You are a DevOps engineer reviewing the infrastructure and configuration impact of code changes. You've been told which environment variables and config keys the changed code references. Check if they exist in all the right places: .env.example, docker-compose, CI workflows, deployment configs. Check if database migrations exist for any new columns or tables the code assumes. Check if Dockerfile needs changes for new dependencies. Be thorough — missing config is one of the top causes of production outages.

**Output:** Structured JSON:
```json
{
  "role": "infra_config_analyst",
  "config_issues": [
    {
      "severity": "high|medium|low",
      "issue": "<description>",
      "files_checked": ["<paths>"],
      "recommendation": "<what to do>"
    }
  ],
  "dockerfile_impact": "<assessment>",
  "migration_status": "<assessment of whether required migrations exist>",
  "ci_impact": "<assessment>",
  "dependency_changes": "<new deps, removed deps, version changes>",
  "environment_variables": {
    "referenced_in_code": ["<vars>"],
    "present_in_config": ["<vars>"],
    "missing_from_config": ["<vars>"]
  }
}
```

### 4. Test Gap Analyst (1 instance)

**Purpose:** Identify testing gaps for changed code — untested paths, missing edge cases, coverage holes.

**Seed context:** Changed node FQNs + test directory paths.

**Tools:** `read_file`, `search_files`, `grep_content`, `list_directory`, `query_graph_node`

**What it does:**
- Searches for test files related to changed nodes (by name, by import, by directory convention)
- Reads existing tests to understand what's already covered
- Identifies new code paths introduced by the PR that have no test coverage
- Checks for integration tests that cover end-to-end flows through changed code
- Identifies edge cases that should be tested (null inputs, error paths, boundary conditions)

**System prompt guidance:**
> You are a QA engineer analyzing test coverage for code changes. For each changed node, find its tests. Read them. Determine if the new behavior introduced by this PR is covered. Focus on: (1) new code paths that have zero tests, (2) changed behavior in existing code where tests still pass but test the old behavior, (3) edge cases and error paths. Be specific about what test is missing and what it should verify.

**Output:** Structured JSON:
```json
{
  "role": "test_gap_analyst",
  "coverage_assessment": [
    {
      "node_fqn": "<fqn>",
      "existing_tests": ["<test names>"],
      "gap": "<what's not tested>",
      "severity": "high|medium|low",
      "suggested_test": "<what test should be written>"
    }
  ],
  "test_files_analyzed": ["<paths>"],
  "untested_paths": ["<specific code paths with no coverage>"],
  "integration_test_status": "<whether e2e flows through changed code are tested>",
  "overall_assessment": "<summary>"
}
```

### 5. Supervisor Agent

**Purpose:** Synthesize all subagent reports into a single comprehensive narrative. Investigate gaps and contradictions. Generate the final production-safety-focused summary.

**Input:**
- All subagent reports (structured JSON)
- Aggregate impact data (`AggregatedImpact`)
- Drift report (`DriftReport`)
- Risk classification (High/Medium/Low)
- PR metadata (title, description, author, branches)

**Tools:** `read_file`, `search_files`, `grep_content`, `list_directory`, `query_graph_node`, `get_node_impact`, `find_path`, `dispatch_subagent`

**Max tool calls:** 50

**`dispatch_subagent` tool:** Spawns a new ad-hoc subagent (25 tool calls, full context) for follow-up investigations. The supervisor provides a focused prompt and receives the subagent's report.

**System prompt:**
> You are a senior production engineer reviewing a pull request. Your primary job is to prevent outages. You have reports from specialist analysts — treat them as junior engineers' findings: trust but verify.
>
> Your output is a comprehensive PR analysis that will be read by a reviewer who decides whether to merge. It must cover:
>
> 1. **Verdict** — Risk level + what this PR does + the single most dangerous thing about it.
>
> 2. **What This PR Does** — Semantic description of the changes based on code analyst reports. Not "modified 5 files" but "adds discount validation to the order creation flow."
>
> 3. **Production Impact Trace** — This is the core section. For each changed node that matters, trace through its full impact chain:
>    - Direct dependents that will see different behavior
>    - Transitive impacts (2nd, 3rd hop) — name specific classes, functions, tables
>    - Cross-tech impacts — API endpoints (are contracts changing?), message queues (are schemas changing?), database tables (are columns missing?)
>    - Transaction flow impact — how end-to-end flows are affected, latency implications
>
> 4. **What Will Break If Merged As-Is** — Explicit list of definite breakages. Not "might affect" but "WILL fail because X."
>
> 5. **What Might Break Under Edge Cases** — Conditional failures: missing env vars, empty tables, race conditions, high load.
>
> 6. **Missing Safeguards** — Tests not written, migrations not created, configs not updated, error handling missing.
>
> 7. **Architecture Drift** — New module dependencies, layer violations, coupling changes. Only if relevant.
>
> 8. **Recommendations** — Prioritized list: BLOCKER (must fix before merge), HIGH (should fix), MEDIUM (consider fixing).
>
> Be specific everywhere — use actual class names, function names, file paths, table names. If you don't know something, use your tools to find out. If a subagent report seems incomplete, dispatch a follow-up subagent.
>
> Do not just concatenate subagent reports. Synthesize. Look for contradictions between reports. Look for gaps that no subagent covered. Your analysis should read like a senior architect's PR review, not a tool output.

---

## Tool Definitions

Six tools available to all agents, plus `dispatch_subagent` for the supervisor:

### `read_file`
```
Parameters:
  path: string        # Relative path from repo root
  line_start?: int    # Optional start line (1-indexed)
  line_end?: int      # Optional end line

Returns:
  content: string     # File content with line numbers
  total_lines: int    # Total line count
  truncated: bool     # True if file was truncated (>500 lines without line range)

Notes:
  - If file exceeds 500 lines and no line range specified, returns first 500 lines
    with a note: "File truncated. Use line_start/line_end to read specific sections."
  - Binary files return an error message.
```

### `search_files`
```
Parameters:
  glob_pattern: string   # Glob pattern (e.g., "**/*Service*.java", "**/test_*.py")

Returns:
  files: string[]        # Matching file paths (max 100)
  total_matches: int     # Total matches (may exceed 100)

Notes:
  - Searches from repository root.
  - Returns paths sorted by modification time (newest first).
```

### `grep_content`
```
Parameters:
  pattern: string        # Regex pattern to search for in file contents
  glob?: string          # Optional glob filter (e.g., "*.java"). Defaults to all files.
  max_results?: int      # Default 20, max 50

Returns:
  matches: Array<{file: string, line: int, content: string}>
  total_matches: int

Notes:
  - Searches file contents (ripgrep-style) within the repo.
  - Each match includes the file path, line number, and the matching line.
  - Essential for finding callers/consumers by searching for method names,
    annotations (e.g., @KafkaListener), env var references, etc.
```

### `list_directory`
```
Parameters:
  path: string           # Relative path from repo root (empty string = root)
  recursive?: bool       # Default false. If true, returns full tree (max 500 entries).

Returns:
  entries: Array<{name: string, type: "file"|"dir", size?: int}>
```

### `query_graph_node`
```
Parameters:
  fqn: string            # Fully qualified name of the node

Returns:
  node: {fqn, name, type, language, path, line, end_line, loc, complexity, fan_in, fan_out, community_id}
  callers: Array<{fqn, name, type}>      # Nodes that call this node (max 50)
  callees: Array<{fqn, name, type}>      # Nodes called by this node (max 50)
  annotations: string[]                   # Java/Spring annotations, decorators, etc.

Notes:
  - Returns null if node not found in graph.
  - Queries Neo4j using the project's app_name.
```

### `get_node_impact`
```
Parameters:
  fqn: string
  direction: "downstream" | "upstream" | "both"
  depth?: int            # Default 5, max 10

Returns:
  affected: Array<{fqn, name, type, file, depth}>
  total: int
  by_type: Record<string, int>

Notes:
  - Reuses Phase 3 impact analysis Cypher queries.
```

### `find_path`
```
Parameters:
  source_fqn: string
  target_fqn: string

Returns:
  nodes: Array<{fqn, name, type}>
  edges: Array<{type, source, target}>
  path_length: int

Notes:
  - Returns shortest path. Empty if no path exists.
  - Reuses Phase 3 path finder Cypher.
```

### `dispatch_subagent` (Supervisor only)
```
Parameters:
  role: string           # A descriptive role name (e.g., "kafka_consumer_analyst")
  prompt: string         # Focused task description
  tools: string[]        # Subset of VALID tool names to give the subagent.
                         # Valid names: "read_file", "search_files", "grep_content",
                         # "list_directory", "query_graph_node", "get_node_impact", "find_path"
                         # Invalid names return an error.

Returns:
  report: string         # The subagent's complete response

Notes:
  - Spawns a new agentic loop with 25 tool calls, full context window.
  - Blocks until the subagent completes (or times out at 120s).
  - The supervisor timeout EXCLUDES time spent waiting for dispatched subagents.
  - The supervisor should use this sparingly for specific follow-up investigations.
  - Counts toward the pipeline's max_subagents budget.
```

---

## Triage Logic

Deterministic Python — no LLM involved. Runs before any agent is dispatched.

**File categorization rules:**

```python
CATEGORIES = {
    "source":      ["*.java", "*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.cs", "*.go"],
    "test":        ["*test*", "*spec*", "*Test*", "*Spec*"],
    "config":      ["*.yml", "*.yaml", "*.properties", "*.toml", "*.ini", "*.json",
                    "*.env*", "settings.*", "config.*", "application.*"],
    "infra":       ["Dockerfile*", "docker-compose*", ".github/**", ".gitlab-ci*",
                    "Makefile", "*.tf", "Jenkinsfile", "Procfile"],
    "migration":   ["**/migration*/**", "**/migrations/**", "**/flyway/**",
                    "**/alembic/**", "**/liquibase/**"],
    "docs":        ["*.md", "*.txt", "*.rst", "LICENSE*", "CHANGELOG*"],
}
```

**Batching logic for Code Change Analysts:**
- **Preferred:** Use graph node FQN to determine module. For each changed file, look up its graph nodes and extract the top-level module (first 2 segments of the FQN, e.g., `com.app.orders` from `com.app.orders.OrderService.createOrder`).
- **Fallback (no graph data):** Strip language-specific prefixes (`src/main/java/`, `src/`, `app/`, `lib/`) then group by first 2 directory segments.
- Max 5 files per batch
- If a module has >5 files, split into multiple batches
- **Circuit breaker:** If total code batches > `Settings.pr_analysis_max_subagents - 3` (reserving 3 for specialist agents), merge the smallest batches until within budget.

**Dispatch plan output:**
```python
@dataclass
class TriageResult:
    code_batches: list[CodeBatch]        # Each becomes a Code Change Analyst
    config_files: list[str]              # Goes to Infra & Config Analyst
    infra_files: list[str]               # Goes to Infra & Config Analyst
    migration_files: list[str]           # Goes to Infra & Config Analyst
    test_files: list[str]                # Referenced by Test Gap Analyst
    doc_files: list[str]                 # Mentioned in triage summary only
    env_vars_referenced: list[str]       # Extracted from graph node properties
    total_subagents: int                 # N code analysts + 3 specialists

@dataclass
class CodeBatch:
    batch_id: str                        # e.g., "com.app.orders"
    files: list[str]                     # File paths
    graph_node_fqns: list[str]           # FQNs of nodes in these files
```

---

## Execution Details

### Parallelism

All subagents in Stage 2 run concurrently via `asyncio.gather()`. They are fully independent — no shared state, no communication between subagents. Each gets its own Anthropic API call chain and its own tool execution context.

```python
reports = await asyncio.gather(
    *[run_agent(code_batch) for code_batch in triage.code_batches],
    run_agent(arch_analyst_config),
    run_agent(infra_analyst_config),
    run_agent(test_analyst_config),
    return_exceptions=True,  # Don't fail all if one fails
)
```

### Agent Limits

| Agent | Max tool calls | Context window | Timeout |
|-------|---------------|----------------|---------|
| Code Change Analyst (each) | 25 | Full | 120s |
| Architecture Impact Analyst | 25 | Full | 120s |
| Infra & Config Analyst | 25 | Full | 120s |
| Test Gap Analyst | 25 | Full | 120s |
| Supervisor | 50 | Full | 180s (excludes subagent wait time) |
| Ad-hoc subagent (dispatched by supervisor) | 25 | Full | 120s |

### Model Selection

| Agent | Model | Rationale |
|-------|-------|-----------|
| All subagents | Claude Sonnet | Fast, cost-effective, good at focused analysis tasks |
| Supervisor | Claude Sonnet (configurable to Opus) | Needs strong synthesis and reasoning. Configurable per project. |

The model is configurable via `Settings.pr_analysis_model` (default: `claude-sonnet-4-20250514`).

### Circuit Breakers

Two safety limits prevent runaway cost:

1. **Max subagents** (`Settings.pr_analysis_max_subagents`, default 15): If triage would dispatch more subagents than this limit (e.g., a 200-file PR with 40 module batches), the triage merges the smallest batches until within budget. If still over budget after merging, the pipeline falls back to single-call mode.

2. **Max total tokens** (`Settings.pr_analysis_max_total_tokens`, default 500,000): The orchestrator tracks cumulative tokens across all agents. If the budget is exceeded mid-pipeline, remaining subagents are skipped and the supervisor runs with whatever reports are available.

### Error Handling

```
If a subagent fails (API error, timeout):
  → Supervisor receives a note: "Code analyst for orders/ failed: <error>"
  → Supervisor still runs with available reports
  → Supervisor can dispatch a replacement subagent if needed

If supervisor fails:
  → Fall back to single-call summary (old M7 approach)
  → Log the failure for monitoring

If all agents fail:
  → Store ai_summary = "AI analysis unavailable — pipeline failed. See logs."
  → PR analysis still completes with deterministic data (impact, drift, risk)
```

### Cost Tracking

Each `run_agent()` call tracks:
- `input_tokens`: sum of all request tokens across the agent's turns
- `output_tokens`: sum of all response tokens across the agent's turns
- `tool_calls_made`: count of tool invocations

The orchestrator sums across all agents:
```python
total_tokens = sum(agent.input_tokens + agent.output_tokens for agent in all_agents)
pr_record.ai_summary_tokens = total_tokens
```

Per-agent costs are logged via structlog for monitoring:
```python
logger.info("agent_completed",
    role=agent.role, tokens=agent.total_tokens,
    tool_calls=agent.tool_calls_made, duration_ms=agent.duration_ms)
```

---

## File Structure

```
cast-clone-backend/app/pr_analysis/ai/
├── __init__.py              # Public API: generate_pr_summary()
├── supervisor.py            # Supervisor agent loop + final summary assembly
├── subagents.py             # Shared agentic loop runner (run_agent function)
├── tools.py                 # Tool definitions (Anthropic format) + async handlers
├── tool_context.py          # ToolContext dataclass (repo_path, graph_store, app_name)
├── prompts.py               # System prompts for all 5 roles + supervisor
├── triage.py                # Deterministic file categorization + batching
└── report_types.py          # Structured report dataclasses for subagent outputs
```

### Integration Point

`app/pr_analysis/ai/__init__.py` exposes the same interface as the old `ai_summary.py`:

```python
async def generate_pr_summary(
    pr_event: PullRequestEvent,
    impact: AggregatedImpact,
    drift: DriftReport,
    risk_level: str,
    api_key: str,
    repo_path: str,           # NEW: path to cloned repo
    graph_store: GraphStore,   # NEW: Neo4j connection
    app_name: str,             # NEW: project identifier
) -> SummaryResult:
```

The M8 orchestrator (`analyzer.py`) must be updated to pass `repo_path`, `graph_store`, and `app_name` to this function. It resolves `repo_path` from the project's `Repository.local_path` field.

**Updated `SummaryResult`:**
```python
@dataclass
class SummaryResult:
    summary: str
    tokens_used: int
    agents_run: int           # Total agents dispatched (including ad-hoc)
    agents_failed: int        # Agents that failed/timed out
    total_duration_ms: int    # Wall-clock time for entire pipeline
```

### GraphStore Usage

All graph-querying tools (`query_graph_node`, `get_node_impact`, `find_path`) use the existing `GraphStore.query()` and `GraphStore.query_single()` generic Cypher methods. No new methods are added to the `GraphStore` interface. Each tool builds its own Cypher query string and calls `graph_store.query(cypher, params)`.

### Subagent Report Parsing

Subagents produce structured JSON as their final text response. Parsing strategy:

1. Extract the last JSON block from the agent's response (agents may produce thinking text before the JSON)
2. Parse with `json.loads()`
3. If parsing fails, wrap the raw text in a fallback report: `{"role": "<role>", "raw_text": "<response>", "parse_failed": true}`
4. The supervisor receives both parsed and fallback reports — it can read raw text just fine
5. Report dataclasses in `report_types.py` are used for type hints and documentation, not strict validation — the supervisor is the consumer and handles variation gracefully

---

## Summary Output Structure

The supervisor generates a narrative covering all of the following sections (as applicable):

### 1. Verdict
1-2 sentences. Risk level, what the PR does, the single most dangerous aspect.

### 2. What This PR Does
Semantic description based on code analyst reports. What the code change means in business/system terms.

### 3. Production Impact Trace (core section)
For each significant changed node:
- What changed and how it behaves differently
- Direct dependents seeing different behavior (named specifically)
- Transitive impacts at 2nd/3rd hop (named specifically)
- Cross-tech impacts: API endpoints (contract changes?), message queues (schema changes?), database tables (column changes?)
- Transaction flow impact: how end-to-end flows are affected, latency implications

### 4. What Will Break If Merged As-Is
Explicit list of definite breakages. Not "might affect" — "WILL fail because X."

### 5. What Might Break Under Edge Cases
Conditional failures: missing env vars, empty tables, race conditions, high load.

### 6. Missing Safeguards
Tests not written, migrations not created, configs not updated, error handling missing.

### 7. Architecture Drift
New module dependencies, layer violations, coupling changes. Only if relevant.

### 8. Recommendations
Prioritized: BLOCKER (must fix before merge), HIGH (should fix), MEDIUM (consider fixing).

---

## What This Replaces

This spec replaces the `app/pr_analysis/ai_summary.py` module defined in Phase 5a M7. The old module was a single `anthropic.messages.create()` call with structured data as context. The new module is a multi-agent pipeline with the same public interface.

The M7 plan file (`2026-03-13-phase5a-m7-ai-summary.md`) should be rewritten to implement this spec instead.
