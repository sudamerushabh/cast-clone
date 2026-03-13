"use client"

import React, { useCallback, useEffect, useRef, useState } from "react"
import { useParams } from "next/navigation"
import type cytoscape from "cytoscape"
import { Activity, Filter, GitBranch, RefreshCw, Route } from "lucide-react"

import { Button } from "@/components/ui/button"

import { GraphView } from "@/components/graph/GraphView"
import { GraphToolbar } from "@/components/graph/GraphToolbar"
import { NodeProperties } from "@/components/graph/NodeProperties"
import { FilterPanel } from "@/components/graph/FilterPanel"
import { Breadcrumbs } from "@/components/graph/Breadcrumbs"
import { TransactionSelector } from "@/components/graph/TransactionSelector"
import { SearchDialog } from "@/components/search/SearchDialog"
import { CodeViewer } from "@/components/code/CodeViewer"
import { ImpactPanel, applyImpactOverlay, clearImpactOverlay } from "@/components/analysis/ImpactPanel"
import { PathFinderPanel, applyPathOverlay, clearPathOverlay } from "@/components/analysis/PathFinderPanel"
import { applyCommunityColors, clearCommunityColors } from "@/components/analysis/CommunityToggle"
import { CircularDepsPanel, highlightCycle, clearCycleHighlight } from "@/components/analysis/CircularDepsPanel"
import { DeadCodePanel } from "@/components/analysis/DeadCodePanel"
import { TraceRouteModal } from "@/components/analysis/TraceRouteModal"
import type { TraceRouteNode } from "@/components/analysis/TraceRouteModal"
import { useGraph } from "@/hooks/useGraph"
import { useTransactions } from "@/hooks/useTransactions"
import { useImpactAnalysis } from "@/hooks/useImpactAnalysis"
import { usePathFinder } from "@/hooks/usePathFinder"
import { useAnalysisData } from "@/hooks/useAnalysisData"
import type { ViewMode } from "@/lib/types"

const LAYOUT_CONFIGS: Record<ViewMode, cytoscape.LayoutOptions> = {
  architecture: {
    name: "dagre",
    rankDir: "TB",
    nodeSep: 50,
    rankSep: 80,
    fit: true,
    animate: true,
  } as cytoscape.LayoutOptions,
  dependency: {
    name: "fcose",
    quality: "default",
    randomize: true,
    animate: true,
    animationDuration: 500,
    nodeRepulsion: 4500,
    idealEdgeLength: 100,
    fit: true,
  } as cytoscape.LayoutOptions,
  transaction: {
    name: "dagre",
    rankDir: "LR",
    nodeSep: 30,
    rankSep: 60,
    fit: true,
    animate: true,
  } as cytoscape.LayoutOptions,
}

