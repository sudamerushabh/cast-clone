# Phase 3 M5: Community Coloring + Circular Dependencies + Dead Code — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add community coloring toggle to the graph toolbar, a circular dependency panel listing cycles, and a dead code candidates panel with a sortable table.

**Architecture:** All three features are overlays on the existing graph view. Community coloring maps `communityId` to a color palette via Cytoscape styling. Circular dependencies and dead code are rendered as list panels. Data is fetched via `useAnalysisData` hook from M3.

**Tech Stack:** TypeScript, React 18, Cytoscape.js, Tailwind CSS, shadcn components

**Dependencies:** Phase 3 M2 (backend APIs), Phase 3 M3 (hooks + types), Phase 3 M4 (graph page integration pattern)

---

## File Structure

```
cast-clone-frontend/
├── components/
│   ├── analysis/
│   │   ├── CommunityToggle.tsx        # CREATE — toolbar toggle + Cytoscape coloring
│   │   ├── CircularDepsPanel.tsx       # CREATE — cycle list panel
│   │   └── DeadCodePanel.tsx          # CREATE — sortable dead code table
│   └── graph/
│       └── GraphToolbar.tsx           # MODIFY — add community toggle + analysis buttons
├── app/
│   └── projects/
│       └── [id]/
│           └── graph/
│               └── page.tsx           # MODIFY — integrate panels
└── hooks/
    └── useAnalysisData.ts             # FROM M3
```

---

## Prerequisite Note: `communityId` in Graph Elements

The community coloring feature reads `node.data("communityId")` from Cytoscape elements. GDS Louvain (M1) writes `communityId` directly to Neo4j Class nodes. The Phase 2 graph API already returns all node properties (via the `properties` dict in `GraphNodeResponse`), so `communityId` will flow through automatically. If community coloring doesn't work, verify that `communityId` is included in the node properties returned by the graph query endpoints.

The existing Phase 1 enricher used `community_id` (snake_case). M1 standardizes on `communityId` (camelCase) to match GDS conventions. Any tests referencing `community_id` should be updated.

---

## Task 1: Create CommunityToggle Component

**Files:**
- Create: `cast-clone-frontend/components/analysis/CommunityToggle.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client"

import * as React from "react"
import { Palette } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

const COMMUNITY_PALETTE = [
  "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
  "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#84cc16",
  "#06b6d4", "#e11d48", "#a855f7", "#10b981", "#d946ef",
]

interface CommunityToggleProps {
  enabled: boolean
  onToggle: () => void
}

export function CommunityToggle({ enabled, onToggle }: CommunityToggleProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant={enabled ? "default" : "outline"}
          size="icon"
          className="h-8 w-8"
          onClick={onToggle}
        >
          <Palette className="h-4 w-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        {enabled ? "Hide community colors" : "Show community colors"}
      </TooltipContent>
    </Tooltip>
  )
}

/**
 * Apply community coloring to Cytoscape nodes.
 * Nodes with a communityId data property get colored.
 */
export function applyCommunityColors(cy: cytoscape.Core) {
  cy.nodes().forEach((node) => {
    const communityId = node.data("communityId")
    if (communityId !== undefined && communityId !== null) {
      node.style(
        "background-color",
        COMMUNITY_PALETTE[communityId % COMMUNITY_PALETTE.length]
      )
    }
  })
}

/**
 * Remove community coloring — restore default styles.
 */
export function clearCommunityColors(cy: cytoscape.Core) {
  cy.nodes().removeStyle("background-color")
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add components/analysis/CommunityToggle.tsx
git commit -m "feat(phase3): add CommunityToggle with color palette for graph nodes"
```

---

## Task 2: Create CircularDepsPanel Component

