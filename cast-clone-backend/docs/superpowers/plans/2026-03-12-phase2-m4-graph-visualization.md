# Phase 2 M4: Graph Visualization — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Cytoscape.js for interactive graph visualization with module-level rendering, drill-down to classes/methods, and Architecture (dagre) + Dependency (fcose) view layouts.

**Architecture:** Cytoscape.js via react-cytoscapejs wrapper. Extensions registered once at module level. Data fetched via API client from M2, converted to Cytoscape elements format. Graph state managed in useGraph hook with Map-based cache.

**Tech Stack:** Cytoscape.js, react-cytoscapejs, cytoscape-dagre, cytoscape-fcose, cytoscape-expand-collapse, React 19, TypeScript

**Dependencies:**
- M1 (backend APIs): `/api/v1/graphs/{project}/nodes`, `/api/v1/graphs/{project}/edges`, `/api/v1/graphs/{project}/search`
- M2 (frontend foundation): `@/lib/types` (GraphNode, GraphEdge, Module, AggregatedEdge), `@/lib/api` (API client functions)
- M3 (frontend pages): graph page shell at `/projects/[id]/graph`

---

## File Structure

```
cast-clone-frontend/
├── lib/
│   ├── cytoscape-setup.ts         # CREATE — one-time extension registration
│   ├── cytoscape-elements.ts      # CREATE — API data → Cytoscape format converters
│   ├── graph-styles.ts            # CREATE — Cytoscape stylesheet array
│   ├── types.ts                   # ASSUMED FROM M2 — GraphNode, GraphEdge, Module, etc.
│   └── api.ts                     # ASSUMED FROM M2 — getModules(), getClassesInModule(), etc.
├── hooks/
│   └── useGraph.ts                # CREATE — graph data management hook
├── components/
│   └── graph/
│       ├── GraphView.tsx          # CREATE — main Cytoscape wrapper
│       └── GraphToolbar.tsx       # CREATE — toolbar with view switcher + controls
└── app/
    └── projects/
        └── [id]/
            └── graph/
                └── page.tsx       # CREATE — graph explorer page
```

---

## Task 1: Install npm packages

**Time:** 2 minutes

- [ ] **Step 1.1: Install Cytoscape.js and extensions**

```bash
cd cast-clone-frontend
npm install cytoscape react-cytoscapejs cytoscape-dagre cytoscape-fcose cytoscape-expand-collapse
```

- [ ] **Step 1.2: Install TypeScript type definitions**

```bash
cd cast-clone-frontend
npm install --save-dev @types/cytoscape
```

Note: `react-cytoscapejs` does not have `@types` — we will create a local declaration file.

- [ ] **Step 1.3: Create type declarations for untyped packages**

Create `cast-clone-frontend/types/cytoscape-extensions.d.ts`:

```typescript
// types/cytoscape-extensions.d.ts
// Type declarations for Cytoscape extensions that lack @types packages

declare module "react-cytoscapejs" {
  import cytoscape from "cytoscape";
  import { Component } from "react";

  interface CytoscapeComponentProps {
    id?: string;
    cy?: (cy: cytoscape.Core) => void;
    style?: React.CSSProperties;
    elements: cytoscape.ElementDefinition[];
    layout?: cytoscape.LayoutOptions;
    stylesheet?: cytoscape.Stylesheet[];
    className?: string;
    zoom?: number;
    pan?: cytoscape.Position;
    minZoom?: number;
    maxZoom?: number;
    zoomingEnabled?: boolean;
    userZoomingEnabled?: boolean;
    panningEnabled?: boolean;
    userPanningEnabled?: boolean;
    boxSelectionEnabled?: boolean;
    autoungrabify?: boolean;
    autounselectify?: boolean;
    autolock?: boolean;
  }

  export default class CytoscapeComponent extends Component<CytoscapeComponentProps> {
    static normalizeElements(
      elements:
        | cytoscape.ElementDefinition[]
        | { nodes: cytoscape.ElementDefinition[]; edges: cytoscape.ElementDefinition[] }
    ): cytoscape.ElementDefinition[];
  }
}

declare module "cytoscape-dagre" {
  import cytoscape from "cytoscape";
  const register: (cs: typeof cytoscape) => void;
  export default register;
}

declare module "cytoscape-fcose" {
  import cytoscape from "cytoscape";
  const register: (cs: typeof cytoscape) => void;
  export default register;
}

declare module "cytoscape-expand-collapse" {
  import cytoscape from "cytoscape";
  const register: (cs: typeof cytoscape) => void;
  export default register;
}
```

- [ ] **Step 1.4: Verify TypeScript compilation**

```bash
cd cast-clone-frontend
npx tsc --noEmit 2>&1 | head -20
```

Expected: no new errors related to the installed packages.

---

## Task 2: Create cytoscape-setup.ts (extension registration)

**File:** `cast-clone-frontend/lib/cytoscape-setup.ts`
**Time:** 2 minutes

- [ ] **Step 2.1: Create the extension registration module**

Create `cast-clone-frontend/lib/cytoscape-setup.ts`:

```typescript
// lib/cytoscape-setup.ts
//
// One-time registration of Cytoscape.js extensions.
// Must be called before creating any Cytoscape instance.
// Safe to call multiple times — guarded by a flag.

import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";
import fcose from "cytoscape-fcose";
import expandCollapse from "cytoscape-expand-collapse";

let registered = false;

/**
 * Register all Cytoscape extensions (dagre, fcose, expand-collapse).
 * No-op if already registered. Call this once at module load time
 * in any component that creates a Cytoscape instance.
 */
export function ensureCytoscapeExtensions(): void {
  if (registered) return;

  cytoscape.use(dagre);
  cytoscape.use(fcose);
  cytoscape.use(expandCollapse);

  registered = true;
}
```

- [ ] **Step 2.2: Verify the module compiles**

```bash
cd cast-clone-frontend
npx tsc --noEmit 2>&1 | grep cytoscape-setup || echo "No errors"
```

---

## Task 3: Create graph-styles.ts (stylesheet)

**File:** `cast-clone-frontend/lib/graph-styles.ts`
**Time:** 5 minutes

- [ ] **Step 3.1: Create the Cytoscape stylesheet**

Create `cast-clone-frontend/lib/graph-styles.ts`:

