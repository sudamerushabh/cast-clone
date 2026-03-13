# Phase 3 M3: Frontend Foundation — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add TypeScript types, API client functions, and React hooks for all Phase 3 features — impact analysis, path finder, communities, circular dependencies, dead code, metrics, and enhanced node details.

**Architecture:** Extend existing `lib/types.ts` with Phase 3 response types. Extend existing `lib/api.ts` with 7 new fetch functions. Create 3 new hooks: `useImpactAnalysis`, `usePathFinder`, `useAnalysisData` (covers communities, circular deps, dead code, metrics).

**Tech Stack:** TypeScript, React 18, Next.js 14 (App Router)

**Dependencies:** Phase 2 M2 (frontend foundation), Phase 3 M2 (backend API endpoints)

---

## File Structure

```
cast-clone-frontend/
├── lib/
│   ├── types.ts                     # MODIFY — add Phase 3 types
│   └── api.ts                       # MODIFY — add 7 API functions
└── hooks/
    ├── useImpactAnalysis.ts         # CREATE
    ├── usePathFinder.ts             # CREATE
    └── useAnalysisData.ts           # CREATE
```

---

## Task 1: Add Phase 3 TypeScript Types

**Files:**
- Modify: `cast-clone-frontend/lib/types.ts`

- [ ] **Step 1: Add types to the end of lib/types.ts**

```typescript
// ── Phase 3: Impact Analysis ────────────────────────────

export interface AffectedNode {
  fqn: string
  name: string
  type: string
  file: string | null
  depth: number
}

export interface ImpactSummary {
  total: number
  by_type: Record<string, number>
  by_depth: Record<string, number>
}

export interface ImpactAnalysisResponse {
  node: string
  direction: string
  max_depth: number
  summary: ImpactSummary
  affected: AffectedNode[]
}

// ── Phase 3: Path Finder ────────────────────────────────

export interface PathNode {
  fqn: string
  name: string
  type: string
}

export interface PathEdge {
  type: string
  source: string
  target: string
}

export interface PathFinderResponse {
  from_fqn: string
  to_fqn: string
  nodes: PathNode[]
  edges: PathEdge[]
  path_length: number
}

// ── Phase 3: Communities ────────────────────────────────

export interface CommunityInfo {
  community_id: number
  size: number
  members: string[]
}

export interface CommunitiesResponse {
  communities: CommunityInfo[]
  total: number
  modularity: number | null
}

// ── Phase 3: Circular Dependencies ──────────────────────

export interface CircularDependency {
  cycle: string[]
  cycle_length: number
}

export interface CircularDependenciesResponse {
  cycles: CircularDependency[]
  total: number
  level: string
}

// ── Phase 3: Dead Code ──────────────────────────────────

export interface DeadCodeCandidate {
  fqn: string
  name: string
  path: string | null
  line: number | null
  loc: number | null
}

export interface DeadCodeResponse {
  candidates: DeadCodeCandidate[]
  total: number
  type_filter: string
}

// ── Phase 3: Metrics Dashboard ──────────────────────────

export interface OverviewStats {
  modules: number
  classes: number
  functions: number
  total_loc: number
}

export interface RankedItem {
  fqn: string
  name: string
  value: number
}

export interface MetricsResponse {
  overview: OverviewStats
  most_complex: RankedItem[]
  highest_fan_in: RankedItem[]
  highest_fan_out: RankedItem[]
  community_count: number
  circular_dependency_count: number
  dead_code_count: number
}

// ── Phase 3: Enhanced Node Details ──────────────────────

export interface NodeDetailResponse {
  fqn: string
  name: string
  type: string
  language: string | null
  path: string | null
  line: number | null
  loc: number | null
  complexity: number | null
  fan_in: number
  fan_out: number
  community_id: number | null
  callers: PathNode[]
  callees: PathNode[]
}
```

- [ ] **Step 2: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add lib/types.ts
git commit -m "feat(phase3): add TypeScript types for analysis API responses"
```

---

## Task 2: Add API Client Functions

**Files:**
- Modify: `cast-clone-frontend/lib/api.ts`

- [ ] **Step 1: Add 7 new API functions to the end of lib/api.ts**

```typescript
// ── Phase 3: Analysis APIs ──────────────────────────────

export async function getImpactAnalysis(
  projectId: string,
  nodeFqn: string,
  direction: "downstream" | "upstream" | "both" = "downstream",
  maxDepth: number = 5
): Promise<ImpactAnalysisResponse> {
  const params = new URLSearchParams({
    direction,
    max_depth: String(maxDepth),
  })
  return apiFetch<ImpactAnalysisResponse>(
    `/api/v1/analysis/${projectId}/impact/${encodeURIComponent(nodeFqn)}?${params}`
  )
}

