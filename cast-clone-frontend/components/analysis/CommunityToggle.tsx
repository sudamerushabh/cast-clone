"use client"

import * as React from "react"
import type cytoscape from "cytoscape"
import { Palette } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

// ─── 15-color palette for community coloring ─────────────────────────────────

export const COMMUNITY_PALETTE: string[] = [
  "#3b82f6", // blue
  "#ef4444", // red
  "#22c55e", // green
  "#f59e0b", // amber
  "#8b5cf6", // violet
  "#ec4899", // pink
  "#14b8a6", // teal
  "#f97316", // orange
  "#6366f1", // indigo
  "#84cc16", // lime
  "#06b6d4", // cyan
  "#e11d48", // rose
  "#a855f7", // purple
  "#0ea5e9", // sky
  "#d946ef", // fuchsia
]

// ─── Overlay functions ──────────────────────────────────────────────────────

export function applyCommunityColors(cy: cytoscape.Core): void {
  cy.nodes().forEach((node) => {
    const communityId = node.data("communityId") as number | undefined
    if (communityId !== undefined && communityId !== null) {
      const color = COMMUNITY_PALETTE[communityId % COMMUNITY_PALETTE.length]
      node.style("background-color", color)
    }
  })
}

export function clearCommunityColors(cy: cytoscape.Core): void {
  cy.nodes().removeStyle("background-color")
}

// ─── Component ──────────────────────────────────────────────────────────────

interface CommunityToggleProps {
  enabled: boolean
  onToggle: () => void
}

export function CommunityToggle({ enabled, onToggle }: CommunityToggleProps) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant={enabled ? "secondary" : "ghost"}
            size="sm"
            className="size-7 p-0"
            onClick={onToggle}
            aria-label="Toggle community colors"
          >
            <Palette className="size-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{enabled ? "Hide" : "Show"} community colors</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
