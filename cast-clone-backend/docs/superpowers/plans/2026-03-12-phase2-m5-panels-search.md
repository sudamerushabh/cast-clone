# Phase 2 M5: Properties Panel, Search & Filters — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add node properties panel (right sidebar), global Cmd+K search with navigate-to-node, breadcrumb navigation for drill-down path, and client-side node type/language filters.

**Architecture:** Properties panel reads from Cytoscape node data(). Search calls backend API with debounce. Filters use Cytoscape's native show()/hide(). Breadcrumbs track drill-down path from useGraph hook.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, shadcn/ui (Dialog, Input, Badge, Checkbox, ScrollArea)

---

## Dependencies

| Dependency | What it provides | Status |
|------------|-----------------|--------|
| **M2 (Foundation)** | `@/lib/types.ts` (GraphNodeResponse, GraphSearchHit, GraphSearchResponse), `@/lib/api.ts` (searchGraph), `@/components/layout/AppLayout.tsx`, shadcn components (dialog, input, badge, scroll-area) | Must be complete |
| **M4 (Cytoscape)** | `@/components/graph/GraphView.tsx` (exposes cy ref via callback), `@/hooks/useGraph.ts` (drilldownPath, drillUp, expandToNode), `@/app/projects/[id]/graph/page.tsx` (graph page with selectedNode state) | Must be complete |

### Assumed M4 Interfaces

These are the types and hooks M5 depends on. If M4 signatures differ, adjust accordingly.

```typescript
// From @/hooks/useGraph.ts
interface UseGraphReturn {
  elements: cytoscape.ElementDefinition[];
  isLoading: boolean;
  drilldownPath: DrilldownSegment[];
  drillDown: (fqn: string) => Promise<void>;
  drillUp: (toIndex: number) => void;
  expandToNode: (fqn: string) => Promise<void>;
}

interface DrilldownSegment {
  fqn: string;
  name: string;
  kind: string;
}

// From @/components/graph/GraphView.tsx
interface GraphViewProps {
  elements: cytoscape.ElementDefinition[];
  onNodeSelect?: (nodeData: GraphNodeResponse | null) => void;
  onCyReady?: (cy: cytoscape.Core) => void;
  // ... other props
}
```

---

## File Structure

```
cast-clone-frontend/
├── components/
│   ├── graph/
│   │   ├── NodeProperties.tsx        # CREATE — Right sidebar properties panel
│   │   ├── FilterPanel.tsx           # CREATE — Left sidebar filter checkboxes
│   │   └── Breadcrumbs.tsx           # CREATE — Drill-down breadcrumb navigation
│   ├── search/
│   │   └── SearchDialog.tsx          # CREATE — Cmd+K search modal
│   └── ui/
│       └── checkbox.tsx              # CREATE (via shadcn CLI) — needed for FilterPanel
├── hooks/
│   └── useSearch.ts                  # CREATE — Debounced search hook
└── app/
    └── projects/
        └── [id]/
            └── graph/
                └── page.tsx          # MODIFY — Wire in all new components
```

---

## Task 1: Install Checkbox Component + Create Directories

**Files:**
- Install: `components/ui/checkbox.tsx` (via shadcn)
- Create directories: `components/graph/`, `components/search/`

### Overview

The FilterPanel needs a checkbox component. We also need the graph and search directories to exist for subsequent tasks.

- [ ] **Step 1: Install shadcn checkbox component**

```bash
cd cast-clone-frontend && npx shadcn@latest add checkbox --yes
```

- [ ] **Step 2: Create component directories**

```bash
mkdir -p cast-clone-frontend/components/graph cast-clone-frontend/components/search
```

- [ ] **Step 3: Verify checkbox was installed**

```bash
ls cast-clone-frontend/components/ui/checkbox.tsx
```

---

## Task 2: Create NodeProperties Panel

**Files:**
- Create: `cast-clone-frontend/components/graph/NodeProperties.tsx`

### Overview

The right sidebar panel that displays details about the currently selected Cytoscape node. It reads directly from the node's data object (which mirrors `GraphNodeResponse`). Shows name, fully qualified name, kind badge, language, file path with line number, metrics (LOC, complexity, fan-in, fan-out), connection summaries, and a "View Source" button placeholder. Renders an empty state when no node is selected.

- [ ] **Step 1: Create NodeProperties.tsx**

