// cast-clone-frontend/components/analysis/TraceRouteModal.tsx
"use client"

import * as React from "react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import CytoscapeComponent from "react-cytoscapejs"
import type cytoscape from "cytoscape"
import ReactMarkdown from "react-markdown"
import {
  GitBranch,
  List,
  Network,
  Sparkles,
  RefreshCw,
  Globe,
  Cog,
  Archive,
  Database,
  Loader2,
  PanelRightOpen,
  PanelRightClose,
} from "lucide-react"
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
import { useTraceRoute } from "@/hooks/useTraceRoute"
import { useTraceSummary } from "@/hooks/useTraceSummary"
import type { TraceNode, TraceEdge, TraceRouteResponse, TraceSummaryResponse } from "@/lib/types"

ensureCytoscapeExtensions()

// ─── Layer configuration ────────────────────────────────────────────────────

const LAYER_CONFIG: Record<string, { color: string; bandColor: string; label: string }> = {
  api:        { color: "#A855F7", bandColor: "rgba(168,85,247,0.05)", label: "API / Controller" },
  service:    { color: "#3B82F6", bandColor: "rgba(59,130,246,0.05)", label: "Service" },
  repository: { color: "#10B981", bandColor: "rgba(16,185,129,0.05)", label: "Repository" },
  database:   { color: "#F97316", bandColor: "rgba(249,115,22,0.05)", label: "Database" },
  other:      { color: "#6B7280", bandColor: "rgba(107,114,128,0.05)", label: "Other" },
}

const LAYER_ORDER = ["api", "service", "repository", "database", "other"]

// ─── Layer-based badge classes for list view ────────────────────────────────

const LAYER_BADGE_CLASSES: Record<string, string> = {
  api:        "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  service:    "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  repository: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
  database:   "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  other:      "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200",
}

function layerBadgeClass(layer: string): string {
  return LAYER_BADGE_CLASSES[layer] ?? "bg-muted text-muted-foreground"
}

// ─── Sequence badge colors ──────────────────────────────────────────────────

const DEPTH_BADGE_CLASSES: Record<number, string> = {
  1: "bg-red-500 text-white",
  2: "bg-orange-500 text-white",
  3: "bg-yellow-500 text-black",
  4: "bg-yellow-300 text-black",
  5: "bg-yellow-100 text-black",
}

function depthBadgeClass(depth: number): string {
  return DEPTH_BADGE_CLASSES[depth] ?? DEPTH_BADGE_CLASSES[5]!
}

// ─── Layer icon ─────────────────────────────────────────────────────────────

function LayerIcon({ layer, className }: { layer: string; className?: string }) {
  switch (layer) {
    case "api":        return <Globe className={className} />
    case "service":    return <Cog className={className} />
    case "repository": return <Archive className={className} />
    case "database":   return <Database className={className} />
    default:           return <GitBranch className={className} />
  }
}

// ─── Build Cytoscape elements from trace data ───────────────────────────────

function parentFqn(fqn: string): string | null {
  const lastDot = fqn.lastIndexOf(".")
  if (lastDot <= 0) return null
  return fqn.substring(0, lastDot)
}

function shortLabel(fqn: string): string {
  const parts = fqn.split(".")
  return parts[parts.length - 1]
}

