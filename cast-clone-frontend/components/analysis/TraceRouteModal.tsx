// cast-clone-frontend/components/analysis/TraceRouteModal.tsx
"use client"

import * as React from "react"
import { useCallback, useEffect, useMemo, useRef } from "react"
import CytoscapeComponent from "react-cytoscapejs"
import type cytoscape from "cytoscape"
import { GitBranch, List, Network } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ensureCytoscapeExtensions } from "@/lib/cytoscape-setup"
import { useTraceRoute, type TraceEdge } from "@/hooks/useTraceRoute"
import type { AffectedNode } from "@/lib/types"

ensureCytoscapeExtensions()

// ─── Kind → Cytoscape node color ─────────────────────────────────────────────

const KIND_NODE_COLORS: Record<string, string> = {
  CLASS: "#3B82F6",
  INTERFACE: "#14B8A6",
  FUNCTION: "#EAB308",
  TABLE: "#F97316",
  API_ENDPOINT: "#A855F7",
  MODULE: "#6B7280",
  ENUM: "#F59E0B",
  ROUTE: "#A855F7",
}

function kindNodeColor(kind: string): string {
  return KIND_NODE_COLORS[kind?.toUpperCase()] ?? "#6B7280"
}

// ─── Depth badge (for list view) ─────────────────────────────────────────────

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

// ─── Kind badge (for list view) ──────────────────────────────────────────────

const KIND_BADGE_COLORS: Record<string, string> = {
  CLASS: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  INTERFACE: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  FUNCTION: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  TABLE: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  API_ENDPOINT: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  MODULE: "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200",
  ENUM: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
}

function kindBadgeClass(kind: string): string {
  return KIND_BADGE_COLORS[kind] ?? "bg-muted text-muted-foreground"
}

// ─── Build Cytoscape elements from trace data ────────────────────────────────

/**
 * Derive the parent class/module FQN from a fully-qualified node name.
 * e.g. "com.example.service.AccountServiceImpl.closeAccount"
 *    → "com.example.service.AccountServiceImpl"
 */
function parentFqn(fqn: string): string | null {
  const lastDot = fqn.lastIndexOf(".")
  if (lastDot <= 0) return null
  return fqn.substring(0, lastDot)
}

/**
 * Short label: last segment of a dot-separated FQN.
 */
function shortLabel(fqn: string): string {
  const parts = fqn.split(".")
  return parts[parts.length - 1]
}

