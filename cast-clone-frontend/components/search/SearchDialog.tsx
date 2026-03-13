"use client"

import * as React from "react"
import { Search, Loader2, Box, GitBranch, Zap, Database, Globe } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useSearch } from "@/hooks/useSearch"
import type { GraphSearchHit } from "@/lib/types"

const KIND_ICONS: Record<string, React.ElementType> = {
  CLASS: Box,
  INTERFACE: GitBranch,
  FUNCTION: Zap,
  TABLE: Database,
  API_ENDPOINT: Globe,
}

const KIND_LABELS: Record<string, string> = {
  CLASS: "Classes",
  INTERFACE: "Interfaces",
  FUNCTION: "Functions",
  TABLE: "Tables",
  API_ENDPOINT: "Endpoints",
}

interface SearchDialogProps {
  projectId: string
  onNavigate: (fqn: string) => void
}

export function SearchDialog({ projectId, onNavigate }: SearchDialogProps) {
  const [open, setOpen] = React.useState(false)
  const { query, setQuery, groupedResults, isSearching, error, clear } =
    useSearch(projectId)
  const inputRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setOpen((prev) => !prev)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  React.useEffect(() => {
    if (open) {
      const t = setTimeout(() => inputRef.current?.focus(), 50)
      return () => clearTimeout(t)
    } else {
      clear()
    }
  }, [open, clear])

  function handleSelect(hit: GraphSearchHit) {
    onNavigate(hit.fqn)
    setOpen(false)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-lg">
        <DialogTitle className="sr-only">Search nodes</DialogTitle>

        <div className="flex items-center gap-2 border-b px-3 py-2">
          {isSearching ? (
            <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
          ) : (
            <Search className="size-4 shrink-0 text-muted-foreground" />
          )}
          <Input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search classes, functions, tables..."
            className="h-8 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
          />
          <kbd className="pointer-events-none hidden h-5 select-none items-center gap-0.5 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground sm:flex">
            ESC
          </kbd>
        </div>

        <ScrollArea className="max-h-80">
          {error ? (
            <div className="px-4 py-3 text-sm text-destructive">{error}</div>
          ) : null}

          {!error && query.trim() && !isSearching && groupedResults.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              No results found for &ldquo;{query}&rdquo;
            </div>
          ) : null}

          {!error
            ? groupedResults.map((group) => {
                const Icon = KIND_ICONS[group.kind] ?? Box
                const label = KIND_LABELS[group.kind] ?? group.kind

                return (
                  <div key={group.kind}>
                    <div className="flex items-center gap-2 px-4 py-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      <Icon className="size-3" />
                      {label}
                    </div>
                    {group.hits.map((hit) => (
                      <button
                        key={hit.fqn}
                        className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors hover:bg-muted focus:bg-muted focus:outline-none"
                        onClick={() => handleSelect(hit)}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-medium">{hit.name}</div>
                          <div className="truncate text-xs text-muted-foreground">
                            {hit.fqn}
                          </div>
                        </div>
                        {hit.language ? (
                          <Badge variant="outline" className="shrink-0 text-[10px]">
                            {hit.language}
                          </Badge>
                        ) : null}
                      </button>
                    ))}
                  </div>
                )
              })
            : null}
        </ScrollArea>

        {groupedResults.length > 0 ? (
          <div className="border-t px-4 py-2 text-xs text-muted-foreground">
            Click a result to navigate to it in the graph
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
