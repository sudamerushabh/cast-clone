# Phase 3 M4: Impact Analysis + Path Finder UI — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add impact analysis overlay (color nodes by depth, dim unaffected, summary panel) and path finder UI (select two nodes, highlight path) to the graph explorer page.

**Architecture:** Impact analysis and path finder are overlays on the existing Cytoscape graph — no separate views. New components render summary panels and controls. Graph styling applied via Cytoscape's `cy.style()` API. State managed via `useImpactAnalysis` and `usePathFinder` hooks from M3.

**Tech Stack:** TypeScript, React 18, Cytoscape.js (via existing GraphView), Tailwind CSS, shadcn components

**Dependencies:** Phase 3 M2 (backend APIs), Phase 3 M3 (hooks + types), Phase 2 M4 (GraphView), Phase 2 M5 (NodeProperties)

---

## File Structure

```
cast-clone-frontend/
├── components/
│   ├── analysis/
│   │   ├── ImpactPanel.tsx          # CREATE — impact analysis summary + controls
│   │   └── PathFinderPanel.tsx      # CREATE — path finder controls + result
│   └── graph/
│       ├── NodeProperties.tsx       # MODIFY — add "Show Impact" button
│       └── GraphView.tsx            # READ ONLY — ref is used for cy instance
├── app/
│   └── projects/
│       └── [id]/
│           └── graph/
│               └── page.tsx         # MODIFY — integrate impact + path state
└── hooks/
    ├── useImpactAnalysis.ts         # FROM M3
    └── usePathFinder.ts             # FROM M3
```

---

## Task 1: Create ImpactPanel Component