export async function getShortestPath(
  projectId: string,
  fromFqn: string,
  toFqn: string,
  maxDepth: number = 10
): Promise<PathFinderResponse> {
  const params = new URLSearchParams({
    from_fqn: fromFqn,
    to_fqn: toFqn,
    max_depth: String(maxDepth),
  })
  return apiFetch<PathFinderResponse>(
    `/api/v1/analysis/${projectId}/path?${params}`
  )
}

export async function getCommunities(
  projectId: string
): Promise<CommunitiesResponse> {
  return apiFetch<CommunitiesResponse>(
    `/api/v1/analysis/${projectId}/communities`
  )
}

export async function getCircularDependencies(
  projectId: string,
  level: "module" | "class" = "module"
): Promise<CircularDependenciesResponse> {
  return apiFetch<CircularDependenciesResponse>(
    `/api/v1/analysis/${projectId}/circular-dependencies?level=${level}`
  )
}

export async function getDeadCode(
  projectId: string,
  type: "function" | "class" = "function",
  minLoc: number = 5
): Promise<DeadCodeResponse> {
  const params = new URLSearchParams({
    type,
    min_loc: String(minLoc),
  })
  return apiFetch<DeadCodeResponse>(
    `/api/v1/analysis/${projectId}/dead-code?${params}`
  )
}

export async function getMetrics(
  projectId: string
): Promise<MetricsResponse> {
  return apiFetch<MetricsResponse>(
    `/api/v1/analysis/${projectId}/metrics`
  )
}

export async function getNodeDetails(
  projectId: string,
  nodeFqn: string
): Promise<NodeDetailResponse> {
  return apiFetch<NodeDetailResponse>(
    `/api/v1/analysis/${projectId}/node/${encodeURIComponent(nodeFqn)}/details`
  )
}
```

Also add the necessary type imports at the top of `lib/api.ts`:

```typescript
import type {
  // ... existing imports ...
  ImpactAnalysisResponse,
  PathFinderResponse,
  CommunitiesResponse,
  CircularDependenciesResponse,
  DeadCodeResponse,
  MetricsResponse,
  NodeDetailResponse,
} from "./types"
```

- [ ] **Step 2: Verify compilation**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add lib/api.ts
git commit -m "feat(phase3): add API client functions for analysis endpoints"
```

---

## Task 3: Create useImpactAnalysis Hook

**Files:**
- Create: `cast-clone-frontend/hooks/useImpactAnalysis.ts`

- [ ] **Step 1: Write the hook**

```typescript
"use client"

import { useCallback, useState } from "react"
import { getImpactAnalysis } from "@/lib/api"
import type { ImpactAnalysisResponse } from "@/lib/types"

interface UseImpactAnalysisReturn {
  data: ImpactAnalysisResponse | null
  isLoading: boolean
  error: string | null
  analyze: (
    projectId: string,
    nodeFqn: string,
    direction?: "downstream" | "upstream" | "both",
    maxDepth?: number
  ) => Promise<void>
  clear: () => void
}

export function useImpactAnalysis(): UseImpactAnalysisReturn {
  const [data, setData] = useState<ImpactAnalysisResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const analyze = useCallback(
    async (
      projectId: string,
      nodeFqn: string,
      direction: "downstream" | "upstream" | "both" = "downstream",
      maxDepth: number = 5
    ) => {
      setIsLoading(true)
      setError(null)
      try {
        const result = await getImpactAnalysis(
          projectId,
          nodeFqn,
          direction,
          maxDepth
        )
        setData(result)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Impact analysis failed")
        setData(null)
      } finally {
        setIsLoading(false)
      }
    },
    []
  )

  const clear = useCallback(() => {
    setData(null)
    setError(null)
  }, [])

  return { data, isLoading, error, analyze, clear }
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add hooks/useImpactAnalysis.ts
git commit -m "feat(phase3): add useImpactAnalysis hook"
```

---

## Task 4: Create usePathFinder Hook

**Files:**
- Create: `cast-clone-frontend/hooks/usePathFinder.ts`

- [ ] **Step 1: Write the hook**

