// cast-clone-frontend/components/analysis/TraceRouteModal.tsx
"use client"

import * as React from "react"
import { useEffect } from "react"
import { GitBranch } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useTraceRoute } from "@/hooks/useTraceRoute"
import type { AffectedNode } from "@/lib/types"

// ─── Depth badge ─────────────────────────────────────────────────────────────

const DEPTH_BADGE_CLASSES: Record<number, string> = {
  1: "bg-red-500 text-white",
  2: "bg-orange-500 text-white",
  3: "bg-yellow-500 text-black",
  4: "bg-yellow-300 text-black",
  5: "bg-yellow-100 text-black",
}

function depthBadgeClass(depth: number): string {
  return DEPTH_BADGE_CLASSES[depth] ?? DEPTH_BADGE_CLASSES[5]
}

// ─── Kind badge ──────────────────────────────────────────────────────────────

const KIND_COLORS: Record<string, string> = {
  CLASS: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  INTERFACE: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  FUNCTION: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  TABLE: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  API_ENDPOINT: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  MODULE: "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200",
  ENUM: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
}

function kindBadgeClass(kind: string): string {
  return KIND_COLORS[kind] ?? "bg-muted text-muted-foreground"
}

// ─── Node row ────────────────────────────────────────────────────────────────

function NodeRow({ node }: { node: AffectedNode }) {
  return (
    <div className="flex items-center gap-2 rounded-md px-2 py-1.5">
      <Badge
        className={`shrink-0 text-[10px] px-1.5 py-0 ${depthBadgeClass(node.depth)}`}
      >
        {node.depth}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="break-all text-xs font-medium">{node.name}</p>
        <p
          className="break-all text-[10px] text-muted-foreground"
          title={node.fqn}
        >
          {node.fqn}
        </p>
      </div>
      <Badge className={`shrink-0 text-[10px] px-1.5 py-0 ${kindBadgeClass(node.type)}`}>
        {node.type}
      </Badge>
    </div>
  )
}

// ─── Section ─────────────────────────────────────────────────────────────────

function Section({
  title,
  count,
  nodes,
  isLoading,
  emptyMessage,
}: {
  title: string
  count: number
  nodes: AffectedNode[]
  isLoading: boolean
  emptyMessage: string
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </span>
        {!isLoading && (
          <Badge variant="outline" className="text-[10px]">
            {count}
          </Badge>
        )}
      </div>
      {isLoading ? (
        <p className="py-4 text-center text-xs text-muted-foreground">
          Loading...
        </p>
      ) : nodes.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted-foreground">
          {emptyMessage}
        </p>
      ) : (
        <div className="space-y-0.5">
          {nodes.map((node) => (
            <NodeRow key={node.fqn} node={node} />
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Props ───────────────────────────────────────────────────────────────────

export interface TraceRouteNode {
  fqn: string
  name: string
  kind: string
  language?: string | null
}

interface TraceRouteModalProps {
  open: boolean
  onClose: () => void
  node: TraceRouteNode | null
  projectId: string
}

// ─── Modal ───────────────────────────────────────────────────────────────────

export function TraceRouteModal({
  open,
  onClose,
  node,
  projectId,
}: TraceRouteModalProps) {
  const { upstreamData, downstreamData, isLoading, error, fetchTrace, clear } =
    useTraceRoute()

  // Fetch when modal opens
  useEffect(() => {
    if (open && node) {
      fetchTrace(projectId, node.fqn)
    }
    if (!open) {
      clear()
    }
  }, [open, node, projectId, fetchTrace, clear])

  const upstreamNodes = upstreamData?.affected ?? []
  const downstreamNodes = downstreamData?.affected ?? []

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose() }}>
      <DialogContent className="flex max-h-[80vh] w-full max-w-2xl flex-col gap-0 p-0">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle className="flex items-center gap-2 text-base">
            <GitBranch className="size-4 text-blue-500" />
            Trace Route
          </DialogTitle>
          {node && (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="break-all text-sm font-medium">{node.name}</span>
              {node.kind && (
                <Badge className={`text-[10px] ${kindBadgeClass(node.kind)}`}>
                  {node.kind}
                </Badge>
              )}
              {node.language && (
                <Badge variant="outline" className="text-[10px]">
                  {node.language}
                </Badge>
              )}
            </div>
          )}
        </DialogHeader>

        {error ? (
          <div className="px-6 py-8 text-center text-sm text-destructive">
            {error}
          </div>
        ) : (
          <ScrollArea className="flex-1 overflow-hidden">
            <div className="space-y-0 px-6 py-4">
              {/* Upstream callers */}
              <Section
                title="Upstream Callers"
                count={upstreamNodes.length}
                nodes={upstreamNodes}
                isLoading={isLoading}
                emptyMessage="No callers found"
              />

              <Separator className="my-4" />

              {/* This node */}
              <div className="flex items-center gap-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 dark:border-blue-800 dark:bg-blue-950">
                <GitBranch className="size-3.5 shrink-0 text-blue-500" />
                <div className="min-w-0 flex-1">
                  <p className="break-all text-xs font-semibold">
                    {node?.name ?? ""}
                  </p>
                  <p
                    className="break-all text-[10px] text-muted-foreground"
                    title={node?.fqn ?? ""}
                  >
                    {node?.fqn ?? ""}
                  </p>
                </div>
                <Badge variant="outline" className="shrink-0 text-[10px]">
                  this node
                </Badge>
              </div>

              <Separator className="my-4" />

              {/* Downstream callees */}
              <Section
                title="Downstream Callees"
                count={downstreamNodes.length}
                nodes={downstreamNodes}
                isLoading={isLoading}
                emptyMessage="No callees found"
              />
            </div>
          </ScrollArea>
        )}
      </DialogContent>
    </Dialog>
  )
}
