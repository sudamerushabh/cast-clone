# Phase 2 M6: Transaction View — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add transaction list selection and call-graph rendering showing end-to-end flows from API entry point to database, using dagre left-to-right layout.

**Architecture:** Transaction view is a separate data mode that replaces the module graph. TransactionSelector dropdown fetches list, selecting one fetches detail and renders the call chain. Uses dagre LR layout.

**Tech Stack:** React 19, TypeScript, Cytoscape.js (dagre LR), shadcn/ui

---

## Dependencies

- **M4 (Cytoscape integration):** `GraphView`, `GraphToolbar`, cytoscape-elements converters
- **M2 (foundation):** API client, types

Assumes these exist:

| Import | What it provides |
|--------|-----------------|
| `@/lib/api` | `getTransactions(projectId)`, `getTransactionDetail(projectId, fqn)` |
| `@/lib/types` | `TransactionListItem { fqn, name, method, path, depth, node_count }`, `TransactionDetailResponse { nodes, edges }`, `GraphNodeResponse`, `GraphEdgeResponse` |
| `@/components/graph/GraphView` | Cytoscape wrapper accepting `elements` + `layout` config props |
| `@/components/graph/GraphToolbar` | Toolbar with view switcher |
| `@/lib/cytoscape-elements.ts` | Existing module-level converters (we add `transactionToElements()` here) |
| `@/app/projects/[id]/graph/page.tsx` | Graph page with `currentView` state (`'architecture' | 'dependency' | 'transaction'`) |

---

## File Structure

```
cast-clone-frontend/
├── hooks/
│   └── useTransactions.ts                    # CREATE — transaction data hook
├── components/
│   └── graph/
│       └── TransactionSelector.tsx           # CREATE — searchable transaction dropdown
├── lib/
│   └── cytoscape-elements.ts                 # MODIFY — add transactionToElements()
├── app/
│   └── projects/
│       └── [id]/
│           └── graph/
│               └── page.tsx                  # MODIFY — wire transaction view
├── components/
│   └── graph/
│       └── GraphView.tsx                     # MODIFY — add transaction mode support
```

---

## Task 1: Create `useTransactions` Hook

**Files:**
- Create: `cast-clone-frontend/hooks/useTransactions.ts`

- [ ] **Step 1.1: Create the hooks directory (if needed) and file**

```bash
mkdir -p cast-clone-frontend/hooks
```

- [ ] **Step 1.2: Write the useTransactions hook**

```typescript
// cast-clone-frontend/hooks/useTransactions.ts
"use client";

import { useCallback, useRef, useState } from "react";
import { getTransactionDetail, getTransactions } from "@/lib/api";
import type {
  TransactionDetailResponse,
  TransactionListItem,
} from "@/lib/types";
import { transactionToElements } from "@/lib/cytoscape-elements";
import type { ElementDefinition } from "cytoscape";

interface UseTransactionsReturn {
  /** Full list of available transactions */
  transactions: TransactionListItem[];
  /** Currently selected transaction FQN, or null */
  selectedFqn: string | null;
  /** Cytoscape elements for the selected transaction */
  transactionElements: ElementDefinition[];
  /** True while fetching list or detail */
  isLoading: boolean;
  /** Error message if last operation failed */
  error: string | null;
  /** Fetch the transaction list for a project */
  loadTransactions: (projectId: string) => Promise<void>;
  /** Select a transaction by FQN — fetches detail and converts to elements */
  selectTransaction: (projectId: string, fqn: string) => Promise<void>;
  /** Clear the selection */
  clearSelection: () => void;
}

export function useTransactions(): UseTransactionsReturn {
  const [transactions, setTransactions] = useState<TransactionListItem[]>([]);
  const [selectedFqn, setSelectedFqn] = useState<string | null>(null);
  const [transactionElements, setTransactionElements] = useState<
    ElementDefinition[]
  >([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Cache detail responses to avoid re-fetching
  const detailCache = useRef(new Map<string, TransactionDetailResponse>());

  const loadTransactions = useCallback(async (projectId: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const list = await getTransactions(projectId);
      setTransactions(list);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load transactions";
      setError(message);
      setTransactions([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const selectTransaction = useCallback(
    async (projectId: string, fqn: string) => {
      setIsLoading(true);
      setError(null);
      setSelectedFqn(fqn);
      try {
        // Check cache first
        let detail = detailCache.current.get(fqn);
        if (!detail) {
          detail = await getTransactionDetail(projectId, fqn);
          detailCache.current.set(fqn, detail);
        }

        // Find the matching transaction to get the entry_point_fqn
        const txn = transactions.find((t) => t.fqn === fqn);
        const entryPointFqn = txn?.fqn ?? null;

        const elements = transactionToElements(detail, entryPointFqn);
        setTransactionElements(elements);
      } catch (err) {
        const message =
          err instanceof Error
            ? err.message
            : "Failed to load transaction detail";
        setError(message);
        setTransactionElements([]);
      } finally {
        setIsLoading(false);
      }
    },
    [transactions],
  );

  const clearSelection = useCallback(() => {
    setSelectedFqn(null);
    setTransactionElements([]);
    setError(null);
  }, []);

  return {
    transactions,
    selectedFqn,
    transactionElements,
    isLoading,
    error,
    loadTransactions,
    selectTransaction,
    clearSelection,
  };
}
```