function buildTraceElements(
  data: TraceRouteResponse,
): cytoscape.ElementDefinition[] {
  const elements: cytoscape.ElementDefinition[] = []

  interface PrefixedNode {
    node: TraceNode
    prefix: "u" | "d"
  }

  const allNodes: PrefixedNode[] = [
    ...data.upstream.map((n) => ({ node: n, prefix: "u" as const })),
    ...data.downstream.map((n) => ({ node: n, prefix: "d" as const })),
  ]

  const upstreamFqns = new Set(data.upstream.map((n) => n.fqn))
  const downstreamFqns = new Set(data.downstream.map((n) => n.fqn))

  // ─── Compound parent grouping ───────────────────────────────────────
  const GROUPABLE_KINDS = new Set(["FUNCTION", "METHOD", "CONSTRUCTOR", "STORED_PROCEDURE"])

  const parentGroups = new Map<string, PrefixedNode[]>()
  for (const pn of allNodes) {
    if (!GROUPABLE_KINDS.has(pn.node.kind?.toUpperCase())) continue
    const pFqn = parentFqn(pn.node.fqn)
    if (!pFqn) continue
    const key = `${pn.prefix}:${pFqn}`
    if (!parentGroups.has(key)) parentGroups.set(key, [])
    parentGroups.get(key)!.push(pn)
  }

  const compoundParents = new Set<string>()
  for (const [key, members] of parentGroups.entries()) {
    if (members.length >= 2) compoundParents.add(key)
  }

  // ─── Compound parent nodes ──────────────────────────────────────────
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

  // ─── Center node ────────────────────────────────────────────────────
  elements.push({
    data: {
      id: "__center__",
      label: data.center_name,
      kind: data.center_kind,
      layer: data.center_layer,
      isCenter: true,
      traceDepth: 0,
      fqn: data.center_fqn,
      sequence: 0,
    },
  })

  // ─── Child nodes ────────────────────────────────────────────────────
  for (const pn of allNodes) {
    const pFqn = parentFqn(pn.node.fqn)
    const groupKey = pFqn ? `${pn.prefix}:${pFqn}` : null
    const hasCompound = groupKey && compoundParents.has(groupKey)

    elements.push({
      data: {
        id: `${pn.prefix}:${pn.node.fqn}`,
        label: pn.node.name,
        kind: pn.node.kind,
        layer: pn.node.layer,
        depth: pn.node.depth,
        traceDepth: pn.prefix === "u" ? -pn.node.depth : pn.node.depth,
        fqn: pn.node.fqn,
        file: pn.node.file,
        direction: pn.node.direction,
        sequence: pn.node.sequence,
        sequenceLabel: `${pn.node.sequence}`,
        ...(hasCompound ? { parent: groupKey } : {}),
      },
    })
  }

  // ─── Edges ──────────────────────────────────────────────────────────
  function resolveNodeId(fqn: string): string | null {
    if (fqn === data.center_fqn) return "__center__"
    if (upstreamFqns.has(fqn)) return `u:${fqn}`
    if (downstreamFqns.has(fqn)) return `d:${fqn}`
    return null
  }

  const addedEdges = new Set<string>()

  for (const edge of data.edges) {
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
        sequence: edge.sequence,
        sequenceLabel: edge.sequence != null ? `${edge.sequence}` : "",
      },
    })
  }

  // ─── Fallback for disconnected nodes ────────────────────────────────
  const connectedNodes = new Set<string>()
  for (const edgeKey of addedEdges) {
    const [src, tgt] = edgeKey.split("->")
    connectedNodes.add(src)
    connectedNodes.add(tgt)
  }

  for (const pn of allNodes) {
    const nodeId = `${pn.prefix}:${pn.node.fqn}`
    if (connectedNodes.has(nodeId)) continue

    if (pn.prefix === "u") {
      const edgeKey = `${nodeId}->__center__`
      if (!addedEdges.has(edgeKey)) {
        addedEdges.add(edgeKey)
        elements.push({
          data: {
            id: `e:${edgeKey}`,
            source: nodeId,
            target: "__center__",
            edgeType: "CALLS",
            sequence: pn.node.sequence,
            sequenceLabel: `${pn.node.sequence}`,
          },
        })
      }
    } else {
      const edgeKey = `__center__->${nodeId}`
      if (!addedEdges.has(edgeKey)) {
        addedEdges.add(edgeKey)
        elements.push({
          data: {
            id: `e:${edgeKey}`,
            source: "__center__",
            target: nodeId,
            edgeType: "CALLS",
            sequence: pn.node.sequence,
            sequenceLabel: `${pn.node.sequence}`,
          },
        })
      }
    }
  }

  return elements
}

// ─── Cytoscape stylesheet ───────────────────────────────────────────────────