```tsx
// cast-clone-frontend/components/graph/NodeProperties.tsx
"use client";

import * as React from "react";
import {
  Code2,
  FileCode2,
  GitFork,
  ArrowDownToLine,
  ArrowUpFromLine,
  Ruler,
  Gauge,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import type { GraphNodeResponse } from "@/lib/types";

// ─── Kind → color mapping ────────────────────────────────────────────────────

const KIND_COLORS: Record<string, string> = {
  CLASS: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  INTERFACE: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  FUNCTION: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  TABLE: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  API_ENDPOINT: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  MODULE: "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200",
  ENUM: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
};

function kindBadgeClass(kind: string): string {
  return KIND_COLORS[kind] ?? "bg-muted text-muted-foreground";
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface NodePropertiesProps {
  /** The currently selected node, or null if nothing is selected */
  node: GraphNodeResponse | null;
  /** Called when the user clicks the close / deselect button */
  onClose: () => void;
  /** Called when the user clicks "View Source". Receives file path and line. */
  onViewSource?: (file: string, line: number) => void;
}

// ─── Metric row helper ───────────────────────────────────────────────────────

function MetricRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number | null | undefined;
}) {
  if (value === null || value === undefined) return null;
  return (
    <div className="flex items-center justify-between py-1">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className="size-3.5 shrink-0" />
        <span>{label}</span>
      </div>
      <span className="text-sm font-medium tabular-nums">{value}</span>
    </div>
  );
}

// ─── Connection row helper ───────────────────────────────────────────────────

function ConnectionRow({
  icon: Icon,
  label,
  count,
}: {
  icon: React.ElementType;
  label: string;
  count: number | null | undefined;
}) {
  if (count === null || count === undefined || count === 0) return null;
  return (
    <div className="flex items-center justify-between py-1">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className="size-3.5 shrink-0" />
        <span>{label}</span>
      </div>
      <Badge variant="secondary" className="tabular-nums">
        {count}
      </Badge>
    </div>
  );
}

// ─── Component ───────────────────────────────────────────────────────────────

export function NodeProperties({ node, onClose, onViewSource }: NodePropertiesProps) {
  if (!node) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center">
        <div className="text-sm text-muted-foreground">
          <Code2 className="mx-auto mb-2 size-8 opacity-40" />
          <p>Select a node to view its properties</p>
        </div>
      </div>
    );
  }

  const props = node.properties ?? {};
  const fanIn = typeof props.fan_in === "number" ? props.fan_in : null;
  const fanOut = typeof props.fan_out === "number" ? props.fan_out : null;
  const calledByCount = typeof props.called_by_count === "number" ? props.called_by_count : null;
  const callsCount = typeof props.calls_count === "number" ? props.calls_count : null;
  const readsCount = typeof props.reads_count === "number" ? props.reads_count : null;

  return (
    <ScrollArea className="h-full">
      <div className="p-4">
        {/* ── Header ─────────────────────────────────────────── */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold">{node.name}</h3>
            <p
              className="mt-0.5 truncate text-xs text-muted-foreground"
              title={node.fqn}
            >
              {node.fqn}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={onClose}
            aria-label="Close properties panel"
          >
            <X className="size-3" />
          </Button>
        </div>

        {/* ── Kind + Language badges ─────────────────────────── */}
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Badge className={kindBadgeClass(node.kind)}>{node.kind}</Badge>
          {node.language && (
            <Badge variant="outline">{node.language}</Badge>
          )}
          {node.visibility && (
            <Badge variant="outline" className="capitalize">
              {node.visibility}
            </Badge>
          )}
        </div>

        <Separator className="my-4" />

        {/* ── File location ──────────────────────────────────── */}
        {node.path && (
          <>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Location
            </div>
            <button
              className="group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted"
              onClick={() => {
                if (node.path && onViewSource) {
                  onViewSource(node.path, node.line ?? 1);
                }
              }}
              disabled={!onViewSource}
            >
              <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs" title={node.path}>
                  {node.path}
                </p>
                {node.line && (
                  <p className="text-xs text-muted-foreground">
                    Line {node.line}
                    {node.end_line ? ` - ${node.end_line}` : ""}
                  </p>
                )}
              </div>
            </button>

            <Separator className="my-4" />
          </>
        )}

        {/* ── Metrics ────────────────────────────────────────── */}
        {(node.loc !== null || node.complexity !== null || fanIn !== null || fanOut !== null) && (
          <>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Metrics
            </div>
            <div className="space-y-0.5">
              <MetricRow icon={Ruler} label="Lines of Code" value={node.loc} />
              <MetricRow icon={Gauge} label="Complexity" value={node.complexity} />
              <MetricRow icon={ArrowDownToLine} label="Fan-in" value={fanIn} />
              <MetricRow icon={ArrowUpFromLine} label="Fan-out" value={fanOut} />
            </div>
            <Separator className="my-4" />
          </>
        )}

        {/* ── Connections ────────────────────────────────────── */}
        {(calledByCount || callsCount || readsCount) && (
          <>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Connections
            </div>
            <div className="space-y-0.5">
              <ConnectionRow icon={ArrowDownToLine} label="Called by" count={calledByCount} />
              <ConnectionRow icon={ArrowUpFromLine} label="Calls" count={callsCount} />
              <ConnectionRow icon={GitFork} label="Reads tables" count={readsCount} />
            </div>
            <Separator className="my-4" />
          </>
        )}

        {/* ── View Source button ──────────────────────────────── */}
        {node.path && (
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => {
              if (node.path && onViewSource) {
                onViewSource(node.path, node.line ?? 1);
              }
            }}
            disabled={!onViewSource}
          >
            <Code2 className="size-3.5" />
            View Source
          </Button>
        )}

        {/* ── Tags placeholder (Phase 4) ─────────────────────── */}
        <div className="mt-4">
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Tags
          </div>
          <p className="text-xs italic text-muted-foreground">
            No tags yet. Tags will be available in Phase 4.
          </p>
        </div>
      </div>
    </ScrollArea>
  );
}
```