---

## Task 2: Create `TransactionSelector` Component

**Files:**
- Create: `cast-clone-frontend/components/graph/TransactionSelector.tsx`

- [ ] **Step 2.1: Create the graph components directory (if needed)**

```bash
mkdir -p cast-clone-frontend/components/graph
```

- [ ] **Step 2.2: Write the TransactionSelector component**

```tsx
// cast-clone-frontend/components/graph/TransactionSelector.tsx
"use client";

import * as React from "react";
import { ChevronDown, Loader2, Route, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { TransactionListItem } from "@/lib/types";

interface TransactionSelectorProps {
  transactions: TransactionListItem[];
  selectedFqn: string | null;
  isLoading: boolean;
  onSelect: (fqn: string) => void;
}

/** HTTP method badge color mapping */
function methodColor(method: string): string {
  switch (method.toUpperCase()) {
    case "GET":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
    case "POST":
      return "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300";
    case "PUT":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
    case "PATCH":
      return "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300";
    case "DELETE":
      return "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
    default:
      return "bg-gray-100 text-gray-800 dark:bg-gray-900/40 dark:text-gray-300";
  }
}

export function TransactionSelector({
  transactions,
  selectedFqn,
  isLoading,
  onSelect,
}: TransactionSelectorProps) {
  const [open, setOpen] = React.useState(false);
  const [filter, setFilter] = React.useState("");
  const containerRef = React.useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  React.useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
      return () =>
        document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [open]);

  const filtered = React.useMemo(() => {
    if (!filter) return transactions;
    const lowerFilter = filter.toLowerCase();
    return transactions.filter(
      (t) =>
        t.name.toLowerCase().includes(lowerFilter) ||
        t.path?.toLowerCase().includes(lowerFilter) ||
        t.method?.toLowerCase().includes(lowerFilter),
    );
  }, [transactions, filter]);

  const selectedTxn = transactions.find((t) => t.fqn === selectedFqn);

  return (
    <div ref={containerRef} className="relative">
      {/* Trigger button */}
      <Button
        variant="outline"
        size="default"
        className="w-72 justify-between gap-2"
        onClick={() => setOpen((prev) => !prev)}
        disabled={isLoading && transactions.length === 0}
      >
        <div className="flex items-center gap-2 truncate">
          {isLoading ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Route className="size-3.5 shrink-0" />
          )}
          <span className="truncate">
            {selectedTxn ? selectedTxn.name : "Select transaction..."}
          </span>
        </div>
        <ChevronDown className="size-3.5 shrink-0 opacity-50" />
      </Button>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-96 rounded-md border bg-popover shadow-lg">
          {/* Search filter */}
          <div className="border-b p-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter transactions..."
                className="h-7 pl-7 text-xs"
                autoFocus
              />
            </div>
          </div>

          {/* Transaction list */}
          <ScrollArea className="max-h-72">
            {filtered.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                {transactions.length === 0
                  ? "No transactions discovered"
                  : "No matching transactions"}
              </div>
            ) : (
              <div className="p-1">
                {filtered.map((txn) => (
                  <button
                    key={txn.fqn}
                    className={cn(
                      "flex w-full items-start gap-2 rounded-sm px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent",
                      txn.fqn === selectedFqn && "bg-accent",
                    )}
                    onClick={() => {
                      onSelect(txn.fqn);
                      setOpen(false);
                      setFilter("");
                    }}
                  >
                    {/* HTTP method badge */}
                    {txn.method && (
                      <span
                        className={cn(
                          "mt-0.5 inline-flex shrink-0 rounded px-1 py-0.5 text-[10px] font-semibold leading-none",
                          methodColor(txn.method),
                        )}
                      >
                        {txn.method}
                      </span>
                    )}

                    {/* Name and metadata */}
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{txn.name}</div>
                      <div className="mt-0.5 flex gap-2 text-muted-foreground">
                        <span>depth: {txn.depth}</span>
                        <span>nodes: {txn.node_count}</span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </ScrollArea>
        </div>
      )}
    </div>
  );
}
```

