"use client"

import React, { useCallback, useEffect, useRef } from "react"
import CytoscapeComponent from "react-cytoscapejs"
import type cytoscape from "cytoscape"

import { ensureCytoscapeExtensions } from "@/lib/cytoscape-setup"
import { defaultStylesheet, layerStylesheet } from "@/lib/graph-styles"
import type { ViewMode } from "@/lib/types"
import type { LayoutMode } from "@/hooks/useGraph"

ensureCytoscapeExtensions()

const LAYOUT_CONFIGS: Record<ViewMode, cytoscape.LayoutOptions> = {
  architecture: {
    name: "dagre",
    rankDir: "TB",
    nodeSep: 50,
    rankSep: 80,
    fit: false,
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
    fit: false,
  } as cytoscape.LayoutOptions,
  transaction: {
    name: "dagre",
    rankDir: "LR",
    nodeSep: 30,
    rankSep: 60,
    fit: false,
    animate: true,
    animationDuration: 300,
  } as cytoscape.LayoutOptions,
}

interface GraphViewProps {
  elements: cytoscape.ElementDefinition[]
  viewMode: ViewMode
  performanceTier: "full" | "no-animation" | "simplified" | "force-drilldown"
  layoutMode?: LayoutMode
  colorBy?: "kind" | "layer"
  onNodeSelect?: (nodeData: Record<string, unknown>) => void
  onNodeDrillDown?: (fqn: string, name: string, level: string) => void
  onCyInit?: (cy: cytoscape.Core) => void
  onNodeRightClick?: (fqn: string, position: { x: number; y: number }) => void
}