function buildTraceElements(
  centerNode: TraceRouteNode,
  upstreamNodes: AffectedNode[],
  downstreamNodes: AffectedNode[],
  realEdges: TraceEdge[],
): cytoscape.ElementDefinition[] {
  const elements: cytoscape.ElementDefinition[] = []

  // ─── Collect all nodes with their direction prefix ────────────────────
  // prefix avoids ID collisions if the same FQN appears in both directions
  interface PrefixedNode {
    node: AffectedNode
    prefix: "u" | "d"
    direction: "upstream" | "downstream"
  }

  // Filter out Transaction nodes (fqn starts with "txn:") — they flatten
  // the trace and create misleading shortcuts via INCLUDES edges.
  const isTransaction = (fqn: string) => fqn.startsWith("txn:")
  const filteredUpstream = upstreamNodes.filter((n) => !isTransaction(n.fqn))
  const filteredDownstream = downstreamNodes.filter((n) => !isTransaction(n.fqn))

  const allNodes: PrefixedNode[] = [
    ...filteredUpstream.map((n) => ({ node: n, prefix: "u" as const, direction: "upstream" as const })),
    ...filteredDownstream.map((n) => ({ node: n, prefix: "d" as const, direction: "downstream" as const })),
  ]

  // Build FQN → direction prefix lookup for edge resolution
  const upstreamFqns = new Set(filteredUpstream.map((n) => n.fqn))
  const downstreamFqns = new Set(filteredDownstream.map((n) => n.fqn))

  // ─── Determine compound parent groups ─────────────────────────────────
  // Only group FUNCTION-type nodes by their parent class.
  // CLASS, MODULE, TABLE etc. stay ungrouped.
  const GROUPABLE_TYPES = new Set(["FUNCTION", "METHOD", "CONSTRUCTOR"])

  const parentGroups = new Map<string, PrefixedNode[]>()
  for (const pn of allNodes) {
    if (!GROUPABLE_TYPES.has(pn.node.type?.toUpperCase())) continue
    const pFqn = parentFqn(pn.node.fqn)
    if (!pFqn) continue
    const key = `${pn.prefix}:${pFqn}`
    if (!parentGroups.has(key)) parentGroups.set(key, [])
    parentGroups.get(key)!.push(pn)
  }

  // Create compound nodes for every group (even single-child)
  const compoundParents = new Set<string>()
  for (const key of parentGroups.keys()) {
    compoundParents.add(key)
  }

  // ─── Create compound parent nodes ─────────────────────────────────────
  for (const key of compoundParents) {
    const pFqn = key.substring(key.indexOf(":") + 1)
    elements.push({
      data: {
        id: key,
        label: shortLabel(pFqn),
        kind: "CLASS",
        fqn: pFqn,
        isCompound: true,
      },
    })
  }

  // ─── Center node ──────────────────────────────────────────────────────
  elements.push({
    data: {
      id: "__center__",
      label: centerNode.name,
      kind: centerNode.kind,
      isCenter: true,
      traceDepth: 0,
      fqn: centerNode.fqn,
    },
  })

  // ─── Child nodes ──────────────────────────────────────────────────────
  for (const pn of allNodes) {
    const pFqn = parentFqn(pn.node.fqn)
    const groupKey = pFqn ? `${pn.prefix}:${pFqn}` : null
    const hasCompound = groupKey && compoundParents.has(groupKey)

    elements.push({
      data: {
        id: `${pn.prefix}:${pn.node.fqn}`,
        label: pn.node.name,
        kind: pn.node.type,
        depth: pn.node.depth,
        traceDepth: pn.prefix === "u" ? -pn.node.depth : pn.node.depth,
        fqn: pn.node.fqn,
        file: pn.node.file,
        direction: pn.direction,
        ...(hasCompound ? { parent: groupKey } : {}),
      },
    })
  }

  // ─── Edges from real path finder data ─────────────────────────────────
  // Map FQN → element ID (with direction prefix)
  // A node could be center, upstream, or downstream
  function resolveNodeId(fqn: string): string | null {
    if (fqn === centerNode.fqn) return "__center__"
    if (upstreamFqns.has(fqn)) return `u:${fqn}`
    if (downstreamFqns.has(fqn)) return `d:${fqn}`
    return null
  }

  const addedEdges = new Set<string>()

  for (const edge of realEdges) {
    const sourceId = resolveNodeId(edge.source)
    const targetId = resolveNodeId(edge.target)
    if (!sourceId || !targetId) continue
    if (sourceId === targetId) continue

    const edgeKey = `${sourceId}->${targetId}`
    if (addedEdges.has(edgeKey)) continue
    addedEdges.add(edgeKey)

    elements.push({
      data: {
        id: `e:${edgeKey}`,
        source: sourceId,
        target: targetId,
        edgeType: edge.type,
      },
    })
  }

  // ─── Fallback for disconnected nodes ────────────────────────────────
  // After filtering structural edges (INCLUDES/CONTAINS), some nodes may
  // have no connections. Connect them to center as a last resort.
  const connectedNodes = new Set<string>()
  for (const edgeKey of addedEdges) {
    const [src, tgt] = edgeKey.split("->")
    connectedNodes.add(src)
    connectedNodes.add(tgt)
  }

  for (const pn of allNodes) {
    const nodeId = `${pn.prefix}:${pn.node.fqn}`
    if (connectedNodes.has(nodeId)) continue

    // This node has no edges — connect it directly to center
    if (pn.prefix === "u") {
      const edgeKey = `${nodeId}->__center__`
      if (!addedEdges.has(edgeKey)) {
        addedEdges.add(edgeKey)
        elements.push({
          data: { id: `e:${edgeKey}`, source: nodeId, target: "__center__" },
        })
      }
    } else {
      const edgeKey = `__center__->${nodeId}`
      if (!addedEdges.has(edgeKey)) {
        addedEdges.add(edgeKey)
        elements.push({
          data: { id: `e:${edgeKey}`, source: "__center__", target: nodeId },
        })
      }
    }
  }

  return elements
}

// ─── Cytoscape stylesheet for the trace graph ───────────────────────────────