---

## Task 3: Add `transactionToElements` Converter

**Files:**
- Modify: `cast-clone-frontend/lib/cytoscape-elements.ts`

- [ ] **Step 3.1: Add the transactionToElements function**

Append the following to `cast-clone-frontend/lib/cytoscape-elements.ts`. If the file does not exist yet (M4 not implemented), create it with just this function.

```typescript
// Add to cast-clone-frontend/lib/cytoscape-elements.ts

import type { ElementDefinition } from "cytoscape";
import type {
  GraphNodeResponse,
  GraphEdgeResponse,
  TransactionDetailResponse,
} from "@/lib/types";

/**
 * Map a node kind to a CSS class for Cytoscape styling.
 * These classes are referenced in the GraphView stylesheet.
 */
function nodeClass(node: GraphNodeResponse): string {
  const classes: string[] = [];

  switch (node.kind?.toUpperCase()) {
    case "FUNCTION":
      classes.push("fn-node");
      break;
    case "CLASS":
      classes.push("class-node");
      break;
    case "TABLE":
      classes.push("table-node");
      break;
    case "ENDPOINT":
      classes.push("endpoint-node");
      break;
    default:
      classes.push("default-node");
  }

  return classes.join(" ");
}

/**
 * Convert a TransactionDetailResponse into Cytoscape ElementDefinition[].
 *
 * Applies special styling classes:
 * - `entry-point`: bold border + slightly larger — the first node in the flow
 * - `terminal-node`: orange border — nodes with WRITES edges to tables
 * - `fn-node`, `class-node`, `table-node`, `endpoint-node`: kind-based styling
 *
 * @param detail  The transaction detail response (nodes + edges)
 * @param entryPointFqn  FQN of the transaction (used to find the entry point via STARTS_AT edge)
 */
export function transactionToElements(
  detail: TransactionDetailResponse,
  entryPointFqn: string | null,
): ElementDefinition[] {
  const elements: ElementDefinition[] = [];

  // Build a set of FQNs that have outgoing WRITES edges (terminal nodes)
  const terminalFqns = new Set<string>();
  for (const edge of detail.edges) {
    if (edge.kind === "WRITES" || edge.kind === "READS") {
      terminalFqns.add(edge.source_fqn);
    }
  }

  // Find entry point FQN: the target of STARTS_AT edge from the transaction node
  let resolvedEntryFqn: string | null = null;
  for (const edge of detail.edges) {
    if (edge.kind === "STARTS_AT") {
      resolvedEntryFqn = edge.target_fqn;
      break;
    }
  }

  // Build node set for quick lookup
  const nodeFqns = new Set(detail.nodes.map((n) => n.fqn));

  // Convert nodes
  for (const node of detail.nodes) {
    // Skip Transaction-type meta nodes — we only render the actual call chain
    if (node.kind?.toUpperCase() === "TRANSACTION") {
      continue;
    }

    const classes: string[] = [nodeClass(node)];

    if (node.fqn === resolvedEntryFqn) {
      classes.push("entry-point");
    }
    if (terminalFqns.has(node.fqn)) {
      classes.push("terminal-node");
    }

    elements.push({
      group: "nodes",
      data: {
        id: node.fqn,
        label: node.name,
        kind: node.kind,
        language: node.language,
        path: node.path,
        line: node.line,
        loc: node.loc,
        complexity: node.complexity,
        ...node.properties,
      },
      classes: classes.join(" "),
    });
  }

  // Convert edges — only include edges where both source and target are in the node set
  // Skip meta-edges (STARTS_AT, ENDS_AT, INCLUDES) as they connect to the Transaction node
  const META_EDGE_KINDS = new Set(["STARTS_AT", "ENDS_AT", "INCLUDES"]);

  for (const edge of detail.edges) {
    if (META_EDGE_KINDS.has(edge.kind)) {
      continue;
    }

    // Only include edges where both endpoints are visible nodes
    if (!nodeFqns.has(edge.source_fqn) || !nodeFqns.has(edge.target_fqn)) {
      continue;
    }

    elements.push({
      group: "edges",
      data: {
        id: `${edge.source_fqn}->${edge.target_fqn}:${edge.kind}`,
        source: edge.source_fqn,
        target: edge.target_fqn,
        kind: edge.kind,
        confidence: edge.confidence,
        label: edge.kind,
      },
      classes: edge.kind === "WRITES" || edge.kind === "READS" ? "data-edge" : "call-edge",
    });
  }

  return elements;
}
```

