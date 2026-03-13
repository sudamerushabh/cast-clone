# Trace Route Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Trace Route modal that shows all upstream callers and downstream callees for any selected graph node, triggered via a NodeProperties button and a right-click context menu.

**Architecture:** A new `useTraceRoute` hook fires two parallel impact analysis API calls (upstream + downstream) using the existing `getImpactAnalysis` function. A new `TraceRouteModal` renders the results in three sections: upstream callers → selected node divider → downstream callees. Two existing components are extended: `NodeProperties` gets a button, `GraphView` gets a right-click callback. The graph page wires everything together with a context menu overlay.

**Tech Stack:** Next.js 14 App Router, TypeScript, Tailwind CSS, Radix UI Dialog (`@/components/ui/dialog`), lucide-react icons, existing `ImpactAnalysisResponse` type from `@/lib/types`.

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `cast-clone-frontend/hooks/useTraceRoute.ts` | Parallel upstream + downstream fetch hook |
| Create | `cast-clone-frontend/components/analysis/TraceRouteModal.tsx` | Modal rendering upstream/node/downstream |
| Modify | `cast-clone-frontend/components/graph/NodeProperties.tsx` | Add Trace Route button |
| Modify | `cast-clone-frontend/components/graph/GraphView.tsx` | Add `onNodeRightClick` prop + cxttap handler |
| Modify | `cast-clone-frontend/app/projects/[id]/graph/page.tsx` | Wire modal state, context menu, handlers |

---

## Chunk 1: Data Layer + Modal

### Task 1: `useTraceRoute` hook

**Files:**
- Create: `cast-clone-frontend/hooks/useTraceRoute.ts`

**Context:** Model after `hooks/useImpactAnalysis.ts`. The `getImpactAnalysis` function lives in `lib/api.ts` and accepts `(projectId, nodeFqn, direction, maxDepth)`. `ImpactAnalysisResponse` is in `lib/types.ts`.

- [ ] **Step 1: Create the hook file**

```typescript
// cast-clone-frontend/hooks/useTraceRoute.ts
"use client";

import { useCallback, useState } from "react";
import { getImpactAnalysis } from "@/lib/api";
import type { ImpactAnalysisResponse } from "@/lib/types";

interface UseTraceRouteResult {
  upstreamData: ImpactAnalysisResponse | null;
  downstreamData: ImpactAnalysisResponse | null;
  isLoading: boolean;
  error: string | null;
  fetchTrace: (projectId: string, fqn: string) => Promise<void>;
  clear: () => void;
}

export function useTraceRoute(): UseTraceRouteResult {
  const [upstreamData, setUpstreamData] =
    useState<ImpactAnalysisResponse | null>(null);
  const [downstreamData, setDownstreamData] =
    useState<ImpactAnalysisResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTrace = useCallback(async (projectId: string, fqn: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const [upstream, downstream] = await Promise.all([
        getImpactAnalysis(projectId, fqn, "upstream", 10),
        getImpactAnalysis(projectId, fqn, "downstream", 10),
      ]);
      setUpstreamData(upstream);
      setDownstreamData(downstream);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Trace route failed",
      );
      setUpstreamData(null);
      setDownstreamData(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setUpstreamData(null);
    setDownstreamData(null);
    setError(null);
  }, []);

  return { upstreamData, downstreamData, isLoading, error, fetchTrace, clear };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd cast-clone-frontend
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors related to `useTraceRoute.ts`.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add hooks/useTraceRoute.ts
git commit -m "feat: add useTraceRoute hook for parallel upstream/downstream fetch"
```

---

### Task 2: `TraceRouteModal` component

**Files:**
- Create: `cast-clone-frontend/components/analysis/TraceRouteModal.tsx`

