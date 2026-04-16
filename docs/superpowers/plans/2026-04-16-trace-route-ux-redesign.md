# Trace Route UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the trace route modal with swim-lane visualization, layer-aware node styling, and an AI-generated flow summary sidebar.

**Architecture:** Backend adds layer detection to existing trace endpoint + new trace summary endpoint. Frontend rewrites the TraceRouteModal as a split-panel (60% graph with swim-lanes, 40% AI summary). AI summary uses the same provider infrastructure as existing node summaries.

**Tech Stack:** Python/FastAPI (backend), Next.js/TypeScript/Cytoscape.js (frontend), Claude Sonnet via Bedrock or OpenAI (AI summary), react-markdown (rendering)

---

## Task 1: Add `layer` field to backend TraceNode schema

**Files:**
- Modify: `cast-clone-backend/app/schemas/analysis_views.py:127-154`

- [ ] **Step 1: Update TraceNode schema**

In `cast-clone-backend/app/schemas/analysis_views.py`, add the `layer` field to `TraceNode`:

```python
class TraceNode(BaseModel):
    fqn: str
    name: str
    kind: str
    file: str | None = None
    language: str | None = None
    depth: int
    sequence: int
    direction: str  # "upstream" | "downstream"
    layer: str = "other"  # "api" | "service" | "repository" | "database" | "other"
```

- [ ] **Step 2: Update TraceRouteResponse schema**

In the same file, add `layers_present` and `center_layer` to `TraceRouteResponse`:

```python
class TraceRouteResponse(BaseModel):
    center_fqn: str
    center_name: str
    center_kind: str
    center_layer: str  # NEW
    max_depth: int
    upstream: list[TraceNode]
    downstream: list[TraceNode]
    edges: list[TraceEdge]
    upstream_count: int
    downstream_count: int
    layers_present: list[str] = Field(default_factory=list)  # NEW
```

- [ ] **Step 3: Add TraceSummaryResponse schema**

Append after `TraceRouteResponse` in the same file:

```python
class TraceSummaryResponse(BaseModel):
    fqn: str
    summary: str
    layers_involved: list[str] = Field(default_factory=list)
    tables_touched: list[str] = Field(default_factory=list)
    cached: bool
    model: str | None = None
    tokens_used: int | None = None
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "import ast; ast.parse(open('app/schemas/analysis_views.py').read()); print('OK')"`

Expected: `OK`

- [ ] **Step 5: Run ruff**

Run: `uv run ruff check app/schemas/analysis_views.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add cast-clone-backend/app/schemas/analysis_views.py
git commit -m "feat(api): add layer + TraceSummaryResponse to trace schemas"
```

---

## Task 2: Add layer detection logic to backend trace endpoint

**Files:**
- Modify: `cast-clone-backend/app/api/analysis_views.py:222-370`

The layer detection function classifies nodes by architectural tier. It runs after we have both nodes and edges, so it can detect repository nodes by their READS/WRITES edges.

- [ ] **Step 1: Add the `_detect_layer` function and `_LAYER_ORDER` constant**

Add these right after the `_TRACE_EDGE_TYPES` constant (line ~240) in `cast-clone-backend/app/api/analysis_views.py`:

```python
import re

# Canonical layer ordering for swim-lane display (top to bottom)
_LAYER_ORDER = ["api", "service", "repository", "database", "other"]

_DB_KINDS = {"TABLE", "STORED_PROCEDURE", "VIEW", "COLUMN"}
_API_KINDS = {"API_ENDPOINT", "ROUTE"}
_CONTROLLER_RE = re.compile(r"controller", re.IGNORECASE)
_REPO_RE = re.compile(r"repositor|\.repo\b", re.IGNORECASE)
_SERVICE_RE = re.compile(r"service", re.IGNORECASE)


def _detect_layer(
    fqn: str,
    kind: str,
    rw_source_fqns: set[str],
) -> str:
    """Classify a node into an architectural layer.

    Args:
        fqn: Fully qualified name of the node.
        kind: Node kind (FUNCTION, TABLE, etc.).
        rw_source_fqns: Set of FQNs that are sources of
            READS/WRITES edges (i.e., repository methods).

    Returns one of: api, service, repository, database, other.
    Rules are checked in priority order; first match wins.
    """
    if kind in _DB_KINDS:
        return "database"
    if kind in _API_KINDS or _CONTROLLER_RE.search(fqn):
        return "api"
    if _REPO_RE.search(fqn) or fqn in rw_source_fqns:
        return "repository"
    if _SERVICE_RE.search(fqn):
        return "service"
    return "other"
```