- [ ] **Step 3.2: Verify the file compiles**

```bash
cd cast-clone-frontend && npx tsc --noEmit --pretty 2>&1 | head -30
```

Fix any type errors. Common issues:
- `cytoscape` types not installed: run `npm install --save-dev @types/cytoscape`
- Missing `TransactionDetailResponse` type — should exist from M2

---

## Task 4: Wire Transaction View into Graph Page

**Files:**
- Modify: `cast-clone-frontend/app/projects/[id]/graph/page.tsx`

- [ ] **Step 4.1: Add transaction imports and hook call**

Add these imports at the top of the file:

```typescript
import { useTransactions } from "@/hooks/useTransactions";
import { TransactionSelector } from "@/components/graph/TransactionSelector";
```

- [ ] **Step 4.2: Initialize the useTransactions hook in the component body**

Add inside the component function, after existing state declarations:

```typescript
const {
  transactions,
  selectedFqn: selectedTxnFqn,
  transactionElements,
  isLoading: txnLoading,
  error: txnError,
  loadTransactions,
  selectTransaction,
  clearSelection: clearTxnSelection,
} = useTransactions();
```

- [ ] **Step 4.3: Load transactions when switching to transaction view**

Add a `useEffect` that triggers when `currentView` changes to `'transaction'`:

```typescript
React.useEffect(() => {
  if (currentView === "transaction" && transactions.length === 0) {
    loadTransactions(projectId);
  }
  // Clear transaction selection when leaving transaction view
  if (currentView !== "transaction") {
    clearTxnSelection();
  }
}, [currentView, projectId, transactions.length, loadTransactions, clearTxnSelection]);
```

- [ ] **Step 4.4: Add TransactionSelector to the toolbar area**

In the JSX, inside the toolbar/controls area, add a conditional render when in transaction view:

```tsx
{currentView === "transaction" && (
  <TransactionSelector
    transactions={transactions}
    selectedFqn={selectedTxnFqn}
    isLoading={txnLoading}
    onSelect={(fqn) => selectTransaction(projectId, fqn)}
  />
)}
```

- [ ] **Step 4.5: Define the dagre LR layout config**

Add a layout config constant (near the top of the file or inside the component):

```typescript
const TRANSACTION_LAYOUT = {
  name: "dagre",
  rankDir: "LR",
  nodeSep: 30,
  rankSep: 60,
  animate: true,
  animationDuration: 300,
};
```

- [ ] **Step 4.6: Pass transaction elements and layout to GraphView**

Update the `GraphView` render to conditionally use transaction data:

```tsx
<GraphView
  elements={currentView === "transaction" ? transactionElements : moduleElements}
  layout={currentView === "transaction" ? TRANSACTION_LAYOUT : defaultLayout}
  mode={currentView === "transaction" ? "transaction" : "explore"}
  onNodeSelect={handleNodeSelect}
/>
```

- [ ] **Step 4.7: Show error state for transaction loading failures**

Add error display below the TransactionSelector:

```tsx
{currentView === "transaction" && txnError && (
  <div className="px-3 py-2 text-xs text-destructive">
    {txnError}
  </div>
)}
```