**Context:**
- Uses `Dialog`, `DialogContent`, `DialogHeader`, `DialogTitle` from `@/components/ui/dialog`
- Uses `ScrollArea` from `@/components/ui/scroll-area`
- Uses `Badge` from `@/components/ui/badge`
- Uses `Separator` from `@/components/ui/separator`
- `AffectedNode` type from `@/lib/types`: `{ fqn: string; name: string; type: string; file: string | null; depth: number }`
- Depth badge colors from `ImpactPanel.tsx`:
  - depth 1 → `"bg-red-500 text-white"`
  - depth 2 → `"bg-orange-500 text-white"`
  - depth 3 → `"bg-yellow-500 text-black"`
  - depth 4 → `"bg-yellow-300 text-black"`
  - depth 5+ → `"bg-yellow-100 text-black"`
- Kind badge colors from `NodeProperties.tsx` (`KIND_COLORS` map):
  ```
  CLASS → "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
  INTERFACE → "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200"
  FUNCTION → "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
  TABLE → "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200"
  API_ENDPOINT → "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
  MODULE → "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200"
  ENUM → "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
  ```
- The `useTraceRoute` hook is called internally — modal owns the fetch lifecycle.
- Modal fires `fetch` when `open` becomes `true` and `node` is not null. Calls `clear` on close.

- [ ] **Step 1: Create the modal file**