- [ ] **Step 2: Wire layer detection into the `trace_route()` endpoint**

In the `trace_route()` function, after the edge records are fetched and before building `trace_edges`, compute the set of READS/WRITES source FQNs:

Find the section that starts with `edge_records = await store.query(` (around line 360) and add this right after:

```python
        # Identify nodes that are sources of READS/WRITES edges
        rw_source_fqns: set[str] = set()
        for r in edge_records:
            if r["type"] in ("READS", "WRITES"):
                rw_source_fqns.add(r["source"])
```

- [ ] **Step 3: Add layer to center node and each TraceNode**

Update the downstream_nodes and upstream_nodes list comprehensions to include `layer`. Replace the existing downstream_nodes block:

```python
        downstream_nodes = [
            TraceNode(
                fqn=r["fqn"],
                name=r["name"],
                kind=r["kind"] or "FUNCTION",
                file=r.get("file"),
                language=r.get("language"),
                depth=r["depth"],
                sequence=idx + 1,
                direction="downstream",
                layer=_detect_layer(
                    r["fqn"],
                    r["kind"] or "FUNCTION",
                    rw_source_fqns,
                ),
            )
            for idx, r in enumerate(down_records)
        ]
```

Do the same for upstream_nodes:

```python
        upstream_nodes = [
            TraceNode(
                fqn=r["fqn"],
                name=r["name"],
                kind=r["kind"] or "FUNCTION",
                file=r.get("file"),
                language=r.get("language"),
                depth=r["depth"],
                sequence=idx + 1,
                direction="upstream",
                layer=_detect_layer(
                    r["fqn"],
                    r["kind"] or "FUNCTION",
                    rw_source_fqns,
                ),
            )
            for idx, r in enumerate(up_records)
        ]
```

- [ ] **Step 4: Compute center_layer and layers_present, update the return**

The `rw_source_fqns` computation must happen BEFORE the node list comprehensions, but the edges are fetched AFTER nodes. Restructure: move the `rw_source_fqns` computation right after `edge_records` fetch, then move the node list comprehensions after that. Update the return statement:

```python
        center_layer = _detect_layer(
            node_fqn, center_kind, rw_source_fqns
        )

        # Collect unique layers in canonical order
        all_layers = {center_layer}
        for n in downstream_nodes:
            all_layers.add(n.layer)
        for n in upstream_nodes:
            all_layers.add(n.layer)
        layers_present = [
            la for la in _LAYER_ORDER if la in all_layers
        ]

        return TraceRouteResponse(
            center_fqn=node_fqn,
            center_name=center_name,
            center_kind=center_kind,
            center_layer=center_layer,
            max_depth=max_depth,
            upstream=upstream_nodes,
            downstream=downstream_nodes,
            edges=trace_edges,
            upstream_count=len(upstream_nodes),
            downstream_count=len(downstream_nodes),
            layers_present=layers_present,
        )
```

- [ ] **Step 5: Update the import for `re`**

Add `import re` to the top of the file (next to the existing `import asyncio`).

- [ ] **Step 6: Restructure the function to compute edges before nodes**

The trace_route function currently builds node lists, THEN fetches edges. But layer detection needs `rw_source_fqns` from edges. Restructure so the order is:

