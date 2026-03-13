# Phase 3 M6: Metrics Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a new metrics dashboard page at `/projects/[id]/metrics` showing summary cards (modules, classes, functions, LOC), top-10 tables (complexity, fan-in, fan-out), and counts for communities, circular dependencies, and dead code. Click any row to navigate to that node in the graph.

**Architecture:** New Next.js page. Uses `useAnalysisData.loadMetrics()` hook from M3. Simple component composition: MetricCard for summary stats, TopTenTable for ranked lists. No charts — tables are sufficient per spec.

**Tech Stack:** TypeScript, React 18, Next.js 14 (App Router), Tailwind CSS, shadcn components

**Dependencies:** Phase 3 M2 (metrics API endpoint), Phase 3 M3 (hooks + types)

---

## File Structure

```
cast-clone-frontend/
├── app/
│   └── projects/
│       └── [id]/
│           ├── page.tsx             # MODIFY — add link to metrics dashboard
│           └── metrics/
│               └── page.tsx         # CREATE — metrics dashboard page
└── components/
    └── metrics/
        ├── MetricCard.tsx           # CREATE — summary stat card
        └── TopTenTable.tsx          # CREATE — ranked table component
```

---

## Task 1: Create MetricCard Component

**Files:**
- Create: `cast-clone-frontend/components/metrics/MetricCard.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client"

import * as React from "react"
import type { LucideIcon } from "lucide-react"

interface MetricCardProps {
  title: string
  value: number | string
  icon: LucideIcon
  subtitle?: string
  className?: string
}

export function MetricCard({ title, value, icon: Icon, subtitle, className }: MetricCardProps) {
  return (
    <div className={`rounded-lg border bg-card p-4 ${className ?? ""}`}>
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">{title}</span>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-2 text-2xl font-bold">{typeof value === "number" ? value.toLocaleString() : value}</div>
      {subtitle && <div className="mt-1 text-xs text-muted-foreground">{subtitle}</div>}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add components/metrics/MetricCard.tsx
git commit -m "feat(phase3): add MetricCard component"
```

---

## Task 2: Create TopTenTable Component

**Files:**
- Create: `cast-clone-frontend/components/metrics/TopTenTable.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client"

import * as React from "react"
import type { RankedItem } from "@/lib/types"

interface TopTenTableProps {
  title: string
  items: RankedItem[]
  valueLabel: string
  onRowClick?: (fqn: string) => void
}

export function TopTenTable({ title, items, valueLabel, onRowClick }: TopTenTableProps) {
  return (
    <div className="rounded-lg border bg-card">
      <div className="px-4 py-3 border-b">
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="text-left px-4 py-2 font-medium">#</th>
              <th className="text-left px-4 py-2 font-medium">Name</th>
              <th className="text-right px-4 py-2 font-medium">{valueLabel}</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={3} className="px-4 py-4 text-center text-muted-foreground">
                  No data available
                </td>
              </tr>
            )}
            {items.map((item, idx) => (
              <tr
                key={item.fqn}
                className="border-b last:border-0 hover:bg-muted/50 cursor-pointer"
                onClick={() => onRowClick?.(item.fqn)}
              >
                <td className="px-4 py-2 text-muted-foreground">{idx + 1}</td>
                <td className="px-4 py-2">
                  <div className="font-medium">{item.name}</div>
                  <div className="text-xs text-muted-foreground font-mono truncate max-w-xs">
                    {item.fqn}
                  </div>
                </td>
                <td className="px-4 py-2 text-right font-mono font-medium">
                  {item.value.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add components/metrics/TopTenTable.tsx
git commit -m "feat(phase3): add TopTenTable component"
```

---

## Task 3: Create Metrics Dashboard Page

**Files:**
- Create: `cast-clone-frontend/app/projects/[id]/metrics/page.tsx`

- [ ] **Step 1: Write the page**