- [ ] **Step 2: Verify the file compiles in isolation**

Check for import errors by running typecheck (may have errors from missing M2/M4 files -- that is expected if those milestones are not yet implemented):

```bash
cd cast-clone-frontend && npx tsc --noEmit --pretty 2>&1 | head -20
```

---

## Task 3: Create useSearch Hook

**Files:**
- Create: `cast-clone-frontend/hooks/useSearch.ts`

### Overview

Custom hook that encapsulates debounced search logic. Accepts a project ID, returns reactive query/results/loading state. Uses a simple setTimeout/clearTimeout debounce pattern (300ms). Calls `searchGraph()` from the API client. Groups results by kind for display in SearchDialog.

- [ ] **Step 1: Create useSearch.ts**

```typescript
// cast-clone-frontend/hooks/useSearch.ts
"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { searchGraph } from "@/lib/api";
import type { GraphSearchHit } from "@/lib/types";

const DEBOUNCE_MS = 300;

interface GroupedResults {
  kind: string;
  hits: GraphSearchHit[];
}

interface UseSearchReturn {
  query: string;
  setQuery: (q: string) => void;
  results: GraphSearchHit[];
  groupedResults: GroupedResults[];
  isSearching: boolean;
  error: string | null;
  clear: () => void;
}

export function useSearch(projectId: string): UseSearchReturn {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GraphSearchHit[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Debounced search effect
  useEffect(() => {
    // Clear previous timer
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }

    // Clear results if query is empty
    if (!query.trim()) {
      setResults([]);
      setIsSearching(false);
      setError(null);
      return;
    }

    setIsSearching(true);

    timerRef.current = setTimeout(async () => {
      // Abort previous in-flight request
      if (abortRef.current) {
        abortRef.current.abort();
      }
      abortRef.current = new AbortController();

      try {
        const response = await searchGraph(projectId, query.trim());
        setResults(response.hits);
        setError(null);
      } catch (err) {
        // Ignore abort errors
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        setError(err instanceof Error ? err.message : "Search failed");
        setResults([]);
      } finally {
        setIsSearching(false);
      }
    }, DEBOUNCE_MS);

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [query, projectId]);

  // Group results by kind
  const groupedResults: GroupedResults[] = React.useMemo(() => {
    const groups = new Map<string, GraphSearchHit[]>();
    for (const hit of results) {
      const existing = groups.get(hit.kind) ?? [];
      existing.push(hit);
      groups.set(hit.kind, existing);
    }
    // Sort groups: CLASS, INTERFACE, FUNCTION, TABLE, API_ENDPOINT, then rest
    const ORDER = ["CLASS", "INTERFACE", "FUNCTION", "TABLE", "API_ENDPOINT"];
    return Array.from(groups.entries())
      .sort(([a], [b]) => {
        const ai = ORDER.indexOf(a);
        const bi = ORDER.indexOf(b);
        const aOrder = ai === -1 ? ORDER.length : ai;
        const bOrder = bi === -1 ? ORDER.length : bi;
        return aOrder - bOrder;
      })
      .map(([kind, hits]) => ({ kind, hits }));
  }, [results]);

  const clear = useCallback(() => {
    setQuery("");
    setResults([]);
    setError(null);
    setIsSearching(false);
  }, []);

  return { query, setQuery, results, groupedResults, isSearching, error, clear };
}
```