1. Fetch center node
2. Run downstream + upstream Cypher queries (get raw records)
3. Build `all_fqns` list from raw records (not TraceNode objects)
4. Fetch edges between all nodes
5. Compute `rw_source_fqns` from edges
6. Build TraceNode lists WITH layer
7. Build TraceEdge list
8. Return

Replace the section from `down_records, up_records = await _parallel_queries(...)` through the end of the return statement. The key change: build `all_fqns` from raw records:

```python
        down_records, up_records = await _parallel_queries(
            store, downstream_cypher, upstream_cypher, params
        )

        # ── Fetch edges FIRST (need rw_source_fqns for layer) ──
        all_fqns = (
            [node_fqn]
            + [r["fqn"] for r in down_records]
            + [r["fqn"] for r in up_records]
        )

        edges_cypher = (
            f"MATCH (a)-[r:{_TRACE_EDGE_TYPES}]->(b) "
            "WHERE a.fqn IN $fqns AND b.fqn IN $fqns "
            "AND a.app_name = $appName "
            "AND b.app_name = $appName "
            "RETURN DISTINCT a.fqn AS source, "
            "b.fqn AS target, type(r) AS type"
        )
        edge_records = await store.query(
            edges_cypher,
            {"fqns": all_fqns, "appName": project_id},
        )

        rw_source_fqns: set[str] = set()
        for r in edge_records:
            if r["type"] in ("READS", "WRITES"):
                rw_source_fqns.add(r["source"])

        # ── Build trace nodes with layer + sequence ────────────
        downstream_nodes = [
            TraceNode(
                fqn=r["fqn"],
                name=r["name"],
                kind=r["kind"] or "FUNCTION",
                file=r.get("file"),
                language=r.get("language"),
                depth=r["depth"],
                sequence=idx + 1,
                direction="downstream",
                layer=_detect_layer(
                    r["fqn"],
                    r["kind"] or "FUNCTION",
                    rw_source_fqns,
                ),
            )
            for idx, r in enumerate(down_records)
        ]

        upstream_nodes = [
            TraceNode(
                fqn=r["fqn"],
                name=r["name"],
                kind=r["kind"] or "FUNCTION",
                file=r.get("file"),
                language=r.get("language"),
                depth=r["depth"],
                sequence=idx + 1,
                direction="upstream",
                layer=_detect_layer(
                    r["fqn"],
                    r["kind"] or "FUNCTION",
                    rw_source_fqns,
                ),
            )
            for idx, r in enumerate(up_records)
        ]

        # ── Build edge list ────────────────────────────────────
        downstream_fqn_seq = {
            n.fqn: n.sequence for n in downstream_nodes
        }
        upstream_fqn_seq = {
            n.fqn: n.sequence for n in upstream_nodes
        }

        trace_edges = [
            TraceEdge(
                source=r["source"],
                target=r["target"],
                type=r["type"],
                sequence=downstream_fqn_seq.get(
                    r["target"],
                    upstream_fqn_seq.get(r["source"]),
                ),
            )
            for r in edge_records
        ]
        trace_edges.sort(
            key=lambda e: (e.sequence or 999, e.source)
        )

        center_layer = _detect_layer(
            node_fqn, center_kind, rw_source_fqns
        )
        all_layers = {center_layer}
        for n in downstream_nodes:
            all_layers.add(n.layer)
        for n in upstream_nodes:
            all_layers.add(n.layer)
        layers_present = [
            la for la in _LAYER_ORDER if la in all_layers
        ]

        return TraceRouteResponse(
            center_fqn=node_fqn,
            center_name=center_name,
            center_kind=center_kind,
            center_layer=center_layer,
            max_depth=max_depth,
            upstream=upstream_nodes,
            downstream=downstream_nodes,
            edges=trace_edges,
            upstream_count=len(upstream_nodes),
            downstream_count=len(downstream_nodes),
            layers_present=layers_present,
        )
```

- [ ] **Step 7: Verify syntax and lint**

Run: `python -c "import ast; ast.parse(open('app/api/analysis_views.py').read()); print('OK')"` — Expected: `OK`

