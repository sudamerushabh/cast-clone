"use client"

import * as React from "react"
import {
  Activity,
  Code2,
  FileCode2,
  ArrowDownToLine,
  ArrowUpFromLine,
  GitBranch,
  Route,
  Ruler,
  Gauge,
  X,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { AnnotationList } from "@/components/annotations/AnnotationList"
import { AddAnnotation } from "@/components/annotations/AddAnnotation"
import { TagBadges } from "@/components/annotations/TagBadges"
import type { AnnotationResponse, TagResponse, TagName } from "@/lib/types"

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

interface NodePropertiesProps {
  node: Record<string, unknown> | null
  onClose: () => void
  onViewSource?: (file: string, line: number) => void
  onShowImpact?: (fqn: string) => void
  onStartPathFrom?: (fqn: string) => void
  onTraceRoute?: (fqn: string) => void
  projectId?: string
  annotations?: AnnotationResponse[]
  tags?: TagResponse[]
  onAddAnnotation?: (projectId: string, nodeFqn: string, content: string) => Promise<void>
  onEditAnnotation?: (annotationId: string, content: string) => Promise<void>
  onDeleteAnnotation?: (annotationId: string) => Promise<void>
  onAddTag?: (projectId: string, nodeFqn: string, tagName: TagName) => Promise<void>
  onRemoveTag?: (tagId: string) => Promise<void>
}

function MetricRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType
  label: string
  value: string | number | null | undefined
}) {
  if (value === null || value === undefined) return null
  return (
    <div className="flex items-center justify-between py-1">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className="size-3.5 shrink-0" />
        <span>{label}</span>
      </div>
      <span className="text-sm font-medium tabular-nums">{value}</span>
    </div>
  )
}

export function NodeProperties({
  node,
  onClose,
  onViewSource,
  onShowImpact,
  onStartPathFrom,
  onTraceRoute,
  projectId,
  annotations = [],
  tags = [],
  onAddAnnotation,
  onEditAnnotation,
  onDeleteAnnotation,
  onAddTag,
  onRemoveTag,
}: NodePropertiesProps) {
  if (!node) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center">
        <div className="text-sm text-muted-foreground">
          <Code2 className="mx-auto mb-2 size-8 opacity-40" />
          <p>Select a node to view its properties</p>
        </div>
      </div>
    )
  }

  const name = typeof node.label === "string" ? node.label : String(node.label ?? "")
  const fqn = typeof node.id === "string" ? node.id : ""
  const kind = typeof node.kind === "string" ? node.kind : ""
  const language = typeof node.language === "string" ? node.language : null
  const path = typeof node.path === "string" ? node.path : null
  const line = typeof node.line === "number" ? node.line : null
  const endLine = typeof node.end_line === "number" ? node.end_line : null
  const loc = typeof node.loc === "number" ? node.loc : null
  const complexity = typeof node.complexity === "number" ? node.complexity : null
  const layer = typeof node.layer === "string" ? node.layer : null
  const fanIn = typeof node.fan_in === "number" ? node.fan_in : null
  const fanOut = typeof node.fan_out === "number" ? node.fan_out : null
  const visibility = typeof node.visibility === "string" ? node.visibility : null

  return (
    <ScrollArea className="h-full w-full">
      <div className="w-full overflow-hidden p-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-2 overflow-hidden">
          <div className="min-w-0 flex-1 overflow-hidden">
            <h3 className="break-all text-sm font-semibold">{name}</h3>
            <p className="mt-0.5 break-all text-xs text-muted-foreground" title={fqn}>
              {fqn}
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="size-7 p-0"
            onClick={onClose}
            aria-label="Close properties panel"
          >
            <X className="size-3" />
          </Button>
        </div>

        {/* Kind + Language badges */}
        <div className="mt-3 flex flex-wrap gap-1.5">
          {kind ? <Badge className={kindBadgeClass(kind)}>{kind}</Badge> : null}
          {language ? <Badge variant="outline">{language}</Badge> : null}
          {visibility ? (
            <Badge variant="outline" className="capitalize">{visibility}</Badge>
          ) : null}
        </div>

        <Separator className="my-4" />

        {/* File location */}
        {path ? (
          <>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Location
            </div>
            <button
              className="group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted"
              onClick={() => {
                if (path && onViewSource) {
                  onViewSource(path, line ?? 1)
                }
              }}
              disabled={!onViewSource}
            >
              <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1 overflow-hidden">
                <p className="break-all text-xs" title={path}>{path}</p>
                {line ? (
                  <p className="text-xs text-muted-foreground">
                    Line {line}{endLine ? ` - ${endLine}` : ""}
                  </p>
                ) : null}
              </div>
            </button>
            <Separator className="my-4" />
          </>
        ) : null}

        {/* Metrics */}
        {(loc !== null || complexity !== null || fanIn !== null || fanOut !== null) ? (
          <>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Metrics
            </div>
            <div className="space-y-0.5">
              <MetricRow icon={Ruler} label="Lines of Code" value={loc} />
              <MetricRow icon={Gauge} label="Complexity" value={complexity} />
              <MetricRow icon={ArrowDownToLine} label="Fan-in" value={fanIn} />
              <MetricRow icon={ArrowUpFromLine} label="Fan-out" value={fanOut} />
            </div>
            <Separator className="my-4" />
          </>
        ) : null}

        {/* Layer */}
        {layer ? (
          <>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Layer
            </div>
            <p className="text-sm capitalize">{layer}</p>
            <Separator className="my-4" />
          </>
        ) : null}

        {/* View Source button */}
        {path ? (
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => {
              if (path && onViewSource) {
                onViewSource(path, line ?? 1)
              }
            }}
            disabled={!onViewSource}
          >
            <Code2 className="size-3.5" />
            View Source
          </Button>
        ) : null}

        {/* Impact & Path buttons */}
        {fqn ? (
          <div className="mt-2 flex flex-col gap-2">
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => onShowImpact?.(fqn)}
              disabled={!onShowImpact}
            >
              <Activity className="size-3.5" />
              Show Impact
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => onStartPathFrom?.(fqn)}
              disabled={!onStartPathFrom}
            >
              <Route className="size-3.5" />
              Find Path
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => onTraceRoute?.(fqn)}
              disabled={!onTraceRoute}
            >
              <GitBranch className="size-3.5" />
              Trace Route
            </Button>
          </div>
        ) : null}

        {/* Annotations & Tags */}
        {fqn && projectId && onAddTag && onRemoveTag && onAddAnnotation && onEditAnnotation && onDeleteAnnotation ? (
          <div className="border-t pt-3 mt-4 space-y-3">
            <div>
              <h4 className="text-xs font-medium text-muted-foreground mb-1">Tags</h4>
              <TagBadges
                tags={tags}
                onAdd={(tagName) => onAddTag(projectId, fqn, tagName)}
                onRemove={onRemoveTag}
              />
            </div>
            <div>
              <h4 className="text-xs font-medium text-muted-foreground mb-1">Annotations</h4>
              <AnnotationList
                annotations={annotations}
                onEdit={onEditAnnotation}
                onDelete={onDeleteAnnotation}
              />
              <div className="mt-1.5">
                <AddAnnotation
                  onAdd={(content) => onAddAnnotation(projectId, fqn, content)}
                />
              </div>
            </div>
          </div>
        ) : null}

        {node.drillable ? (
          <p className="mt-4 text-xs text-muted-foreground italic">
            Double-click to drill down
          </p>
        ) : null}
      </div>
    </ScrollArea>
  )
}