```typescript
// lib/graph-styles.ts
//
// Cytoscape stylesheet for graph visualization.
// Colors by node kind and layer, edge styles by relationship type.

import type cytoscape from "cytoscape";

/** Color palette for node kinds */
const KIND_COLORS: Record<string, string> = {
  MODULE: "#3B82F6",          // blue-500
  CLASS: "#22C55E",           // green-500
  INTERFACE: "#14B8A6",       // teal-500
  FUNCTION: "#EAB308",        // yellow-500
  TABLE: "#F97316",           // orange-500
  API_ENDPOINT: "#A855F7",    // purple-500
  ROUTE: "#A855F7",           // purple-500
  TRANSACTION: "#EC4899",     // pink-500
  MESSAGE_TOPIC: "#06B6D4",   // cyan-500
  FIELD: "#6B7280",           // gray-500
  CONFIG_FILE: "#6B7280",     // gray-500
};

/** Color palette for architectural layers */
const LAYER_COLORS: Record<string, string> = {
  presentation: "#3B82F6",    // blue-500
  business: "#22C55E",        // green-500
  data: "#F97316",            // orange-500
  utility: "#6B7280",         // gray-500
};

/** Default node color when kind is unknown */
const DEFAULT_NODE_COLOR = "#6B7280";

/** Edge style mappings */
const EDGE_STYLES: Record<string, { lineStyle: string; color: string }> = {
  CALLS: { lineStyle: "solid", color: "#6B7280" },
  DEPENDS_ON: { lineStyle: "dotted", color: "#9CA3AF" },
  READS: { lineStyle: "dashed", color: "#F97316" },
  WRITES: { lineStyle: "dashed", color: "#EF4444" },
  INHERITS: { lineStyle: "solid", color: "#3B82F6" },
  IMPLEMENTS: { lineStyle: "solid", color: "#14B8A6" },
  IMPORTS: { lineStyle: "dotted", color: "#D1D5DB" },
  CONTAINS: { lineStyle: "solid", color: "#E5E7EB" },
  INJECTS: { lineStyle: "solid", color: "#8B5CF6" },
};

/**
 * Build the Cytoscape stylesheet array.
 *
 * @param colorBy - Whether to color nodes by "kind" or "layer"
 * @returns Cytoscape stylesheet array
 */
export function buildStylesheet(
  colorBy: "kind" | "layer" = "kind"
): cytoscape.Stylesheet[] {
  const styles: cytoscape.Stylesheet[] = [
    // ── Base node style ──
    {
      selector: "node",
      style: {
        label: "data(label)",
        "text-valign": "center",
        "text-halign": "center",
        "font-size": "11px",
        "font-family": "Inter, system-ui, sans-serif",
        color: "#1F2937",
        "text-outline-color": "#FFFFFF",
        "text-outline-width": 1.5,
        "background-color": DEFAULT_NODE_COLOR,
        width: "mapData(loc, 0, 5000, 30, 80)",
        height: "mapData(loc, 0, 5000, 30, 80)",
        "min-width": "30px" as any,
        "min-height": "30px" as any,
        "border-width": 1,
        "border-color": "#D1D5DB",
        "overlay-padding": "4px",
      },
    },

    // ── Compound (parent) node style ──
    {
      selector: "node:parent",
      style: {
        "background-opacity": 0.08,
        "background-color": "#3B82F6",
        "border-width": 2,
        "border-color": "#93C5FD",
        "border-style": "dashed" as any,
        "text-valign": "top",
        "text-halign": "center",
        "font-size": "13px",
        "font-weight": "bold" as any,
        padding: "16px" as any,
        shape: "roundrectangle",
      },
    },

    // ── Selected node highlight ──
    {
      selector: "node:selected",
      style: {
        "border-width": 3,
        "border-color": "#2563EB",
        "background-color": "#DBEAFE",
        "overlay-color": "#3B82F6",
        "overlay-opacity": 0.15,
      },
    },

    // ── Base edge style ──
    {
      selector: "edge",
      style: {
        width: "mapData(weight, 1, 50, 1, 6)",
        "line-color": "#9CA3AF",
        "target-arrow-color": "#9CA3AF",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.8,
        "curve-style": "bezier",
        opacity: 0.7,
        "font-size": "9px",
      },
    },

    // ── Selected edge highlight ──
    {
      selector: "edge:selected",
      style: {
        "line-color": "#2563EB",
        "target-arrow-color": "#2563EB",
        width: 3,
        opacity: 1,
      },
    },

    // ── Hover effects ──
    {
      selector: "node:active",
      style: {
        "overlay-color": "#3B82F6",
        "overlay-opacity": 0.2,
      },
    },
  ];

  // ── Node kind-specific colors ──
  if (colorBy === "kind") {
    for (const [kind, color] of Object.entries(KIND_COLORS)) {
      styles.push({
        selector: `node[kind = "${kind}"]`,
        style: {
          "background-color": color,
          "border-color": color,
        },
      });
    }
  } else {
    // Color by architectural layer
    for (const [layer, color] of Object.entries(LAYER_COLORS)) {
      styles.push({
        selector: `node[layer = "${layer}"]`,
        style: {
          "background-color": color,
          "border-color": color,
        },
      });
    }
  }

  // ── Edge kind-specific styles ──
  for (const [kind, cfg] of Object.entries(EDGE_STYLES)) {
    styles.push({
      selector: `edge[kind = "${kind}"]`,
      style: {
        "line-style": cfg.lineStyle as any,
        "line-color": cfg.color,
        "target-arrow-color": cfg.color,
      },
    });
  }

  return styles;
}

/** Pre-built stylesheet for default (kind-based) coloring */
export const defaultStylesheet = buildStylesheet("kind");

/** Pre-built stylesheet for layer-based coloring */
export const layerStylesheet = buildStylesheet("layer");
```

---

## Task 4: Create cytoscape-elements.ts (data converters)

**File:** `cast-clone-frontend/lib/cytoscape-elements.ts`
**Time:** 5 minutes

- [ ] **Step 4.1: Create the type definitions for API responses**

These types represent what the backend API returns. They are assumed to exist in `@/lib/types` from M2. If M2 has not been implemented yet, create them here temporarily.

Create `cast-clone-frontend/lib/types.ts` (if it does not already exist — skip if M2 provided it):