**Files:**
- Create: `cast-clone-frontend/components/analysis/ImpactPanel.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client"

import * as React from "react"
import { Activity, X, ArrowDown, ArrowUp, ArrowLeftRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import type { ImpactAnalysisResponse } from "@/lib/types"

const DEPTH_COLORS: Record<number, string> = {
  1: "bg-red-500",
  2: "bg-orange-500",
  3: "bg-yellow-500",
  4: "bg-yellow-400",
  5: "bg-yellow-200",
}

interface ImpactPanelProps {
  data: ImpactAnalysisResponse
  isLoading: boolean
  direction: "downstream" | "upstream" | "both"
  onDirectionChange: (dir: "downstream" | "upstream" | "both") => void
  onClose: () => void
  onNodeClick?: (fqn: string) => void
}

export function ImpactPanel({
  data,
  isLoading,
  direction,
  onDirectionChange,
  onClose,
  onNodeClick,
}: ImpactPanelProps) {
  return (
    <div className="w-80 border-l bg-background flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-red-500" />
          <span className="font-semibold text-sm">Impact Analysis</span>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Direction toggle */}
      <div className="flex gap-1 p-2 border-b">
        <Button
          variant={direction === "downstream" ? "default" : "outline"}
          size="sm"
          className="flex-1 text-xs"
          onClick={() => onDirectionChange("downstream")}
        >
          <ArrowDown className="h-3 w-3 mr-1" />
          Down
        </Button>
        <Button
          variant={direction === "upstream" ? "default" : "outline"}
          size="sm"
          className="flex-1 text-xs"
          onClick={() => onDirectionChange("upstream")}
        >
          <ArrowUp className="h-3 w-3 mr-1" />
          Up
        </Button>
        <Button
          variant={direction === "both" ? "default" : "outline"}
          size="sm"
          className="flex-1 text-xs"
          onClick={() => onDirectionChange("both")}
        >
          <ArrowLeftRight className="h-3 w-3 mr-1" />
          Both
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center p-8 text-sm text-muted-foreground">
          Analyzing...
        </div>
      ) : (
        <>
          {/* Summary */}
          <div className="p-3 border-b space-y-2">
            <div className="text-xs text-muted-foreground">
              Analyzing: <span className="font-mono text-foreground">{data.node.split(".").pop()}</span>
            </div>
            <div className="text-lg font-bold">
              {data.summary.total} nodes affected
            </div>
            <div className="flex flex-wrap gap-1">
              {Object.entries(data.summary.by_type).map(([type, count]) => (
                <Badge key={type} variant="secondary" className="text-xs">
                  {count} {type}{count !== 1 ? "s" : ""}
                </Badge>
              ))}
            </div>
          </div>

          {/* Depth legend */}
          <div className="flex items-center gap-2 px-3 py-2 border-b">
            <span className="text-xs text-muted-foreground">Depth:</span>
            {[1, 2, 3, 4, 5].map((d) => (
              <div key={d} className="flex items-center gap-1">
                <div className={`w-3 h-3 rounded-full ${DEPTH_COLORS[d]}`} />
                <span className="text-xs">{d}</span>
              </div>
            ))}
          </div>

          {/* Affected nodes list */}
          <ScrollArea className="flex-1">
            <div className="p-2 space-y-1">
              {data.affected.map((node) => (
                <button
                  key={node.fqn}
                  className="w-full text-left px-2 py-1.5 rounded hover:bg-muted text-xs flex items-center gap-2"
                  onClick={() => onNodeClick?.(node.fqn)}
                >
                  <div className={`w-2 h-2 rounded-full shrink-0 ${DEPTH_COLORS[node.depth] || "bg-yellow-100"}`} />
                  <div className="min-w-0 flex-1">
                    <div className="font-mono truncate">{node.name}</div>
                    <div className="text-muted-foreground truncate">{node.type}</div>
                  </div>
                  <Badge variant="outline" className="text-[10px] shrink-0">
                    d{node.depth}
                  </Badge>
                </button>
              ))}
            </div>
          </ScrollArea>
        </>
      )}
    </div>
  )
}

/**
 * Apply impact highlighting to a Cytoscape instance.
 * Call this after receiving impact analysis data.
 */
export function applyImpactOverlay(
  cy: cytoscape.Core,
  affected: ImpactAnalysisResponse["affected"],
  startFqn: string
) {
  // Reset all nodes to dim
  cy.nodes().style("opacity", 0.2)
  cy.edges().style("opacity", 0.1)

  // Highlight start node
  const startNode = cy.getElementById(startFqn)
  if (startNode.length) {
    startNode.style({
      "background-color": "#dc2626",
      opacity: 1,
      "border-width": 3,
      "border-color": "#991b1b",
    })
  }

  // Color affected nodes by depth
  const depthColors: Record<number, string> = {
    1: "#ef4444",
    2: "#f97316",
    3: "#eab308",
    4: "#facc15",
    5: "#fef08a",
  }

  const affectedFqns = new Set<string>([startFqn])

  affected.forEach(({ fqn, depth }) => {
    affectedFqns.add(fqn)
    const node = cy.getElementById(fqn)
    if (node.length) {
      node.style({
        "background-color": depthColors[depth] || "#fef9c3",
        opacity: 1,
      })
    }
  })

  // Show edges between affected nodes
  cy.edges().forEach((edge) => {
    const src = edge.source().id()
    const tgt = edge.target().id()
    if (affectedFqns.has(src) && affectedFqns.has(tgt)) {
      edge.style({ opacity: 0.8 })
    }
  })
}

/**
 * Remove impact overlay and restore normal styling.
 */
export function clearImpactOverlay(cy: cytoscape.Core) {
  cy.nodes().removeStyle("opacity background-color border-width border-color")
  cy.edges().removeStyle("opacity")
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add components/analysis/ImpactPanel.tsx
git commit -m "feat(phase3): add ImpactPanel component with depth-colored overlay"
```

---

## Task 2: Create PathFinderPanel Component