Wait -- there is a `React.useMemo` reference but `React` is not imported. Let me fix that in the actual file content. I'll use the named import instead.

- [ ] **Step 2: Fix: The hook uses `useMemo` -- verify the import is correct**

The file should import `useMemo` from React directly. Here is the corrected import line at the top of the file:

```typescript
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
```

And the `groupedResults` computation should use `useMemo(...)` not `React.useMemo(...)`.

The corrected complete file content is in Step 1 above with these two fixes applied. Ensure the final file has:
- `import { useState, useEffect, useRef, useCallback, useMemo } from "react";`
- `const groupedResults: GroupedResults[] = useMemo(() => {`

---

## Task 3 (corrected): Create useSearch Hook

**Files:**
- Create: `cast-clone-frontend/hooks/useSearch.ts`

- [ ] **Step 1: Create useSearch.ts**

```typescript
// cast-clone-frontend/hooks/useSearch.ts
"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { searchGraph } from "@/lib/api";
import type { GraphSearchHit } from "@/lib/types";

const DEBOUNCE_MS = 300;

export interface GroupedResults {
  kind: string;
  hits: GraphSearchHit[];
}

export interface UseSearchReturn {
  query: string;
  setQuery: (q: string) => void;
  results: GraphSearchHit[];
  groupedResults: GroupedResults[];
  isSearching: boolean;
  error: string | null;
  clear: () => void;
}

export function useSearch(projectId: string): UseSearchReturn {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GraphSearchHit[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounced search effect
  useEffect(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }

    if (!query.trim()) {
      setResults([]);
      setIsSearching(false);
      setError(null);
      return;
    }

    setIsSearching(true);

    timerRef.current = setTimeout(async () => {
      try {
        const response = await searchGraph(projectId, query.trim());
        setResults(response.hits);
        setError(null);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        setError(err instanceof Error ? err.message : "Search failed");
        setResults([]);
      } finally {
        setIsSearching(false);
      }
    }, DEBOUNCE_MS);

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [query, projectId]);

  // Group results by kind, ordered: CLASS, INTERFACE, FUNCTION, TABLE, API_ENDPOINT
  const groupedResults: GroupedResults[] = useMemo(() => {
    const groups = new Map<string, GraphSearchHit[]>();
    for (const hit of results) {
      const existing = groups.get(hit.kind) ?? [];
      existing.push(hit);
      groups.set(hit.kind, existing);
    }
    const ORDER = ["CLASS", "INTERFACE", "FUNCTION", "TABLE", "API_ENDPOINT"];
    return Array.from(groups.entries())
      .sort(([a], [b]) => {
        const ai = ORDER.indexOf(a);
        const bi = ORDER.indexOf(b);
        return (ai === -1 ? ORDER.length : ai) - (bi === -1 ? ORDER.length : bi);
      })
      .map(([kind, hits]) => ({ kind, hits }));
  }, [results]);

  const clear = useCallback(() => {
    setQuery("");
    setResults([]);
    setError(null);
    setIsSearching(false);
  }, []);

  return { query, setQuery, results, groupedResults, isSearching, error, clear };
}
```

---

## Task 4: Create SearchDialog

**Files:**
- Create: `cast-clone-frontend/components/search/SearchDialog.tsx`

### Overview

A Cmd+K / Ctrl+K modal dialog for global search. Uses the shadcn Dialog component. Contains a text input wired to `useSearch`, displays results grouped by kind, and navigates to a node on click. The dialog opens via a global keydown listener and closes on result selection or Escape.

- [ ] **Step 1: Create SearchDialog.tsx**