const traceStylesheet: cytoscape.StylesheetJsonBlock[] = [
  // Base node style
  {
    selector: "node",
    style: {
      label: "data(label)",
      shape: "round-rectangle",
      width: 55,
      height: 36,
      "text-valign": "center",
      "text-halign": "center",
      "font-size": "9px",
      "font-family": "Inter, system-ui, sans-serif",
      color: "#FFFFFF",
      "text-outline-color": "transparent",
      "text-outline-width": 0,
      "background-color": "#6B7280",
      "border-width": 1,
      "border-color": "#D1D5DB",
      "text-wrap": "ellipsis",
      "text-max-width": "50px",
    },
  },
  // Compound parent nodes
  {
    selector: "node:parent",
    style: {
      "background-opacity": 0.08,
      "background-color": "#3B82F6",
      "border-width": 2,
      "border-color": "#93C5FD",
      "text-valign": "top",
      "text-halign": "center",
      "font-size": "10px",
      "font-weight": "bold",
      padding: "16px",
      shape: "roundrectangle",
      "text-wrap": "ellipsis",
      "text-max-width": "180px",
      color: "#1F2937",
    },
  },
  // Center node
  {
    selector: "node[isCenter]",
    style: {
      width: 65,
      height: 42,
      "border-width": 3,
      "border-color": "#FFFFFF",
      "font-size": "10px",
      "font-weight": "bold",
      label: "data(label)",
    },
  },
  // ── Layer-based node colors ─────────────────────────────────────────
  {
    selector: 'node[layer = "api"]',
    style: {
      "background-color": "#A855F7",
      "border-color": "#9333EA",
    },
  },
  {
    selector: 'node[layer = "service"]',
    style: {
      "background-color": "#3B82F6",
      "border-color": "#2563EB",
    },
  },
  {
    selector: 'node[layer = "repository"]',
    style: {
      "background-color": "#10B981",
      "border-color": "#059669",
    },
  },
  {
    selector: 'node[layer = "database"]',
    style: {
      "background-color": "#F97316",
      "border-color": "#EA580C",
    },
  },
  {
    selector: 'node[layer = "other"]',
    style: {
      "background-color": "#6B7280",
      "border-color": "#4B5563",
    },
  },
  // ── Edges ───────────────────────────────────────────────────────────
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
      label: "data(sequenceLabel)",
      "font-size": "10px",
      "font-weight": "bold",
      "text-rotation": "autorotate",
      color: "#1D4ED8",
      "text-outline-color": "#FFFFFF",
      "text-outline-width": 2,
      "text-background-color": "#EFF6FF",
      "text-background-opacity": 0.9,
      "text-background-padding": "3px",
      "text-background-shape": "roundrectangle",
    },
  },
  // WRITES edges (dashed red)
  {
    selector: 'edge[edgeType = "WRITES"]',
    style: {
      "line-style": "dashed",
      "line-color": "#EF4444",
      "target-arrow-color": "#EF4444",
    },
  },
  // READS edges (dashed blue)
  {
    selector: 'edge[edgeType = "READS"]',
    style: {
      "line-style": "dashed",
      "line-color": "#3B82F6",
      "target-arrow-color": "#3B82F6",
    },
  },
]

// ─── Swim lane type ─────────────────────────────────────────────────────────

interface SwimLane {
  layer: string
  top: number
  height: number
}

// ─── Tooltip state ──────────────────────────────────────────────────────────

interface TooltipState {
  visible: boolean
  x: number
  y: number
  name: string
  fqn: string
  kind: string
  layer: string
  sequence: number | null
  depth: number | null
  direction: string
  file: string | null
}

const EMPTY_TOOLTIP: TooltipState = {
  visible: false, x: 0, y: 0, name: "", fqn: "", kind: "", layer: "",
  sequence: null, depth: null, direction: "", file: null,
}

// ─── Trace Graph component ──────────────────────────────────────────────────

