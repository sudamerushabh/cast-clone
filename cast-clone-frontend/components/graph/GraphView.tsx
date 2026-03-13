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
}: GraphViewProps) {
  const cyRef = useRef<cytoscape.Core | null>(null)
  const prevElementIdsRef = useRef<Set<string>>(new Set())

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
        })
      } catch {
        // expand-collapse may fail if no compound nodes exist
      }

      // Click → select node
      cy.on("tap", "node", (event) => {
        const node = event.target
        if (onNodeSelect) {
          onNodeSelect(node.data())
        }
      })

      // Double-click → drill down
      cy.on("dbltap", "node", (event) => {
        const node = event.target
        const data = node.data()
        if (data.drillable && onNodeDrillDown) {
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
    },
    [onNodeSelect, onNodeDrillDown, onCyInit, performanceTier]
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
          // only within the parent's bounding box
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
                // Get parent's current bounding box to constrain children
                const parentBB = parentNode.boundingBox()

                // Layout new nodes using a grid inside the parent's area
                newNodes
                  .layout({
                    name: "grid",
                    boundingBox: {
                      x1: parentBB.x1,
                      y1: parentBB.y1,
                      x2: Math.max(parentBB.x2, parentBB.x1 + 200),
                      y2: Math.max(parentBB.y2, parentBB.y1 + 200),
                    },
                    animate: false,
                    condense: true,
                    avoidOverlap: true,
                  } as cytoscape.LayoutOptions)
                  .run()

                // Smoothly center on the expanded parent
                cy.animate({
                  center: { eles: parentNode },
                  duration: 300,
                })
              } else {
                // No parent (shouldn't happen) — just fit
                cy.animate({ fit: { eles: cy.elements(), padding: 30 }, duration: 300 })
              }
            }
          }
        } else {
          // Full layout: reposition everything
          cy.layout(layoutConfig).run()
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