const traceStylesheet: cytoscape.StylesheetJsonBlock[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "text-valign": "center",
      "text-halign": "center",
      "font-size": "10px",
      "font-family": "Inter, system-ui, sans-serif",
      color: "#1F2937",
      "text-outline-color": "#FFFFFF",
      "text-outline-width": 1.5,
      "background-color": "#6B7280",
      width: 40,
      height: 40,
      "border-width": 1,
      "border-color": "#D1D5DB",
      "text-wrap": "ellipsis",
      "text-max-width": "80px",
    },
  },
  // Compound parent nodes (boxes containing children)
  {
    selector: "node:parent",
    style: {
      "background-opacity": 0.08,
      "background-color": "#3B82F6",
      "border-width": 2,
      "border-color": "#93C5FD",
      "text-valign": "top",
      "text-halign": "center",
      "font-size": "12px",
      "font-weight": "bold",
      padding: "16px",
      shape: "roundrectangle",
      "text-wrap": "ellipsis",
      "text-max-width": "180px",
    },
  },
  {
    selector: "node[isCenter]",
    style: {
      "background-color": "#2563EB",
      "border-width": 3,
      "border-color": "#1D4ED8",
      width: 55,
      height: 55,
      "font-size": "12px",
      "font-weight": "bold",
      color: "#1E3A8A",
    },
  },
  {
    selector: "edge",
    style: {
      width: 2,
      "line-color": "#94A3B8",
      "target-arrow-color": "#94A3B8",
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.8,
      "curve-style": "bezier",
      opacity: 0.7,
      label: "data(edgeType)",
      "font-size": "8px",
      "text-rotation": "autorotate",
      color: "#64748B",
      "text-outline-color": "#FFFFFF",
      "text-outline-width": 2,
      "text-background-color": "#FFFFFF",
      "text-background-opacity": 0.8,
      "text-background-padding": "2px",
    },
  },
  // Kind-based coloring (only for leaf nodes, not compound parents)
  ...Object.entries(KIND_NODE_COLORS).map(([kind, color]) => ({
    selector: `node[kind = "${kind}"]`,
    style: {
      "background-color": color,
      "border-color": color,
    },
  })),
]

// ─── Trace Graph component ──────────────────────────────────────────────────

interface TooltipState {
  visible: boolean
  x: number
  y: number
  name: string
  fqn: string
  kind: string
  depth: number | null
  direction: string
  file: string | null
}

const EMPTY_TOOLTIP: TooltipState = {
  visible: false, x: 0, y: 0, name: "", fqn: "", kind: "", depth: null, direction: "", file: null,
}