```tsx
// cast-clone-frontend/components/search/SearchDialog.tsx
"use client";

import * as React from "react";
import { Search, Loader2, Box, GitBranch, Zap, Database, Globe } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useSearch } from "@/hooks/useSearch";
import type { GraphSearchHit } from "@/lib/types";

// ─── Kind → icon mapping ─────────────────────────────────────────────────────

const KIND_ICONS: Record<string, React.ElementType> = {
  CLASS: Box,
  INTERFACE: GitBranch,
  FUNCTION: Zap,
  TABLE: Database,
  API_ENDPOINT: Globe,
};

// ─── Kind → human-readable label ─────────────────────────────────────────────

const KIND_LABELS: Record<string, string> = {
  CLASS: "Classes",
  INTERFACE: "Interfaces",
  FUNCTION: "Functions",
  TABLE: "Tables",
  API_ENDPOINT: "Endpoints",
};

// ─── Props ────────────────────────────────────────────────────────────────────

interface SearchDialogProps {
  projectId: string;
  /** Called when a search result is clicked. Receives the FQN of the node. */
  onNavigate: (fqn: string) => void;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function SearchDialog({ projectId, onNavigate }: SearchDialogProps) {
  const [open, setOpen] = React.useState(false);
  const { query, setQuery, groupedResults, isSearching, error, clear } =
    useSearch(projectId);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // ── Global Cmd+K / Ctrl+K listener ─────────────────────────────────────────
  React.useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Focus input when dialog opens
  React.useEffect(() => {
    if (open) {
      // Small delay to let dialog animate open
      const t = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(t);
    } else {
      clear();
    }
  }, [open, clear]);

  function handleSelect(hit: GraphSearchHit) {
    onNavigate(hit.fqn);
    setOpen(false);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-lg">
        <DialogTitle className="sr-only">Search nodes</DialogTitle>

        {/* ── Search input ─────────────────────────────────────── */}
        <div className="flex items-center gap-2 border-b px-3 py-2">
          {isSearching ? (
            <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
          ) : (
            <Search className="size-4 shrink-0 text-muted-foreground" />
          )}
          <Input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search classes, functions, tables..."
            className="h-8 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
          />
          <kbd className="pointer-events-none hidden h-5 select-none items-center gap-0.5 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground sm:flex">
            ESC
          </kbd>
        </div>

        {/* ── Results ──────────────────────────────────────────── */}
        <ScrollArea className="max-h-80">
          {error && (
            <div className="px-4 py-3 text-sm text-destructive">{error}</div>
          )}

          {!error && query.trim() && !isSearching && groupedResults.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              No results found for &ldquo;{query}&rdquo;
            </div>
          )}

          {!error && groupedResults.map((group) => {
            const Icon = KIND_ICONS[group.kind] ?? Box;
            const label = KIND_LABELS[group.kind] ?? group.kind;

            return (
              <div key={group.kind}>
                <div className="flex items-center gap-2 px-4 py-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <Icon className="size-3" />
                  {label}
                </div>
                {group.hits.map((hit) => (
                  <button
                    key={hit.fqn}
                    className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors hover:bg-muted focus:bg-muted focus:outline-none"
                    onClick={() => handleSelect(hit)}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{hit.name}</div>
                      <div className="truncate text-xs text-muted-foreground">
                        {hit.fqn}
                      </div>
                    </div>
                    {hit.language && (
                      <Badge variant="outline" className="shrink-0 text-[10px]">
                        {hit.language}
                      </Badge>
                    )}
                  </button>
                ))}
              </div>
            );
          })}
        </ScrollArea>

        {/* ── Footer hint ─────────────────────────────────────── */}
        {groupedResults.length > 0 && (
          <div className="border-t px-4 py-2 text-xs text-muted-foreground">
            Click a result to navigate to it in the graph
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
```

---

## Task 5: Create FilterPanel

**Files:**
- Create: `cast-clone-frontend/components/graph/FilterPanel.tsx`

### Overview

Left sidebar filter controls with checkboxes for node types and languages. Operates directly on the Cytoscape instance using `cy.nodes('[kind="X"]').hide()` and `.show()`. Purely client-side -- no API calls. Receives the cy instance ref as a prop.

- [ ] **Step 1: Create FilterPanel.tsx**