function TraceGraph({ data }: { data: TraceRouteResponse }) {
  const cyRef = useRef<cytoscape.Core | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [tooltip, setTooltip] = useState<TooltipState>(EMPTY_TOOLTIP)
  const [swimLanes, setSwimLanes] = useState<SwimLane[]>([])

  const elements = useMemo(() => buildTraceElements(data), [data])

  const computeSwimLanes = useCallback(() => {
    const cy = cyRef.current
    if (!cy || cy.nodes().length === 0) return

    const pan = cy.pan()
    const zoom = cy.zoom()

    // Group nodes by layer
    const layerNodes = new Map<string, cytoscape.NodeCollection>()
    for (const layer of LAYER_ORDER) {
      const nodes = cy.nodes(`[layer = "${layer}"]`)
      if (nodes.length > 0) {
        layerNodes.set(layer, nodes)
      }
    }

    const rawLanes: SwimLane[] = []
    for (const [layer, nodes] of layerNodes.entries()) {
      let minY = Infinity
      let maxY = -Infinity

      nodes.forEach((node: cytoscape.NodeSingular) => {
        const pos = node.position()
        const h = node.outerHeight() ?? 36
        const nodeTopY = (pos.y - h / 2) * zoom + pan.y
        const nodeBottomY = (pos.y + h / 2) * zoom + pan.y
        if (nodeTopY < minY) minY = nodeTopY
        if (nodeBottomY > maxY) maxY = nodeBottomY
      })

      if (minY !== Infinity) {
        const padding = 25
        rawLanes.push({
          layer,
          top: minY - padding,
          height: maxY - minY + padding * 2,
        })
      }
    }

    // Ensure no overlap: push each lane below the previous
    const minGap = 4
    for (let i = 1; i < rawLanes.length; i++) {
      const prev = rawLanes[i - 1]
      const prevBottom = prev.top + prev.height
      if (rawLanes[i].top < prevBottom + minGap) {
        rawLanes[i].top = prevBottom + minGap
      }
    }

    setSwimLanes(rawLanes)
  }, [])

  const handleCy = useCallback((cy: cytoscape.Core) => {
    if (cyRef.current === cy) return
    cyRef.current = cy

    cy.on("mouseover", "node", (event) => {
      const node = event.target
      const d = node.data()
      setTooltip({
        visible: true,
        x: node.renderedPosition().x,
        y: node.renderedPosition().y,
        name: d.label ?? "",
        fqn: d.fqn ?? d.id ?? "",
        kind: d.kind ?? "",
        layer: d.layer ?? "other",
        sequence: d.sequence ?? null,
        depth: d.depth ?? null,
        direction: d.isCenter ? "selected" : (d.direction ?? ""),
        file: d.file ?? null,
      })
    })

    cy.on("mouseout", "node", () => {
      setTooltip(EMPTY_TOOLTIP)
    })

    cy.on("viewport", () => {
      setTooltip((prev) => (prev.visible ? EMPTY_TOOLTIP : prev))
      computeSwimLanes()
    })

    const timer = setTimeout(() => {
      try {
        const layout = cy.layout({
          name: "dagre",
          rankDir: "TB",
          nodeSep: 60,
          rankSep: 80,
          fit: true,
          padding: 40,
          animate: false,
        } as cytoscape.LayoutOptions)
        layout.run()
        // Compute swim lanes after layout
        setTimeout(computeSwimLanes, 50)
      } catch {
        // Layout may fail with 0 nodes
      }
    }, 50)

    return () => clearTimeout(timer)
  }, [computeSwimLanes])

  // Re-run layout when elements change
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || elements.length === 0) return

    const timer = setTimeout(() => {
      try {
        const layout = cy.layout({
          name: "dagre",
          rankDir: "TB",
          nodeSep: 60,
          rankSep: 80,
          fit: true,
          padding: 40,
          animate: false,
        } as cytoscape.LayoutOptions)
        layout.run()
        setTimeout(computeSwimLanes, 50)
      } catch {
        // noop
      }
    }, 100)

    return () => clearTimeout(timer)
  }, [elements, computeSwimLanes])

  if (elements.length <= 1) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No upstream or downstream connections found
      </div>
    )
  }

  return (
    <div ref={containerRef} className="absolute inset-0">
      {/* Swim-lane background bands */}
      {swimLanes.map((lane) => {
        const cfg = LAYER_CONFIG[lane.layer]
        if (!cfg) return null
        return (
          <div
            key={lane.layer}
            className="pointer-events-none absolute left-0 right-0"
            style={{
              top: lane.top,
              height: lane.height,
              backgroundColor: cfg.bandColor,
              borderTop: `1px solid ${cfg.color}20`,
              borderBottom: `1px solid ${cfg.color}20`,
              zIndex: 0,
            }}
          >
            <span
              className="absolute left-2 text-[10px] font-semibold"
              style={{
                color: cfg.color,
                top: "50%",
                transform: "translateY(-50%)",
                opacity: 0.9,
                textShadow: "0 0 4px rgba(255,255,255,0.8)",
              }}
            >
              {cfg.label}
            </span>
          </div>
        )
      })}

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
          zIndex: 1,
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
            {tooltip.layer && (
              <Badge
                className="text-[10px] px-1.5 py-0"
                style={{
                  backgroundColor: LAYER_CONFIG[tooltip.layer]?.color ?? "#6B7280",
                  color: "#FFFFFF",
                }}
              >
                {LAYER_CONFIG[tooltip.layer]?.label ?? tooltip.layer}
              </Badge>
            )}
            {tooltip.kind && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
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
                {tooltip.sequence !== null && (
                  <Badge className="bg-blue-600 text-white text-[10px] px-1.5 py-0">
                    #{tooltip.sequence}
                  </Badge>
                )}
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

// ─── AI Summary Panel ───────────────────────────────────────────────────────

function AiSummaryPanel({
  projectId,
  nodeFqn,
  maxDepth,
  hasConnections,
}: {
  projectId: string
  nodeFqn: string | null
  maxDepth: number
  hasConnections: boolean
}) {
  const { summary, isLoading, error, fetch: fetchSummary, retry, clear } = useTraceSummary()

  useEffect(() => {
    if (nodeFqn && hasConnections) {
      fetchSummary(projectId, nodeFqn, maxDepth)
    }
    return () => {
      clear()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeFqn, projectId, maxDepth, hasConnections])

  // No connections state
  if (!hasConnections) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center">
        <GitBranch className="size-8 text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground">No connections to summarize</p>
      </div>
    )
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4">
        <Loader2 className="size-6 animate-spin text-blue-500" />
        <p className="text-sm text-muted-foreground">Generating AI summary...</p>
      </div>
    )
  }

  // Error state
  if (error) {
    const isAuthError = error.includes("401") || error.toLowerCase().includes("not configured")
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
        <Sparkles className="size-8 text-muted-foreground/40" />
        {isAuthError ? (
          <>
            <p className="text-sm text-muted-foreground">AI provider not configured</p>
            <a
              href="/settings/system"
              className="inline-flex items-center gap-1.5 text-xs text-blue-600 hover:underline"
            >
              <Cog className="size-3" />
              Configure AI provider in Settings
            </a>
          </>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">Summary unavailable</p>
            <p className="text-xs text-muted-foreground/70">{error}</p>
            <Button variant="outline" size="sm" onClick={retry} className="mt-1 gap-1.5">
              <RefreshCw className="size-3" />
              Retry
            </Button>
          </>
        )}
      </div>
    )
  }

  // Success state
  if (summary) {
    return (
      <div className="flex h-full flex-col">
        {/* Header */}
        <div className="flex items-center gap-2 border-b pb-3">
          <Sparkles className="size-4 text-amber-500" />
          <span className="text-sm font-semibold">AI Flow Summary</span>
          {summary.cached && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">
              Cached
            </Badge>
          )}
        </div>

        {/* Markdown content */}
        <div className="mt-3 flex-1 overflow-y-auto">
          <div className="prose prose-sm dark:prose-invert max-w-none text-sm leading-relaxed">
            <ReactMarkdown>{summary.summary}</ReactMarkdown>
          </div>
        </div>

        {/* Footer metadata */}
        {(summary.layers_involved.length > 0 || summary.tables_touched.length > 0) && (
          <div className="mt-3 border-t pt-3 space-y-2">
            {summary.layers_involved.length > 0 && (
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground mb-1">
                  Layers
                </p>
                <div className="flex flex-wrap gap-1">
                  {summary.layers_involved.map((layer) => (
                    <Badge
                      key={layer}
                      className={`text-[10px] px-1.5 py-0 ${layerBadgeClass(layer)}`}
                    >
                      {LAYER_CONFIG[layer]?.label ?? layer}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {summary.tables_touched.length > 0 && (
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground mb-1">
                  Tables
                </p>
                <div className="flex flex-wrap gap-1">
                  {summary.tables_touched.map((table) => (
                    <Badge
                      key={table}
                      variant="outline"
                      className="text-[10px] px-1.5 py-0"
                    >
                      <Database className="mr-1 size-2.5" />
                      {table}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  // Default / waiting state
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center">
      <Sparkles className="size-8 text-muted-foreground/40" />
      <p className="text-sm text-muted-foreground">AI summary will appear here</p>
    </div>
  )
}

// ─── Node row (for list view) ───────────────────────────────────────────────

function NodeRow({ node }: { node: TraceNode }) {
  return (
    <div className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50">
      <Badge className="shrink-0 bg-blue-600 text-white text-[10px] px-1.5 py-0 tabular-nums min-w-[24px] justify-center">
        {node.sequence}
      </Badge>
      <Badge
        className={`shrink-0 text-[10px] px-1.5 py-0 ${depthBadgeClass(node.depth)}`}
      >
        d{node.depth}
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
      <Badge className={`shrink-0 text-[10px] px-1.5 py-0 ${layerBadgeClass(node.layer)}`}>
        {LAYER_CONFIG[node.layer]?.label ?? node.layer}
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
  nodes: TraceNode[]
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

// ─── Props ──────────────────────────────────────────────────────────────────

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

// ─── Depth options ──────────────────────────────────────────────────────────

const DEPTH_OPTIONS = [1, 2, 3, 5, 7, 10] as const

// ─── Modal ──────────────────────────────────────────────────────────────────

export function TraceRouteModal({
  open,
  onClose,
  node,
  projectId,
}: TraceRouteModalProps) {
  const { data, isLoading, error, fetchTrace, clear } = useTraceRoute()
  const [viewMode, setViewMode] = useState<"graph" | "list">("graph")
  const [maxDepth, setMaxDepth] = useState(5)
  const [summaryOpen, setSummaryOpen] = useState(true)

  // Fetch trace when modal opens or depth changes
  useEffect(() => {
    if (open && node) {
      fetchTrace(projectId, node.fqn, maxDepth)
    }
    if (!open) {
      clear()
    }
  }, [open, node, projectId, maxDepth, fetchTrace, clear])

  const upstreamCount = data?.upstream_count ?? 0
  const downstreamCount = data?.downstream_count ?? 0
  const hasConnections = upstreamCount > 0 || downstreamCount > 0

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose() }}>
      <DialogContent className="flex h-[80vh] w-[85vw] !max-w-none flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-4">
          <div className="flex items-center justify-between">
            <DialogTitle className="flex items-center gap-2 text-base">
              <GitBranch className="size-4 text-blue-500" />
              Trace Route
            </DialogTitle>
            <div className="flex items-center gap-3">
              {/* Depth control */}
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
                  Depth
                </span>
                <select
                  value={maxDepth}
                  onChange={(e) => setMaxDepth(Number(e.target.value))}
                  className="h-7 rounded-md border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  {DEPTH_OPTIONS.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </div>
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
              {/* AI summary toggle */}
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => setSummaryOpen((v) => !v)}
                title={summaryOpen ? "Hide AI summary" : "Show AI summary"}
              >
                {summaryOpen ? (
                  <PanelRightClose className="mr-1 size-3" />
                ) : (
                  <PanelRightOpen className="mr-1 size-3" />
                )}
                <Sparkles className="size-3" />
              </Button>
            </div>
          </div>
          {node && (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="break-all text-sm font-medium">{node.name}</span>
              {node.kind && (
                <Badge variant="outline" className="text-[10px]">
                  {node.kind}
                </Badge>
              )}
              {node.language && (
                <Badge variant="outline" className="text-[10px]">
                  {node.language}
                </Badge>
              )}
              {!isLoading && hasConnections && (
                <Badge variant="outline" className="text-[10px]">
                  {upstreamCount} upstream / {downstreamCount} downstream
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
            <Loader2 className="mr-2 size-4 animate-spin" />
            <span className="text-sm text-muted-foreground">Analyzing trace route...</span>
          </div>
        ) : (
          <div className="flex flex-1 min-h-0">
            {/* Left panel: graph or list */}
            <div className={`relative transition-all duration-200 ${summaryOpen ? "w-[60%]" : "w-full"}`}>
              {viewMode === "graph" ? (
                <div className="relative h-full overflow-hidden">
                  {data && <TraceGraph data={data} />}
                  {/* Legend */}
                  <div className="absolute bottom-3 left-3 z-10 flex flex-wrap items-center gap-2 rounded-md border bg-background/90 px-3 py-1.5 text-[10px] backdrop-blur-sm">
                    {LAYER_ORDER.map((layer) => {
                      const cfg = LAYER_CONFIG[layer]
                      if (!cfg) return null
                      return (
                        <span key={layer} className="inline-flex items-center gap-1">
                          <span
                            className="inline-block size-2.5 rounded-sm"
                            style={{ backgroundColor: cfg.color }}
                          />
                          <span className="text-muted-foreground">{cfg.label}</span>
                        </span>
                      )
                    })}
                    <span className="ml-1 border-l pl-2 text-muted-foreground">
                      Numbers = call sequence
                    </span>
                  </div>
                </div>
              ) : (
                <div className="h-full overflow-y-auto">
                  <div className="space-y-0 px-6 py-4">
                    <Section
                      title="Upstream Callers"
                      count={upstreamCount}
                      nodes={data?.upstream ?? []}
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
                      count={downstreamCount}
                      nodes={data?.downstream ?? []}
                      isLoading={isLoading}
                      emptyMessage="No callees found"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Right panel: AI summary (collapsible) */}
            {summaryOpen && (
              <div className="w-[40%] border-l overflow-y-auto p-4">
                <AiSummaryPanel
                  projectId={projectId}
                  nodeFqn={node?.fqn ?? null}
                  maxDepth={maxDepth}
                  hasConnections={hasConnections}
                />
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
