"use client"

import * as React from "react"
import type cytoscape from "cytoscape"
import { Activity, X, ArrowDown, ArrowUp, ArrowLeftRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import type { ImpactAnalysisResponse, AffectedNode } from "@/lib/types"

// ─── Depth color mapping ────────────────────────────────────────────────────

const DEPTH_COLORS: Record<number, string> = {
  1: "#ef4444",
  2: "#f97316",
  3: "#eab308",
  4: "#facc15",
  5: "#fef08a",
}

const DEPTH_BADGE_CLASSES: Record<number, string> = {
  1: "bg-red-500 text-white",
  2: "bg-orange-500 text-white",
  3: "bg-yellow-500 text-black",
  4: "bg-yellow-300 text-black",
  5: "bg-yellow-100 text-black",
}

function depthColor(depth: number): string {
  return DEPTH_COLORS[depth] ?? DEPTH_COLORS[5]
}

function depthBadgeClass(depth: number): string {
  return DEPTH_BADGE_CLASSES[depth] ?? DEPTH_BADGE_CLASSES[5]
}

// ─── Overlay functions ──────────────────────────────────────────────────────

export function applyImpactOverlay(
  cy: cytoscape.Core,
  affected: AffectedNode[],
  startFqn: string,
): void {
  // Dim everything
  cy.nodes().style("opacity", 0.2)
  cy.edges().style("opacity", 0.2)

  // Build set of affected FQNs for quick lookup
  const affectedFqns = new Set(affected.map((a) => a.fqn))
  affectedFqns.add(startFqn)

  // Highlight start node in red
  const startNode = cy.getElementById(startFqn)
  if (startNode.length > 0) {
    startNode.style({
      "opacity": 1,
      "background-color": "#ef4444",
      "border-color": "#991b1b",
      "border-width": 3,
    })
  }

  // Color affected nodes by depth
  for (const node of affected) {
    const cyNode = cy.getElementById(node.fqn)
    if (cyNode.length > 0) {
      cyNode.style({
        "opacity": 1,
        "background-color": depthColor(node.depth),
      })
    }
  }

  // Show edges between affected nodes
  cy.edges().forEach((edge) => {
    const src = edge.source().id()
    const tgt = edge.target().id()
    if (affectedFqns.has(src) && affectedFqns.has(tgt)) {
      edge.style({
        "opacity": 1,
        "line-color": "#94a3b8",
        "width": 2,
      })
    }
  })
}

export function clearImpactOverlay(cy: cytoscape.Core): void {
  cy.nodes().removeStyle("opacity background-color border-color border-width")
  cy.edges().removeStyle("opacity line-color width")
}

// ─── Component ──────────────────────────────────────────────────────────────

type Direction = "downstream" | "upstream" | "both"

const DIRECTION_ICONS: Record<Direction, React.ElementType> = {
  downstream: ArrowDown,
  upstream: ArrowUp,
  both: ArrowLeftRight,
}

interface ImpactPanelProps {
  data: ImpactAnalysisResponse | null
  isLoading: boolean
  error: string | null
  direction: Direction
  onDirectionChange: (dir: Direction) => void
  onClose: () => void
  onNodeClick?: (fqn: string) => void
}

export function ImpactPanel({
  data,
  isLoading,
  error,
  direction,
  onDirectionChange,
  onClose,
  onNodeClick,
}: ImpactPanelProps) {
  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Activity className="size-4 text-red-500" />
          <span className="text-sm font-semibold">Impact Analysis</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="size-7 p-0"
          onClick={onClose}
          aria-label="Close impact panel"
        >
          <X className="size-3" />
        </Button>
      </div>

      {/* Direction toggle */}
      <div className="flex gap-1 border-b px-4 py-2">
        {(["downstream", "upstream", "both"] as Direction[]).map((dir) => {
          const Icon = DIRECTION_ICONS[dir]
          return (
            <Button
              key={dir}
              variant={direction === dir ? "secondary" : "ghost"}
              size="sm"
              className="flex-1 text-xs capitalize"
              onClick={() => onDirectionChange(dir)}
            >
              <Icon className="mr-1 size-3" />
              {dir}
            </Button>
          )
        })}
      </div>

      {/* Content */}
      <ScrollArea className="flex-1">
        <div className="p-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <span className="text-sm text-muted-foreground">Analyzing...</span>
            </div>
          ) : error ? (
            <div className="py-4 text-center text-sm text-destructive">{error}</div>
          ) : !data ? (
            <div className="py-4 text-center text-sm text-muted-foreground">
              Select a node and click &quot;Show Impact&quot; to begin
            </div>
          ) : (
            <>
              {/* Summary */}
              <div className="mb-3">
                <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Source Node
                </h4>
                <p className="mt-1 break-all text-sm font-medium" title={data.node}>
                  {data.node.split(".").pop() ?? data.node}
                </p>
                <p className="break-all text-xs text-muted-foreground" title={data.node}>
                  {data.node}
                </p>
              </div>

              <div className="mb-3 flex items-center gap-2">
                <Badge variant="outline" className="text-xs">
                  {data.summary.total} affected
                </Badge>
                <Badge variant="outline" className="text-xs">
                  depth {data.max_depth}
                </Badge>
              </div>

              {/* By type badges */}
              {Object.keys(data.summary.by_type).length > 0 ? (
                <div className="mb-3 flex flex-wrap gap-1">
                  {Object.entries(data.summary.by_type).map(([type, count]) => (
                    <Badge key={type} variant="secondary" className="text-xs">
                      {type}: {count}
                    </Badge>
                  ))}
                </div>
              ) : null}

              <Separator className="my-3" />

              {/* Depth legend */}
              <div className="mb-3">
                <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Depth Legend
                </h4>
                <div className="flex gap-2">
                  {[1, 2, 3, 4, 5].map((d) => (
                    <div key={d} className="flex items-center gap-1">
                      <span
                        className="inline-block size-2.5 rounded-full"
                        style={{ backgroundColor: depthColor(d) }}
                      />
                      <span className="text-xs text-muted-foreground">{d}</span>
                    </div>
                  ))}
                </div>
              </div>

              <Separator className="my-3" />

              {/* Affected nodes list */}
              <div>
                <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Affected Nodes ({data.affected.length})
                </h4>
                <div className="space-y-1">
                  {data.affected.map((node) => (
                    <button
                      key={node.fqn}
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted cursor-pointer"
                      title={node.fqn}
                      onClick={() => onNodeClick?.(node.fqn)}
                    >
                      <Badge className={`shrink-0 text-[10px] px-1.5 py-0 ${depthBadgeClass(node.depth)}`}>
                        {node.depth}
                      </Badge>
                      <div className="min-w-0 flex-1 text-left">
                        <p className="break-all text-xs font-medium">{node.name}</p>
                        <p className="break-all text-[10px] text-muted-foreground">
                          {node.type}
                          {node.file ? ` - ${node.file}` : ""}
                        </p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