```tsx
// cast-clone-frontend/components/analysis/TraceRouteModal.tsx
"use client"

import * as React from "react"
import { useEffect } from "react"
import { GitBranch } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useTraceRoute } from "@/hooks/useTraceRoute"
import type { AffectedNode } from "@/lib/types"

// ─── Depth badge ─────────────────────────────────────────────────────────────

const DEPTH_BADGE_CLASSES: Record<number, string> = {
  1: "bg-red-500 text-white",
  2: "bg-orange-500 text-white",
  3: "bg-yellow-500 text-black",
  4: "bg-yellow-300 text-black",
  5: "bg-yellow-100 text-black",
}

function depthBadgeClass(depth: number): string {
  return DEPTH_BADGE_CLASSES[depth] ?? DEPTH_BADGE_CLASSES[5]
}

// ─── Kind badge ──────────────────────────────────────────────────────────────

const KIND_COLORS: Record<string, string> = {
  CLASS: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  INTERFACE: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  FUNCTION: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  TABLE: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  API_ENDPOINT: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  MODULE: "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200",
  ENUM: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
}

function kindBadgeClass(kind: string): string {
  return KIND_COLORS[kind] ?? "bg-muted text-muted-foreground"
}

// ─── Node row ────────────────────────────────────────────────────────────────

function NodeRow({ node }: { node: AffectedNode }) {
  return (
    <div className="flex items-center gap-2 rounded-md px-2 py-1.5">
      <Badge
        className={`shrink-0 text-[10px] px-1.5 py-0 ${depthBadgeClass(node.depth)}`}
      >
        {node.depth}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="break-all text-xs font-medium">{node.name}</p>
        <p
          className="break-all text-[10px] text-muted-foreground"
          title={node.fqn}
        >
          {node.fqn}
        </p>
      </div>
      <Badge className={`shrink-0 text-[10px] px-1.5 py-0 ${kindBadgeClass(node.type)}`}>
        {node.type}
      </Badge>
    </div>
  )
}

// ─── Section ─────────────────────────────────────────────────────────────────

function Section({
  title,
  count,
  nodes,
  isLoading,
  emptyMessage,
}: {
  title: string
  count: number
  nodes: AffectedNode[]
  isLoading: boolean
  emptyMessage: string
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </span>
        {!isLoading && (
          <Badge variant="outline" className="text-[10px]">
            {count}
          </Badge>
        )}
      </div>
      {isLoading ? (
        <p className="py-4 text-center text-xs text-muted-foreground">
          Loading...
        </p>
      ) : nodes.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted-foreground">
          {emptyMessage}
        </p>
      ) : (
        <div className="space-y-0.5">
          {nodes.map((node) => (
            <NodeRow key={node.fqn} node={node} />
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Props ───────────────────────────────────────────────────────────────────

export interface TraceRouteNode {
  fqn: string
  name: string
  kind: string
  language?: string | null
}

interface TraceRouteModalProps {
  open: boolean
  onClose: () => void
  node: TraceRouteNode | null
  projectId: string
}

// ─── Modal ───────────────────────────────────────────────────────────────────

export function TraceRouteModal({
  open,
  onClose,
  node,
  projectId,
}: TraceRouteModalProps) {
  const { upstreamData, downstreamData, isLoading, error, fetchTrace, clear } =
    useTraceRoute()

  // Fetch when modal opens
  useEffect(() => {
    if (open && node) {
      fetchTrace(projectId, node.fqn)
    }
    if (!open) {
      clear()
    }
  }, [open, node, projectId, fetchTrace, clear])

  const upstreamNodes = upstreamData?.affected ?? []
  const downstreamNodes = downstreamData?.affected ?? []

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose() }}>
      <DialogContent className="flex max-h-[80vh] w-full max-w-2xl flex-col gap-0 p-0">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle className="flex items-center gap-2 text-base">
            <GitBranch className="size-4 text-blue-500" />
            Trace Route
          </DialogTitle>
          {node && (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="break-all text-sm font-medium">{node.name}</span>
              {node.kind && (
                <Badge className={`text-[10px] ${kindBadgeClass(node.kind)}`}>
                  {node.kind}
                </Badge>
              )}
              {node.language && (
                <Badge variant="outline" className="text-[10px]">
                  {node.language}
                </Badge>
              )}
            </div>
          )}
        </DialogHeader>

        {error ? (
          <div className="px-6 py-8 text-center text-sm text-destructive">
            {error}
          </div>
        ) : (
          <ScrollArea className="flex-1 overflow-hidden">
            <div className="space-y-0 px-6 py-4">
              {/* Upstream callers */}
              <Section
                title="Upstream Callers"
                count={upstreamNodes.length}
                nodes={upstreamNodes}
                isLoading={isLoading}
                emptyMessage="No callers found"
              />

              <Separator className="my-4" />

              {/* This node */}
              <div className="flex items-center gap-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 dark:border-blue-800 dark:bg-blue-950">
                <GitBranch className="size-3.5 shrink-0 text-blue-500" />
                <div className="min-w-0 flex-1">
                  <p className="break-all text-xs font-semibold">
                    {node?.name ?? ""}
                  </p>
                  <p
                    className="break-all text-[10px] text-muted-foreground"
                    title={node?.fqn ?? ""}
                  >
                    {node?.fqn ?? ""}
                  </p>
                </div>
                <Badge variant="outline" className="shrink-0 text-[10px]">
                  this node
                </Badge>
              </div>

              <Separator className="my-4" />

              {/* Downstream callees */}
              <Section
                title="Downstream Callees"
                count={downstreamNodes.length}
                nodes={downstreamNodes}
                isLoading={isLoading}
                emptyMessage="No callees found"
              />
            </div>
          </ScrollArea>
        )}
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 1: Create the modal file** — write the full `TraceRouteModal.tsx` code block above into `cast-clone-frontend/components/analysis/TraceRouteModal.tsx`.

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd cast-clone-frontend
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add components/analysis/TraceRouteModal.tsx
git commit -m "feat: add TraceRouteModal component"
```

---

## Chunk 2: Trigger Points + Wiring

### Task 3: Add Trace Route button to NodeProperties

**Files:**
- Modify: `cast-clone-frontend/components/graph/NodeProperties.tsx`