```tsx
"use client"

import * as React from "react"
import { useParams, useRouter } from "next/navigation"
import {
  Box,
  Code2,
  FileCode2,
  Hash,
  GitBranch,
  RefreshCcw,
  Trash2,
  Palette,
  ArrowLeft,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { MetricCard } from "@/components/metrics/MetricCard"
import { TopTenTable } from "@/components/metrics/TopTenTable"
import { useAnalysisData } from "@/hooks/useAnalysisData"

export default function MetricsDashboardPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const { metrics, isLoading, error, loadMetrics } = useAnalysisData()

  React.useEffect(() => {
    if (params.id) {
      loadMetrics(params.id)
    }
  }, [params.id, loadMetrics])

  const navigateToGraph = (fqn: string) => {
    // Navigate to graph page with the node selected
    router.push(`/projects/${params.id}/graph?select=${encodeURIComponent(fqn)}`)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-muted-foreground">Loading metrics...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-red-500">{error}</div>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-muted-foreground">No metrics available. Run analysis first.</div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-auto">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b">
        <Button variant="ghost" size="icon" onClick={() => router.back()}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-lg font-semibold">Metrics Dashboard</h1>
      </div>

      <div className="p-4 space-y-6 max-w-5xl mx-auto w-full">
        {/* Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard title="Modules" value={metrics.overview.modules} icon={Box} />
          <MetricCard title="Classes" value={metrics.overview.classes} icon={Code2} />
          <MetricCard title="Functions" value={metrics.overview.functions} icon={FileCode2} />
          <MetricCard
            title="Total LOC"
            value={metrics.overview.total_loc}
            icon={Hash}
          />
        </div>

        {/* Analysis Summary Cards */}
        <div className="grid grid-cols-3 gap-4">
          <MetricCard
            title="Communities"
            value={metrics.community_count}
            icon={Palette}
            subtitle="Louvain algorithm"
          />
          <MetricCard
            title="Circular Dependencies"
            value={metrics.circular_dependency_count}
            icon={RefreshCcw}
            subtitle={metrics.circular_dependency_count > 0 ? "Needs attention" : "Clean"}
            className={metrics.circular_dependency_count > 0 ? "border-red-200" : ""}
          />
          <MetricCard
            title="Dead Code Candidates"
            value={metrics.dead_code_count}
            icon={Trash2}
            subtitle="Unreferenced functions"
          />
        </div>

        {/* Top 10 Tables */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <TopTenTable
            title="Most Complex Classes"
            items={metrics.most_complex}
            valueLabel="Complexity"
            onRowClick={navigateToGraph}
          />
          <TopTenTable
            title="Highest Fan-In (Most Depended Upon)"
            items={metrics.highest_fan_in}
            valueLabel="Fan-In"
            onRowClick={navigateToGraph}
          />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <TopTenTable
            title="Highest Fan-Out (Depends on Most)"
            items={metrics.highest_fan_out}
            valueLabel="Fan-Out"
            onRowClick={navigateToGraph}
          />
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add app/projects/[id]/metrics/page.tsx
git commit -m "feat(phase3): add metrics dashboard page with summary cards and top-10 tables"
```

---

## Task 4: Add Metrics Link to Project Dashboard

**Files:**
- Modify: `cast-clone-frontend/app/projects/[id]/page.tsx`

- [ ] **Step 1: Add a link/button to the metrics dashboard**

In the project dashboard page, add a button that navigates to the metrics page. Add it alongside the existing "View Graph" link:

```tsx
<Button
  variant="outline"
  onClick={() => router.push(`/projects/${params.id}/metrics`)}
  disabled={project?.status !== "analyzed"}
>
  <Hash className="h-4 w-4 mr-2" />
  View Metrics
</Button>
```

Add the `Hash` import from `lucide-react`.

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add app/projects/[id]/page.tsx
git commit -m "feat(phase3): add metrics dashboard link to project page"
```

---

## Task 5: Verify All Compiles

- [ ] **Step 1: Run type check**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 2: Run dev server to verify rendering**

Run: `cd cast-clone-frontend && npm run dev`
Expected: Dev server starts without errors. Navigate to `/projects/[id]/metrics` shows the dashboard layout.