```typescript
// lib/types.ts
//
// Shared TypeScript types matching the backend Pydantic schemas.
// These mirror cast-clone-backend/app/schemas/graph.py

export interface GraphNode {
  fqn: string;
  name: string;
  kind: string;
  language?: string | null;
  path?: string | null;
  line?: number | null;
  end_line?: number | null;
  loc?: number | null;
  complexity?: number | null;
  visibility?: string | null;
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  source_fqn: string;
  target_fqn: string;
  kind: string;
  confidence: string;
  evidence: string;
  properties: Record<string, unknown>;
}

export interface GraphNodeListResponse {
  nodes: GraphNode[];
  total: number;
  offset: number;
  limit: number;
}

export interface GraphEdgeListResponse {
  edges: GraphEdge[];
  total: number;
  offset: number;
  limit: number;
}

export interface AggregatedEdge {
  source_fqn: string;
  target_fqn: string;
  weight: number;
  kinds: string[];
}

export type ViewMode = "architecture" | "dependency" | "transaction";
export type DrilldownLevel = "module" | "class" | "method";
```

- [ ] **Step 4.2: Create the API client functions**

Create `cast-clone-frontend/lib/api.ts` (if it does not already exist — skip if M2 provided it):

```typescript
// lib/api.ts
//
// API client for communicating with the cast-clone backend.
// All functions return typed responses matching the backend schemas.

import type {
  GraphNode,
  GraphEdge,
  GraphNodeListResponse,
  GraphEdgeListResponse,
  AggregatedEdge,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

/** Fetch all modules for a project */
export async function getModules(projectId: string): Promise<GraphNode[]> {
  const resp = await apiFetch<GraphNodeListResponse>(
    `/api/v1/graphs/${projectId}/nodes?kind=MODULE&limit=500`
  );
  return resp.nodes;
}

/** Fetch classes within a module */
export async function getClassesInModule(
  projectId: string,
  moduleFqn: string
): Promise<GraphNode[]> {
  // Get children of a module by querying nodes that belong to this module
  const resp = await apiFetch<GraphNodeListResponse>(
    `/api/v1/graphs/${projectId}/nodes?kind=CLASS&limit=500`
  );
  // Filter client-side by FQN prefix until we have a dedicated endpoint
  return resp.nodes.filter((n) => n.fqn.startsWith(moduleFqn + "."));
}

/** Fetch methods within a class */
export async function getMethodsInClass(
  projectId: string,
  classFqn: string
): Promise<GraphNode[]> {
  const resp = await apiFetch<GraphNodeListResponse>(
    `/api/v1/graphs/${projectId}/nodes?kind=FUNCTION&limit=500`
  );
  // Filter client-side by FQN prefix until we have a dedicated endpoint
  return resp.nodes.filter((n) => n.fqn.startsWith(classFqn + "."));
}

/** Fetch edges for a project, optionally filtered by kind */
export async function getEdges(
  projectId: string,
  kind?: string
): Promise<GraphEdge[]> {
  const kindParam = kind ? `&kind=${kind}` : "";
  const resp = await apiFetch<GraphEdgeListResponse>(
    `/api/v1/graphs/${projectId}/edges?limit=2000${kindParam}`
  );
  return resp.edges;
}

/**
 * Fetch aggregated edges between modules.
 * Computes weights client-side from raw edges until a dedicated endpoint exists.
 */
export async function getAggregatedEdges(
  projectId: string,
  moduleFqns: string[]
): Promise<AggregatedEdge[]> {
  const edges = await getEdges(projectId);

  // Build module membership map: class FQN → module FQN
  const fqnToModule = new Map<string, string>();
  for (const mfqn of moduleFqns) {
    // Any FQN starting with this module prefix belongs to it
    for (const edge of edges) {
      for (const fqn of [edge.source_fqn, edge.target_fqn]) {
        if (fqn.startsWith(mfqn + ".") || fqn === mfqn) {
          fqnToModule.set(fqn, mfqn);
        }
      }
    }
  }

  // Aggregate edges between modules
  const aggregated = new Map<string, AggregatedEdge>();
  for (const edge of edges) {
    const srcModule = fqnToModule.get(edge.source_fqn);
    const tgtModule = fqnToModule.get(edge.target_fqn);
    if (!srcModule || !tgtModule || srcModule === tgtModule) continue;

    const key = `${srcModule}→${tgtModule}`;
    const existing = aggregated.get(key);
    if (existing) {
      existing.weight += 1;
      if (!existing.kinds.includes(edge.kind)) {
        existing.kinds.push(edge.kind);
      }
    } else {
      aggregated.set(key, {
        source_fqn: srcModule,
        target_fqn: tgtModule,
        weight: 1,
        kinds: [edge.kind],
      });
    }
  }

  return Array.from(aggregated.values());
}
```

- [ ] **Step 4.3: Create the Cytoscape elements converter**

Create `cast-clone-frontend/lib/cytoscape-elements.ts`:

