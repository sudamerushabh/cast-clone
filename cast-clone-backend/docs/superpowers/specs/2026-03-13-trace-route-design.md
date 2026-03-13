# Trace Route Feature Design

**Date:** 2026-03-13

---

## Goal

Add a "Trace Route" feature to the graph explorer that shows the full through-path of any selected node — all upstream callers and all downstream callees — displayed in a self-contained modal popup.

## Architecture

Two parallel calls to the existing impact analysis API (no new backend endpoints). A new React hook manages fetching, a new modal component renders the result, and two existing components are extended to add trigger points.

## Tech Stack

- **Frontend:** Next.js 14+ (App Router), TypeScript, Tailwind CSS, Radix UI Dialog
- **Graph:** Cytoscape.js (right-click event via `cy.on('cxttap')`)
- **Backend:** Existing FastAPI endpoints — no changes required

---

## Trigger Points

### 1. NodeProperties Panel Button

A "Trace Route" button is added to `components/graph/NodeProperties.tsx`, placed below the existing "Show Impact" and "Find Path" buttons. Uses a `GitBranch` icon from lucide-react. Disabled when no `fqn` is available.

### 2. Right-Click Context Menu on Graph Nodes

`components/graph/GraphView.tsx` listens for Cytoscape's `cxttap` event on nodes. On right-click, a small absolutely-positioned context menu `div` appears at cursor coordinates, containing three actions:
- Trace Route
- Show Impact
- Find Path From Here

The menu is dismissed on click-outside or `Escape` key. It is rendered inside the graph page component, not inside GraphView itself, to keep GraphView's concerns narrow. GraphView exposes an `onNodeRightClick` callback prop: `(fqn: string, position: { x: number; y: number }) => void`.

---

## Data Flow

When the modal opens for a node with a given `fqn`:

1. `useTraceRoute` hook fires two parallel requests:
   - `GET /api/v1/analysis/{projectId}/impact/{fqn}?direction=upstream&max_depth=10`
   - `GET /api/v1/analysis/{projectId}/impact/{fqn}?direction=downstream&max_depth=10`
2. Both resolve into `ImpactAnalysisResponse` (existing type from `@/lib/types`).
3. Hook exposes: `{ upstreamData, downstreamData, isLoading, error, fetch, clear }`.
4. Modal renders from this data — no graph overlay, no node click actions.

---

## Modal Layout

A centered Radix UI `Dialog` (using existing `@/components/ui/dialog`). Fixed width ~600px, max-height 80vh, internal `ScrollArea` for overflow.

```
┌─────────────────────────────────────────┐
│  🔀 Trace Route              [X close]  │
│  UserServiceImpl · CLASS · java         │
├─────────────────────────────────────────┤
│  UPSTREAM CALLERS (N)                   │
│    [depth 1] UserController             │
│              com.example.UserController │
│    [depth 1] AuthController             │
│    [depth 2] ApiGatewayFilter           │
│    ...                                  │
├─────────────────────────────────────────┤
│  ▶ UserServiceImpl         [this node]  │
│    com.example.UserServiceImpl          │
├─────────────────────────────────────────┤
│  DOWNSTREAM CALLEES (N)                 │
│    [depth 1] UserRepository             │
│    [depth 2] UserEntity                 │
│    [depth 3] users (TABLE)              │
│    ...                                  │
└─────────────────────────────────────────┘
```

**Depth badges** reuse the color scale from `ImpactPanel`:
- depth 1 → red (`bg-red-500 text-white`)
- depth 2 → orange (`bg-orange-500 text-white`)
- depth 3 → yellow (`bg-yellow-500 text-black`)
- depth 4+ → yellow-light

Each row shows:
- Depth badge
- Node name (bold, `break-all`)
- FQN (`text-muted-foreground`, `break-all`, `title` tooltip for full value)
- Type badge (CLASS, FUNCTION, TABLE, etc.) using existing `KIND_COLORS` palette

Rows are read-only — no click actions.

**Empty states:**
- Upstream section: "No callers found" if 0 upstream results
- Downstream section: "No callees found" if 0 downstream results
- Loading: spinner/text in each section independently (upstream may load before downstream)
- Error: inline error message per section

---

## New Files

### `hooks/useTraceRoute.ts`

```typescript
interface UseTraceRouteResult {
  upstreamData: ImpactAnalysisResponse | null
  downstreamData: ImpactAnalysisResponse | null
  isLoading: boolean
  error: string | null
  fetch: (projectId: string, fqn: string) => void
  clear: () => void
}
```

Calls both directions in parallel via `Promise.all`. Sets `isLoading` true for the duration of both calls. On any error, sets `error` and leaves data as `null`.

### `components/analysis/TraceRouteModal.tsx`

Props:
```typescript
interface TraceRouteModalProps {
  open: boolean
  onClose: () => void
  node: { fqn: string; name: string; kind: string; language?: string } | null
  projectId: string
}
```

Internally uses `useTraceRoute` hook. Fires `fetch` when `open` becomes true and `node` is set. Calls `clear` when closed.

---

## Modified Files

### `components/graph/NodeProperties.tsx`

Add prop: `onTraceRoute?: (fqn: string) => void`

Add button below "Find Path":
```tsx
<Button variant="outline" size="sm" className="w-full"
  onClick={() => onTraceRoute?.(fqn)} disabled={!onTraceRoute}>
  <GitBranch className="size-3.5" />
  Trace Route
</Button>
```

### `components/graph/GraphView.tsx`

Add prop: `onNodeRightClick?: (fqn: string, position: { x: number; y: number }) => void`

In the Cytoscape event setup:
```typescript
cy.on('cxttap', 'node', (evt) => {
  const node = evt.target
  const renderedPos = evt.renderedPosition
  onNodeRightClick?.(node.id(), { x: renderedPos.x, y: renderedPos.y })
})
```

### `app/projects/[id]/graph/page.tsx`

Add state:
```typescript
const [traceRouteOpen, setTraceRouteOpen] = useState(false)
const [traceRouteNode, setTraceRouteNode] = useState<TraceRouteNode | null>(null)
const [contextMenu, setContextMenu] = useState<{ fqn: string; x: number; y: number } | null>(null)
```

Add handlers:
- `handleTraceRoute(fqn)` — sets `traceRouteNode` from selected node data, opens modal
- `handleNodeRightClick(fqn, pos)` — sets `contextMenu` state
- `handleContextMenuClose()` — clears `contextMenu`

Render:
- `<TraceRouteModal>` wired to state
- Context menu `div` positioned absolutely over the graph container, dismissed on outside click/Escape

---

## Right-Click Context Menu

Rendered as a plain `div` with shadow and border (Tailwind), positioned at `{ x, y }` relative to the graph container element. Contains three `button` elements:

```
┌──────────────────────┐
│  🔀 Trace Route      │
│  ⚡ Show Impact      │
│  → Find Path From    │
└──────────────────────┘
```

Clicking any option: fires the relevant handler and closes the menu. Click-outside and `Escape` key close it without action.

---

## Out of Scope

- No backend changes — all data comes from existing impact analysis endpoints
- No graph canvas overlay when modal is open
- No interactive node clicks inside the modal
- No persistence of trace route results
- No export of trace route data