**Context:** The file currently has these imports at the top:
```tsx
import { Activity, Code2, FileCode2, ArrowDownToLine, ArrowUpFromLine, Route, Ruler, Gauge, X } from "lucide-react"
```
And this props interface:
```tsx
interface NodePropertiesProps {
  node: Record<string, unknown> | null
  onClose: () => void
  onViewSource?: (file: string, line: number) => void
  onShowImpact?: (fqn: string) => void
  onStartPathFrom?: (fqn: string) => void
}
```
The action buttons section (around line 197) currently reads:
```tsx
{fqn ? (
  <div className="mt-2 flex flex-col gap-2">
    <Button variant="outline" size="sm" className="w-full"
      onClick={() => onShowImpact?.(fqn)} disabled={!onShowImpact}>
      <Activity className="size-3.5" />
      Show Impact
    </Button>
    <Button variant="outline" size="sm" className="w-full"
      onClick={() => onStartPathFrom?.(fqn)} disabled={!onStartPathFrom}>
      <Route className="size-3.5" />
      Find Path
    </Button>
  </div>
) : null}
```

- [ ] **Step 1: Add `GitBranch` to the lucide-react import**

Find this line in `components/graph/NodeProperties.tsx`:
```tsx
import {
  Activity,
  Code2,
  FileCode2,
  ArrowDownToLine,
  ArrowUpFromLine,
  Route,
  Ruler,
  Gauge,
  X,
} from "lucide-react"
```
Replace with:
```tsx
import {
  Activity,
  Code2,
  FileCode2,
  ArrowDownToLine,
  ArrowUpFromLine,
  GitBranch,
  Route,
  Ruler,
  Gauge,
  X,
} from "lucide-react"
```

- [ ] **Step 2: Add `onTraceRoute` prop to interface**

Find:
```tsx
interface NodePropertiesProps {
  node: Record<string, unknown> | null
  onClose: () => void
  onViewSource?: (file: string, line: number) => void
  onShowImpact?: (fqn: string) => void
  onStartPathFrom?: (fqn: string) => void
}
```
Replace with:
```tsx
interface NodePropertiesProps {
  node: Record<string, unknown> | null
  onClose: () => void
  onViewSource?: (file: string, line: number) => void
  onShowImpact?: (fqn: string) => void
  onStartPathFrom?: (fqn: string) => void
  onTraceRoute?: (fqn: string) => void
}
```

- [ ] **Step 3: Add `onTraceRoute` to destructured props**

Find:
```tsx
export function NodeProperties({ node, onClose, onViewSource, onShowImpact, onStartPathFrom }: NodePropertiesProps) {
```
Replace with:
```tsx
export function NodeProperties({ node, onClose, onViewSource, onShowImpact, onStartPathFrom, onTraceRoute }: NodePropertiesProps) {
```

- [ ] **Step 4: Add Trace Route button below Find Path**

Find:
```tsx
    <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => onStartPathFrom?.(fqn)}
          disabled={!onStartPathFrom}
        >
          <Route className="size-3.5" />
          Find Path
        </Button>
```
Replace with:
```tsx
    <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => onStartPathFrom?.(fqn)}
          disabled={!onStartPathFrom}
        >
          <Route className="size-3.5" />
          Find Path
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => onTraceRoute?.(fqn)}
          disabled={!onTraceRoute}
        >
          <GitBranch className="size-3.5" />
          Trace Route
        </Button>
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd cast-clone-frontend
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd cast-clone-frontend
git add components/graph/NodeProperties.tsx
git commit -m "feat: add Trace Route button to NodeProperties panel"
```

---

### Task 4: Add right-click callback to GraphView

**Files:**
- Modify: `cast-clone-frontend/components/graph/GraphView.tsx`

**Context:** The `GraphViewProps` interface is at line 45. The `handleCyRef` callback registers Cytoscape events (tap, dbltap) starting around line 74. The Cytoscape right-click event is `cxttap`. `evt.renderedPosition` gives the pixel position relative to the canvas container.

- [ ] **Step 1: Add `onNodeRightClick` to `GraphViewProps` interface**