```typescript
// lib/cytoscape-elements.ts
//
// Converters from API response data to Cytoscape.js ElementDefinition format.
// Each function takes typed API data and returns an array of Cytoscape elements.

import type cytoscape from "cytoscape";
import type { GraphNode, GraphEdge, AggregatedEdge } from "@/lib/types";

type ElementDefinition = cytoscape.ElementDefinition;

/**
 * Convert module nodes + aggregated edges to Cytoscape elements.
 * Modules are rendered as compound-capable nodes (potential parents).
 */
export function modulesToElements(
  modules: GraphNode[],
  edges: AggregatedEdge[]
): ElementDefinition[] {
  const elements: ElementDefinition[] = [];

  for (const mod of modules) {
    elements.push({
      group: "nodes",
      data: {
        id: mod.fqn,
        label: mod.name,
        kind: mod.kind,
        language: mod.language ?? undefined,
        loc: mod.loc ?? 0,
        complexity: mod.complexity ?? 0,
        path: mod.path ?? undefined,
        line: mod.line ?? undefined,
        layer: (mod.properties?.layer as string) ?? undefined,
        drillable: true,
        drillLevel: "module",
      },
    });
  }

  for (const edge of edges) {
    elements.push({
      group: "edges",
      data: {
        id: `edge-${edge.source_fqn}→${edge.target_fqn}`,
        source: edge.source_fqn,
        target: edge.target_fqn,
        weight: edge.weight,
        kind: edge.kinds[0] ?? "DEPENDS_ON",
        label: edge.weight > 1 ? String(edge.weight) : undefined,
      },
    });
  }

  return elements;
}

/**
 * Convert class nodes to Cytoscape elements as children of a module compound node.
 * The parentFqn becomes the `parent` field in Cytoscape data — rendering
 * the classes inside the module's compound boundary.
 */
export function classesToElements(
  classes: GraphNode[],
  parentFqn: string
): ElementDefinition[] {
  return classes.map((cls) => ({
    group: "nodes" as const,
    data: {
      id: cls.fqn,
      label: cls.name,
      kind: cls.kind,
      parent: parentFqn,
      language: cls.language ?? undefined,
      loc: cls.loc ?? 0,
      complexity: cls.complexity ?? 0,
      path: cls.path ?? undefined,
      line: cls.line ?? undefined,
      layer: (cls.properties?.layer as string) ?? undefined,
      drillable: true,
      drillLevel: "class",
    },
  }));
}

/**
 * Convert method/function nodes to Cytoscape elements as children of a class.
 * Methods are the leaf level — no further drill-down (drillable: false).
 * Rendered as flat nodes within the class compound boundary.
 */
export function methodsToElements(
  methods: GraphNode[],
  parentFqn: string
): ElementDefinition[] {
  return methods.map((fn) => ({
    group: "nodes" as const,
    data: {
      id: fn.fqn,
      label: fn.name,
      kind: fn.kind,
      parent: parentFqn,
      language: fn.language ?? undefined,
      loc: fn.loc ?? 0,
      complexity: fn.complexity ?? 0,
      path: fn.path ?? undefined,
      line: fn.line ?? undefined,
      drillable: false,
      drillLevel: "method",
    },
  }));
}

/**
 * Convert raw GraphEdge[] (e.g., class-level edges within an expanded module)
 * to Cytoscape edge elements. Only includes edges where both source and target
 * are present in the visibleFqns set.
 */
export function edgesToElements(
  edges: GraphEdge[],
  visibleFqns: Set<string>
): ElementDefinition[] {
  const elements: ElementDefinition[] = [];

  for (const edge of edges) {
    if (!visibleFqns.has(edge.source_fqn) || !visibleFqns.has(edge.target_fqn)) {
      continue;
    }

    elements.push({
      group: "edges",
      data: {
        id: `edge-${edge.source_fqn}→${edge.target_fqn}-${edge.kind}`,
        source: edge.source_fqn,
        target: edge.target_fqn,
        kind: edge.kind,
        weight: 1,
        confidence: edge.confidence,
      },
    });
  }

  return elements;
}

/**
 * Count elements to determine performance tier.
 * Returns the recommended performance strategy.
 */
export function getPerformanceTier(
  nodeCount: number
): "full" | "no-animation" | "simplified" | "force-drilldown" {
  if (nodeCount < 500) return "full";
  if (nodeCount < 2000) return "no-animation";
  if (nodeCount < 5000) return "simplified";
  return "force-drilldown";
}
```

---

## Task 5: Create useGraph.ts hook

**File:** `cast-clone-frontend/hooks/useGraph.ts`
**Time:** 5 minutes

- [ ] **Step 5.1: Create the graph data management hook**

Create `cast-clone-frontend/hooks/useGraph.ts`:

```typescript
// hooks/useGraph.ts
//
// React hook for managing graph data: loading, drill-down, drill-up, caching.
// All data fetching flows through @/lib/api, conversion through @/lib/cytoscape-elements.

"use client";

import { useCallback, useRef, useState } from "react";
import type cytoscape from "cytoscape";

import {
  getModules,
  getClassesInModule,
  getMethodsInClass,
  getEdges,
  getAggregatedEdges,
} from "@/lib/api";
import {
  modulesToElements,
  classesToElements,
  methodsToElements,
  edgesToElements,
  getPerformanceTier,
} from "@/lib/cytoscape-elements";
import type { GraphNode } from "@/lib/types";

type ElementDefinition = cytoscape.ElementDefinition;

interface DrilldownEntry {
  level: "module" | "class";
  fqn: string;
  name: string;
}

interface UseGraphReturn {
  /** Current Cytoscape elements to render */
  elements: ElementDefinition[];
  /** Whether data is currently loading */
  isLoading: boolean;
  /** Error message if the last operation failed */
  error: string | null;
  /** Breadcrumb path of drill-down navigation */
  drilldownPath: DrilldownEntry[];
  /** Performance tier based on current node count */
  performanceTier: "full" | "no-animation" | "simplified" | "force-drilldown";
  /** Load the initial module-level view */
  loadModules: (projectId: string) => Promise<void>;
  /** Drill into a module to show its classes */
  drillIntoModule: (projectId: string, moduleFqn: string, moduleName: string) => Promise<void>;
  /** Drill into a class to show its methods */
  drillIntoClass: (projectId: string, classFqn: string, className: string) => Promise<void>;
  /** Navigate back up one level */
  drillUp: (projectId: string) => Promise<void>;
}

/**
 * Hook for managing graph visualization data.
 *
 * Handles:
 * - Loading module-level overview
 * - Drill-down into modules (classes) and classes (methods)
 * - Drill-up navigation with breadcrumb tracking
 * - Map-based caching in useRef (no re-fetches for visited nodes)
 * - Performance tier detection
 */
export function useGraph(): UseGraphReturn {
  const [elements, setElements] = useState<ElementDefinition[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drilldownPath, setDrilldownPath] = useState<DrilldownEntry[]>([]);
  const [performanceTier, setPerformanceTier] = useState<
    "full" | "no-animation" | "simplified" | "force-drilldown"
  >("full");

  // Cache: key → ElementDefinition[]
  const cache = useRef(new Map<string, ElementDefinition[]>());
  // Cache for raw node data (needed for drill-up reconstruction)
  const nodeCache = useRef(new Map<string, GraphNode[]>());

  const loadModules = useCallback(async (projectId: string) => {
    const cacheKey = `modules:${projectId}`;

    setIsLoading(true);
    setError(null);
    setDrilldownPath([]);

    try {
      if (cache.current.has(cacheKey)) {
        const cached = cache.current.get(cacheKey)!;
        setElements(cached);
        setPerformanceTier(
          getPerformanceTier(cached.filter((e) => e.group === "nodes").length)
        );
        return;
      }

      const modules = await getModules(projectId);
      const moduleFqns = modules.map((m) => m.fqn);
      const aggregatedEdges = await getAggregatedEdges(projectId, moduleFqns);
      const els = modulesToElements(modules, aggregatedEdges);

      cache.current.set(cacheKey, els);
      nodeCache.current.set(cacheKey, modules);

      const nodeCount = els.filter((e) => e.group === "nodes").length;
      setPerformanceTier(getPerformanceTier(nodeCount));
      setElements(els);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load modules");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const drillIntoModule = useCallback(
    async (projectId: string, moduleFqn: string, moduleName: string) => {
      const cacheKey = `classes:${projectId}:${moduleFqn}`;

      setIsLoading(true);
      setError(null);

      try {
        let classElements: ElementDefinition[];

        if (cache.current.has(cacheKey)) {
          classElements = cache.current.get(cacheKey)!;
        } else {
          const classes = await getClassesInModule(projectId, moduleFqn);
          classElements = classesToElements(classes, moduleFqn);

          // Also fetch edges between these classes
          const allEdges = await getEdges(projectId);
          const classFqns = new Set(classes.map((c) => c.fqn));
          const classEdgeElements = edgesToElements(allEdges, classFqns);

          classElements = [...classElements, ...classEdgeElements];
          cache.current.set(cacheKey, classElements);
          nodeCache.current.set(cacheKey, classes);
        }

        // Add class children to existing elements
        setElements((prev) => [...prev, ...classElements]);
        setDrilldownPath((prev) => [
          ...prev,
          { level: "module", fqn: moduleFqn, name: moduleName },
        ]);

        const totalNodes =
          elements.filter((e) => e.group === "nodes").length +
          classElements.filter((e) => e.group === "nodes").length;
        setPerformanceTier(getPerformanceTier(totalNodes));
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load classes"
        );
      } finally {
        setIsLoading(false);
      }
    },
    [elements]
  );

  const drillIntoClass = useCallback(
    async (projectId: string, classFqn: string, className: string) => {
      const cacheKey = `methods:${projectId}:${classFqn}`;

      setIsLoading(true);
      setError(null);

      try {
        let methodElements: ElementDefinition[];

        if (cache.current.has(cacheKey)) {
          methodElements = cache.current.get(cacheKey)!;
        } else {
          const methods = await getMethodsInClass(projectId, classFqn);
          methodElements = methodsToElements(methods, classFqn);
          cache.current.set(cacheKey, methodElements);
        }

        setElements((prev) => [...prev, ...methodElements]);
        setDrilldownPath((prev) => [
          ...prev,
          { level: "class", fqn: classFqn, name: className },
        ]);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load methods"
        );
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  const drillUp = useCallback(
    async (projectId: string) => {
      if (drilldownPath.length === 0) return;

      // Pop the last drilldown entry
      const newPath = drilldownPath.slice(0, -1);
      setDrilldownPath(newPath);

      // Reload from the appropriate level
      if (newPath.length === 0) {
        // Back to module view
        await loadModules(projectId);
      } else {
        // Rebuild elements up to this drilldown level
        // Start with modules
        const moduleCacheKey = `modules:${projectId}`;
        let els = cache.current.get(moduleCacheKey) ?? [];

        for (const entry of newPath) {
          if (entry.level === "module") {
            const classCacheKey = `classes:${projectId}:${entry.fqn}`;
            const classEls = cache.current.get(classCacheKey) ?? [];
            els = [...els, ...classEls];
          } else if (entry.level === "class") {
            const methodCacheKey = `methods:${projectId}:${entry.fqn}`;
            const methodEls = cache.current.get(methodCacheKey) ?? [];
            els = [...els, ...methodEls];
          }
        }

        setElements(els);
      }
    },
    [drilldownPath, loadModules]
  );

  return {
    elements,
    isLoading,
    error,
    drilldownPath,
    performanceTier,
    loadModules,
    drillIntoModule,
    drillIntoClass,
    drillUp,
  };
}
```