**Files:**
- Create: `cast-clone-frontend/components/analysis/PathFinderPanel.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client"

import * as React from "react"
import { Route, X, Search } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { PathFinderResponse } from "@/lib/types"

interface PathFinderPanelProps {
  data: PathFinderResponse | null
  isLoading: boolean
  error: string | null
  selectedNodeFqn: string | null
  onFindPath: (fromFqn: string, toFqn: string) => void
  onClose: () => void
  onNodeClick?: (fqn: string) => void
}

export function PathFinderPanel({
  data,
  isLoading,
  error,
  selectedNodeFqn,
  onFindPath,
  onClose,
  onNodeClick,
}: PathFinderPanelProps) {
  const [fromFqn, setFromFqn] = React.useState("")
  const [toFqn, setToFqn] = React.useState("")

  // Auto-fill from/to when a node is selected
  React.useEffect(() => {
    if (selectedNodeFqn) {
      if (!fromFqn) {
        setFromFqn(selectedNodeFqn)
      } else if (!toFqn && selectedNodeFqn !== fromFqn) {
        setToFqn(selectedNodeFqn)
      }
    }
  }, [selectedNodeFqn, fromFqn, toFqn])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (fromFqn && toFqn) {
      onFindPath(fromFqn, toFqn)
    }
  }

  return (
    <div className="w-80 border-l bg-background flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b">
        <div className="flex items-center gap-2">
          <Route className="h-4 w-4 text-blue-500" />
          <span className="font-semibold text-sm">Path Finder</span>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="p-3 border-b space-y-3">
        <div className="space-y-1">
          <Label className="text-xs">From (click a node to set)</Label>
          <Input
            value={fromFqn}
            onChange={(e) => setFromFqn(e.target.value)}
            placeholder="source.fqn"
            className="h-8 text-xs font-mono"
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">To (click another node)</Label>
          <Input
            value={toFqn}
            onChange={(e) => setToFqn(e.target.value)}
            placeholder="target.fqn"
            className="h-8 text-xs font-mono"
          />
        </div>
        <Button
          type="submit"
          size="sm"
          className="w-full"
          disabled={!fromFqn || !toFqn || isLoading}
        >
          <Search className="h-3 w-3 mr-1" />
          {isLoading ? "Finding..." : "Find Path"}
        </Button>
      </form>

      {/* Error */}
      {error && (
        <div className="p-3 text-xs text-red-500 border-b">{error}</div>
      )}

      {/* Results */}
      {data && (
        <div className="flex-1 overflow-auto">
          {data.path_length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground text-center">
              No path found between these nodes.
            </div>
          ) : (
            <div className="p-3 space-y-3">
              <div className="text-sm font-medium">
                Path length: <Badge variant="secondary">{data.path_length}</Badge>
              </div>
              <div className="space-y-1">
                {data.nodes.map((node, idx) => (
                  <React.Fragment key={node.fqn}>
                    <button
                      className="w-full text-left px-2 py-1.5 rounded hover:bg-muted text-xs flex items-center gap-2"
                      onClick={() => onNodeClick?.(node.fqn)}
                    >
                      <div className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="font-mono truncate">{node.name}</div>
                        <div className="text-muted-foreground">{node.type}</div>
                      </div>
                    </button>
                    {idx < data.edges.length && (
                      <div className="ml-3 pl-1 border-l-2 border-blue-300 py-0.5">
                        <span className="text-[10px] text-muted-foreground ml-1">
                          {data.edges[idx].type}
                        </span>
                      </div>
                    )}
                  </React.Fragment>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Apply path highlighting to a Cytoscape instance.
 */
export function applyPathOverlay(
  cy: cytoscape.Core,
  pathData: PathFinderResponse
) {
  if (pathData.path_length === 0) return

  // Dim everything
  cy.nodes().style("opacity", 0.2)
  cy.edges().style("opacity", 0.1)

  const pathFqns = new Set(pathData.nodes.map((n) => n.fqn))

  // Highlight path nodes
  pathData.nodes.forEach((node, idx) => {
    const cyNode = cy.getElementById(node.fqn)
    if (cyNode.length) {
      const isEndpoint = idx === 0 || idx === pathData.nodes.length - 1
      cyNode.style({
        "background-color": isEndpoint ? "#3b82f6" : "#60a5fa",
        opacity: 1,
        "border-width": isEndpoint ? 3 : 1,
        "border-color": "#1d4ed8",
      })
    }
  })

  // Highlight path edges
  cy.edges().forEach((edge) => {
    const src = edge.source().id()
    const tgt = edge.target().id()
    if (pathFqns.has(src) && pathFqns.has(tgt)) {
      edge.style({
        opacity: 1,
        "line-color": "#3b82f6",
        width: 3,
      })
    }
  })
}

/**
 * Remove path overlay.
 */
export function clearPathOverlay(cy: cytoscape.Core) {
  cy.nodes().removeStyle("opacity background-color border-width border-color")
  cy.edges().removeStyle("opacity line-color width")
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add components/analysis/PathFinderPanel.tsx
git commit -m "feat(phase3): add PathFinderPanel component with path overlay"
```

