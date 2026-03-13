"use client"

import * as React from "react"
import { useCallback, useEffect, useMemo, useRef } from "react"
import CytoscapeComponent from "react-cytoscapejs"
import type cytoscape from "cytoscape"
import { Route } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ensureCytoscapeExtensions } from "@/lib/cytoscape-setup"
import type { PathFinderResponse } from "@/lib/types"

ensureCytoscapeExtensions()

// ─── Kind → node color ──────────────────────────────────────────────────────

const KIND_COLORS: Record<string, string> = {
  CLASS: "#22C55E",
  Class: "#22C55E",
  INTERFACE: "#14B8A6",
  Interface: "#14B8A6",
  FUNCTION: "#EAB308",
  Function: "#EAB308",
  MODULE: "#3B82F6",
  Module: "#3B82F6",
  TABLE: "#F97316",
  Table: "#F97316",
  API_ENDPOINT: "#A855F7",
}

// ─── Build Cytoscape elements from path data ────────────────────────────────

function buildPathElements(
  data: PathFinderResponse,
): cytoscape.ElementDefinition[] {
  const elements: cytoscape.ElementDefinition[] = []
  const endpointFqns = new Set([data.from_fqn, data.to_fqn])

  for (const node of data.nodes) {
    elements.push({
      data: {
        id: node.fqn,
        label: node.name,
        kind: node.type,
        fqn: node.fqn,
        isEndpoint: endpointFqns.has(node.fqn),
      },
    })
  }

  for (const edge of data.edges) {
    elements.push({
      data: {
        id: `${edge.source}->${edge.target}`,
        source: edge.source,
        target: edge.target,
        edgeType: edge.type,
      },
    })
  }

  return elements
}

// ─── Stylesheet ─────────────────────────────────────────────────────────────

const pathStylesheet: cytoscape.StylesheetJsonBlock[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "text-valign": "center",
      "text-halign": "center",
      "font-size": "12px",
      "font-family": "Inter, system-ui, sans-serif",
      color: "#1F2937",
      "text-outline-color": "#FFFFFF",
      "text-outline-width": 2,
      "background-color": "#6B7280",
      width: 45,
      height: 45,
      "border-width": 2,
      "border-color": "#D1D5DB",
      "text-wrap": "ellipsis",
      "text-max-width": "100px",
    },
  },
  {
    selector: "node[?isEndpoint]",
    style: {
      "border-width": 3,
      "border-color": "#1e3a5f",
      width: 55,
      height: 55,
      "font-weight": "bold",
      "font-size": "13px",
    },
  },
  {
    selector: "edge",
    style: {
      width: 3,
      "line-color": "#3b82f6",
      "target-arrow-color": "#3b82f6",
      "target-arrow-shape": "triangle",
      "arrow-scale": 1,
      "curve-style": "bezier",
      label: "data(edgeType)",
      "font-size": "10px",
      "text-rotation": "autorotate",
      color: "#64748B",
      "text-outline-color": "#FFFFFF",
      "text-outline-width": 2,
      "text-background-color": "#FFFFFF",
      "text-background-opacity": 0.9,
      "text-background-padding": "3px",
    },
  },
  ...Object.entries(KIND_COLORS).map(([kind, color]) => ({
    selector: `node[kind = "${kind}"]`,
    style: { "background-color": color, "border-color": color },
  })),
]

// ─── Kind badge colors (for tooltip) ────────────────────────────────────────

const KIND_BADGE_COLORS: Record<string, string> = {
  CLASS: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  INTERFACE: "bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200",
  FUNCTION: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  TABLE: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  API_ENDPOINT: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  MODULE: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
}

function kindBadgeClass(kind: string): string {
  return KIND_BADGE_COLORS[kind?.toUpperCase()] ?? "bg-muted text-muted-foreground"
}

// ─── Tooltip state ──────────────────────────────────────────────────────────

interface TooltipState {
  visible: boolean
  x: number
  y: number
  name: string
  fqn: string
  kind: string
  isEndpoint: boolean
}

const EMPTY_TOOLTIP: TooltipState = {
  visible: false, x: 0, y: 0, name: "", fqn: "", kind: "", isEndpoint: false,
}

// ─── Graph component ────────────────────────────────────────────────────────

function PathGraph({ data }: { data: PathFinderResponse }) {
  const cyRef = useRef<cytoscape.Core | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [tooltip, setTooltip] = React.useState<TooltipState>(EMPTY_TOOLTIP)

  const elements = useMemo(() => buildPathElements(data), [data])

  const handleCy = useCallback((cy: cytoscape.Core) => {
    if (cyRef.current === cy) return
    cyRef.current = cy

    // Hover → show tooltip
    cy.on("mouseover", "node", (event) => {
      const node = event.target
      const d = node.data()
      const renderedPos = node.renderedPosition()
      setTooltip({
        visible: true,
        x: renderedPos.x,
        y: renderedPos.y,
        name: d.label ?? "",
        fqn: d.fqn ?? d.id ?? "",
        kind: d.kind ?? "",
        isEndpoint: !!d.isEndpoint,
      })
    })

    cy.on("mouseout", "node", () => {
      setTooltip(EMPTY_TOOLTIP)
    })

    cy.on("viewport", () => {
      setTooltip((prev) => (prev.visible ? EMPTY_TOOLTIP : prev))
    })

    const timer = setTimeout(() => {
      try {
        cy.layout({
          name: "dagre",
          rankDir: "LR",
          nodeSep: 60,
          rankSep: 120,
          fit: true,
          padding: 40,
          animate: false,
        } as cytoscape.LayoutOptions).run()
      } catch {
        // noop
      }
    }, 50)

    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy || elements.length === 0) return

    const timer = setTimeout(() => {
      try {
        cy.layout({
          name: "dagre",
          rankDir: "LR",
          nodeSep: 60,
          rankSep: 120,
          fit: true,
          padding: 40,
          animate: false,
        } as cytoscape.LayoutOptions).run()
      } catch {
        // noop
      }
    }, 100)

    return () => clearTimeout(timer)
  }, [elements])

  return (
    <div ref={containerRef} className="absolute inset-0">
      <CytoscapeComponent
        elements={CytoscapeComponent.normalizeElements(elements)}
        stylesheet={pathStylesheet}
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
        zoomingEnabled
        userZoomingEnabled
        panningEnabled
        userPanningEnabled
        boxSelectionEnabled={false}
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
            {tooltip.isEndpoint && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                endpoint
              </Badge>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Modal ──────────────────────────────────────────────────────────────────

interface PathGraphModalProps {
  open: boolean
  onClose: () => void
  data: PathFinderResponse | null
}

export function PathGraphModal({ open, onClose, data }: PathGraphModalProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose() }}>
      <DialogContent className="flex h-[80vh] w-[70vw] !max-w-none flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-4">
          <div className="flex items-center justify-between">
            <DialogTitle className="flex items-center gap-2 text-base">
              <Route className="size-4 text-blue-500" />
              Path Graph
            </DialogTitle>
          </div>
          {data && (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">
                {data.nodes[0]?.name} → {data.nodes[data.nodes.length - 1]?.name}
              </span>
              <Badge variant="outline" className="text-[10px]">
                {data.path_length} hops
              </Badge>
              <Badge variant="outline" className="text-[10px]">
                {data.nodes.length} nodes
              </Badge>
            </div>
          )}
        </DialogHeader>

        <div className="relative min-h-0 flex-1 overflow-hidden">
          {data && <PathGraph data={data} />}
        </div>
      </DialogContent>
    </Dialog>
  )
}