---

## Task 6: Create GraphView.tsx (Cytoscape wrapper)

**File:** `cast-clone-frontend/components/graph/GraphView.tsx`
**Time:** 5 minutes

- [ ] **Step 6.1: Create the main Cytoscape visualization component**

Create `cast-clone-frontend/components/graph/GraphView.tsx`:

```typescript
// components/graph/GraphView.tsx
//
// Main Cytoscape.js wrapper component using react-cytoscapejs.
// Handles: rendering, layout, click/dblclick events, expand-collapse init.

"use client";

import React, { useCallback, useEffect, useRef } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import type cytoscape from "cytoscape";

import { ensureCytoscapeExtensions } from "@/lib/cytoscape-setup";
import { defaultStylesheet, layerStylesheet } from "@/lib/graph-styles";
import type { ViewMode } from "@/lib/types";

// Register extensions before any Cytoscape instance is created
ensureCytoscapeExtensions();

/** Layout configurations for each view mode */
const LAYOUT_CONFIGS: Record<ViewMode, cytoscape.LayoutOptions> = {
  architecture: {
    name: "dagre",
    rankDir: "TB",
    nodeSep: 50,
    rankSep: 80,
    animate: true,
    animationDuration: 300,
  } as cytoscape.LayoutOptions,
  dependency: {
    name: "fcose",
    quality: "default",
    randomize: true,
    animate: true,
    animationDuration: 500,
    nodeRepulsion: 4500,
    idealEdgeLength: 100,
  } as cytoscape.LayoutOptions,
  transaction: {
    name: "dagre",
    rankDir: "LR",
    nodeSep: 30,
    rankSep: 60,
    animate: true,
    animationDuration: 300,
  } as cytoscape.LayoutOptions,
};

interface GraphViewProps {
  /** Cytoscape elements to render */
  elements: cytoscape.ElementDefinition[];
  /** Active view mode controls layout algorithm */
  viewMode: ViewMode;
  /** Performance tier from useGraph */
  performanceTier: "full" | "no-animation" | "simplified" | "force-drilldown";
  /** Whether to color nodes by "kind" or "layer" */
  colorBy?: "kind" | "layer";
  /** Called when a node is clicked (selected) */
  onNodeSelect?: (nodeData: Record<string, unknown>) => void;
  /** Called when a drillable node is double-clicked */
  onNodeDrillDown?: (fqn: string, name: string, level: string) => void;
}

export function GraphView({
  elements,
  viewMode,
  performanceTier,
  colorBy = "kind",
  onNodeSelect,
  onNodeDrillDown,
}: GraphViewProps) {
  const cyRef = useRef<cytoscape.Core | null>(null);
  const expandCollapseApiRef = useRef<any>(null);

  const stylesheet =
    colorBy === "layer" ? layerStylesheet : defaultStylesheet;

  /** Store the cy instance and set up event listeners */
  const handleCyRef = useCallback(
    (cy: cytoscape.Core) => {
      // Skip if same instance
      if (cyRef.current === cy) return;
      cyRef.current = cy;

      // Initialize expand-collapse extension
      try {
        expandCollapseApiRef.current = (cy as any).expandCollapse({
          layoutBy: {
            name: "dagre",
            animate: performanceTier === "full",
            animationDuration: 300,
          },
          fisheye: false,
          animate: performanceTier === "full",
          animationDuration: 300,
          cueEnabled: true,
          expandCollapseCuePosition: "top-left",
        });
      } catch {
        // expand-collapse may fail silently if no compound nodes exist
      }

      // ── Click → select node ──
      cy.on("tap", "node", (event) => {
        const node = event.target;
        if (onNodeSelect) {
          onNodeSelect(node.data());
        }
      });

      // ── Double-click → drill down ──
      cy.on("dbltap", "node", (event) => {
        const node = event.target;
        const data = node.data();
        if (data.drillable && onNodeDrillDown) {
          onNodeDrillDown(data.id, data.label, data.drillLevel);
        }
      });

      // ── Click canvas background → deselect ──
      cy.on("tap", (event) => {
        if (event.target === cy) {
          if (onNodeSelect) {
            onNodeSelect({});
          }
        }
      });
    },
    [onNodeSelect, onNodeDrillDown, performanceTier]
  );

  /** Re-run layout when view mode or elements change */
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || elements.length === 0) return;

    const layoutConfig = { ...LAYOUT_CONFIGS[viewMode] };

    // Adjust animation based on performance tier
    if (performanceTier !== "full") {
      (layoutConfig as any).animate = false;
    }

    // Small delay to let elements render before layout
    const timer = setTimeout(() => {
      try {
        cy.layout(layoutConfig).run();
      } catch {
        // Layout algorithm may fail with 0 nodes
      }
    }, 50);

    return () => clearTimeout(timer);
  }, [viewMode, elements, performanceTier]);

  return (
    <div className="relative h-full w-full">
      <CytoscapeComponent
        elements={CytoscapeComponent.normalizeElements(elements)}
        stylesheet={stylesheet}
        cy={handleCyRef}
        style={{
          width: "100%",
          height: "100%",
          position: "absolute",
          top: 0,
          left: 0,
        }}
        minZoom={0.1}
        maxZoom={3}
        zoomingEnabled={true}
        userZoomingEnabled={true}
        panningEnabled={true}
        userPanningEnabled={true}
        boxSelectionEnabled={false}
        autoungrabify={false}
      />

      {/* Performance warning overlay */}
      {performanceTier === "force-drilldown" && (
        <div className="absolute inset-x-0 top-0 z-10 bg-yellow-50 px-4 py-2 text-center text-sm text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-200">
          Too many nodes to render at once. Please drill down into a specific
          module for a better experience.
        </div>
      )}
    </div>
  );
}
```