```tsx
// cast-clone-frontend/components/graph/FilterPanel.tsx
"use client";

import * as React from "react";
import { Filter } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import type cytoscape from "cytoscape";

// ─── Filter definitions ──────────────────────────────────────────────────────

interface FilterItem {
  id: string;
  label: string;
}

const NODE_TYPE_FILTERS: FilterItem[] = [
  { id: "CLASS", label: "Classes" },
  { id: "INTERFACE", label: "Interfaces" },
  { id: "FUNCTION", label: "Functions" },
  { id: "TABLE", label: "Tables" },
  { id: "API_ENDPOINT", label: "Endpoints" },
  { id: "MODULE", label: "Modules" },
  { id: "ENUM", label: "Enums" },
];

const LANGUAGE_FILTERS: FilterItem[] = [
  { id: "java", label: "Java" },
  { id: "typescript", label: "TypeScript" },
  { id: "python", label: "Python" },
  { id: "csharp", label: "C#" },
];

// ─── Props ────────────────────────────────────────────────────────────────────

interface FilterPanelProps {
  /** Cytoscape core instance. Null if not yet initialized. */
  cy: cytoscape.Core | null;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function FilterPanel({ cy }: FilterPanelProps) {
  // Track which filters are active (checked = visible). All start checked.
  const [visibleKinds, setVisibleKinds] = React.useState<Set<string>>(
    () => new Set(NODE_TYPE_FILTERS.map((f) => f.id)),
  );
  const [visibleLanguages, setVisibleLanguages] = React.useState<Set<string>>(
    () => new Set(LANGUAGE_FILTERS.map((f) => f.id)),
  );

  // Apply kind filter to Cytoscape
  function toggleKind(kind: string, checked: boolean) {
    setVisibleKinds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(kind);
      } else {
        next.delete(kind);
      }
      return next;
    });

    if (!cy) return;

    if (checked) {
      cy.nodes(`[kind = "${kind}"]`).show();
    } else {
      cy.nodes(`[kind = "${kind}"]`).hide();
    }
  }

  // Apply language filter to Cytoscape
  function toggleLanguage(language: string, checked: boolean) {
    setVisibleLanguages((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(language);
      } else {
        next.delete(language);
      }
      return next;
    });

    if (!cy) return;

    if (checked) {
      cy.nodes(`[language = "${language}"]`).show();
    } else {
      cy.nodes(`[language = "${language}"]`).hide();
    }
  }

  // Reset all filters
  function resetFilters() {
    setVisibleKinds(new Set(NODE_TYPE_FILTERS.map((f) => f.id)));
    setVisibleLanguages(new Set(LANGUAGE_FILTERS.map((f) => f.id)));
    if (cy) {
      cy.nodes().show();
    }
  }

  const hasActiveFilters =
    visibleKinds.size < NODE_TYPE_FILTERS.length ||
    visibleLanguages.size < LANGUAGE_FILTERS.length;

  return (
    <ScrollArea className="h-full">
      <div className="p-3">
        {/* ── Header ─────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <Filter className="size-3" />
            Filters
          </div>
          {hasActiveFilters && (
            <button
              onClick={resetFilters}
              className="text-xs text-primary hover:underline"
            >
              Reset
            </button>
          )}
        </div>

        <Separator className="my-3" />

        {/* ── Node Type filters ──────────────────────────────── */}
        <div className="mb-1 text-xs font-medium text-muted-foreground">
          Node Type
        </div>
        <div className="space-y-2">
          {NODE_TYPE_FILTERS.map((filter) => (
            <label
              key={filter.id}
              className="flex cursor-pointer items-center gap-2 text-sm"
            >
              <Checkbox
                checked={visibleKinds.has(filter.id)}
                onCheckedChange={(checked) =>
                  toggleKind(filter.id, checked === true)
                }
              />
              <span>{filter.label}</span>
            </label>
          ))}
        </div>

        <Separator className="my-3" />

        {/* ── Language filters ────────────────────────────────── */}
        <div className="mb-1 text-xs font-medium text-muted-foreground">
          Language
        </div>
        <div className="space-y-2">
          {LANGUAGE_FILTERS.map((filter) => (
            <label
              key={filter.id}
              className="flex cursor-pointer items-center gap-2 text-sm"
            >
              <Checkbox
                checked={visibleLanguages.has(filter.id)}
                onCheckedChange={(checked) =>
                  toggleLanguage(filter.id, checked === true)
                }
              />
              <span>{filter.label}</span>
            </label>
          ))}
        </div>
      </div>
    </ScrollArea>
  );
}
```

---

## Task 6: Create Breadcrumbs

**Files:**
- Create: `cast-clone-frontend/components/graph/Breadcrumbs.tsx`

### Overview

A breadcrumb bar that shows the drill-down path (e.g., "Application > com.app.user > UserService"). Each segment is clickable to drill back up to that level. The first segment is always "Home" (root). Receives the drilldown path array and a callback to navigate up.

- [ ] **Step 1: Create Breadcrumbs.tsx**