Run: `uv run ruff check app/api/analysis_views.py` — Expected: `All checks passed!`

- [ ] **Step 8: Test via curl**

Run: `curl -s "http://localhost:8000/api/v1/analysis/8161cd28-0be6-41ea-af94-0383708bb90e/trace/io.github.anantharajuc.sbat.core_backend.persistence.repositories.AuditLogRepository.deleteById?max_depth=5" | python3 -m json.tool | head -30`

Expected: Each node has a `"layer"` field; center node has `"center_layer": "repository"`; response has `"layers_present": [...]`

- [ ] **Step 9: Commit**

```bash
git add cast-clone-backend/app/api/analysis_views.py cast-clone-backend/app/schemas/analysis_views.py
git commit -m "feat(api): add layer detection to trace route endpoint"
```

---

## Task 3: Add trace summary backend endpoint

**Files:**
- Modify: `cast-clone-backend/app/ai/summaries.py`
- Modify: `cast-clone-backend/app/api/analysis_views.py`

- [ ] **Step 1: Add `generate_trace_summary` to summaries.py**

Append to the end of `cast-clone-backend/app/ai/summaries.py`:

```python
TRACE_SUMMARY_SYSTEM_PROMPT = (
    "You are an expert software architect analyzing a code "
    "execution trace.\n"
    "Describe the flow in 2-3 concise paragraphs:\n"
    "- Name specific classes and methods\n"
    "- State which architectural layers are involved\n"
    "- Mention database tables touched and whether they are "
    "read or written\n"
    "- Note any patterns: fan-out, circular calls, "
    "cross-layer shortcuts\n"
    "Use markdown formatting. Be specific, not generic."
)


def compute_trace_hash(trace_context: dict[str, Any]) -> str:
    """Compute SHA-256 hash of trace topology for caching.

    Hash = SHA-256(center_fqn:sorted upstream fqns:sorted downstream fqns)
    """
    center = trace_context["center"]["fqn"]
    up = sorted(n["fqn"] for n in trace_context["upstream"])
    down = sorted(n["fqn"] for n in trace_context["downstream"])
    raw = f"{center}:{','.join(up)}:{','.join(down)}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def generate_trace_summary_text(
    client: AsyncAnthropicBedrock | AsyncOpenAI,
    model: str,
    max_tokens: int,
    trace_context: dict[str, Any],
    ai_config: EffectiveAiConfig | None = None,
) -> tuple[str, int]:
    """Call the LLM to generate a trace flow summary.

    Same dual-provider pattern as generate_summary().
    Returns (summary_text, tokens_used).
    """
    user_content = json.dumps(trace_context, default=str)

    if isinstance(client, AsyncOpenAI):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": TRACE_SUMMARY_SYSTEM_PROMPT,
                },
                {"role": "user", "content": user_content},
            ],
        }
        if ai_config and ai_config.temperature != 1.0:
            kwargs["temperature"] = ai_config.temperature
        response = await client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or ""
        usage = response.usage
        tokens = (
            (
                (usage.prompt_tokens or 0)
                + (usage.completion_tokens or 0)
            )
            if usage
            else 0
        )
        return text, tokens

    # Anthropic / Bedrock path
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=TRACE_SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    text = response.content[0].text
    tokens = (
        response.usage.input_tokens
        + response.usage.output_tokens
    )
    return text, tokens
```

- [ ] **Step 2: Add the trace summary API endpoint**

In `cast-clone-backend/app/api/analysis_views.py`, add the new endpoint. Place it right after the `trace_route()` endpoint (before `# ── 2. Path Finder`).

First update the imports at the top of the file to add `TraceSummaryResponse`:

```python
from app.schemas.analysis_views import (
    # ... existing imports ...
    TraceSummaryResponse,
)
```

Then add these imports near the top:

```python
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.postgres import get_session
from app.api.dependencies import get_current_user
from app.models.db import AiSummary, Project, User
from app.services.ai_provider import (
    create_bedrock_client,
    create_openai_client,
    get_ai_config,
)
from app.ai.summaries import (
    compute_trace_hash,
    generate_trace_summary_text,
)
from app.config import get_settings
```