export default function GraphPage() {
  const params = useParams<{ id: string }>()
  const projectId = params.id

  const {
    elements,
    isLoading,
    error,
    drilldownPath,
    performanceTier,
    layoutMode,
    loadModules,
    drillIntoModule,
    drillIntoClass,
    drillUp,
  } = useGraph()

  const {
    transactions,
    selectedFqn: selectedTxnFqn,
    transactionElements,
    isLoading: txnLoading,
    error: txnError,
    loadTransactions,
    selectTransaction,
    clearSelection: clearTxnSelection,
  } = useTransactions()

  const [viewMode, setViewMode] = useState<ViewMode>("architecture")
  const [selectedNode, setSelectedNode] = useState<Record<
    string,
    unknown
  > | null>(null)
  const [showFilterPanel, setShowFilterPanel] = useState(false)
  const [cyInstance, setCyInstance] = useState<cytoscape.Core | null>(null)
  const [codeViewerOpen, setCodeViewerOpen] = useState(false)
  const [codeViewerFile, setCodeViewerFile] = useState<string>("")
  const [codeViewerLine, setCodeViewerLine] = useState<number>(1)
  const [activeAnalysis, setActiveAnalysis] = useState<"impact" | "path" | "circularDeps" | "deadCode" | null>(null)
  const [impactDirection, setImpactDirection] = useState<"downstream" | "upstream" | "both">("downstream")
  const [pathFromFqn, setPathFromFqn] = useState<string>("")
  const [communityColorsEnabled, setCommunityColorsEnabled] = useState(false)
  const [circularDepsLevel, setCircularDepsLevel] = useState<"module" | "class">("module")
  const [deadCodeType, setDeadCodeType] = useState<"function" | "class">("function")
  const [traceRouteOpen, setTraceRouteOpen] = useState(false)
  const [traceRouteNode, setTraceRouteNode] = useState<TraceRouteNode | null>(null)
  const [contextMenu, setContextMenu] = useState<{
    fqn: string
    x: number
    y: number
  } | null>(null)

  const cyInstanceRef = useRef<cytoscape.Core | null>(null)

  const impact = useImpactAnalysis()
  const pathFinder = usePathFinder()
  const analysisData = useAnalysisData()

  // Load modules on mount
  useEffect(() => {
    if (projectId) {
      loadModules(projectId)
    }
  }, [projectId, loadModules])

  // Load transactions when switching to transaction view
  useEffect(() => {
    if (viewMode === "transaction" && transactions.length === 0) {
      loadTransactions(projectId)
    }
    if (viewMode !== "transaction") {
      clearTxnSelection()
    }
  }, [viewMode, projectId, transactions.length, loadTransactions, clearTxnSelection])

  // Store cy instance
  const handleCyInit = useCallback((cy: cytoscape.Core) => {
    cyInstanceRef.current = cy
    setCyInstance(cy)
  }, [])

  // Node selection
  const handleNodeSelect = useCallback((nodeData: Record<string, unknown>) => {
    if (Object.keys(nodeData).length === 0) {
      setSelectedNode(null)
    } else {
      setSelectedNode(nodeData)
    }
  }, [])

  // Drill-down (disabled in transaction mode)
  const handleNodeDrillDown = useCallback(
    (fqn: string, name: string, level: string) => {
      if (viewMode === "transaction") return
      if (level === "module") {
        drillIntoModule(projectId, fqn, name)
      } else if (level === "class") {
        drillIntoClass(projectId, fqn, name)
      }
    },
    [projectId, viewMode, drillIntoModule, drillIntoClass]
  )

  // Drill-up
  const handleDrillUp = useCallback(() => {
    drillUp(projectId)
  }, [projectId, drillUp])

  // Search navigate — center on node in graph
  const handleSearchNavigate = useCallback((fqn: string) => {
    const cy = cyInstanceRef.current
    if (!cy) return
    const node = cy.getElementById(fqn)
    if (node.length > 0) {
      cy.nodes().unselect()
      node.select()
      cy.animate({
        center: { eles: node },
        zoom: cy.zoom(),
        duration: 300,
      })
      setSelectedNode(node.data())
    }
  }, [])

  // Zoom controls
  const handleZoomIn = useCallback(() => {
    const cy = cyInstanceRef.current
    if (cy) cy.zoom(cy.zoom() * 1.3)
  }, [])

  const handleZoomOut = useCallback(() => {
    const cy = cyInstanceRef.current
    if (cy) cy.zoom(cy.zoom() / 1.3)
  }, [])

  const handleFitToScreen = useCallback(() => {
    const cy = cyInstanceRef.current
    if (cy) cy.fit(undefined, 40)
  }, [])

  // Layout refresh
  const handleRefreshLayout = useCallback(() => {
    const cy = cyInstanceRef.current
    if (!cy) return
    const config = { ...LAYOUT_CONFIGS[viewMode] }
    if (performanceTier !== "full") {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(config as Record<string, any>).animate = false
    }
    try {
      cy.layout(config).run()
    } catch {
      // Layout may fail with 0 nodes
    }
  }, [viewMode, performanceTier])

  // Code viewer
  const handleViewSource = useCallback(
    (file: string, line: number) => {
      setCodeViewerFile(file)
      setCodeViewerLine(line)
      setCodeViewerOpen(true)
      // Load callees for the currently selected node
      if (selectedNode?.fqn) {
        analysisData.loadNodeDetails(projectId, selectedNode.fqn as string)
      }
    },
    [selectedNode, projectId, analysisData],
  )

  const handleCloseCodeViewer = useCallback(() => {
    setCodeViewerOpen(false)
  }, [])

  const handleNavigateToNode = useCallback((fqn: string) => {
    setCodeViewerOpen(false)
    const cy = cyInstanceRef.current
    if (!cy) return
    const node = cy.getElementById(fqn)
    if (node?.length) {
      node.select()
      cy.animate({ center: { eles: node }, duration: 300 })
    }
  }, [])

  // ─── Impact analysis handlers ───────────────────────────────────────────
  const handleShowImpact = useCallback(
    (fqn: string) => {
      setActiveAnalysis("impact")
      impact.analyze(projectId, fqn, impactDirection)
    },
    [projectId, impactDirection, impact],
  )

  const handleImpactDirectionChange = useCallback(
    (dir: "downstream" | "upstream" | "both") => {
      setImpactDirection(dir)
      if (impact.data) {
        impact.analyze(projectId, impact.data.node, dir)
      }
    },
    [projectId, impact],
  )

  const handleCloseImpact = useCallback(() => {
    setActiveAnalysis(null)
    impact.clear()
    const cy = cyInstanceRef.current
    if (cy) clearImpactOverlay(cy)
  }, [impact])

  // ─── Path finder handlers ─────────────────────────────────────────────
  const handleStartPathFrom = useCallback((fqn: string) => {
    setActiveAnalysis("path")
    setPathFromFqn(fqn)
  }, [])

  const handleFindPath = useCallback(
    (fromFqn: string, toFqn: string) => {
      pathFinder.findPath(projectId, fromFqn, toFqn)
    },
    [projectId, pathFinder],
  )

  const handleClosePath = useCallback(() => {
    setActiveAnalysis(null)
    setPathFromFqn("")
    pathFinder.clear()
    const cy = cyInstanceRef.current
    if (cy) clearPathOverlay(cy)
  }, [pathFinder])

  // ─── Community colors handlers ─────────────────────────────────────────
  const handleToggleCommunityColors = useCallback(() => {
    const cy = cyInstanceRef.current
    if (!cy) return
    if (communityColorsEnabled) {
      clearCommunityColors(cy)
      setCommunityColorsEnabled(false)
    } else {
      if (!analysisData.communities) {
        analysisData.loadCommunities(projectId)
      }
      setCommunityColorsEnabled(true)
      // Colors will be applied by the useEffect when data arrives
    }
  }, [communityColorsEnabled, projectId, analysisData])

  // Apply community colors once data is loaded and toggle is enabled
  useEffect(() => {
    const cy = cyInstanceRef.current
    if (!cy) return
    if (communityColorsEnabled && analysisData.communities) {
      // Write communityId to node data from API response
      analysisData.communities.communities.forEach((comm) => {
        comm.members.forEach((fqn) => {
          const node = cy.getElementById(fqn)
          if (node.length) {
            node.data("communityId", comm.community_id)
          }
        })
      })
      applyCommunityColors(cy)
    }
  }, [communityColorsEnabled, analysisData.communities])

  // ─── Circular dependencies handlers ────────────────────────────────────
  const handleShowCircularDeps = useCallback(() => {
    setActiveAnalysis("circularDeps")
    analysisData.loadCircularDeps(projectId, circularDepsLevel)
  }, [projectId, circularDepsLevel, analysisData])

  const handleCircularDepsLevelChange = useCallback(
    (level: "module" | "class") => {
      setCircularDepsLevel(level)
      analysisData.loadCircularDeps(projectId, level)
    },
    [projectId, analysisData],
  )

  const handleHighlightCycle = useCallback((cycleFqns: string[]) => {
    const cy = cyInstanceRef.current
    if (cy) highlightCycle(cy, cycleFqns)
  }, [])

  const handleCloseCircularDeps = useCallback(() => {
    setActiveAnalysis(null)
    const cy = cyInstanceRef.current
    if (cy) clearCycleHighlight(cy)
  }, [])

  // ─── Dead code handlers ────────────────────────────────────────────────
  const handleShowDeadCode = useCallback(() => {
    setActiveAnalysis("deadCode")
    analysisData.loadDeadCode(projectId, deadCodeType)
  }, [projectId, deadCodeType, analysisData])

  const handleDeadCodeTypeChange = useCallback(
    (type: "function" | "class") => {
      setDeadCodeType(type)
      analysisData.loadDeadCode(projectId, type)
    },
    [projectId, analysisData],
  )

  const handleDeadCodeNavigate = useCallback(
    (fqn: string) => {
      handleSearchNavigate(fqn)
      // Also open code viewer if the candidate has path info
      const candidate = analysisData.deadCode?.candidates.find(
        (c) => c.fqn === fqn,
      )
      if (candidate?.path) {
        setCodeViewerFile(candidate.path)
        setCodeViewerLine(candidate.line ?? 1)
        setCodeViewerOpen(true)
      }
    },
    [handleSearchNavigate, analysisData.deadCode],
  )

  const handleCloseDeadCode = useCallback(() => {
    setActiveAnalysis(null)
  }, [])

  // ─── Trace Route handlers ──────────────────────────────────────────────
  const handleTraceRoute = useCallback(
    (fqn: string) => {
      const cy = cyInstanceRef.current
      const cyNode = cy?.getElementById(fqn)
      const data = cyNode?.data() ?? {} as Record<string, unknown>
      const node: TraceRouteNode = {
        fqn,
        name: typeof data.label === "string" ? data.label : fqn,
        kind: typeof data.kind === "string" ? data.kind : "",
        language: typeof data.language === "string" ? data.language : null,
      }
      setTraceRouteNode(node)
      setTraceRouteOpen(true)
      setContextMenu(null)
    },
    [],
  )

  const handleNodeRightClick = useCallback(
    (fqn: string, position: { x: number; y: number }) => {
      const MENU_WIDTH = 160
      const MENU_HEIGHT = 120
      const x = Math.min(position.x, window.innerWidth - MENU_WIDTH)
      const y = Math.min(position.y, window.innerHeight - MENU_HEIGHT)
      setContextMenu({ fqn, x, y })
    },
    [],
  )

  const handleContextMenuClose = useCallback(() => {
    setContextMenu(null)
  }, [])

  // Dismiss context menu on Escape key
  useEffect(() => {
    if (!contextMenu) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleContextMenuClose()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [contextMenu, handleContextMenuClose])

  // ─── Apply overlays when data changes ─────────────────────────────────
  useEffect(() => {
    const cy = cyInstanceRef.current
    if (!cy) return
    if (activeAnalysis === "impact" && impact.data) {
      clearImpactOverlay(cy)
      applyImpactOverlay(cy, impact.data.affected, impact.data.node)
    }
  }, [activeAnalysis, impact.data])

  useEffect(() => {
    const cy = cyInstanceRef.current
    if (!cy) return
    if (activeAnalysis === "path" && pathFinder.data) {
      clearPathOverlay(cy)
      applyPathOverlay(cy, pathFinder.data)
    }
  }, [activeAnalysis, pathFinder.data])

  // Retry handler — respects current view mode
  const handleRetry = useCallback(() => {
    if (viewMode === "transaction") {
      loadTransactions(projectId)
    } else {
      loadModules(projectId)
    }
  }, [viewMode, projectId, loadModules, loadTransactions])

  // Determine which elements and loading/error to show
  const isTransactionView = viewMode === "transaction"
  const activeElements = isTransactionView ? transactionElements : elements
  const activeLoading = isTransactionView ? txnLoading : isLoading
  const activeError = isTransactionView ? txnError : error

  return (
    <div className="flex h-screen flex-col">
      <GraphToolbar
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        onZoomIn={handleZoomIn}
        onZoomOut={handleZoomOut}
        onFitToScreen={handleFitToScreen}
        onRefreshLayout={handleRefreshLayout}
        isLoading={activeLoading}
        cy={cyInstance}
        communityColorsEnabled={communityColorsEnabled}
        onToggleCommunityColors={handleToggleCommunityColors}
        onShowCircularDeps={handleShowCircularDeps}
        onShowDeadCode={handleShowDeadCode}
      />

      {/* Sub-toolbar: filter toggle + transaction selector or breadcrumbs */}
      <div className="flex items-center gap-2 border-b bg-background px-3 py-1">
        <Button
          variant={showFilterPanel ? "secondary" : "ghost"}
          size="sm"
          className="size-7 p-0"
          onClick={() => setShowFilterPanel((v) => !v)}
          title="Toggle filters"
        >
          <Filter className="size-4" />
        </Button>

        <div className="mx-1 h-4 w-px bg-border" />

        {isTransactionView ? (
          <>
            <TransactionSelector
              transactions={transactions}
              selectedFqn={selectedTxnFqn}
              isLoading={txnLoading}
              onSelect={(fqn) => selectTransaction(projectId, fqn)}
            />
            {txnError ? (
              <span className="text-xs text-destructive">{txnError}</span>
            ) : null}
          </>
        ) : (
          <Breadcrumbs
            path={drilldownPath}
            onNavigateHome={handleDrillUp}
          />
        )}
      </div>

      {/* Search dialog — floating, triggered by Cmd+K */}
      <SearchDialog
        projectId={projectId}
        onNavigate={handleSearchNavigate}
      />

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {/* Left filter panel */}
        {showFilterPanel ? (
          <div className="w-56 shrink-0 border-r bg-background">
            <FilterPanel cy={cyInstance} elementKey={activeElements.length} />
          </div>
        ) : null}

        {/* Graph canvas */}
        <div className="flex-1">
          {activeError ? (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <p className="text-sm text-destructive">{activeError}</p>
                <button
                  className="mt-2 text-xs text-muted-foreground underline"
                  onClick={handleRetry}
                >
                  Retry
                </button>
              </div>
            </div>
          ) : isTransactionView && !selectedTxnFqn && !txnLoading ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              Select a transaction above to view its call flow
            </div>
          ) : activeElements.length === 0 && !activeLoading ? (
            <div className="flex h-full items-center justify-center">
              <p className="text-sm text-muted-foreground">
                No graph data found. Run an analysis first.
              </p>
            </div>
          ) : (
            <GraphView
              elements={activeElements}
              viewMode={viewMode}
              performanceTier={performanceTier}
              layoutMode={isTransactionView ? "full" : layoutMode}
              colorBy="kind"
              onNodeSelect={handleNodeSelect}
              onNodeDrillDown={handleNodeDrillDown}
              onCyInit={handleCyInit}
              onNodeRightClick={handleNodeRightClick}
            />
          )}

          {/* Loading overlay */}
          {activeLoading ? (
            <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/50">
              <div className="flex items-center gap-2 rounded-md bg-background px-4 py-2 shadow-md">
                <RefreshCw className="size-4 animate-spin text-muted-foreground" />
                <span className="text-sm text-muted-foreground">
                  {isTransactionView ? "Loading transaction..." : "Loading graph data..."}
                </span>
              </div>
            </div>
          ) : null}
        </div>

        {/* Right: Analysis / Node properties panel */}
        <div className="w-72 shrink-0 overflow-x-hidden overflow-y-auto border-l bg-background">
          {activeAnalysis === "impact" ? (
            <ImpactPanel
              data={impact.data}
              isLoading={impact.isLoading}
              error={impact.error}
              direction={impactDirection}
              onDirectionChange={handleImpactDirectionChange}
              onClose={handleCloseImpact}
              onNodeClick={handleSearchNavigate}
            />
          ) : activeAnalysis === "path" ? (
            <PathFinderPanel
              data={pathFinder.data}
              isLoading={pathFinder.isLoading}
              error={pathFinder.error}
              initialFromFqn={pathFromFqn}
              onFindPath={handleFindPath}
              onClose={handleClosePath}
              onNodeClick={handleSearchNavigate}
            />
          ) : activeAnalysis === "circularDeps" ? (
            <CircularDepsPanel
              data={analysisData.circularDeps}
              isLoading={analysisData.isLoading}
              error={analysisData.error}
              level={circularDepsLevel}
              onLevelChange={handleCircularDepsLevelChange}
              onHighlightCycle={handleHighlightCycle}
              onClose={handleCloseCircularDeps}
            />
          ) : activeAnalysis === "deadCode" ? (
            <DeadCodePanel
              data={analysisData.deadCode}
              isLoading={analysisData.isLoading}
              error={analysisData.error}
              typeFilter={deadCodeType}
              onTypeChange={handleDeadCodeTypeChange}
              onNavigate={handleDeadCodeNavigate}
              onClose={handleCloseDeadCode}
            />
          ) : (
            <NodeProperties
              node={selectedNode}
              onClose={() => setSelectedNode(null)}
              onViewSource={handleViewSource}
              onShowImpact={handleShowImpact}
              onStartPathFrom={handleStartPathFrom}
              onTraceRoute={handleTraceRoute}
            />
          )}
        </div>
      </div>

      {codeViewerOpen && codeViewerFile && (
        <CodeViewer
          projectId={projectId}
          file={codeViewerFile}
          line={codeViewerLine}
          onClose={handleCloseCodeViewer}
          callees={analysisData.nodeDetails?.callees?.map((c) => ({
            fqn: c.fqn,
            name: c.name,
          }))}
          onNavigateToNode={handleNavigateToNode}
        />
      )}

      {/* Trace Route modal */}
      <TraceRouteModal
        open={traceRouteOpen}
        onClose={() => setTraceRouteOpen(false)}
        node={traceRouteNode}
        projectId={projectId}
      />

      {/* Right-click context menu */}
      {contextMenu && (
        <>
          {/* Invisible backdrop to dismiss on outside click */}
          <div
            className="fixed inset-0 z-40"
            onClick={handleContextMenuClose}
          />
          <div
            className="fixed z-50 min-w-[160px] rounded-md border bg-background shadow-md"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <div className="py-1">
              <button
                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
                onClick={() => handleTraceRoute(contextMenu.fqn)}
              >
                <GitBranch className="size-3.5 text-blue-500" />
                Trace Route
              </button>
              <button
                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
                onClick={() => {
                  handleShowImpact(contextMenu.fqn)
                  handleContextMenuClose()
                }}
              >
                <Activity className="size-3.5 text-red-500" />
                Show Impact
              </button>
              <button
                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
                onClick={() => {
                  handleStartPathFrom(contextMenu.fqn)
                  handleContextMenuClose()
                }}
              >
                <Route className="size-3.5 text-blue-500" />
                Find Path From Here
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