---

## Task 3: Add "Show Impact" Button to NodeProperties

**Files:**
- Modify: `cast-clone-frontend/components/graph/NodeProperties.tsx`

- [ ] **Step 1: Add the button to NodeProperties**

Add a new prop `onShowImpact` to the `NodePropertiesProps` interface:

```typescript
interface NodePropertiesProps {
  node: Record<string, unknown> | null
  onClose: () => void
  onViewSource?: (file: string, line: number) => void
  onShowImpact?: (fqn: string) => void
  onStartPathFrom?: (fqn: string) => void
}
```

Add two buttons after the "View Source" button in the component JSX:

```tsx
{onShowImpact && node?.fqn && (
  <Button
    variant="outline"
    size="sm"
    className="w-full"
    onClick={() => onShowImpact(node.fqn as string)}
  >
    <Activity className="h-3 w-3 mr-1" />
    Show Impact
  </Button>
)}

{onStartPathFrom && node?.fqn && (
  <Button
    variant="outline"
    size="sm"
    className="w-full"
    onClick={() => onStartPathFrom(node.fqn as string)}
  >
    <Route className="h-3 w-3 mr-1" />
    Find Path From Here
  </Button>
)}
```

Add the `Activity` and `Route` imports from `lucide-react`.

- [ ] **Step 2: Verify compilation**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add components/graph/NodeProperties.tsx
git commit -m "feat(phase3): add Show Impact and Find Path buttons to NodeProperties"
```

---

## Task 4: Integrate Impact + Path into Graph Page

**Files:**
- Modify: `cast-clone-frontend/app/projects/[id]/graph/page.tsx`

- [ ] **Step 1: Add state and hooks**

Add to the imports:

```typescript
import { useImpactAnalysis } from "@/hooks/useImpactAnalysis"
import { usePathFinder } from "@/hooks/usePathFinder"
import { ImpactPanel, applyImpactOverlay, clearImpactOverlay } from "@/components/analysis/ImpactPanel"
import { PathFinderPanel, applyPathOverlay, clearPathOverlay } from "@/components/analysis/PathFinderPanel"
```

Add state inside the component:

```typescript
const [activeAnalysis, setActiveAnalysis] = React.useState<"impact" | "path" | null>(null)
const [impactDirection, setImpactDirection] = React.useState<"downstream" | "upstream" | "both">("downstream")
const impact = useImpactAnalysis()
const pathFinder = usePathFinder()
const cyRef = React.useRef<cytoscape.Core | null>(null)
```

- [ ] **Step 2: Add handler functions**

```typescript
const handleShowImpact = React.useCallback(
  async (fqn: string) => {
    setActiveAnalysis("impact")
    await impact.analyze(params.id, fqn, impactDirection)
  },
  [impact, params.id, impactDirection]
)

const handleImpactDirectionChange = React.useCallback(
  async (dir: "downstream" | "upstream" | "both") => {
    setImpactDirection(dir)
    if (impact.data) {
      await impact.analyze(params.id, impact.data.node, dir)
    }
  },
  [impact, params.id]
)