```tsx
// cast-clone-frontend/components/graph/Breadcrumbs.tsx
"use client";

import * as React from "react";
import { ChevronRight, Home } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface DrilldownSegment {
  fqn: string;
  name: string;
  kind: string;
}

interface BreadcrumbsProps {
  /** The current drill-down path. Empty array means root level. */
  path: DrilldownSegment[];
  /** Called when a breadcrumb segment is clicked. Index -1 means root/home. */
  onNavigate: (toIndex: number) => void;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function Breadcrumbs({ path, onNavigate }: BreadcrumbsProps) {
  return (
    <nav
      aria-label="Drill-down breadcrumbs"
      className="flex items-center gap-1 overflow-x-auto px-3 py-1.5 text-sm"
    >
      {/* Home / Root segment — always present */}
      <button
        onClick={() => onNavigate(-1)}
        className={cn(
          "flex shrink-0 items-center gap-1 rounded-sm px-1.5 py-0.5 transition-colors",
          path.length === 0
            ? "font-medium text-foreground"
            : "text-muted-foreground hover:bg-muted hover:text-foreground",
        )}
        disabled={path.length === 0}
      >
        <Home className="size-3" />
        <span>Application</span>
      </button>

      {/* Path segments */}
      {path.map((segment, index) => {
        const isLast = index === path.length - 1;
        return (
          <React.Fragment key={segment.fqn}>
            <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
            <button
              onClick={() => onNavigate(index)}
              className={cn(
                "shrink-0 truncate rounded-sm px-1.5 py-0.5 transition-colors",
                isLast
                  ? "font-medium text-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
              disabled={isLast}
              title={segment.fqn}
            >
              {segment.name}
            </button>
          </React.Fragment>
        );
      })}
    </nav>
  );
}
```

---

## Task 7: Wire Everything into the Graph Page

**Files:**
- Modify: `cast-clone-frontend/app/projects/[id]/graph/page.tsx`

### Overview

The graph page is the orchestration point. It manages `selectedNode` state, holds the cy instance ref, and renders all M5 components in the correct layout positions: Breadcrumbs above the graph, FilterPanel in the left sidebar, NodeProperties in the right panel, and SearchDialog floating. The `onNavigate` callback from SearchDialog calls `expandToNode` from useGraph to handle collapsed compound nodes.

- [ ] **Step 1: Update the graph page to integrate all M5 components**

The graph page should already exist from M4. Apply the following changes to `cast-clone-frontend/app/projects/[id]/graph/page.tsx`:

```tsx
// cast-clone-frontend/app/projects/[id]/graph/page.tsx
"use client";

import * as React from "react";
import { use } from "react";
import type cytoscape from "cytoscape";
import { AppLayout } from "@/components/layout/AppLayout";
import { GraphView } from "@/components/graph/GraphView";
import { NodeProperties } from "@/components/graph/NodeProperties";
import { FilterPanel } from "@/components/graph/FilterPanel";
import { Breadcrumbs } from "@/components/graph/Breadcrumbs";
import { SearchDialog } from "@/components/search/SearchDialog";
import { useGraph } from "@/hooks/useGraph";
import type { GraphNodeResponse } from "@/lib/types";

interface GraphPageProps {
  params: Promise<{ id: string }>;
}

export default function GraphPage({ params }: GraphPageProps) {
  const { id: projectId } = use(params);

  // ── Graph data hook ─────────────────────────────────────────────────────────
  const {
    elements,
    isLoading,
    drilldownPath,
    drillUp,
    expandToNode,
  } = useGraph(projectId);

  // ── Local state ─────────────────────────────────────────────────────────────
  const [selectedNode, setSelectedNode] = React.useState<GraphNodeResponse | null>(null);
  const [cyInstance, setCyInstance] = React.useState<cytoscape.Core | null>(null);
  const [codeViewerFile, setCodeViewerFile] = React.useState<{
    file: string;
    line: number;
  } | null>(null);

  // ── Callbacks ───────────────────────────────────────────────────────────────

  /** Called by GraphView when a node is clicked */
  function handleNodeSelect(nodeData: GraphNodeResponse | null) {
    setSelectedNode(nodeData);
  }

  /** Called by GraphView when Cytoscape instance is ready */
  function handleCyReady(cy: cytoscape.Core) {
    setCyInstance(cy);
  }

  /** Called by SearchDialog when a result is clicked */
  async function handleSearchNavigate(fqn: string) {
    // expandToNode handles: expand collapsed parents, center + select the node
    await expandToNode(fqn);

    // After expansion, find and select the node in Cytoscape
    if (cyInstance) {
      const node = cyInstance.getElementById(fqn);
      if (node.length > 0) {
        cyInstance.nodes().unselect();
        node.select();
        cyInstance.animate({
          center: { eles: node },
          zoom: cyInstance.zoom(),
          duration: 300,
        });
        // Update React state with the node data
        setSelectedNode(node.data() as GraphNodeResponse);
      }
    }
  }

  /** Called by NodeProperties "View Source" button */
  function handleViewSource(file: string, line: number) {
    setCodeViewerFile({ file, line });
    // Code viewer integration is in M7 — for now just store the state
  }

  /** Called by Breadcrumbs when a segment is clicked */
  function handleBreadcrumbNavigate(toIndex: number) {
    drillUp(toIndex);
    setSelectedNode(null); // Clear selection when navigating up
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <AppLayout
      projectName="Project" // TODO: fetch project name
      sidebar={<FilterPanel cy={cyInstance} />}
      rightPanel={
        <NodeProperties
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
          onViewSource={handleViewSource}
        />
      }
    >
      {/* Search dialog — floating, triggered by Cmd+K */}
      <SearchDialog
        projectId={projectId}
        onNavigate={handleSearchNavigate}
      />

      {/* Breadcrumbs — above the graph */}
      <div className="border-b bg-background">
        <Breadcrumbs
          path={drilldownPath}
          onNavigate={handleBreadcrumbNavigate}
        />
      </div>

      {/* Graph view — fills remaining space */}
      <div className="relative flex-1">
        {isLoading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60">
            <div className="text-sm text-muted-foreground">Loading graph...</div>
          </div>
        )}
        <GraphView
          elements={elements}
          onNodeSelect={handleNodeSelect}
          onCyReady={handleCyReady}
        />
      </div>
    </AppLayout>
  );
}
```