---

## Task 7: Create GraphToolbar.tsx

**File:** `cast-clone-frontend/components/graph/GraphToolbar.tsx`
**Time:** 5 minutes

- [ ] **Step 7.1: Create the toolbar component**

Create `cast-clone-frontend/components/graph/GraphToolbar.tsx`:

```typescript
// components/graph/GraphToolbar.tsx
//
// Toolbar above the graph with view switcher, zoom controls, and breadcrumb.

"use client";

import React from "react";
import {
  Layers,
  Network,
  ArrowRight,
  ZoomIn,
  ZoomOut,
  Maximize,
  RefreshCw,
  ChevronRight,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ViewMode } from "@/lib/types";

interface BreadcrumbEntry {
  level: "module" | "class";
  fqn: string;
  name: string;
}

interface GraphToolbarProps {
  /** Active view mode */
  viewMode: ViewMode;
  /** Callback to change view mode */
  onViewModeChange: (mode: ViewMode) => void;
  /** Current drill-down breadcrumb path */
  drilldownPath: BreadcrumbEntry[];
  /** Callback for drill-up navigation */
  onDrillUp: () => void;
  /** Callback to zoom in */
  onZoomIn: () => void;
  /** Callback to zoom out */
  onZoomOut: () => void;
  /** Callback to fit graph to viewport */
  onFitToScreen: () => void;
  /** Callback to re-run the current layout */
  onRefreshLayout: () => void;
  /** Whether data is loading */
  isLoading: boolean;
}

const VIEW_TABS: { mode: ViewMode; label: string; icon: React.ReactNode }[] = [
  {
    mode: "architecture",
    label: "Architecture",
    icon: <Layers className="size-3.5" />,
  },
  {
    mode: "dependency",
    label: "Dependency",
    icon: <Network className="size-3.5" />,
  },
  {
    mode: "transaction",
    label: "Transaction",
    icon: <ArrowRight className="size-3.5" />,
  },
];

export function GraphToolbar({
  viewMode,
  onViewModeChange,
  drilldownPath,
  onDrillUp,
  onZoomIn,
  onZoomOut,
  onFitToScreen,
  onRefreshLayout,
  isLoading,
}: GraphToolbarProps) {
  return (
    <div className="flex items-center justify-between border-b bg-background px-3 py-1.5">
      {/* ── Left: View switcher ── */}
      <div className="flex items-center gap-1">
        {VIEW_TABS.map((tab) => (
          <Button
            key={tab.mode}
            variant={viewMode === tab.mode ? "secondary" : "ghost"}
            size="sm"
            onClick={() => onViewModeChange(tab.mode)}
            disabled={isLoading}
          >
            {tab.icon}
            <span className="ml-1">{tab.label}</span>
          </Button>
        ))}
      </div>

      {/* ── Center: Breadcrumb ── */}
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <button
          className="hover:text-foreground transition-colors"
          onClick={onDrillUp}
          disabled={drilldownPath.length === 0}
        >
          Root
        </button>
        {drilldownPath.map((entry, idx) => (
          <React.Fragment key={entry.fqn}>
            <ChevronRight className="size-3 text-muted-foreground/50" />
            <span
              className={
                idx === drilldownPath.length - 1
                  ? "font-medium text-foreground"
                  : "hover:text-foreground cursor-pointer transition-colors"
              }
            >
              {entry.name}
            </span>
          </React.Fragment>
        ))}
      </div>

      {/* ── Right: Zoom + layout controls ── */}
      <div className="flex items-center gap-0.5">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onZoomIn}
          title="Zoom in"
        >
          <ZoomIn />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onZoomOut}
          title="Zoom out"
        >
          <ZoomOut />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onFitToScreen}
          title="Fit to screen"
        >
          <Maximize />
        </Button>
        <div className="mx-1 h-4 w-px bg-border" />
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onRefreshLayout}
          title="Re-run layout"
          disabled={isLoading}
        >
          <RefreshCw className={isLoading ? "animate-spin" : ""} />
        </Button>
      </div>
    </div>
  );
}
```

---

## Task 8: Create graph page

