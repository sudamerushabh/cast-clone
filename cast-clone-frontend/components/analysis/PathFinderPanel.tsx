"use client"

import * as React from "react"
import { useState, useEffect } from "react"
import type cytoscape from "cytoscape"
import { Route, X, Search } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { PathFinderResponse } from "@/lib/types"

// ─── Overlay functions ──────────────────────────────────────────────────────

export function applyPathOverlay(
  cy: cytoscape.Core,
  pathData: PathFinderResponse,
): void {
  // Dim everything
  cy.nodes().style("opacity", 0.2)
  cy.edges().style("opacity", 0.2)

  const pathFqns = new Set(pathData.nodes.map((n) => n.fqn))
  const endpointFqns = new Set([pathData.from_fqn, pathData.to_fqn])

  // Highlight path nodes
  for (const node of pathData.nodes) {
    const cyNode = cy.getElementById(node.fqn)
    if (cyNode.length > 0) {
      const isEndpoint = endpointFqns.has(node.fqn)
      cyNode.style({
        "opacity": 1,
        "background-color": "#3b82f6",
        "border-color": isEndpoint ? "#1e3a5f" : "#3b82f6",
        "border-width": isEndpoint ? 3 : 1,
      })
    }
  }

  // Highlight path edges
  cy.edges().forEach((edge) => {
    const src = edge.source().id()
    const tgt = edge.target().id()
    if (pathFqns.has(src) && pathFqns.has(tgt)) {
      // Check if this edge is actually in the path
      const isPathEdge = pathData.edges.some(
        (e) => (e.source === src && e.target === tgt) || (e.source === tgt && e.target === src),
      )
      if (isPathEdge) {
        edge.style({
          "opacity": 1,
          "line-color": "#3b82f6",
          "width": 3,
        })
      }
    }
  })
}

export function clearPathOverlay(cy: cytoscape.Core): void {
  cy.nodes().removeStyle()
  cy.edges().removeStyle()
}

// ─── Component ──────────────────────────────────────────────────────────────

interface PathFinderPanelProps {
  data: PathFinderResponse | null
  isLoading: boolean
  error: string | null
  initialFromFqn?: string
  onFindPath: (fromFqn: string, toFqn: string) => void
  onClose: () => void
}

export function PathFinderPanel({
  data,
  isLoading,
  error,
  initialFromFqn,
  onFindPath,
  onClose,
}: PathFinderPanelProps) {
  const [fromFqn, setFromFqn] = useState(initialFromFqn ?? "")
  const [toFqn, setToFqn] = useState("")

  // Update from FQN when initialFromFqn changes
  useEffect(() => {
    if (initialFromFqn) {
      setFromFqn(initialFromFqn)
    }
  }, [initialFromFqn])

  const handleFind = () => {
    if (fromFqn.trim() && toFqn.trim()) {
      onFindPath(fromFqn.trim(), toFqn.trim())
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Route className="size-4 text-blue-500" />
          <span className="text-sm font-semibold">Path Finder</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="size-7 p-0"
          onClick={onClose}
          aria-label="Close path finder panel"
        >
          <X className="size-3" />
        </Button>
      </div>

      {/* Inputs */}
      <div className="space-y-3 border-b px-4 py-3">
        <div>
          <Label htmlFor="path-from" className="text-xs">
            From (FQN)
          </Label>
          <Input
            id="path-from"
            value={fromFqn}
            onChange={(e) => setFromFqn(e.target.value)}
            placeholder="e.g. com.example.UserService"
            className="mt-1 h-8 text-xs"
          />
        </div>
        <div>
          <Label htmlFor="path-to" className="text-xs">
            To (FQN)
          </Label>
          <Input
            id="path-to"
            value={toFqn}
            onChange={(e) => setToFqn(e.target.value)}
            placeholder="e.g. com.example.OrderRepository"
            className="mt-1 h-8 text-xs"
          />
        </div>
        <Button
          size="sm"
          className="w-full"
          onClick={handleFind}
          disabled={isLoading || !fromFqn.trim() || !toFqn.trim()}
        >
          <Search className="mr-1 size-3" />
          {isLoading ? "Searching..." : "Find Path"}
        </Button>
      </div>

      {/* Results */}
      <ScrollArea className="flex-1">
        <div className="p-4">
          {error ? (
            <div className="py-4 text-center text-sm text-destructive">{error}</div>
          ) : !data ? (
            <div className="py-4 text-center text-sm text-muted-foreground">
              Enter two FQNs and click Find Path
            </div>
          ) : data.path_length === 0 ? (
            <div className="py-4 text-center text-sm text-muted-foreground">
              No path found between these nodes
            </div>
          ) : (
            <>
              <div className="mb-3 flex items-center gap-2">
                <Badge variant="outline" className="text-xs">
                  Path length: {data.path_length}
                </Badge>
                <Badge variant="outline" className="text-xs">
                  {data.nodes.length} nodes
                </Badge>
              </div>

              {/* Path visualization */}
              <div className="space-y-0">
                {data.nodes.map((node, idx) => (
                  <React.Fragment key={node.fqn}>
                    {/* Node */}
                    <div
                      className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
                      title={node.fqn}
                    >
                      <div
                        className="size-2.5 shrink-0 rounded-full"
                        style={{
                          backgroundColor:
                            idx === 0 || idx === data.nodes.length - 1
                              ? "#3b82f6"
                              : "#94a3b8",
                        }}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium">{node.name}</p>
                        <p className="truncate text-[10px] text-muted-foreground">
                          {node.type}
                        </p>
                      </div>
                    </div>

                    {/* Edge label between nodes */}
                    {idx < data.edges.length ? (
                      <div className="flex items-center gap-2 py-0.5 pl-5">
                        <div className="h-4 w-px bg-border" />
                        <Badge variant="secondary" className="text-[10px]">
                          {data.edges[idx].type}
                        </Badge>
                      </div>
                    ) : null}
                  </React.Fragment>
                ))}
              </div>
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