- [ ] **Step 2: Ensure the graph page directory exists**

```bash
mkdir -p cast-clone-frontend/app/projects/\[id\]/graph
```

- [ ] **Step 3: Verify the file is placed at the correct path**

```bash
ls cast-clone-frontend/app/projects/\[id\]/graph/page.tsx
```

---

## Task 8: Verify TypeScript Compilation and Lint

- [ ] **Step 1: Run typecheck**

```bash
cd cast-clone-frontend && npm run typecheck
```

Expected: The only errors should be from missing M4 dependencies (`GraphView`, `useGraph`) if M4 is not yet implemented. All M5 files themselves should have no internal type errors.

- [ ] **Step 2: Run lint**

```bash
cd cast-clone-frontend && npm run lint
```

Fix any lint issues (unused imports, missing `"use client"`, etc.).

- [ ] **Step 3: Run format**

```bash
cd cast-clone-frontend && npm run format
```

---

## Verification Checklist

After all tasks are complete, confirm:

- [ ] `cast-clone-frontend/components/graph/NodeProperties.tsx` exists and exports `NodeProperties`
  - Shows empty state when `node` is null
  - Displays name, fqn, kind badge, language badge, visibility badge
  - Shows file path + line number (clickable)
  - Shows metrics: LOC, complexity, fan-in, fan-out
  - Shows connection counts: called by, calls, reads tables
  - Has "View Source" button that calls `onViewSource`
  - Has close button that calls `onClose`

- [ ] `cast-clone-frontend/hooks/useSearch.ts` exists and exports `useSearch`
  - 300ms debounce on query changes
  - Returns `query`, `setQuery`, `results`, `groupedResults`, `isSearching`, `error`, `clear`
  - Groups results by kind in display order (CLASS, INTERFACE, FUNCTION, TABLE, API_ENDPOINT)

- [ ] `cast-clone-frontend/components/search/SearchDialog.tsx` exists and exports `SearchDialog`
  - Opens on Cmd+K / Ctrl+K
  - Text input with search icon and loading spinner
  - Results grouped by kind with icons
  - Click result calls `onNavigate(fqn)` and closes dialog
  - Shows "No results" empty state
  - ESC closes the dialog

- [ ] `cast-clone-frontend/components/graph/FilterPanel.tsx` exists and exports `FilterPanel`
  - Checkboxes for 7 node types: CLASS, INTERFACE, FUNCTION, TABLE, API_ENDPOINT, MODULE, ENUM
  - Checkboxes for 4 languages: Java, TypeScript, Python, C#
  - All start checked (visible)
  - Unchecking calls `cy.nodes('[kind="X"]').hide()`
  - Checking calls `cy.nodes('[kind="X"]').show()`
  - "Reset" button shows all nodes

- [ ] `cast-clone-frontend/components/graph/Breadcrumbs.tsx` exists and exports `Breadcrumbs`
  - Shows "Application" as root segment
  - Renders path segments with chevron separators
  - Each non-last segment is clickable
  - Last segment is bold and non-clickable
  - Calls `onNavigate(index)` on click

- [ ] `cast-clone-frontend/app/projects/[id]/graph/page.tsx` integrates all components
  - NodeProperties in right panel via AppLayout
  - FilterPanel in left sidebar via AppLayout
  - SearchDialog rendered (floating)
  - Breadcrumbs above graph area
  - selectedNode state flows to NodeProperties
  - cy instance ref flows to FilterPanel
  - Search navigate calls expandToNode + centers + selects

- [ ] `npm run typecheck` passes (ignoring M4 dependency stubs)
- [ ] `npm run lint` passes
- [ ] `npm run format` completes