Then add the endpoint:

```python
@router.get(
    "/{project_id}/trace/{node_fqn:path}/summary",
    response_model=TraceSummaryResponse,
)
async def trace_summary(
    project_id: str,
    node_fqn: str,
    max_depth: int = Query(5, ge=1, le=10),
    store: Neo4jGraphStore = Depends(get_graph_store),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> TraceSummaryResponse:
    """Generate an AI summary of a node's trace route."""
    # Get the trace data via the existing logic
    trace_resp = await trace_route(
        project_id=project_id,
        node_fqn=node_fqn,
        max_depth=max_depth,
        store=store,
    )

    if not trace_resp.upstream and not trace_resp.downstream:
        return TraceSummaryResponse(
            fqn=node_fqn,
            summary="No upstream or downstream connections found "
            "for this node.",
            layers_involved=[],
            tables_touched=[],
            cached=False,
        )

    # Build structured context for the prompt
    tables_touched = []
    for edge in trace_resp.edges:
        if edge.type in ("READS", "WRITES"):
            # Find the target node name
            target_name = edge.target.split(":")[-1]
            tables_touched.append(
                {"name": target_name, "access_type": edge.type}
            )

    trace_context = {
        "center": {
            "name": trace_resp.center_name,
            "kind": trace_resp.center_kind,
            "layer": trace_resp.center_layer,
            "fqn": trace_resp.center_fqn,
        },
        "upstream": [
            {
                "name": n.name,
                "kind": n.kind,
                "layer": n.layer,
                "fqn": n.fqn,
                "sequence": n.sequence,
            }
            for n in trace_resp.upstream
        ],
        "downstream": [
            {
                "name": n.name,
                "kind": n.kind,
                "layer": n.layer,
                "fqn": n.fqn,
                "sequence": n.sequence,
            }
            for n in trace_resp.downstream
        ],
        "tables_touched": tables_touched,
        "layers_involved": trace_resp.layers_present,
    }

    # Check cache
    current_hash = compute_trace_hash(trace_context)
    cache_key = f"trace:{node_fqn}"
    result = await session.execute(
        sa_select(AiSummary).where(
            AiSummary.project_id == project_id,
            AiSummary.node_fqn == cache_key,
        )
    )
    cached = result.scalar_one_or_none()

    if cached and cached.graph_hash == current_hash:
        return TraceSummaryResponse(
            fqn=node_fqn,
            summary=cached.summary,
            layers_involved=trace_resp.layers_present,
            tables_touched=[t["name"] for t in tables_touched],
            cached=True,
            model=cached.model,
            tokens_used=cached.tokens_used,
        )

    # Generate via LLM
    settings = get_settings()
    ai_config = await get_ai_config(session)
    if ai_config.provider == "openai":
        client = create_openai_client(ai_config)
    else:
        client = create_bedrock_client(ai_config)

    summary_text, tokens_used = await generate_trace_summary_text(
        client=client,
        model=ai_config.summary_model,
        max_tokens=settings.summary_max_tokens,
        trace_context=trace_context,
        ai_config=ai_config,
    )

    # Upsert cache
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = (
        pg_insert(AiSummary)
        .values(
            project_id=project_id,
            node_fqn=cache_key,
            summary=summary_text,
            model=ai_config.summary_model,
            graph_hash=current_hash,
            tokens_used=tokens_used,
        )
        .on_conflict_do_update(
            index_elements=["project_id", "node_fqn"],
            set_={
                "summary": summary_text,
                "model": ai_config.summary_model,
                "graph_hash": current_hash,
                "tokens_used": tokens_used,
            },
        )
    )
    await session.execute(stmt)
    await session.commit()

    return TraceSummaryResponse(
        fqn=node_fqn,
        summary=summary_text,
        layers_involved=trace_resp.layers_present,
        tables_touched=[t["name"] for t in tables_touched],
        cached=False,
        model=ai_config.summary_model,
        tokens_used=tokens_used,
    )
```

