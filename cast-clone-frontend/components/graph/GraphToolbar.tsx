"use client"

import React from "react"
import {
  Layers,
  Network,
  ArrowRight,
  ZoomIn,
  ZoomOut,
  Maximize,
  RefreshCw,
  RefreshCcw,
  Trash2,
  Save,
} from "lucide-react"

import type cytoscape from "cytoscape"

import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { ViewMode } from "@/lib/types"
import { CommunityToggle } from "@/components/analysis/CommunityToggle"
import { ExportButtons } from "./ExportButtons"
import { ExportMenu } from "@/components/export/ExportMenu"

interface GraphToolbarProps {
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
  onZoomIn: () => void
  onZoomOut: () => void
  onFitToScreen: () => void
  onRefreshLayout: () => void
  isLoading: boolean
  cy: cytoscape.Core | null
  communityColorsEnabled?: boolean
  onToggleCommunityColors?: () => void
  onShowCircularDeps?: () => void
  onShowDeadCode?: () => void
  onSaveView?: () => void
  projectId?: string
  selectedNodeFqn?: string
}

const VIEW_TABS: { mode: ViewMode; label: string; icon: React.ReactNode }[] = [
  {
    mode: "architecture",
    label: "Architecture",
    icon: <Layers className="size-3.5" />,
  },
  {
    mode: "dependency",
    label: "Dependency",
    icon: <Network className="size-3.5" />,
  },
  {
    mode: "transaction",
    label: "Transaction",
    icon: <ArrowRight className="size-3.5" />,
  },
]

export function GraphToolbar({
  viewMode,
  onViewModeChange,
  onZoomIn,
  onZoomOut,
  onFitToScreen,
  onRefreshLayout,
  isLoading,
  cy,
  communityColorsEnabled,
  onToggleCommunityColors,
  onShowCircularDeps,
  onShowDeadCode,
  onSaveView,
  projectId,
  selectedNodeFqn,
}: GraphToolbarProps) {
  return (
    <div className="flex items-center justify-between border-b bg-background px-3 py-1.5">
      {/* Left: View switcher */}
      <div className="flex items-center gap-1">
        {VIEW_TABS.map((tab) => (
          <Button
            key={tab.mode}
            variant={viewMode === tab.mode ? "secondary" : "ghost"}
            size="sm"
            onClick={() => onViewModeChange(tab.mode)}
            disabled={isLoading}
          >
            {tab.icon}
            <span className="ml-1">{tab.label}</span>
          </Button>
        ))}
      </div>

      {/* Right: Zoom + layout controls */}
      <div className="flex items-center gap-0.5">
        <Button
          variant="ghost"
          size="sm"
          className="size-7 p-0"
          onClick={onZoomIn}
          title="Zoom in"
        >
          <ZoomIn className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="size-7 p-0"
          onClick={onZoomOut}
          title="Zoom out"
        >
          <ZoomOut className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="size-7 p-0"
          onClick={onFitToScreen}
          title="Fit to screen"
        >
          <Maximize className="size-4" />
        </Button>
        <div className="mx-1 h-4 w-px bg-border" />
        <Button
          variant="ghost"
          size="sm"
          className="size-7 p-0"
          onClick={onRefreshLayout}
          title="Re-run layout"
          disabled={isLoading}
        >
          <RefreshCw className={`size-4 ${isLoading ? "animate-spin" : ""}`} />
        </Button>
        <div className="mx-1 h-4 w-px bg-border" />
        <ExportButtons cy={cy} />
        {projectId && (
          <ExportMenu projectId={projectId} selectedNodeFqn={selectedNodeFqn} />
        )}

        {onSaveView && (
          <>
            <div className="mx-1 h-4 w-px bg-border" />
            <Button
              variant="ghost"
              size="sm"
              onClick={onSaveView}
              title="Save current view"
              className="gap-1"
            >
              <Save className="h-4 w-4" />
              <span className="hidden sm:inline text-xs">Save</span>
            </Button>
          </>
        )}

        {/* Analysis tools separator + buttons */}
        <div className="mx-1 h-4 w-px bg-border" />

        {onToggleCommunityColors && (
          <CommunityToggle
            enabled={communityColorsEnabled ?? false}
            onToggle={onToggleCommunityColors}
          />
        )}

        {onShowCircularDeps && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="size-7 p-0"
                  onClick={onShowCircularDeps}
                  aria-label="Show circular dependencies"
                >
                  <RefreshCcw className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Circular dependencies</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}

        {onShowDeadCode && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="size-7 p-0"
                  onClick={onShowDeadCode}
                  aria-label="Show dead code"
                >
                  <Trash2 className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Dead code candidates</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
    </div>
  )
}
