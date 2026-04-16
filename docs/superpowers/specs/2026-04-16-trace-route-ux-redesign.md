# Trace Route UX Redesign + AI Flow Summary

**Date:** 2026-04-16
**Status:** Approved
**Scope:** TraceRouteModal frontend component + new backend trace summary endpoint

---

## Problem

The current trace route modal has three issues:

1. **Plain circle nodes** with no visual hierarchy — all functions, repositories, and tables look identical
2. **No architectural layer distinction** — users can't tell at a glance which layer (controller, service, repository, database) a node belongs to
3. **No AI explanation** — users must manually interpret the graph to understand the flow

## Solution Overview

Three changes to the trace route modal:

1. **Swim-lane graph** — Vertical top-to-bottom layout with colored horizontal bands per architectural layer
2. **Layer-aware node styling** — Distinct colors and shapes per layer, detected server-side
3. **AI flow summary** — Right sidebar panel with auto-generated narrative explaining the trace

---

## 1. Layout: Split-Panel Dialog

The dialog becomes a two-panel layout:

- **Size:** `h-[80vh] w-[85vw]` (wider than current 70vw)
- **Left panel (60%):** Graph or List view with swim-lanes
- **Right panel (40%):** AI-generated flow summary
- **Header:** Unchanged (node name, kind badge, language badge, depth selector, close button)
- **Graph/List toggle:** Bottom-left of graph panel area
- **Right panel:** Own vertical scroll, fixed header "AI Flow Summary"

```
+-----------------------------------+------------------------+
| Header: Trace Route  deleteById   | DEPTH [5]  Graph/List X|
+-----------------------------------+------------------------+
|                                   | AI Flow Summary        |
|  [Controller band]                |                        |
|    verifyAccount ──────┐          | This trace shows a     |
|  [Service band]        │          | delete operation...    |
|    verifyAccount <─────┘          |                        |
|        |                          | **Key observations:**  |
|  [Repository band]                | - Single DB table      |
|    deleteById (selected)          | - 2-hop chain          |
|        |                          |                        |
|  [Database band]                  | Generated in 1.2s      |
|    users                          |                        |
+-----------------------------------+------------------------+
```

---

## 2. Swim-Lane Graph Visualization

### 2a. Backend: Layer Detection

Add a `layer` field to the `TraceNode` schema. Layer is resolved server-side using heuristic rules.

**Layer classification rules (applied in order):**

| Layer | Rule | Priority |
|-------|------|----------|
| `database` | `kind IN (TABLE, STORED_PROCEDURE, VIEW, COLUMN)` | 1 (check first) |
| `api` | `kind IN (API_ENDPOINT, ROUTE)` OR fqn matches `(?i)controller` | 2 |
| `repository` | fqn matches `(?i)(repository\|repo)` OR node is source of a READS/WRITES edge in the trace edges list | 3 |
| `service` | fqn matches `(?i)service` | 4 |
| `other` | Everything else | 5 (fallback) |

Rules checked in priority order; first match wins.

**Schema change — `TraceNode`:**

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
    layer: str      # NEW: "api" | "service" | "repository" | "database" | "other"
```

**`TraceRouteResponse`** also gets:

```python
class TraceRouteResponse(BaseModel):
    # ... existing fields ...
    layers_present: list[str]  # NEW: ordered list of layers in the trace
```

### 2b. Frontend: Swim-Lane Rendering

**Layout:** Dagre with `rankDir: "TB"` (top-to-bottom) instead of current "LR".

**Swim-lane bands:** After dagre layout runs, compute the Y-extent of nodes in each layer and draw colored background bands. Implementation:

1. Group nodes by `layer` field
2. For each layer group, find min/max Y positions of its nodes
3. Render HTML overlay divs (absolute positioned behind the Cytoscape canvas) with:
   - Background color at 5% opacity
   - Left-edge label with layer name + icon
   - Full-width horizontal band

**Layer visual properties:**

| Layer | Band Color | Node Color | Icon |
|-------|-----------|------------|------|
| `api` | `#A855F7` 5% | `#A855F7` (purple) | Globe |
| `service` | `#3B82F6` 5% | `#3B82F6` (blue) | Cog |
| `repository` | `#10B981` 5% | `#10B981` (green) | Archive |
| `database` | `#F97316` 5% | `#F97316` (orange) | Database |
| `other` | `#6B7280` 5% | `#6B7280` (gray) | Circle |

**Node styling:**
- Shape: `round-rectangle` for all (consistent, clean)
- Size: 50w x 36h (wider than tall to fit labels inside)
- Label inside the node (not below)
- Center node: same shape with 3px white ring border + larger size (60x42)
- Sequence badge: `#N` prefix in label text