**File:** `cast-clone-frontend/app/projects/[id]/graph/page.tsx`
**Time:** 5 minutes

- [ ] **Step 8.1: Create the project directory structure**

```bash
mkdir -p cast-clone-frontend/app/projects/\[id\]/graph
```

- [ ] **Step 8.2: Create the graph explorer page**

Create `cast-clone-frontend/app/projects/[id]/graph/page.tsx`:

```typescript
// app/projects/[id]/graph/page.tsx
//
// Graph explorer page — the main visualization interface.
// Composes GraphToolbar + GraphView + NodeProperties panel.

"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import type cytoscape from "cytoscape";

import { GraphView } from "@/components/graph/GraphView";
import { GraphToolbar } from "@/components/graph/GraphToolbar";
import { useGraph } from "@/hooks/useGraph";
import type { ViewMode } from "@/lib/types";

export default function GraphPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;

  const {
    elements,
    isLoading,
    error,
    drilldownPath,
    performanceTier,
    loadModules,
    drillIntoModule,
    drillIntoClass,
    drillUp,
  } = useGraph();

  const [viewMode, setViewMode] = useState<ViewMode>("architecture");
  const [selectedNode, setSelectedNode] = useState<Record<string, unknown> | null>(null);

  // Reference to the Cytoscape core instance for zoom/fit controls
  const cyInstanceRef = useRef<cytoscape.Core | null>(null);

  // Load modules on mount
  useEffect(() => {
    if (projectId) {
      loadModules(projectId);
    }
  }, [projectId, loadModules]);

  // ── Node selection handler ──
  const handleNodeSelect = useCallback(
    (nodeData: Record<string, unknown>) => {
      if (Object.keys(nodeData).length === 0) {
        setSelectedNode(null);
      } else {
        setSelectedNode(nodeData);
      }
    },
    []
  );

  // ── Drill-down handler ──
  const handleNodeDrillDown = useCallback(
    (fqn: string, name: string, level: string) => {
      if (level === "module") {
        drillIntoModule(projectId, fqn, name);
      } else if (level === "class") {
        drillIntoClass(projectId, fqn, name);
      }
      // Methods are not drillable (leaf level)
    },
    [projectId, drillIntoModule, drillIntoClass]
  );

  // ── Drill-up handler ──
  const handleDrillUp = useCallback(() => {
    drillUp(projectId);
  }, [projectId, drillUp]);

  // ── Zoom controls ──
  const handleZoomIn = useCallback(() => {
    const cy = cyInstanceRef.current;
    if (cy) cy.zoom(cy.zoom() * 1.3);
  }, []);

  const handleZoomOut = useCallback(() => {
    const cy = cyInstanceRef.current;
    if (cy) cy.zoom(cy.zoom() / 1.3);
  }, []);

  const handleFitToScreen = useCallback(() => {
    const cy = cyInstanceRef.current;
    if (cy) cy.fit(undefined, 40);
  }, []);

  // ── Layout refresh ──
  const handleRefreshLayout = useCallback(() => {
    // Changing viewMode to same value won't trigger useEffect,
    // so toggle briefly
    setViewMode((prev) => {
      const modes: ViewMode[] = ["architecture", "dependency", "transaction"];
      const idx = modes.indexOf(prev);
      // Force a re-layout by briefly changing and reverting
      return prev;
    });
    // Instead, directly re-run layout on cy
    const cy = cyInstanceRef.current;
    if (!cy) return;
    const layoutConfigs: Record<string, cytoscape.LayoutOptions> = {
      architecture: {
        name: "dagre",
        rankDir: "TB",
        nodeSep: 50,
        rankSep: 80,
        animate: performanceTier === "full",
      } as cytoscape.LayoutOptions,
      dependency: {
        name: "fcose",
        quality: "default",
        randomize: true,
        animate: performanceTier === "full",
        animationDuration: 500,
        nodeRepulsion: 4500,
        idealEdgeLength: 100,
      } as cytoscape.LayoutOptions,
      transaction: {
        name: "dagre",
        rankDir: "LR",
        nodeSep: 30,
        rankSep: 60,
        animate: performanceTier === "full",
      } as cytoscape.LayoutOptions,
    };
    try {
      cy.layout(layoutConfigs[viewMode]).run();
    } catch {
      // Layout may fail with 0 nodes
    }
  }, [viewMode, performanceTier]);

  return (
    <div className="flex h-screen flex-col">
      {/* Toolbar */}
      <GraphToolbar
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        drilldownPath={drilldownPath}
        onDrillUp={handleDrillUp}
        onZoomIn={handleZoomIn}
        onZoomOut={handleZoomOut}
        onFitToScreen={handleFitToScreen}
        onRefreshLayout={handleRefreshLayout}
        isLoading={isLoading}
      />

      {/* Main content area */}
      <div className="relative flex flex-1 overflow-hidden">
        {/* Graph canvas */}
        <div className="flex-1">
          {error ? (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <p className="text-sm text-destructive">{error}</p>
                <button
                  className="mt-2 text-xs text-muted-foreground underline"
                  onClick={() => loadModules(projectId)}
                >
                  Retry
                </button>
              </div>
            </div>
          ) : elements.length === 0 && !isLoading ? (
            <div className="flex h-full items-center justify-center">
              <p className="text-sm text-muted-foreground">
                No graph data found. Run an analysis first.
              </p>
            </div>
          ) : (
            <GraphView
              elements={elements}
              viewMode={viewMode}
              performanceTier={performanceTier}
              onNodeSelect={handleNodeSelect}
              onNodeDrillDown={handleNodeDrillDown}
            />
          )}

          {/* Loading overlay */}
          {isLoading && (
            <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/50">
              <div className="flex items-center gap-2 rounded-md bg-background px-4 py-2 shadow-md">
                <RefreshCw className="size-4 animate-spin text-muted-foreground" />
                <span className="text-sm text-muted-foreground">
                  Loading graph data...
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Node properties panel (right sidebar) */}
        {selectedNode && Object.keys(selectedNode).length > 0 && (
          <div className="w-72 shrink-0 overflow-y-auto border-l bg-background p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">Properties</h3>
              <button
                className="text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setSelectedNode(null)}
              >
                Close
              </button>
            </div>

            <div className="mt-3 space-y-3">
              {/* Node name */}
              <div>
                <p className="text-xs text-muted-foreground">Name</p>
                <p className="text-sm font-medium">
                  {selectedNode.label as string}
                </p>
              </div>

              {/* FQN */}
              <div>
                <p className="text-xs text-muted-foreground">
                  Fully Qualified Name
                </p>
                <p className="break-all font-mono text-xs">
                  {selectedNode.id as string}
                </p>
              </div>

              {/* Kind */}
              <div>
                <p className="text-xs text-muted-foreground">Kind</p>
                <span className="inline-block rounded bg-muted px-1.5 py-0.5 text-xs">
                  {selectedNode.kind as string}
                </span>
              </div>

              {/* Language */}
              {selectedNode.language && (
                <div>
                  <p className="text-xs text-muted-foreground">Language</p>
                  <p className="text-sm">{selectedNode.language as string}</p>
                </div>
              )}

              {/* Metrics */}
              {(selectedNode.loc || selectedNode.complexity) && (
                <div>
                  <p className="text-xs text-muted-foreground">Metrics</p>
                  <div className="mt-1 grid grid-cols-2 gap-2">
                    {selectedNode.loc && (
                      <div className="rounded bg-muted p-2 text-center">
                        <p className="text-lg font-semibold">
                          {selectedNode.loc as number}
                        </p>
                        <p className="text-xs text-muted-foreground">LOC</p>
                      </div>
                    )}
                    {selectedNode.complexity && (
                      <div className="rounded bg-muted p-2 text-center">
                        <p className="text-lg font-semibold">
                          {selectedNode.complexity as number}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Complexity
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* File path */}
              {selectedNode.path && (
                <div>
                  <p className="text-xs text-muted-foreground">File</p>
                  <p className="break-all font-mono text-xs">
                    {selectedNode.path as string}
                    {selectedNode.line ? `:${selectedNode.line}` : ""}
                  </p>
                </div>
              )}

              {/* Layer */}
              {selectedNode.layer && (
                <div>
                  <p className="text-xs text-muted-foreground">Layer</p>
                  <p className="text-sm capitalize">
                    {selectedNode.layer as string}
                  </p>
                </div>
              )}

              {/* Drill-down hint */}
              {selectedNode.drillable && (
                <p className="text-xs text-muted-foreground italic">
                  Double-click to drill down
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Need this import for the loading spinner in the overlay
import { RefreshCw } from "lucide-react";
```