- [ ] **Step 3: Verify syntax and lint**

Run: `python -c "import ast; ast.parse(open('app/api/analysis_views.py').read()); print('OK')"` — Expected: `OK`

Run: `python -c "import ast; ast.parse(open('app/ai/summaries.py').read()); print('OK')"` — Expected: `OK`

Run: `uv run ruff check app/api/analysis_views.py app/ai/summaries.py` — Expected: `All checks passed!`

- [ ] **Step 4: Test via curl**

Run: `curl -s "http://localhost:8000/api/v1/analysis/8161cd28-0be6-41ea-af94-0383708bb90e/trace/io.github.anantharajuc.sbat.core_backend.persistence.repositories.AuditLogRepository.deleteById/summary?max_depth=5" | python3 -m json.tool | head -20`

Expected: JSON with `summary`, `layers_involved`, `tables_touched` fields. If AI is not configured, expect 500 — that's OK; the frontend will handle it gracefully.

- [ ] **Step 5: Commit**

```bash
git add cast-clone-backend/app/ai/summaries.py cast-clone-backend/app/api/analysis_views.py
git commit -m "feat(api): add AI trace summary endpoint with caching"
```

---

## Task 4: Update frontend types and API client

**Files:**
- Modify: `cast-clone-frontend/lib/types.ts:269-297`
- Modify: `cast-clone-frontend/lib/api.ts`

- [ ] **Step 1: Update TraceNode type to include layer**

In `cast-clone-frontend/lib/types.ts`, find the `TraceNode` interface and add `layer`:

```typescript
export interface TraceNode {
  fqn: string;
  name: string;
  kind: string;
  file: string | null;
  language: string | null;
  depth: number;
  sequence: number;
  direction: "upstream" | "downstream";
  layer: "api" | "service" | "repository" | "database" | "other";
}
```

- [ ] **Step 2: Update TraceRouteResponse**

```typescript
export interface TraceRouteResponse {
  center_fqn: string;
  center_name: string;
  center_kind: string;
  center_layer: string;
  max_depth: number;
  upstream: TraceNode[];
  downstream: TraceNode[];
  edges: TraceEdge[];
  upstream_count: number;
  downstream_count: number;
  layers_present: string[];
}
```

- [ ] **Step 3: Add TraceSummaryResponse**

Add after `TraceRouteResponse`:

```typescript
export interface TraceSummaryResponse {
  fqn: string;
  summary: string;
  layers_involved: string[];
  tables_touched: string[];
  cached: boolean;
  model: string | null;
  tokens_used: number | null;
}
```

- [ ] **Step 4: Add getTraceSummary to api.ts**

In `cast-clone-frontend/lib/api.ts`, add the import for `TraceSummaryResponse` alongside existing `TraceRouteResponse` import, then add the function after `getTraceRoute`:

```typescript
export async function getTraceSummary(
  projectId: string,
  nodeFqn: string,
  maxDepth: number = 5,
): Promise<TraceSummaryResponse> {
  const params = new URLSearchParams({
    max_depth: String(maxDepth),
  });
  return apiFetch<TraceSummaryResponse>(
    `/api/v1/analysis/${projectId}/trace/${encodeURIComponent(nodeFqn)}/summary?${params}`,
  );
}
```

- [ ] **Step 5: TypeScript check**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty 2>&1 | head -20`

Expected: No new errors (any pre-existing errors are unrelated).

- [ ] **Step 6: Commit**

```bash
git add cast-clone-frontend/lib/types.ts cast-clone-frontend/lib/api.ts
git commit -m "feat(ui): add trace summary types and API client"
```

---

## Task 5: Create useTraceSummary hook

**Files:**
- Create: `cast-clone-frontend/hooks/useTraceSummary.ts`

- [ ] **Step 1: Create the hook**

Create `cast-clone-frontend/hooks/useTraceSummary.ts`:

```typescript
"use client";