const handleCloseImpact = React.useCallback(() => {
  setActiveAnalysis(null)
  impact.clear()
  if (cyRef.current) clearImpactOverlay(cyRef.current)
}, [impact])

const handleStartPathFrom = React.useCallback((fqn: string) => {
  setActiveAnalysis("path")
}, [])

const handleFindPath = React.useCallback(
  async (fromFqn: string, toFqn: string) => {
    await pathFinder.findPath(params.id, fromFqn, toFqn)
  },
  [pathFinder, params.id]
)

const handleClosePath = React.useCallback(() => {
  setActiveAnalysis(null)
  pathFinder.clear()
  if (cyRef.current) clearPathOverlay(cyRef.current)
}, [pathFinder])
```

- [ ] **Step 3: Apply overlays when data changes**

```typescript
// Apply impact overlay when data arrives
React.useEffect(() => {
  if (cyRef.current && impact.data && activeAnalysis === "impact") {
    applyImpactOverlay(cyRef.current, impact.data.affected, impact.data.node)
  }
}, [impact.data, activeAnalysis])

// Apply path overlay when data arrives
React.useEffect(() => {
  if (cyRef.current && pathFinder.data && activeAnalysis === "path") {
    applyPathOverlay(cyRef.current, pathFinder.data)
  }
}, [pathFinder.data, activeAnalysis])
```

- [ ] **Step 4: Add panels to the JSX layout**

In the main layout, add the ImpactPanel and PathFinderPanel alongside the existing NodeProperties panel:

```tsx
{/* Right panels — show one at a time */}
{activeAnalysis === "impact" && impact.data ? (
  <ImpactPanel
    data={impact.data}
    isLoading={impact.isLoading}
    direction={impactDirection}
    onDirectionChange={handleImpactDirectionChange}
    onClose={handleCloseImpact}
    onNodeClick={(fqn) => {
      // Select the node in the graph
      const node = cyRef.current?.getElementById(fqn)
      if (node?.length) {
        node.select()
      }
    }}
  />
) : activeAnalysis === "path" ? (
  <PathFinderPanel
    data={pathFinder.data}
    isLoading={pathFinder.isLoading}
    error={pathFinder.error}
    selectedNodeFqn={selectedNode?.fqn as string | null}
    onFindPath={handleFindPath}
    onClose={handleClosePath}
    onNodeClick={(fqn) => {
      const node = cyRef.current?.getElementById(fqn)
      if (node?.length) {
        node.select()
      }
    }}
  />
) : selectedNode ? (
  <NodeProperties
    node={selectedNode}
    onClose={() => setSelectedNode(null)}
    onViewSource={handleViewSource}
    onShowImpact={handleShowImpact}
    onStartPathFrom={handleStartPathFrom}
  />
) : null}
```

- [ ] **Step 5: Pass cyRef to GraphView**

Ensure the `GraphView` component passes back the cy instance. If GraphView has an `onCyInit` or `cyRef` prop, use it. If not, add a callback:

```tsx
<GraphView
  elements={elements}
  viewMode={viewMode}
  onNodeSelect={handleNodeSelect}
  onNodeDrillDown={handleDrillDown}
  onCyReady={(cy) => { cyRef.current = cy }}
/>
```

If `GraphView` doesn't support `onCyReady`, modify `GraphView.tsx` to accept and call it:

```tsx
// In GraphView props interface
onCyReady?: (cy: cytoscape.Core) => void

// In the CytoscapeComponent callback
cy={(cy) => {
  cyInstanceRef.current = cy
  onCyReady?.(cy)
}}
```

- [ ] **Step 6: Verify compilation and manual test**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 7: Commit**

```bash
cd cast-clone-frontend
git add app/projects/[id]/graph/page.tsx components/graph/GraphView.tsx
git commit -m "feat(phase3): integrate impact analysis and path finder into graph page"
```