function TraceGraph({
  centerNode,
  upstreamNodes,
  downstreamNodes,
  edges: realEdges,
}: {
  centerNode: TraceRouteNode
  upstreamNodes: AffectedNode[]
  downstreamNodes: AffectedNode[]
  edges: TraceEdge[]
}) {
  const cyRef = useRef<cytoscape.Core | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [tooltip, setTooltip] = React.useState<TooltipState>(EMPTY_TOOLTIP)

  const elements = useMemo(
    () => buildTraceElements(centerNode, upstreamNodes, downstreamNodes, realEdges),
    [centerNode, upstreamNodes, downstreamNodes, realEdges],
  )

  const handleCy = useCallback((cy: cytoscape.Core) => {
    if (cyRef.current === cy) return
    cyRef.current = cy

    // Hover → show tooltip
    cy.on("mouseover", "node", (event) => {
      const node = event.target
      const data = node.data()
      const container = containerRef.current
      if (!container) return
      const rect = container.getBoundingClientRect()
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const renderedPos = node.renderedPosition()
      setTooltip({
        visible: true,
        x: renderedPos.x,
        y: renderedPos.y,
        name: data.label ?? "",
        fqn: data.fqn ?? data.id ?? "",
        kind: data.kind ?? "",
        depth: data.depth ?? null,
        direction: data.isCenter ? "selected" : (data.direction ?? ""),
        file: data.file ?? null,
      })
    })

    cy.on("mouseout", "node", () => {
      setTooltip(EMPTY_TOOLTIP)
    })

    // Hide tooltip on pan/zoom
    cy.on("viewport", () => {
      setTooltip((prev) => (prev.visible ? EMPTY_TOOLTIP : prev))
    })

    // Run dagre layout after mounting
    const timer = setTimeout(() => {
      try {
        const layout = cy.layout({
          name: "dagre",
          rankDir: "LR",
          nodeSep: 40,
          rankSep: 80,
          fit: true,
          padding: 30,
          animate: false,
        } as cytoscape.LayoutOptions)
        layout.run()
      } catch {
        // Layout may fail with 0 nodes
      }
    }, 50)

    return () => clearTimeout(timer)
  }, [])

  // Re-run layout when elements change
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || elements.length === 0) return

    const timer = setTimeout(() => {
      try {
        const layout = cy.layout({
          name: "dagre",
          rankDir: "LR",
          nodeSep: 40,
          rankSep: 80,
          fit: true,
          padding: 30,
          animate: false,
        } as cytoscape.LayoutOptions)
        layout.run()
      } catch {
        // noop
      }
    }, 100)

    return () => clearTimeout(timer)
  }, [elements])

  if (elements.length <= 1) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No upstream or downstream connections found
      </div>
    )
  }

  return (
    <div ref={containerRef} className="absolute inset-0">
      <CytoscapeComponent
        elements={CytoscapeComponent.normalizeElements(elements)}
        stylesheet={traceStylesheet}
        cy={handleCy}
        style={{
          width: "100%",
          height: "100%",
          position: "absolute",
          top: 0,
          left: 0,
        }}
        minZoom={0.3}
        maxZoom={2.5}
        zoomingEnabled={true}
        userZoomingEnabled={true}
        panningEnabled={true}
        userPanningEnabled={true}
        boxSelectionEnabled={false}
        autoungrabify={false}
      />

      {/* Hover tooltip */}
      {tooltip.visible && (
        <div
          className="pointer-events-none absolute z-50 max-w-xs rounded-lg border bg-background px-3 py-2 shadow-lg"
          style={{
            left: tooltip.x + 12,
            top: tooltip.y - 10,
            transform: "translateY(-100%)",
          }}
        >
          <p className="text-sm font-semibold">{tooltip.name}</p>
          <p className="mt-0.5 break-all text-[10px] text-muted-foreground">
            {tooltip.fqn}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {tooltip.kind && (
              <Badge className={`text-[10px] px-1.5 py-0 ${kindBadgeClass(tooltip.kind)}`}>
                {tooltip.kind}
              </Badge>
            )}
            {tooltip.direction === "selected" ? (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                selected node
              </Badge>
            ) : (
              <>
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 capitalize">
                  {tooltip.direction}
                </Badge>
                {tooltip.depth !== null && (
                  <Badge className={`text-[10px] px-1.5 py-0 ${depthBadgeClass(tooltip.depth)}`}>
                    depth {tooltip.depth}
                  </Badge>
                )}
              </>
            )}
          </div>
          {tooltip.file && (
            <p className="mt-1.5 break-all text-[10px] text-muted-foreground">
              {tooltip.file}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Node row (for list view) ───────────────────────────────────────────────

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

// ─── Section (for list view) ────────────────────────────────────────────────

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
  const { upstreamData, downstreamData, edges, isLoading, error, fetchTrace, clear } =
    useTraceRoute()
  const [viewMode, setViewMode] = React.useState<"graph" | "list">("graph")

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
  const totalAffected = upstreamNodes.length + downstreamNodes.length

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose() }}>
      <DialogContent className="flex h-[80vh] w-[70vw] !max-w-none flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-4">
          <div className="flex items-center justify-between">
            <DialogTitle className="flex items-center gap-2 text-base">
              <GitBranch className="size-4 text-blue-500" />
              Trace Route
            </DialogTitle>
            {/* View toggle */}
            <div className="flex items-center gap-1 rounded-md border p-0.5">
              <Button
                variant={viewMode === "graph" ? "secondary" : "ghost"}
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => setViewMode("graph")}
              >
                <Network className="mr-1 size-3" />
                Graph
              </Button>
              <Button
                variant={viewMode === "list" ? "secondary" : "ghost"}
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => setViewMode("list")}
              >
                <List className="mr-1 size-3" />
                List
              </Button>
            </div>
          </div>
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
              {!isLoading && totalAffected > 0 && (
                <Badge variant="outline" className="text-[10px]">
                  {upstreamNodes.length} upstream / {downstreamNodes.length} downstream
                </Badge>
              )}
            </div>
          )}
        </DialogHeader>

        {error ? (
          <div className="px-6 py-8 text-center text-sm text-destructive">
            {error}
          </div>
        ) : isLoading ? (
          <div className="flex flex-1 items-center justify-center">
            <span className="text-sm text-muted-foreground">Analyzing trace route...</span>
          </div>
        ) : viewMode === "graph" ? (
          /* ─── Graph View ─── */
          <div className="relative min-h-0 flex-1 overflow-hidden">
            {node && (
              <TraceGraph
                centerNode={node}
                upstreamNodes={upstreamNodes}
                downstreamNodes={downstreamNodes}
                edges={edges}
              />
            )}
            {/* Legend */}
            <div className="absolute bottom-3 left-3 flex items-center gap-3 rounded-md border bg-background/90 px-3 py-1.5 text-[10px] backdrop-blur-sm">
              <span className="font-medium text-muted-foreground">Flow:</span>
              <span className="text-muted-foreground">Upstream Callers</span>
              <span className="text-muted-foreground">&rarr;</span>
              <span className="inline-flex items-center gap-1">
                <span className="inline-block size-2.5 rounded-full bg-blue-600" />
                <span className="font-medium">Selected Node</span>
              </span>
              <span className="text-muted-foreground">&rarr;</span>
              <span className="text-muted-foreground">Downstream Callees</span>
            </div>
          </div>
        ) : (
          /* ─── List View ─── */
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="space-y-0 px-6 py-4">
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

              <Section
                title="Downstream Callees"
                count={downstreamNodes.length}
                nodes={downstreamNodes}
                isLoading={isLoading}
                emptyMessage="No callees found"
              />
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