- [ ] **Step 4.8: Show empty state when no transaction is selected**

Add a centered message when in transaction view but nothing is selected:

```tsx
{currentView === "transaction" && !selectedTxnFqn && !txnLoading && (
  <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
    Select a transaction above to view its call flow
  </div>
)}
```

---

## Task 5: Update GraphView for Transaction Mode

**Files:**
- Modify: `cast-clone-frontend/components/graph/GraphView.tsx`

- [ ] **Step 5.1: Add mode prop to GraphView**

Update the component's props interface:

```typescript
interface GraphViewProps {
  elements: ElementDefinition[];
  layout: LayoutOptions;
  /** 'explore' enables drill-down; 'transaction' disables it */
  mode?: "explore" | "transaction";
  onNodeSelect?: (nodeData: Record<string, unknown>) => void;
}
```

Default value: `mode = "explore"`.

- [ ] **Step 5.2: Disable double-click drill-down in transaction mode**

In the Cytoscape event handler for `dbltap` (double-click), wrap the drill-down logic in a mode check:

```typescript
cy.on("dbltap", "node", (event) => {
  // No drill-down in transaction view — flat graph
  if (mode === "transaction") return;

  // ... existing drill-down logic ...
});
```

- [ ] **Step 5.3: Add transaction-specific stylesheet entries**

Add these style rules to the Cytoscape stylesheet array:

```typescript
// Entry point node: bold border, slightly larger
{
  selector: ".entry-point",
  style: {
    "border-width": 3,
    "border-color": "#2563eb",    // blue-600
    width: 50,
    height: 50,
    "font-weight": "bold",
  },
},
// Terminal node (table writes): orange border
{
  selector: ".terminal-node",
  style: {
    "border-width": 3,
    "border-color": "#f97316",    // orange-500
    "border-style": "double",
  },
},
// Data edges (READS/WRITES): dashed
{
  selector: ".data-edge",
  style: {
    "line-style": "dashed",
    "line-color": "#f97316",      // orange-500
    "target-arrow-color": "#f97316",
  },
},
// Call edges: solid
{
  selector: ".call-edge",
  style: {
    "line-style": "solid",
    "line-color": "#6b7280",      // gray-500
    "target-arrow-color": "#6b7280",
  },
},
```

---

## Task 6: Verify Transaction Rendering

- [ ] **Step 6.1: Run TypeScript compilation check**

```bash
cd cast-clone-frontend && npm run typecheck
```

Fix any type errors.

- [ ] **Step 6.2: Run lint**

```bash
cd cast-clone-frontend && npm run lint
```

Fix any lint issues.

- [ ] **Step 6.3: Run format**

```bash
cd cast-clone-frontend && npm run format
```

- [ ] **Step 6.4: Manual smoke test**

Start the dev server and verify:

```bash
cd cast-clone-frontend && npm run dev
```

1. Navigate to a project's graph page
2. Switch view to "Transaction" using the view switcher
3. Confirm the TransactionSelector dropdown renders with "Select transaction..." placeholder
4. If the backend is running with analyzed data, select a transaction and verify:
   - The call graph renders left-to-right (dagre LR)
   - Entry point node has a blue bold border
   - Terminal nodes (table writes) have orange borders
   - Double-click does NOT trigger drill-down
   - Edges render as solid (CALLS) or dashed (READS/WRITES)

---

## Verification Checklist

After all tasks are complete, confirm:

- [ ] `cast-clone-frontend/hooks/useTransactions.ts` exists and exports `useTransactions`
- [ ] `cast-clone-frontend/components/graph/TransactionSelector.tsx` exists and exports `TransactionSelector`
- [ ] `cast-clone-frontend/lib/cytoscape-elements.ts` contains `transactionToElements()` function
- [ ] Graph page conditionally renders `TransactionSelector` when `currentView === 'transaction'`
- [ ] Graph page passes `transactionElements` and dagre LR layout to `GraphView` in transaction mode
- [ ] `GraphView` accepts `mode` prop and disables drill-down when `mode === 'transaction'`
- [ ] `GraphView` stylesheet includes entry-point, terminal-node, data-edge, and call-edge styles
- [ ] `npm run typecheck` passes with zero errors
- [ ] `npm run lint` passes