Find:
```tsx
interface GraphViewProps {
  elements: cytoscape.ElementDefinition[]
  viewMode: ViewMode
  performanceTier: "full" | "no-animation" | "simplified" | "force-drilldown"
  layoutMode?: LayoutMode
  colorBy?: "kind" | "layer"
  onNodeSelect?: (nodeData: Record<string, unknown>) => void
  onNodeDrillDown?: (fqn: string, name: string, level: string) => void
  onCyInit?: (cy: cytoscape.Core) => void
}
```
Replace with:
```tsx
interface GraphViewProps {
  elements: cytoscape.ElementDefinition[]
  viewMode: ViewMode
  performanceTier: "full" | "no-animation" | "simplified" | "force-drilldown"
  layoutMode?: LayoutMode
  colorBy?: "kind" | "layer"
  onNodeSelect?: (nodeData: Record<string, unknown>) => void
  onNodeDrillDown?: (fqn: string, name: string, level: string) => void
  onCyInit?: (cy: cytoscape.Core) => void
  onNodeRightClick?: (fqn: string, position: { x: number; y: number }) => void
}
```

- [ ] **Step 2: Add `onNodeRightClick` to destructured props**

Find:
```tsx
export function GraphView({
  elements,
  viewMode,
  performanceTier,
  layoutMode = "full",
  colorBy = "kind",
  onNodeSelect,
  onNodeDrillDown,
  onCyInit,
}: GraphViewProps) {
```
Replace with:
```tsx
export function GraphView({
  elements,
  viewMode,
  performanceTier,
  layoutMode = "full",
  colorBy = "kind",
  onNodeSelect,
  onNodeDrillDown,
  onCyInit,
  onNodeRightClick,
}: GraphViewProps) {
```

- [ ] **Step 3: Register `cxttap` event in `handleCyRef`**