```typescript
"use client"

import { useCallback, useState } from "react"
import { getShortestPath } from "@/lib/api"
import type { PathFinderResponse } from "@/lib/types"

interface UsePathFinderReturn {
  data: PathFinderResponse | null
  isLoading: boolean
  error: string | null
  findPath: (
    projectId: string,
    fromFqn: string,
    toFqn: string,
    maxDepth?: number
  ) => Promise<void>
  clear: () => void
}

export function usePathFinder(): UsePathFinderReturn {
  const [data, setData] = useState<PathFinderResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const findPath = useCallback(
    async (
      projectId: string,
      fromFqn: string,
      toFqn: string,
      maxDepth: number = 10
    ) => {
      setIsLoading(true)
      setError(null)
      try {
        const result = await getShortestPath(projectId, fromFqn, toFqn, maxDepth)
        setData(result)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Path finding failed")
        setData(null)
      } finally {
        setIsLoading(false)
      }
    },
    []
  )

  const clear = useCallback(() => {
    setData(null)
    setError(null)
  }, [])

  return { data, isLoading, error, findPath, clear }
}
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-frontend
git add hooks/usePathFinder.ts
git commit -m "feat(phase3): add usePathFinder hook"
```

---

## Task 5: Create useAnalysisData Hook

**Files:**
- Create: `cast-clone-frontend/hooks/useAnalysisData.ts`

- [ ] **Step 1: Write the hook**

This hook fetches communities, circular dependencies, dead code, and metrics — data that loads once per project and doesn't need interactive state.

```typescript
"use client"

import { useCallback, useState } from "react"
import {
  getCommunities,
  getCircularDependencies,
  getDeadCode,
  getMetrics,
  getNodeDetails,
} from "@/lib/api"
import type {
  CommunitiesResponse,
  CircularDependenciesResponse,
  DeadCodeResponse,
  MetricsResponse,
  NodeDetailResponse,
} from "@/lib/types"

interface AnalysisDataState {
  communities: CommunitiesResponse | null
  circularDeps: CircularDependenciesResponse | null
  deadCode: DeadCodeResponse | null
  metrics: MetricsResponse | null
  nodeDetails: NodeDetailResponse | null
}

interface UseAnalysisDataReturn extends AnalysisDataState {
  isLoading: boolean
  error: string | null
  loadCommunities: (projectId: string) => Promise<void>
  loadCircularDeps: (projectId: string, level?: "module" | "class") => Promise<void>
  loadDeadCode: (projectId: string, type?: "function" | "class", minLoc?: number) => Promise<void>
  loadMetrics: (projectId: string) => Promise<void>
  loadNodeDetails: (projectId: string, fqn: string) => Promise<void>
}

export function useAnalysisData(): UseAnalysisDataReturn {
  const [state, setState] = useState<AnalysisDataState>({
    communities: null,
    circularDeps: null,
    deadCode: null,
    metrics: null,
    nodeDetails: null,
  })
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const wrapLoad = useCallback(
    async <K extends keyof AnalysisDataState>(
      key: K,
      fetcher: () => Promise<AnalysisDataState[K]>
    ) => {
      setIsLoading(true)
      setError(null)
      try {
        const result = await fetcher()
        setState((prev) => ({ ...prev, [key]: result }))
      } catch (err) {
        setError(err instanceof Error ? err.message : `Failed to load ${key}`)
      } finally {
        setIsLoading(false)
      }
    },
    []
  )

  const loadCommunities = useCallback(
    (projectId: string) => wrapLoad("communities", () => getCommunities(projectId)),
    [wrapLoad]
  )

  const loadCircularDeps = useCallback(
    (projectId: string, level: "module" | "class" = "module") =>
      wrapLoad("circularDeps", () => getCircularDependencies(projectId, level)),
    [wrapLoad]
  )

  const loadDeadCode = useCallback(
    (projectId: string, type: "function" | "class" = "function", minLoc = 5) =>
      wrapLoad("deadCode", () => getDeadCode(projectId, type, minLoc)),
    [wrapLoad]
  )

  const loadMetrics = useCallback(
    (projectId: string) => wrapLoad("metrics", () => getMetrics(projectId)),
    [wrapLoad]
  )

  const loadNodeDetails = useCallback(
    (projectId: string, fqn: string) =>
      wrapLoad("nodeDetails", () => getNodeDetails(projectId, fqn)),
    [wrapLoad]
  )

  return {
    ...state,
    isLoading,
    error,
    loadCommunities,
    loadCircularDeps,
    loadDeadCode,
    loadMetrics,
    loadNodeDetails,
  }
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add hooks/useAnalysisData.ts
git commit -m "feat(phase3): add useAnalysisData hook for communities, dead code, metrics"
```