export function GraphView({
  elements,
  viewMode,
  performanceTier,
  layoutMode = "full",
  colorBy = "kind",
  onNodeSelect,
  onNodeDrillDown,
  onCyInit,
  onNodeRightClick,
}: GraphViewProps) {
  const cyRef = useRef<cytoscape.Core | null>(null)
  const prevElementIdsRef = useRef<Set<string>>(new Set())
  // Snapshot parent node positions BEFORE React re-render adds unpositioned children
  const parentPositionsRef = useRef<Map<string, { x: number; y: number; w: number; h: number }>>(new Map())
  const dblTapTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const stylesheet = colorBy === "layer" ? layerStylesheet : defaultStylesheet

  const handleCyRef = useCallback(
    (cy: cytoscape.Core) => {
      if (cyRef.current === cy) return
      cyRef.current = cy

      if (onCyInit) {
        onCyInit(cy)
      }

      // Initialize expand-collapse extension
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        ;(cy as Record<string, any>).expandCollapse({
          layoutBy: null, // Disable automatic full-graph re-layout on expand/collapse
          fisheye: false,
          animate: performanceTier === "full",
          animationDuration: 300,
          cueEnabled: true,
          expandCollapseCuePosition: "top-left",
        })
      } catch {
        // expand-collapse may fail if no compound nodes exist
      }

      // Debounced click → select node (delayed to avoid firing before dbltap)
      cy.on("tap", "node", (event) => {
        const node = event.target
        if (onNodeSelect) {
          if (dblTapTimerRef.current) clearTimeout(dblTapTimerRef.current)
          dblTapTimerRef.current = setTimeout(() => {
            dblTapTimerRef.current = null
            onNodeSelect(node.data())
          }, 250)
        }
      })

      // Double-click → drill down (snapshot parent position first)
      cy.on("dbltap", "node", (event) => {
        // Cancel the pending single-tap select
        if (dblTapTimerRef.current) {
          clearTimeout(dblTapTimerRef.current)
          dblTapTimerRef.current = null
        }

        const node = event.target
        const data = node.data()
        if (data.drillable && onNodeDrillDown) {
          // Snapshot this node's position & size BEFORE new children are added
          // (compound parent bbox will shift once unpositioned children appear)
          const pos = node.position()
          const bb = node.boundingBox()
          parentPositionsRef.current.set(data.id, {
            x: pos.x,
            y: pos.y,
            w: Math.max(bb.w, 200),
            h: Math.max(bb.h, 200),
          })
          onNodeDrillDown(data.id, data.label, data.drillLevel)
        }
      })

      // Click canvas background → deselect
      cy.on("tap", (event) => {
        if (event.target === cy) {
          if (onNodeSelect) {
            onNodeSelect({})
          }
        }
      })

      // Right-click node → context menu
      // Use originalEvent.clientX/Y (viewport coordinates) so the
      // context menu can be positioned with `fixed` correctly regardless
      // of where the Cytoscape canvas sits in the page.
      cy.on("cxttap", "node", (event) => {
        const node = event.target
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const orig = (event as any).originalEvent as MouseEvent
        onNodeRightClick?.(node.id(), { x: orig.clientX, y: orig.clientY })
      })
    },
    [onNodeSelect, onNodeDrillDown, onCyInit, onNodeRightClick, performanceTier]
  )

  // Track the previous viewMode to detect view switches
  const prevViewModeRef = useRef<ViewMode>(viewMode)

  // Re-run layout when view mode or elements change
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || elements.length === 0) return

    const currentIds = new Set(
      elements.map((e) => e.data?.id as string).filter(Boolean)
    )

    const viewModeChanged = prevViewModeRef.current !== viewMode
    prevViewModeRef.current = viewMode

    const layoutConfig = { ...LAYOUT_CONFIGS[viewMode] }

    if (performanceTier !== "full") {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(layoutConfig as Record<string, any>).animate = false
    }

    const timer = setTimeout(() => {
      try {
        if (layoutMode === "drill" && prevElementIdsRef.current.size > 0 && !viewModeChanged) {
          // Drill-down: find new nodes and their parent, then layout
          // only within the parent's SAVED bounding box (not the corrupted one)
          const newIds = [...currentIds].filter(
            (id) => !prevElementIdsRef.current.has(id)
          )
          if (newIds.length > 0) {
            const newNodes = cy.nodes().filter((node) => newIds.includes(node.id()))

            if (newNodes.length > 0) {
              // Find the parent compound node of the new children
              const parentId = newNodes[0].data("parent")
              const parentNode = parentId ? cy.getElementById(parentId) : null

              if (parentNode && parentNode.length > 0) {
                // Use the SAVED position from before children were added
                // (the live bounding box is corrupted by unpositioned children at 0,0)
                const saved = parentPositionsRef.current.get(parentId)
                const cx = saved ? saved.x : parentNode.position().x
                const cy_ = saved ? saved.y : parentNode.position().y
                const w = saved ? saved.w : 200
                const h = saved ? saved.h : 200

                // Layout new nodes using a grid centered on the parent's original position
                newNodes
                  .layout({
                    name: "grid",
                    boundingBox: {
                      x1: cx - w / 2,
                      y1: cy_ - h / 2,
                      x2: cx + w / 2,
                      y2: cy_ + h / 2,
                    },
                    fit: false,
                    animate: false,
                    condense: true,
                    avoidOverlap: true,
                  } as cytoscape.LayoutOptions)
                  .run()

                // Clean up saved position
                if (saved) parentPositionsRef.current.delete(parentId)

                // Smoothly center on the expanded parent (keep current zoom)
                cy.animate({
                  center: { eles: parentNode },
                  zoom: cy.zoom(),
                  duration: 300,
                })
              } else {
                // No parent (shouldn't happen) — just fit
                cy.animate({ fit: { eles: cy.elements(), padding: 30 }, duration: 300 })
              }
            }
          }
        } else {
          // Full layout: reposition everything, then fit to viewport
          const layout = cy.layout(layoutConfig)
          layout.on("layoutstop", () => {
            cy.animate({ fit: { eles: cy.elements(), padding: 40 }, duration: 300 })
          })
          layout.run()
        }
      } catch {
        // Layout algorithm may fail with 0 nodes
      }

      prevElementIdsRef.current = currentIds
    }, 50)

    return () => clearTimeout(timer)
  }, [viewMode, elements, performanceTier, layoutMode])

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

      {performanceTier === "force-drilldown" && (
        <div className="absolute inset-x-0 top-0 z-10 bg-yellow-50 px-4 py-2 text-center text-sm text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-200">
          Too many nodes to render at once. Please drill down into a specific
          module for a better experience.
        </div>
      )}
    </div>
  )
}