**Edge styling:**
- Sequence number as bold blue label on edge
- WRITES edges: dashed line, red-tinted (`#EF4444`)
- READS edges: dashed line, blue-tinted (`#3B82F6`)
- CALLS edges: solid line, gray (`#94A3B8`)

---

## 3. AI Trace Summary

### 3a. Backend Endpoint

```
GET /api/v1/analysis/{project_id}/trace/{node_fqn:path}/summary
    ?max_depth=5  (optional, default 5)
```

**Response:**

```python
class TraceSummaryResponse(BaseModel):
    fqn: str
    summary: str              # Markdown text, 2-3 paragraphs
    layers_involved: list[str]
    tables_touched: list[str]
    cached: bool
    model: str | None = None
    tokens_used: int | None = None
```

### 3b. Implementation

1. **Get trace data** — Call the existing `trace_route()` logic internally (not HTTP, direct function call) to get upstream/downstream/edges
2. **Build prompt context** — Structured JSON of the trace topology:
   ```json
   {
     "center": {"name": "deleteById", "kind": "FUNCTION", "layer": "repository", "fqn": "..."},
     "upstream": [{"name": "verifyAccount", "kind": "FUNCTION", "layer": "service", "edge_type": "CALLS"}],
     "downstream": [{"name": "users", "kind": "TABLE", "layer": "database", "edge_type": "WRITES"}],
     "tables_touched": [{"name": "users", "access_type": "WRITES"}],
     "layers_involved": ["api", "service", "repository", "database"]
   }
   ```
3. **Call LLM** — Same provider infrastructure as existing summaries (`ai_provider.py`). Claude Sonnet, max 512 tokens.
4. **Cache** — Store in `AiSummary` table with `graph_hash` computed from the trace topology (SHA-256 of sorted upstream FQNs + downstream FQNs + edge types). Cache invalidates when the trace changes.
5. **Return** — One-shot JSON response (not streaming).

### 3c. Prompt

```
SYSTEM:
You are an expert software architect analyzing a code execution trace.
Describe the flow in 2-3 concise paragraphs:
- Name specific classes and methods
- State which architectural layers are involved
- Mention database tables touched and whether they are read or written
- Note any patterns: fan-out, circular calls, cross-layer shortcuts
Use markdown formatting. Be specific, not generic.

USER:
<trace topology JSON>
```

### 3d. Frontend Panel

- **Loading state:** Spinner with "Generating AI summary..."
- **Success state:** Rendered markdown using react-markdown or a safe markdown renderer
- **Cached state:** Same as success, with subtle "Cached" badge in header
- **Error states:**
  - AI timeout (30s): "Summary unavailable" + retry button
  - AI not configured: "Configure AI provider in Settings to enable trace summaries" with link to `/settings/system`
  - Empty trace (0+0): Skip AI call, show "No connections to summarize"
- **Auto-trigger:** AI summary request fires when modal opens (same `useEffect` that fetches the trace)

### 3e. Frontend Hook

New `useTraceSummary` hook:

```typescript
interface UseTraceSummaryResult {
  summary: TraceSummaryResponse | null;
  isLoading: boolean;
  error: string | null;
  fetch: (projectId: string, fqn: string, maxDepth: number) => Promise<void>;
  retry: () => void;
  clear: () => void;
}
```

---

## 4. Files to Create/Modify

### Backend

| File | Change |
|------|--------|
| `app/schemas/analysis_views.py` | Add `layer` to `TraceNode`, add `layers_present` to `TraceRouteResponse`, add `TraceSummaryResponse` |
| `app/api/analysis_views.py` | Add layer detection logic in `trace_route()`, add `GET .../trace/{fqn}/summary` endpoint |
| `app/ai/summaries.py` | Add `generate_trace_summary()` function (parallel to existing `generate_summary()`) |

### Frontend

| File | Change |
|------|--------|
| `lib/types.ts` | Add `layer` to `TraceNode`, add `layers_present` to `TraceRouteResponse`, add `TraceSummaryResponse` |
| `lib/api.ts` | Add `getTraceSummary()` function |
| `hooks/useTraceSummary.ts` | New hook for AI summary fetching |
| `components/analysis/TraceRouteModal.tsx` | Rewrite: split-panel layout, swim-lane graph, AI summary panel |

---

## 5. What This Does NOT Include

- Sequence diagram view (Tier 2 future)
- Click-to-navigate to source code (Tier 2 future)
- Animated flow visualization (Tier 3 future)
- Streaming AI response (unnecessary for ~200 token summary)
- Edge type toggle UI (Tier 2 future)