**Files:**
- Create: `cast-clone-frontend/components/analysis/CircularDepsPanel.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client"

import * as React from "react"
import { RefreshCcw, X, AlertTriangle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { CircularDependenciesResponse } from "@/lib/types"

interface CircularDepsPanelProps {
  data: CircularDependenciesResponse | null
  isLoading: boolean
  level: "module" | "class"
  onLevelChange: (level: "module" | "class") => void
  onClose: () => void
  onCycleClick?: (cycleFqns: string[]) => void
}

export function CircularDepsPanel({
  data,
  isLoading,
  level,
  onLevelChange,
  onClose,
  onCycleClick,
}: CircularDepsPanelProps) {
  return (
    <div className="w-80 border-l bg-background flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b">
        <div className="flex items-center gap-2">
          <RefreshCcw className="h-4 w-4 text-red-500" />
          <span className="font-semibold text-sm">Circular Dependencies</span>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Level toggle */}
      <div className="flex gap-1 p-2 border-b">
        <Button
          variant={level === "module" ? "default" : "outline"}
          size="sm"
          className="flex-1 text-xs"
          onClick={() => onLevelChange("module")}
        >
          Module
        </Button>
        <Button
          variant={level === "class" ? "default" : "outline"}
          size="sm"
          className="flex-1 text-xs"
          onClick={() => onLevelChange("class")}
        >
          Class
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center p-8 text-sm text-muted-foreground">
          Detecting cycles...
        </div>
      ) : data ? (
        <>
          <div className="px-3 py-2 border-b">
            <div className="text-sm font-medium">
              {data.total} cycle{data.total !== 1 ? "s" : ""} found
            </div>
          </div>

          <ScrollArea className="flex-1">
            <div className="p-2 space-y-2">
              {data.cycles.length === 0 && (
                <div className="p-4 text-sm text-muted-foreground text-center">
                  No circular dependencies detected.
                </div>
              )}
              {data.cycles.map((cycle, idx) => (
                <button
                  key={idx}
                  className="w-full text-left p-2 rounded border hover:bg-muted"
                  onClick={() => onCycleClick?.(cycle.cycle)}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <AlertTriangle className="h-3 w-3 text-red-500 shrink-0" />
                    <Badge variant="destructive" className="text-[10px]">
                      length {cycle.cycle_length}
                    </Badge>
                  </div>
                  <div className="text-xs font-mono space-y-0.5">
                    {cycle.cycle.map((name, i) => (
                      <div key={i} className="truncate text-muted-foreground">
                        {i > 0 && <span className="text-red-400 mr-1">&rarr;</span>}
                        {name}
                      </div>
                    ))}
                  </div>
                </button>
              ))}
            </div>
          </ScrollArea>
        </>
      ) : null}
    </div>
  )
}

/**
 * Highlight a circular dependency cycle on the graph.
 */
export function highlightCycle(cy: cytoscape.Core, cycleFqns: string[]) {
  // Dim everything
  cy.nodes().style("opacity", 0.2)
  cy.edges().style("opacity", 0.1)

  const cycleSet = new Set(cycleFqns)

  // Highlight cycle nodes
  cycleFqns.forEach((fqn) => {
    const node = cy.getElementById(fqn)
    if (node.length) {
      node.style({
        "background-color": "#ef4444",
        opacity: 1,
        "border-width": 2,
        "border-color": "#dc2626",
      })
    }
  })

  // Highlight edges between cycle nodes
  cy.edges().forEach((edge) => {
    const src = edge.source().id()
    const tgt = edge.target().id()
    if (cycleSet.has(src) && cycleSet.has(tgt)) {
      edge.style({
        opacity: 1,
        "line-color": "#ef4444",
        width: 3,
      })
    }
  })
}

export function clearCycleHighlight(cy: cytoscape.Core) {
  cy.nodes().removeStyle("opacity background-color border-width border-color")
  cy.edges().removeStyle("opacity line-color width")
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add components/analysis/CircularDepsPanel.tsx
git commit -m "feat(phase3): add CircularDepsPanel with cycle highlighting"
```

---

## Task 3: Create DeadCodePanel Component