import { useCallback, useRef, useState } from "react";
import { getTraceSummary } from "@/lib/api";
import type { TraceSummaryResponse } from "@/lib/types";

interface UseTraceSummaryResult {
  summary: TraceSummaryResponse | null;
  isLoading: boolean;
  error: string | null;
  fetch: (projectId: string, fqn: string, maxDepth?: number) => Promise<void>;
  retry: () => void;
  clear: () => void;
}

export function useTraceSummary(): UseTraceSummaryResult {
  const [summary, setSummary] = useState<TraceSummaryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastArgs = useRef<{ projectId: string; fqn: string; maxDepth: number } | null>(null);

  const fetch = useCallback(
    async (projectId: string, fqn: string, maxDepth: number = 5) => {
      lastArgs.current = { projectId, fqn, maxDepth };
      setIsLoading(true);
      setError(null);
      try {
        const result = await getTraceSummary(projectId, fqn, maxDepth);
        setSummary(result);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Summary generation failed";
        setError(msg);
        setSummary(null);
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  const retry = useCallback(() => {
    if (lastArgs.current) {
      const { projectId, fqn, maxDepth } = lastArgs.current;
      fetch(projectId, fqn, maxDepth);
    }
  }, [fetch]);

  const clear = useCallback(() => {
    setSummary(null);
    setError(null);
    lastArgs.current = null;
  }, []);

  return { summary, isLoading, error, fetch, retry, clear };
}
```

- [ ] **Step 2: TypeScript check**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty 2>&1 | head -10`

Expected: No new errors.

- [ ] **Step 3: Commit**

```bash
git add cast-clone-frontend/hooks/useTraceSummary.ts
git commit -m "feat(ui): add useTraceSummary hook"
```

---

## Task 6: Rewrite TraceRouteModal with split-panel layout + swim-lanes + AI summary

**Files:**
- Modify: `cast-clone-frontend/components/analysis/TraceRouteModal.tsx`

This is the largest task. The component gets a full rewrite to implement:
- Split-panel layout (60% graph / 40% AI summary)
- Top-to-bottom dagre layout
- Swim-lane background bands
- Layer-colored nodes with round-rectangle shapes
- Edge styling (dashed for READS/WRITES, solid for CALLS)
- AI summary panel with loading/error/cached states

- [ ] **Step 1: Rewrite TraceRouteModal.tsx**

Replace the entire file `cast-clone-frontend/components/analysis/TraceRouteModal.tsx` with the new implementation. The file is large (~600 lines), so the implementer should write it following this structure:

**Constants section:**
- `LAYER_CONFIG` map: `{ api: { color, bandColor, label, icon }, service: {...}, ... }`
- `LAYER_ORDER`: `["api", "service", "repository", "database", "other"]`

**`buildTraceElements()` function:**
- Same logic as current but adds `layer` data attribute to each node
- Center node gets `layer` from `data.center_layer`
- Each TraceNode gets `layer` from `node.layer`
- Compound parent grouping logic stays the same

**Cytoscape stylesheet:**
- All nodes: `shape: "round-rectangle"`, `width: 50`, `height: 36`
- Label inside node: `"text-valign": "center"`, `"text-halign": "center"`
- Sequence prefix in label: `(ele) => { const s = ele.data("sequence"); return s ? "#" + s + " " + ele.data("label") : ele.data("label"); }`
- Center node: +10px larger, 3px white ring border
- Per-layer selectors: `node[layer = "api"]` → purple, `node[layer = "service"]` → blue, etc.
- WRITES edges: `"line-style": "dashed"`, `"line-color": "#EF4444"`, `"target-arrow-color": "#EF4444"`
- READS edges: `"line-style": "dashed"`, `"line-color": "#3B82F6"`, `"target-arrow-color": "#3B82F6"`
- CALLS edges: solid gray (existing style)

**`TraceGraph` component:**
- Dagre layout with `rankDir: "TB"` (top-to-bottom instead of LR)
- `nodeSep: 60`, `rankSep: 80`
- After layout runs, compute swim-lane bands:
  1. `cy.nodes().forEach()` to group by `layer` data attribute
  2. For each layer group: compute `minY - padding` and `maxY + padding`
  3. Store as state: `swimLanes: Array<{ layer, minY, maxY, color }>`
- Render swim-lane HTML overlays as absolutely positioned divs behind the canvas
- Each band: full width, colored background at 5% opacity, left-edge layer label with Lucide icon

**`AiSummaryPanel` component:**
- Uses `useTraceSummary` hook
- Loading: centered spinner + "Generating AI summary..."
- Error with "AI not configured" detection: show settings link
- Error with timeout: show retry button
- Success: render `summary.summary` with `<ReactMarkdown>` (import from `react-markdown`)
- Header: "AI Flow Summary" with optional "Cached" badge
- Footer: "Generated in Xs" or token count if available
- Empty trace: "No connections to summarize"

**`TraceRouteModal` component:**
- Split panel: `<div className="flex flex-1 min-h-0">` with `<div className="w-[60%]">` and `<div className="w-[40%] border-l">`
- Left panel: graph or list (existing toggle, now in bottom-left)
- Right panel: `<AiSummaryPanel>`
- Dialog size: `w-[85vw]` (up from 70vw)
- `useEffect`: fires both `fetchTrace` and `summaryFetch` on open
- List view: unchanged from current (shows in left panel)

- [ ] **Step 2: TypeScript check**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty 2>&1 | head -20`

Expected: No new errors.

- [ ] **Step 3: Visual smoke test**

1. Open `http://localhost:3000` in the browser
2. Navigate to a repository → Dependencies tab
3. Click on any node → click "Trace Route"
4. Verify:
   - Modal is wider (85vw)
   - Graph is on the left, AI summary on the right
   - Nodes are rectangular, colored by layer
   - Swim-lane bands visible behind nodes
   - Layout is top-to-bottom
   - AI summary shows loading spinner then content (or error if AI not configured)
   - Depth selector still works
   - List view still works
   - WRITES/READS edges are dashed

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/components/analysis/TraceRouteModal.tsx
git commit -m "feat(ui): rewrite TraceRouteModal with swim-lanes and AI summary panel"
```

---

## Task 7: Final integration verification

- [ ] **Step 1: Backend lint + syntax**

Run from `cast-clone-backend/`:
```bash
uv run ruff check app/api/analysis_views.py app/ai/summaries.py app/schemas/analysis_views.py
```
Expected: `All checks passed!`

- [ ] **Step 2: Frontend TypeScript check**

Run from `cast-clone-frontend/`:
```bash
npx tsc --noEmit --pretty
```
Expected: No new errors.

- [ ] **Step 3: Test trace route API with layer data**

```bash
curl -s "http://localhost:8000/api/v1/analysis/8dffe993-05a8-4890-b3ba-6264e11f436f/trace/io.github.anantharajuc.sbat.example.crm.user.services.PersonCommandServiceImpl.deletePerson?max_depth=5" | python3 -c "import json,sys; d=json.load(sys.stdin); print('layers:', d['layers_present']); print('center_layer:', d['center_layer']); [print(f'  {n[\"name\"]}: {n[\"layer\"]}') for n in d['downstream'][:5]]"
```

Expected output showing correct layer assignments:
```
layers: ['service', 'repository', 'database', 'other']
center_layer: service
  ResourceNotFoundException.<init>: other
  delete: repository
  findById: repository
  table:persons: database
  ...
```

- [ ] **Step 4: Visual end-to-end test in browser**

Open trace route for `deletePerson` on master branch project. Verify:
- Swim-lanes show Service → Repository → Database bands
- `table:persons` node is orange in the Database band
- AI summary panel loads on the right
- Dashed red edge from `delete` → `table:persons` (WRITES)
- Dashed blue edge from `findById` → `table:persons` (READS)

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(trace): integration fixes for trace route UX redesign"
```
