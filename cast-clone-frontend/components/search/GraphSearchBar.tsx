"use client"

import * as React from "react"
import { Search, Loader2, Box, GitBranch, Zap, Database, Globe } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { useSearch } from "@/hooks/useSearch"
import type { GraphSearchHit } from "@/lib/types"

const KIND_ICONS: Record<string, React.ElementType> = {
  CLASS: Box,
  INTERFACE: GitBranch,
  FUNCTION: Zap,
  TABLE: Database,
  API_ENDPOINT: Globe,
  MODULE: Box,
}

interface GraphSearchBarProps {
  projectId: string
  onSelect: (hit: GraphSearchHit) => void
}

export function GraphSearchBar({ projectId, onSelect }: GraphSearchBarProps) {
  const { query, setQuery, groupedResults, isSearching, error, clear } =
    useSearch(projectId)
  const [open, setOpen] = React.useState(false)
  const containerRef = React.useRef<HTMLDivElement>(null)
  const inputRef = React.useRef<HTMLInputElement>(null)

  // Close dropdown when clicking outside
  React.useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", onMouseDown)
    return () => document.removeEventListener("mousedown", onMouseDown)
  }, [])

  // Close on Escape
  React.useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && open) {
        setOpen(false)
        inputRef.current?.blur()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [open])

  function handleSelect(hit: GraphSearchHit) {
    onSelect(hit)
    setOpen(false)
    clear()
  }

  const hasResults = groupedResults.length > 0
  const showDropdown = open && query.trim().length > 0

  return (
    <div ref={containerRef} className="relative">
      <div className="flex items-center gap-1.5">
        {isSearching ? (
          <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" />
        ) : (
          <Search className="size-3.5 shrink-0 text-muted-foreground" />
        )}
        <Input
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onFocus={() => {
            if (query.trim()) setOpen(true)
          }}
          placeholder="Search nodes..."
          className="h-7 w-48 border-0 bg-transparent px-1 text-xs shadow-none focus-visible:ring-0"
        />
      </div>

      {showDropdown && (
        <div className="absolute left-0 top-full z-50 mt-1 w-80 rounded-md border bg-background shadow-lg">
          <div className="max-h-72 overflow-y-auto">
            {error ? (
              <div className="px-3 py-2 text-xs text-destructive">{error}</div>
            ) : null}

            {!error && !isSearching && !hasResults ? (
              <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                No results for &ldquo;{query}&rdquo;
              </div>
            ) : null}

            {!error &&
              groupedResults.map((group) => {
                const Icon = KIND_ICONS[group.kind] ?? Box
                return (
                  <div key={group.kind}>
                    <div className="flex items-center gap-1.5 px-3 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                      <Icon className="size-2.5" />
                      {group.kind}
                    </div>
                    {group.hits.map((hit) => (
                      <button
                        key={hit.fqn}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors hover:bg-muted focus:bg-muted focus:outline-none"
                        onClick={() => handleSelect(hit)}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-medium">{hit.name}</div>
                          <div className="truncate text-[10px] text-muted-foreground">
                            {hit.fqn}
                          </div>
                        </div>
                        {hit.language ? (
                          <Badge variant="outline" className="shrink-0 text-[9px]">
                            {hit.language}
                          </Badge>
                        ) : null}
                      </button>
                    ))}
                  </div>
                )
              })}
          </div>
          {hasResults && (
            <div className="border-t px-3 py-1.5 text-[10px] text-muted-foreground">
              Click to navigate in graph
            </div>
          )}
        </div>
      )}
    </div>
  )
}