**Files:**
- Create: `cast-clone-frontend/components/analysis/DeadCodePanel.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client"

import * as React from "react"
import { Trash2, X, ArrowUpDown } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { DeadCodeResponse } from "@/lib/types"

type SortField = "name" | "loc" | "path"
type SortDir = "asc" | "desc"

interface DeadCodePanelProps {
  data: DeadCodeResponse | null
  isLoading: boolean
  typeFilter: "function" | "class"
  onTypeChange: (type: "function" | "class") => void
  onClose: () => void
  onCandidateClick?: (fqn: string) => void
}

export function DeadCodePanel({
  data,
  isLoading,
  typeFilter,
  onTypeChange,
  onClose,
  onCandidateClick,
}: DeadCodePanelProps) {
  const [sortField, setSortField] = React.useState<SortField>("loc")
  const [sortDir, setSortDir] = React.useState<SortDir>("desc")

  const sorted = React.useMemo(() => {
    if (!data) return []
    return [...data.candidates].sort((a, b) => {
      let cmp = 0
      if (sortField === "name") cmp = a.name.localeCompare(b.name)
      else if (sortField === "loc") cmp = (a.loc ?? 0) - (b.loc ?? 0)
      else if (sortField === "path") cmp = (a.path ?? "").localeCompare(b.path ?? "")
      return sortDir === "desc" ? -cmp : cmp
    })
  }, [data, sortField, sortDir])

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortField(field)
      setSortDir("desc")
    }
  }

  return (
    <div className="w-80 border-l bg-background flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b">
        <div className="flex items-center gap-2">
          <Trash2 className="h-4 w-4 text-orange-500" />
          <span className="font-semibold text-sm">Dead Code Candidates</span>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Type toggle */}
      <div className="flex gap-1 p-2 border-b">
        <Button
          variant={typeFilter === "function" ? "default" : "outline"}
          size="sm"
          className="flex-1 text-xs"
          onClick={() => onTypeChange("function")}
        >
          Functions
        </Button>
        <Button
          variant={typeFilter === "class" ? "default" : "outline"}
          size="sm"
          className="flex-1 text-xs"
          onClick={() => onTypeChange("class")}
        >
          Classes
        </Button>
      </div>

      {/* Sort controls */}
      <div className="flex gap-1 px-2 py-1 border-b text-[10px]">
        {(["name", "loc", "path"] as SortField[]).map((field) => (
          <button
            key={field}
            className={`px-1.5 py-0.5 rounded ${sortField === field ? "bg-muted font-medium" : ""}`}
            onClick={() => toggleSort(field)}
          >
            {field.toUpperCase()}
            {sortField === field && (
              <span className="ml-0.5">{sortDir === "asc" ? "\u2191" : "\u2193"}</span>
            )}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center p-8 text-sm text-muted-foreground">
          Scanning...
        </div>
      ) : data ? (
        <>
          <div className="px-3 py-2 border-b">
            <div className="text-xs text-muted-foreground">
              {data.total} candidate{data.total !== 1 ? "s" : ""}
              <span className="ml-1 text-orange-500">(static analysis — verify before deleting)</span>
            </div>
          </div>

          <ScrollArea className="flex-1">
            <div className="p-2 space-y-1">
              {sorted.map((candidate) => (
                <button
                  key={candidate.fqn}
                  className="w-full text-left px-2 py-1.5 rounded hover:bg-muted text-xs"
                  onClick={() => onCandidateClick?.(candidate.fqn)}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono truncate flex-1">{candidate.name}</span>
                    {candidate.loc && (
                      <Badge variant="outline" className="text-[10px] ml-1 shrink-0">
                        {candidate.loc} LOC
                      </Badge>
                    )}
                  </div>
                  {candidate.path && (
                    <div className="text-muted-foreground truncate mt-0.5">
                      {candidate.path}
                      {candidate.line && `:${candidate.line}`}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </ScrollArea>
        </>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add components/analysis/DeadCodePanel.tsx
git commit -m "feat(phase3): add DeadCodePanel with sortable candidate list"
```

---

## Task 4: Add Analysis Buttons to GraphToolbar

**Files:**
- Modify: `cast-clone-frontend/components/graph/GraphToolbar.tsx`

- [ ] **Step 1: Add analysis toggle buttons**

Add new props to `GraphToolbarProps`:

```typescript
interface GraphToolbarProps {
  // ... existing props ...
  communityColorsEnabled?: boolean
  onToggleCommunityColors?: () => void
  onShowCircularDeps?: () => void
  onShowDeadCode?: () => void
}
```

Add buttons in the toolbar after the existing export buttons:

```tsx
{/* Separator + Analysis tools */}
<Separator orientation="vertical" className="h-6" />

<CommunityToggle
  enabled={communityColorsEnabled ?? false}
  onToggle={onToggleCommunityColors ?? (() => {})}
/>

<Tooltip>
  <TooltipTrigger asChild>
    <Button variant="outline" size="icon" className="h-8 w-8" onClick={onShowCircularDeps}>
      <RefreshCcw className="h-4 w-4" />
    </Button>
  </TooltipTrigger>
  <TooltipContent>Circular Dependencies</TooltipContent>
</Tooltip>

<Tooltip>
  <TooltipTrigger asChild>
    <Button variant="outline" size="icon" className="h-8 w-8" onClick={onShowDeadCode}>
      <Trash2 className="h-4 w-4" />
    </Button>
  </TooltipTrigger>
  <TooltipContent>Dead Code Candidates</TooltipContent>
</Tooltip>
```

