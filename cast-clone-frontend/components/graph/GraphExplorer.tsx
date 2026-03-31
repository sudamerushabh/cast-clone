"use client"

import React, { useCallback, useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import type cytoscape from "cytoscape"
import { Activity, Bot, Filter, GitBranch, RefreshCw, Route } from "lucide-react"

import { Button } from "@/components/ui/button"

import { GraphView } from "@/components/graph/GraphView"
import { GraphToolbar } from "@/components/graph/GraphToolbar"
import { NodeProperties } from "@/components/graph/NodeProperties"
import { FilterPanel } from "@/components/graph/FilterPanel"
import { Breadcrumbs } from "@/components/graph/Breadcrumbs"
import { TransactionSelector } from "@/components/graph/TransactionSelector"
import { SearchDialog } from "@/components/search/SearchDialog"
import { GraphSearchBar } from "@/components/search/GraphSearchBar"
import { CodeViewer } from "@/components/code/CodeViewer"
import { ImpactPanel, applyImpactOverlay, clearImpactOverlay } from "@/components/analysis/ImpactPanel"
import { PathFinderPanel, applyPathOverlay, clearPathOverlay } from "@/components/analysis/PathFinderPanel"
import { applyCommunityColors, clearCommunityColors } from "@/components/analysis/CommunityToggle"
import { CircularDepsPanel, highlightCycle, clearCycleHighlight } from "@/components/analysis/CircularDepsPanel"
import { DeadCodePanel } from "@/components/analysis/DeadCodePanel"
import { TraceRouteModal } from "@/components/analysis/TraceRouteModal"
import type { TraceRouteNode } from "@/components/analysis/TraceRouteModal"
import { PathGraphModal } from "@/components/analysis/PathGraphModal"
import { useGraph } from "@/hooks/useGraph"
import { useTransactions } from "@/hooks/useTransactions"
import { useImpactAnalysis } from "@/hooks/useImpactAnalysis"
import { usePathFinder } from "@/hooks/usePathFinder"
import { useAnalysisData } from "@/hooks/useAnalysisData"
import { useSavedViews } from "@/hooks/useSavedViews"
import { SaveViewModal } from "@/components/views/SaveViewModal"
import { useChatContextSafe } from "@/components/chat/ChatProvider"
import type { ViewMode, PathFinderResponse, GraphSearchHit } from "@/lib/types"
import { getNodeAncestry } from "@/lib/api"

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

interface GraphExplorerProps {
  projectId: string
  defaultViewMode?: ViewMode
}

export function GraphExplorer({ projectId, defaultViewMode = "architecture" }: GraphExplorerProps) {
  const {
    elements,
    isLoading,
    error,
    drilldownPath,
    performanceTier,
    layoutMode,
    loadArchitecture,
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

  const [viewMode, setViewMode] = useState<ViewMode>(defaultViewMode)
  const [selectedNode, setSelectedNode] = useState<Record<
    string,
    unknown
  > | null>(null)
  const [showFilterPanel, setShowFilterPanel] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const graphContainerRef = useRef<HTMLDivElement>(null)
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
  const [pathGraphOpen, setPathGraphOpen] = useState(false)
  const [pathGraphData, setPathGraphData] = useState<PathFinderResponse | null>(null)
  const [contextMenu, setContextMenu] = useState<{
    fqn: string
    x: number
    y: number
  } | null>(null)

  const cyInstanceRef = useRef<cytoscape.Core | null>(null)

  const impact = useImpactAnalysis()
  const pathFinder = usePathFinder()
  const analysisData = useAnalysisData()
  const savedViews = useSavedViews()
  const chat = useChatContextSafe()
  const [showSaveViewModal, setShowSaveViewModal] = useState(false)

  // Keep ChatProvider informed about the current graph view + selected node
  useEffect(() => {
    const level = drilldownPath.length === 0 ? "module" : drilldownPath.length === 1 ? "class" : "method"
    chat?.setViewInfo(viewMode, level)
  }, [viewMode, drilldownPath.length, chat]) // eslint-disable-line react-hooks/exhaustive-deps

  // Load data based on view mode
  useEffect(() => {
    if (!projectId) return
    if (viewMode === "architecture") {
      loadArchitecture(projectId)
    } else if (viewMode !== "transaction") {
      loadModules(projectId)
    }
  }, [projectId, viewMode, loadArchitecture, loadModules])

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
      chat?.setSelectedNodeFqn(null)
    } else {
      setSelectedNode(nodeData)
      chat?.setSelectedNodeFqn((nodeData.id as string) ?? null)
    }
  }, [chat]) // eslint-disable-line react-hooks/exhaustive-deps

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

  // Search with drill-down: fetch ancestry, expand modules/classes, then focus
  const handleGraphSearchSelect = useCallback(
    async (hit: GraphSearchHit) => {
      // If already visible in the graph, just navigate to it
      const cy = cyInstanceRef.current
      if (cy) {
        const existing = cy.getElementById(hit.fqn)
        if (existing.length > 0) {
          cy.nodes().unselect()
          existing.select()
          cy.animate({ center: { eles: existing }, zoom: cy.zoom(), duration: 300 })
          setSelectedNode(existing.data())
          return
        }
      }

      // Switch to dependency view for drill-down (architecture view uses different structure)
      if (viewMode === "architecture" || viewMode === "transaction") {
        setViewMode("dependency")
        // Wait for modules to load before proceeding
        await loadModules(projectId)
      }

      try {
        const ancestry = await getNodeAncestry(projectId, hit.fqn)
        const ancestors = ancestry.ancestors

        // Find the module ancestor and drill into it
        const moduleAncestor = ancestors.find((a) => a.kind === "MODULE")
        if (moduleAncestor && hit.kind !== "MODULE") {
          await drillIntoModule(projectId, moduleAncestor.fqn, moduleAncestor.name)

          // If the target is a FUNCTION, also drill into the class
          const classAncestor = ancestors.find(
            (a) => a.kind === "CLASS" || a.kind === "INTERFACE"
          )
          if (classAncestor && hit.kind === "FUNCTION") {
            await drillIntoClass(projectId, classAncestor.fqn, classAncestor.name)
          }
        }

        // Wait a tick for Cytoscape to render the new elements, then navigate
        setTimeout(() => {
          const cy2 = cyInstanceRef.current
          if (!cy2) return
          const node = cy2.getElementById(hit.fqn)
          if (node.length > 0) {
            cy2.nodes().unselect()
            node.select()
            cy2.animate({ center: { eles: node }, zoom: 1.5, duration: 400 })
            setSelectedNode(node.data())
          }
        }, 500)
      } catch {
        // Fallback: just try to navigate to whatever is visible
        handleSearchNavigate(hit.fqn)
      }
    },
    [projectId, viewMode, loadModules, drillIntoModule, drillIntoClass, handleSearchNavigate],
  )

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

  // Fullscreen toggle
  const handleToggleFullscreen = useCallback(() => {
    const el = graphContainerRef.current
    if (!el) return
    if (!document.fullscreenElement) {
      el.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {})
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {})
    }
  }, [])

  // Sync state when user exits fullscreen via Escape
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener("fullscreenchange", handler)
    return () => document.removeEventListener("fullscreenchange", handler)
  }, [])

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

  const handleViewPathGraph = useCallback((data: PathFinderResponse) => {
    setPathGraphData(data)
    setPathGraphOpen(true)
  }, [])

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
    }
  }, [communityColorsEnabled, projectId, analysisData])

  // Apply community colors once data is loaded and toggle is enabled
  useEffect(() => {
    const cy = cyInstanceRef.current
    if (!cy) return
    if (communityColorsEnabled && analysisData.communities) {
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

  // ─── Ask AI about node ─────────────────────────────────────────────────
  const handleAskAI = useCallback(
    (fqn: string) => {
      chat?.setSelectedNodeFqn(fqn)
      chat?.setOpen(true)
      setContextMenu(null)
    },
    [chat],
  )

  const handleNodeRightClick = useCallback(
    (fqn: string, position: { x: number; y: number }) => {
      const MENU_WIDTH = 180
      const MENU_HEIGHT = 160
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
    } else if (viewMode === "architecture") {
      loadArchitecture(projectId)
    } else {
      loadModules(projectId)
    }
  }, [viewMode, projectId, loadArchitecture, loadModules, loadTransactions])

  // Determine which elements and loading/error to show
  const isTransactionView = viewMode === "transaction"
  const activeElements = isTransactionView ? transactionElements : elements
  const activeLoading = isTransactionView ? txnLoading : isLoading
  const activeError = isTransactionView ? txnError : error

  return (
    <div ref={graphContainerRef} className="flex h-full flex-col bg-background">
      {/* Unified toolbar: filter + breadcrumbs (left) | zoom + export + analysis (right) */}
      <div className="flex items-center justify-between border-b bg-background px-3 py-1">
        <div className="flex items-center gap-2">
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

          <GraphSearchBar
            projectId={projectId}
            onSelect={handleGraphSearchSelect}
          />

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

        <GraphToolbar
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
          projectId={projectId}
          selectedNodeFqn={(selectedNode?.fqn as string) ?? undefined}
          onSaveView={() => setShowSaveViewModal(true)}
          isFullscreen={isFullscreen}
          onToggleFullscreen={handleToggleFullscreen}
        />
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
              colorBy={viewMode === "architecture" ? "architecture" : "kind"}
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
              onViewPathGraph={handleViewPathGraph}
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

      {/* Path Graph modal */}
      <PathGraphModal
        open={pathGraphOpen}
        onClose={() => setPathGraphOpen(false)}
        data={pathGraphData}
      />

      {/* Right-click context menu — rendered via portal to escape Cytoscape's stacking context */}
      {contextMenu && typeof document !== "undefined" && createPortal(
        <>
          {/* Invisible backdrop to dismiss on outside click */}
          <div
            className="fixed inset-0 z-[10000]"
            onClick={handleContextMenuClose}
          />
          <div
            className="fixed z-[10001] min-w-[160px] rounded-md border bg-background shadow-md"
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
              <div className="my-1 h-px bg-border" />
              <button
                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
                onClick={() => handleAskAI(contextMenu.fqn)}
              >
                <Bot className="size-3.5 text-violet-500" />
                Ask AI About This
              </button>
            </div>
          </div>
        </>,
        document.body
      )}

      <SaveViewModal
        open={showSaveViewModal}
        onOpenChange={setShowSaveViewModal}
        onSave={async (name, description) => {
          const cy = cyInstanceRef.current
          const state = {
            viewType: viewMode,
            zoom: cy?.zoom() ?? 1,
            pan: cy?.pan() ?? { x: 0, y: 0 },
            visibleNodes: cy?.nodes(":visible").map((n) => n.id()) ?? [],
          }
          await savedViews.save(projectId, name, state, description)
        }}
      />
    </div>
  )
}
