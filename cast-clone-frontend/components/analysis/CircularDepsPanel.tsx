"use client"

import * as React from "react"
import { useState } from "react"
import type cytoscape from "cytoscape"
import { RefreshCcw, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import type { CircularDependenciesResponse } from "@/lib/types"

// ─── Overlay functions ──────────────────────────────────────────────────────

export function highlightCycle(
  cy: cytoscape.Core,
  cycleFqns: string[],
): void {
  // Dim everything
  cy.nodes().style("opacity", 0.2)
  cy.edges().style("opacity", 0.2)

  const cycleSet = new Set(cycleFqns)

  // Highlight cycle nodes in red
  for (const fqn of cycleFqns) {
    const cyNode = cy.getElementById(fqn)
    if (cyNode.length > 0) {
      cyNode.style({
        "opacity": 1,
        "background-color": "#ef4444",
        "border-color": "#991b1b",
        "border-width": 3,
      })
    }
  }

  // Highlight edges between consecutive cycle nodes
  for (let i = 0; i < cycleFqns.length; i++) {
    const src = cycleFqns[i]
    const tgt = cycleFqns[(i + 1) % cycleFqns.length]
    cy.edges().forEach((edge) => {
      const eSrc = edge.source().id()
      const eTgt = edge.target().id()
      if (
        (eSrc === src && eTgt === tgt) ||
        (eSrc === tgt && eTgt === src)
      ) {
        edge.style({
          "opacity": 1,
          "line-color": "#ef4444",
          "width": 3,
        })
      }
    })
  }

  // Also show any edge between two cycle members
  cy.edges().forEach((edge) => {
    const eSrc = edge.source().id()
    const eTgt = edge.target().id()
    if (cycleSet.has(eSrc) && cycleSet.has(eTgt)) {
      edge.style({
        "opacity": 1,
        "line-color": "#ef4444",
        "width": 2,
      })
    }
  })
}

export function clearCycleHighlight(cy: cytoscape.Core): void {
  cy.nodes().removeStyle()
  cy.edges().removeStyle()
}

// ─── Component ──────────────────────────────────────────────────────────────

interface CircularDepsPanelProps {
  data: CircularDependenciesResponse | null
  isLoading: boolean
  error: string | null
  level: "module" | "class"
  onLevelChange: (level: "module" | "class") => void
  onHighlightCycle: (cycleFqns: string[]) => void
  onClose: () => void
}

export function CircularDepsPanel({
  data,
  isLoading,
  error,
  level,
  onLevelChange,
  onHighlightCycle,
  onClose,
}: CircularDepsPanelProps) {
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null)

  const handleCycleClick = (cycle: string[], idx: number) => {
    setSelectedIdx(idx)
    onHighlightCycle(cycle)
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <RefreshCcw className="size-4 text-orange-500" />
          <span className="text-sm font-semibold">Circular Dependencies</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="size-7 p-0"
          onClick={onClose}
          aria-label="Close circular dependencies panel"
        >
          <X className="size-3" />
        </Button>
      </div>

      {/* Level toggle */}
      <div className="flex gap-1 border-b px-4 py-2">
        {(["module", "class"] as const).map((lvl) => (
          <Button
            key={lvl}
            variant={level === lvl ? "secondary" : "ghost"}
            size="sm"
            className="flex-1 text-xs capitalize"
            onClick={() => onLevelChange(lvl)}
          >
            {lvl}
          </Button>
        ))}
      </div>

      {/* Content */}
      <ScrollArea className="flex-1">
        <div className="p-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <span className="text-sm text-muted-foreground">
                Detecting cycles...
              </span>
            </div>
          ) : error ? (
            <div className="py-4 text-center text-sm text-destructive">
              {error}
            </div>
          ) : !data ? (
            <div className="py-4 text-center text-sm text-muted-foreground">
              Loading circular dependency data...
            </div>
          ) : data.cycles.length === 0 ? (
            <div className="py-4 text-center text-sm text-muted-foreground">
              No circular dependencies found at {level} level.
            </div>
          ) : (
            <>
              {/* Cycle count header */}
              <div className="mb-3">
                <Badge variant="outline" className="text-xs">
                  {data.total} cycle{data.total !== 1 ? "s" : ""} found
                </Badge>
              </div>

              <Separator className="my-3" />

              {/* Cycle list */}
              <div className="space-y-2">
                {data.cycles.map((cycle, idx) => {
                  const isSelected = selectedIdx === idx
                  return (
                    <button
                      key={idx}
                      className={`w-full rounded-md border p-2 text-left transition-colors hover:bg-muted ${
                        isSelected
                          ? "border-orange-500 bg-orange-50 dark:bg-orange-950"
                          : "border-border"
                      }`}
                      onClick={() => handleCycleClick(cycle.cycle, idx)}
                    >
                      <div className="mb-1 flex items-center gap-2">
                        <Badge
                          variant="secondary"
                          className="text-[10px] shrink-0"
                        >
                          length {cycle.cycle_length}
                        </Badge>
                      </div>
                      <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                        {cycle.cycle.map((fqn, i) => {
                          const shortName = fqn.split(".").pop() ?? fqn
                          return (
                            <React.Fragment key={fqn}>
                              <span
                                className="truncate font-mono text-[11px]"
                                title={fqn}
                              >
                                {shortName}
                              </span>
                              {i < cycle.cycle.length - 1 && (
                                <span className="text-muted-foreground">
                                  &rarr;
                                </span>
                              )}
                            </React.Fragment>
                          )
                        })}
                        <span className="text-muted-foreground">&rarr;</span>
                        <span
                          className="truncate font-mono text-[11px]"
                          title={cycle.cycle[0]}
                        >
                          {cycle.cycle[0]?.split(".").pop() ?? cycle.cycle[0]}
                        </span>
                      </div>
                    </button>
                  )
                })}
              </div>
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