---

## Task 9: Verify end-to-end rendering

**Time:** 5 minutes

- [ ] **Step 9.1: Verify TypeScript compilation**

```bash
cd cast-clone-frontend
npx tsc --noEmit
```

Expected: no type errors. If there are errors, fix them in the relevant files.

- [ ] **Step 9.2: Verify dev server starts**

```bash
cd cast-clone-frontend
npm run dev
```

Expected: dev server starts without build errors. Open `http://localhost:3000/projects/test-project/graph` in a browser. The page should render:
- The toolbar with Architecture/Dependency/Transaction tabs
- Zoom controls
- Either "No graph data found" message (if no backend) or the graph (if backend is running with data)

- [ ] **Step 9.3: Test with mock data (optional smoke test)**

To verify rendering works without a backend, temporarily add mock data to the graph page. In `app/projects/[id]/graph/page.tsx`, add this after the `useGraph()` call to override elements:

```typescript
// TEMPORARY: Remove after verifying rendering works
const mockElements: cytoscape.ElementDefinition[] = [
  { group: "nodes", data: { id: "com.app.controller", label: "controller", kind: "MODULE", loc: 500, drillable: true, drillLevel: "module", layer: "presentation" } },
  { group: "nodes", data: { id: "com.app.service", label: "service", kind: "MODULE", loc: 1200, drillable: true, drillLevel: "module", layer: "business" } },
  { group: "nodes", data: { id: "com.app.repository", label: "repository", kind: "MODULE", loc: 300, drillable: true, drillLevel: "module", layer: "data" } },
  { group: "nodes", data: { id: "com.app.model", label: "model", kind: "MODULE", loc: 200, drillable: true, drillLevel: "module", layer: "utility" } },
  { group: "edges", data: { id: "e1", source: "com.app.controller", target: "com.app.service", kind: "CALLS", weight: 15 } },
  { group: "edges", data: { id: "e2", source: "com.app.service", target: "com.app.repository", kind: "CALLS", weight: 8 } },
  { group: "edges", data: { id: "e3", source: "com.app.repository", target: "com.app.model", kind: "DEPENDS_ON", weight: 5 } },
  { group: "edges", data: { id: "e4", source: "com.app.service", target: "com.app.model", kind: "DEPENDS_ON", weight: 12 } },
];
```

Then pass `mockElements` instead of `elements` to `<GraphView>` temporarily. After verifying the graph renders correctly with 4 nodes and 4 edges, revert the change.

- [ ] **Step 9.4: Verify view switching**

In the browser:
1. Click "Architecture" tab — graph should use dagre top-to-bottom layout
2. Click "Dependency" tab — graph should reorganize with fcose force-directed layout
3. Click "Transaction" tab — graph should use dagre left-to-right layout
4. Click on a node — properties panel should appear on the right
5. Click the background — properties panel should close
6. Use zoom in/out/fit buttons — verify they work
7. Verify the breadcrumb shows "Root" with no path entries

- [ ] **Step 9.5: Clean up and finalize**

Remove any temporary mock data added in Step 9.3. Run final checks:

```bash
cd cast-clone-frontend
npx tsc --noEmit           # Type check passes
npm run lint               # No lint errors
npm run build              # Production build succeeds
```

---

## Summary of Created Files

| # | File | Purpose |
|---|------|---------|
| 1 | `types/cytoscape-extensions.d.ts` | Type declarations for untyped Cytoscape packages |
| 2 | `lib/cytoscape-setup.ts` | One-time Cytoscape extension registration |
| 3 | `lib/graph-styles.ts` | Cytoscape stylesheet (kind/layer colors, edge styles) |
| 4 | `lib/types.ts` | TypeScript types matching backend schemas (if not from M2) |
| 5 | `lib/api.ts` | API client with getModules, getClassesInModule, etc. (if not from M2) |
| 6 | `lib/cytoscape-elements.ts` | API data to Cytoscape ElementDefinition converters |
| 7 | `hooks/useGraph.ts` | Graph data management hook with caching + drill-down |
| 8 | `components/graph/GraphView.tsx` | Main Cytoscape.js wrapper component |
| 9 | `components/graph/GraphToolbar.tsx` | Toolbar with view switcher + zoom + breadcrumb |
| 10 | `app/projects/[id]/graph/page.tsx` | Graph explorer page composing all components |

All file paths are relative to `cast-clone-frontend/`.