Add the necessary imports.

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add components/graph/GraphToolbar.tsx
git commit -m "feat(phase3): add analysis tool buttons to GraphToolbar"
```

---

## Task 5: Integrate All Panels into Graph Page

**Files:**
- Modify: `cast-clone-frontend/app/projects/[id]/graph/page.tsx`

- [ ] **Step 1: Add state and handlers for communities, circular deps, and dead code**

Extend the state from M4:

```typescript
const [communityColorsEnabled, setCommunityColorsEnabled] = React.useState(false)
const [circularDepsLevel, setCircularDepsLevel] = React.useState<"module" | "class">("module")
const [deadCodeType, setDeadCodeType] = React.useState<"function" | "class">("function")
const analysisData = useAnalysisData()
```

Add handlers:

```typescript
const handleToggleCommunityColors = React.useCallback(() => {
  setCommunityColorsEnabled((prev) => {
    const next = !prev
    if (cyRef.current) {
      if (next) {
        // Load communities if not loaded, then apply
        if (!analysisData.communities) {
          analysisData.loadCommunities(params.id)
        }
        applyCommunityColors(cyRef.current)
      } else {
        clearCommunityColors(cyRef.current)
      }
    }
    return next
  })
}, [analysisData, params.id])

const handleShowCircularDeps = React.useCallback(() => {
  setActiveAnalysis("circularDeps")
  analysisData.loadCircularDeps(params.id, circularDepsLevel)
}, [analysisData, params.id, circularDepsLevel])

const handleShowDeadCode = React.useCallback(() => {
  setActiveAnalysis("deadCode")
  analysisData.loadDeadCode(params.id, deadCodeType)
}, [analysisData, params.id, deadCodeType])
```

- [ ] **Step 2: Extend the activeAnalysis type**

Change from M4's type:

```typescript
const [activeAnalysis, setActiveAnalysis] = React.useState<
  "impact" | "path" | "circularDeps" | "deadCode" | null
>(null)
```

- [ ] **Step 3: Add panels to JSX**

Extend the right panel conditional from M4:

```tsx
{activeAnalysis === "circularDeps" ? (
  <CircularDepsPanel
    data={analysisData.circularDeps}
    isLoading={analysisData.isLoading}
    level={circularDepsLevel}
    onLevelChange={(level) => {
      setCircularDepsLevel(level)
      analysisData.loadCircularDeps(params.id, level)
    }}
    onClose={() => {
      setActiveAnalysis(null)
      if (cyRef.current) clearCycleHighlight(cyRef.current)
    }}
    onCycleClick={(fqns) => {
      if (cyRef.current) highlightCycle(cyRef.current, fqns)
    }}
  />
) : activeAnalysis === "deadCode" ? (
  <DeadCodePanel
    data={analysisData.deadCode}
    isLoading={analysisData.isLoading}
    typeFilter={deadCodeType}
    onTypeChange={(type) => {
      setDeadCodeType(type)
      analysisData.loadDeadCode(params.id, type)
    }}
    onClose={() => setActiveAnalysis(null)}
    onCandidateClick={(fqn) => {
      // Select node in graph
      const node = cyRef.current?.getElementById(fqn)
      if (node?.length) node.select()
    }}
  />
) : /* ...existing M4 panels... */}
```

- [ ] **Step 4: Pass toolbar props**

```tsx
<GraphToolbar
  // ...existing props...
  communityColorsEnabled={communityColorsEnabled}
  onToggleCommunityColors={handleToggleCommunityColors}
  onShowCircularDeps={handleShowCircularDeps}
  onShowDeadCode={handleShowDeadCode}
/>
```

- [ ] **Step 5: Verify compilation**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 6: Commit**

```bash
cd cast-clone-frontend
git add app/projects/[id]/graph/page.tsx
git commit -m "feat(phase3): integrate community colors, circular deps, dead code into graph page"
```
