"use client"

import * as React from "react"
import { useMemo, useState } from "react"
import { AlertTriangle, ArrowUpDown, FileCode2, Trash2, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import type { DeadCodeResponse, DeadCodeCandidate } from "@/lib/types"

// ─── Sort helpers ───────────────────────────────────────────────────────────

type SortKey = "name" | "loc" | "path"
type SortDir = "asc" | "desc"

function compareCandidates(
  a: DeadCodeCandidate,
  b: DeadCodeCandidate,
  key: SortKey,
  dir: SortDir,
): number {
  let cmp = 0
  switch (key) {
    case "name":
      cmp = a.name.localeCompare(b.name)
      break
    case "loc":
      cmp = (a.loc ?? 0) - (b.loc ?? 0)
      break
    case "path":
      cmp = (a.path ?? "").localeCompare(b.path ?? "")
      break
  }
  return dir === "asc" ? cmp : -cmp
}

// ─── Component ──────────────────────────────────────────────────────────────

interface DeadCodePanelProps {
  data: DeadCodeResponse | null
  isLoading: boolean
  error: string | null
  typeFilter: "function" | "class"
  onTypeChange: (type: "function" | "class") => void
  onNavigate: (fqn: string) => void
  onClose: () => void
}

export function DeadCodePanel({
  data,
  isLoading,
  error,
  typeFilter,
  onTypeChange,
  onNavigate,
  onClose,
}: DeadCodePanelProps) {
  const [sortKey, setSortKey] = useState<SortKey>("name")
  const [sortDir, setSortDir] = useState<SortDir>("asc")

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("asc")
    }
  }

  const sortedCandidates = useMemo(() => {
    if (!data) return []
    return [...data.candidates].sort((a, b) =>
      compareCandidates(a, b, sortKey, sortDir),
    )
  }, [data, sortKey, sortDir])

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Trash2 className="size-4 text-yellow-600" />
          <span className="text-sm font-semibold">Dead Code</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="size-7 p-0"
          onClick={onClose}
          aria-label="Close dead code panel"
        >
          <X className="size-3" />
        </Button>
      </div>

      {/* Type toggle */}
      <div className="flex gap-1 border-b px-4 py-2">
        {(["function", "class"] as const).map((t) => (
          <Button
            key={t}
            variant={typeFilter === t ? "secondary" : "ghost"}
            size="sm"
            className="flex-1 text-xs capitalize"
            onClick={() => onTypeChange(t)}
          >
            {t}
          </Button>
        ))}
      </div>

      {/* Content */}
      <ScrollArea className="flex-1">
        <div className="p-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <span className="text-sm text-muted-foreground">
                Scanning for dead code...
              </span>
            </div>
          ) : error ? (
            <div className="py-4 text-center text-sm text-destructive">
              {error}
            </div>
          ) : !data ? (
            <div className="py-4 text-center text-sm text-muted-foreground">
              Loading dead code candidates...
            </div>
          ) : (
            <>
              {/* Count + warning */}
              <div className="mb-3">
                <Badge variant="outline" className="text-xs">
                  {data.total} candidate{data.total !== 1 ? "s" : ""}
                </Badge>
              </div>

              <div className="mb-3 flex items-start gap-2 rounded-md border border-orange-300 bg-orange-50 px-3 py-2 dark:border-orange-700 dark:bg-orange-950">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-orange-600" />
                <span className="text-[11px] text-orange-800 dark:text-orange-300">
                  These are candidates only. Verify before deleting &mdash;
                  reflection, dynamic calls, and external consumers may not be
                  detected.
                </span>
              </div>

              {/* Sort controls */}
              <div className="mb-2 flex items-center gap-1">
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Sort:
                </span>
                {(["name", "loc", "path"] as SortKey[]).map((key) => (
                  <Button
                    key={key}
                    variant={sortKey === key ? "secondary" : "ghost"}
                    size="sm"
                    className="h-5 px-1.5 text-[10px] capitalize"
                    onClick={() => toggleSort(key)}
                  >
                    {key}
                    {sortKey === key && (
                      <ArrowUpDown className="ml-0.5 size-2.5" />
                    )}
                  </Button>
                ))}
              </div>

              <Separator className="my-3" />

              {/* Candidate list */}
              {sortedCandidates.length === 0 ? (
                <div className="py-4 text-center text-sm text-muted-foreground">
                  No dead code candidates found for {typeFilter} type.
                </div>
              ) : (
                <div className="space-y-1">
                  {sortedCandidates.map((candidate) => (
                    <button
                      key={candidate.fqn}
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted"
                      onClick={() => onNavigate(candidate.fqn)}
                      title={candidate.fqn}
                    >
                      <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" />
                      <div className="min-w-0 flex-1">
                        <p className="break-all text-xs font-medium">
                          {candidate.name}
                        </p>
                        <p className="break-all text-[10px] text-muted-foreground">
                          {candidate.path ?? candidate.fqn}
                        </p>
                      </div>
                      {candidate.loc !== null && candidate.loc !== undefined && (
                        <Badge
                          variant="secondary"
                          className="shrink-0 text-[10px] px-1.5 py-0"
                        >
                          {candidate.loc} LOC
                        </Badge>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