Find this block (it's the last event handler before the closing of `handleCyRef`, around line 136):
```tsx
      // Click canvas background → deselect
      cy.on("tap", (event) => {
        if (event.target === cy) {
          if (onNodeSelect) {
            onNodeSelect({})
          }
        }
      })
    },
    [onNodeSelect, onNodeDrillDown, onCyInit, performanceTier]
  )
```
Replace with:
```tsx
      // Click canvas background → deselect
      cy.on("tap", (event) => {
        if (event.target === cy) {
          if (onNodeSelect) {
            onNodeSelect({})
          }
        }
      })

      // Right-click node → context menu
      // Use originalEvent.clientX/Y (viewport coordinates) so the
      // context menu can be positioned with `fixed` correctly regardless
      // of where the Cytoscape canvas sits in the page.
      cy.on("cxttap", "node", (event) => {
        const node = event.target
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const orig = (event as any).originalEvent as MouseEvent
        onNodeRightClick?.(node.id(), { x: orig.clientX, y: orig.clientY })
      })
    },
    [onNodeSelect, onNodeDrillDown, onCyInit, onNodeRightClick, performanceTier]
  )
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd cast-clone-frontend
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
cd cast-clone-frontend
git add components/graph/GraphView.tsx
git commit -m "feat: add onNodeRightClick prop and cxttap handler to GraphView"
```

---

### Task 5: Wire Trace Route in graph page

**Files:**
- Modify: `cast-clone-frontend/app/projects/[id]/graph/page.tsx`

**Context:**
- The page already imports from `@/components/analysis/*`, `@/components/graph/*`, `@/hooks/*`
- State pattern: `useState` for modal open/node/contextMenu
- The `selectedNode` state is `Record<string, unknown> | null` — use `node.id` (string) as fqn, `node.label` as name, `node.kind` as kind, `node.language` as language
- The `<GraphView>` render is around line 502, currently passing `onNodeSelect`, `onNodeDrillDown`, `onCyInit`
- The `<NodeProperties>` render is around line 570, currently passing `node`, `onClose`, `onViewSource`, `onShowImpact`, `onStartPathFrom`
- The context menu must be positioned relative to the graph container `div` (the `flex-1` div wrapping `<GraphView>`). Use a `ref` on that div to get its `getBoundingClientRect()` for correct absolute positioning.
- The `<TraceRouteModal>` and context menu are rendered at the end of the JSX tree, inside the outermost `div`.

- [ ] **Step 1: Add imports**

At the top of `app/projects/[id]/graph/page.tsx`, find the existing analysis imports line:
```tsx
import { DeadCodePanel } from "@/components/analysis/DeadCodePanel"
```
Add after it:
```tsx
import { TraceRouteModal } from "@/components/analysis/TraceRouteModal"
import type { TraceRouteNode } from "@/components/analysis/TraceRouteModal"
```

- [ ] **Step 2: Add state variables**

Find the block of `useState` declarations (around line 87–102):
```tsx
  const [deadCodeType, setDeadCodeType] = useState<"function" | "class">("function")
```
Add after it:
```tsx
  const [traceRouteOpen, setTraceRouteOpen] = useState(false)
  const [traceRouteNode, setTraceRouteNode] = useState<TraceRouteNode | null>(null)
  const [contextMenu, setContextMenu] = useState<{
    fqn: string
    x: number
    y: number
  } | null>(null)
```

- [ ] **Step 3: Add Trace Route handler**

Find the `handleCloseDeadCode` handler:
```tsx
  const handleCloseDeadCode = useCallback(() => {
    setActiveAnalysis(null)
  }, [])
```
Add after it:
```tsx
  // ─── Trace Route handlers ──────────────────────────────────────────────
  const handleTraceRoute = useCallback(
    (fqn: string) => {
      // Build TraceRouteNode from selectedNode data
      const node: TraceRouteNode = {
        fqn,
        name: typeof selectedNode?.label === "string" ? selectedNode.label : fqn,
        kind: typeof selectedNode?.kind === "string" ? selectedNode.kind : "",
        language:
          typeof selectedNode?.language === "string"
            ? selectedNode.language
            : null,
      }
      setTraceRouteNode(node)
      setTraceRouteOpen(true)
      setContextMenu(null)
    },
    [selectedNode],
  )

  const handleNodeRightClick = useCallback(
    (fqn: string, position: { x: number; y: number }) => {
      setContextMenu({ fqn, x: position.x, y: position.y })
    },
    [],
  )

  const handleContextMenuClose = useCallback(() => {
    setContextMenu(null)
  }, [])
```

- [ ] **Step 5: Attach `graphContainerRef` to the graph container div**

- [ ] **Step 5: Pass `onNodeRightClick` to `<GraphView>`**

Find:
```tsx
            <GraphView
              elements={activeElements}
              viewMode={viewMode}
              performanceTier={performanceTier}
              layoutMode={isTransactionView ? "full" : layoutMode}
              colorBy="kind"
              onNodeSelect={handleNodeSelect}
              onNodeDrillDown={handleNodeDrillDown}
              onCyInit={handleCyInit}
            />
```
Replace with:
```tsx
            <GraphView
              elements={activeElements}
              viewMode={viewMode}
              performanceTier={performanceTier}
              layoutMode={isTransactionView ? "full" : layoutMode}
              colorBy="kind"
              onNodeSelect={handleNodeSelect}
              onNodeDrillDown={handleNodeDrillDown}
              onCyInit={handleCyInit}
              onNodeRightClick={handleNodeRightClick}
            />
```

- [ ] **Step 6: Pass `onTraceRoute` to `<NodeProperties>`**

Find:
```tsx
            <NodeProperties
              node={selectedNode}
              onClose={() => setSelectedNode(null)}
              onViewSource={handleViewSource}
              onShowImpact={handleShowImpact}
              onStartPathFrom={handleStartPathFrom}
            />
```
Replace with:
```tsx
            <NodeProperties
              node={selectedNode}
              onClose={() => setSelectedNode(null)}
              onViewSource={handleViewSource}
              onShowImpact={handleShowImpact}
              onStartPathFrom={handleStartPathFrom}
              onTraceRoute={handleTraceRoute}
            />
```

- [ ] **Step 7: Add `<TraceRouteModal>` and context menu to JSX**

Find the closing of the outermost return div, just before the final `</div>`:
```tsx
      {codeViewerOpen && codeViewerFile && (
        <CodeViewer
          ...
        />
      )}
    </div>
  )
```
Add after the `<CodeViewer>` block and before the closing `</div>`:
```tsx
      {/* Trace Route modal */}
      <TraceRouteModal
        open={traceRouteOpen}
        onClose={() => setTraceRouteOpen(false)}
        node={traceRouteNode}
        projectId={projectId}
      />

      {/* Right-click context menu */}
      {contextMenu && (
        <>
          {/* Invisible backdrop to dismiss on outside click */}
          <div
            className="fixed inset-0 z-40"
            onClick={handleContextMenuClose}
          />
          <div
            className="fixed z-50 min-w-[160px] rounded-md border bg-background shadow-md"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <div className="py-1">
              <button
                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
                onClick={() => {
                  // Read node data directly from Cytoscape to avoid stale selectedNode closure
                  const cy = cyInstanceRef.current
                  const cyNode = cy?.getElementById(contextMenu.fqn)
                  const data = cyNode?.data() ?? {} as Record<string, unknown>
                  const node: TraceRouteNode = {
                    fqn: contextMenu.fqn,
                    name: typeof data.label === "string" ? data.label : contextMenu.fqn,
                    kind: typeof data.kind === "string" ? data.kind : "",
                    language: typeof data.language === "string" ? data.language : null,
                  }
                  setTraceRouteNode(node)
                  setTraceRouteOpen(true)
                  setContextMenu(null)
                }}
              >
                <GitBranch className="size-3.5 text-blue-500" />
                Trace Route
              </button>
              <button
                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
                onClick={() => {
                  handleShowImpact(contextMenu.fqn)
                  handleContextMenuClose()
                }}
              >
                <Activity className="size-3.5 text-red-500" />
                Show Impact
              </button>
              <button
                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
                onClick={() => {
                  handleStartPathFrom(contextMenu.fqn)
                  handleContextMenuClose()
                }}
              >
                <Route className="size-3.5 text-blue-500" />
                Find Path From Here
              </button>
            </div>
          </div>
        </>
      )}
```

- [ ] **Step 8: Add missing imports**

Find the existing lucide-react import in `page.tsx`:
```tsx
import { Filter, RefreshCw } from "lucide-react"
```
Replace with:
```tsx
import { Activity, Filter, GitBranch, RefreshCw, Route } from "lucide-react"
```

- [ ] **Step 9: Verify TypeScript compiles**

```bash
cd cast-clone-frontend
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 10: Start the dev server and manually verify**

```bash
cd cast-clone-frontend
npm run dev
```

Open `http://localhost:3000/projects/<any-project-id>/graph`.

**Check 1 — NodeProperties button:**
1. Click any node → NodeProperties panel opens on the right
2. Confirm "Trace Route" button appears below "Find Path"
3. Click "Trace Route" → modal opens
4. Confirm two sections: "Upstream Callers" and "Downstream Callees"
5. Confirm selected node appears as highlighted divider row in the middle
6. Confirm depth badges appear on rows (red=1, orange=2, yellow=3+)
7. Close modal with × — modal closes

**Check 2 — Right-click context menu:**
1. Right-click any node → context menu appears near cursor
2. Confirm three options: Trace Route, Show Impact, Find Path From Here
3. Click outside menu → menu dismisses
4. Right-click again → click "Trace Route" → modal opens with correct node
5. Click "Show Impact" → Impact panel opens in right panel
6. Click "Find Path From Here" → Path Finder panel opens

- [ ] **Step 11: Commit**

```bash
cd cast-clone-frontend
git add app/projects/\[id\]/graph/page.tsx
git commit -m "feat: wire TraceRouteModal and right-click context menu in graph page"
```
