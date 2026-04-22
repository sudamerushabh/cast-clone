"use client"

import * as React from "react"
import {
  Search,
  Loader2,
  Box,
  GitBranch,
  Zap,
  Database,
  Globe,
  History,
  X,
  FileCode,
  MessageSquare,
} from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import { useSearch } from "@/hooks/useSearch"
import { useRecentSearches } from "@/hooks/useRecentSearches"
import type { GraphSearchHit } from "@/lib/types"

const KIND_ICONS: Record<string, React.ElementType> = {
  CLASS: Box,
  INTERFACE: GitBranch,
  FUNCTION: Zap,
  METHOD: Zap,
  TABLE: Database,
  API_ENDPOINT: Globe,
  MODULE: FileCode,
  FILE: FileCode,
}

const KIND_LABELS: Record<string, string> = {
  CLASS: "Classes",
  INTERFACE: "Interfaces",
  FUNCTION: "Functions",
  METHOD: "Methods",
  TABLE: "Tables",
  API_ENDPOINT: "Endpoints",
  MODULE: "Modules",
  FILE: "Files",
}

// Filter tabs the user can choose above the search input.
type TypeFilter = "all" | "file" | "class" | "function" | "annotation"

const FILTER_TABS: { value: TypeFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "file", label: "Files" },
  { value: "class", label: "Classes" },
  { value: "function", label: "Functions" },
  { value: "annotation", label: "Annotations" },
]

// Map a graph-node kind (server-side) into one of our client filter buckets.
function kindToFilter(kind: string): Exclude<TypeFilter, "all" | "annotation"> | null {
  const k = kind.toUpperCase()
  if (k === "MODULE" || k === "FILE") return "file"
  if (k === "CLASS" || k === "INTERFACE") return "class"
  if (k === "FUNCTION" || k === "METHOD") return "function"
  return null
}

interface SearchDialogProps {
  projectId: string | null
  onNavigate: (fqn: string, hit: GraphSearchHit) => void
  /**
   * Optional controlled-mode props. When `open` is defined the dialog is
   * controlled by the parent (e.g. TopBar owns the Cmd+K shortcut) and the
   * built-in global keydown listener is skipped so there is no double toggle.
   * When omitted the dialog manages its own open state and listens for Cmd+K
   * itself (legacy behaviour kept for the graph explorer).
   */
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

export function SearchDialog({
  projectId,
  onNavigate,
  open: openProp,
  onOpenChange,
}: SearchDialogProps) {
  const isControlled = typeof openProp === "boolean"
  const [internalOpen, setInternalOpen] = React.useState(false)
  const open = isControlled ? openProp : internalOpen

  const setOpen = React.useCallback(
    (next: boolean) => {
      if (!isControlled) setInternalOpen(next)
      onOpenChange?.(next)
    },
    [isControlled, onOpenChange],
  )

  // When no project is resolvable we still render the dialog so the user gets
  // feedback — but search is disabled and useSearch is a no-op.
  const effectiveProjectId = projectId ?? ""
  const { query, setQuery, groupedResults, isSearching, error, clear } =
    useSearch(effectiveProjectId)
  const inputRef = React.useRef<HTMLInputElement>(null)
  const listRef = React.useRef<HTMLDivElement>(null)

  const [filter, setFilter] = React.useState<TypeFilter>("all")
  const [activeIndex, setActiveIndex] = React.useState(0)

  const { recent, push: pushRecent, remove: removeRecent, clear: clearRecent } =
    useRecentSearches()

  // Built-in Cmd+K listener — only active in uncontrolled mode so a parent
  // that owns the shortcut does not double-toggle.
  React.useEffect(() => {
    if (isControlled) return
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setInternalOpen((prev) => !prev)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [isControlled])

  // Focus the input when the dialog opens; clear query when it closes.
  React.useEffect(() => {
    if (open) {
      const t = setTimeout(() => inputRef.current?.focus(), 50)
      return () => clearTimeout(t)
    }
    clear()
    setFilter("all")
    setActiveIndex(0)
  }, [open, clear])

  // Flatten grouped results into the order the user sees them, then apply the
  // active type filter so keyboard navigation lines up with the rendered list.
  const filteredGroups = React.useMemo(() => {
    if (filter === "all") return groupedResults
    if (filter === "annotation") return []
    return groupedResults
      .map((g) => ({
        ...g,
        hits: g.hits.filter((hit) => kindToFilter(hit.kind) === filter),
      }))
      .filter((g) => g.hits.length > 0)
  }, [groupedResults, filter])

  const flatHits: GraphSearchHit[] = React.useMemo(
    () => filteredGroups.flatMap((g) => g.hits),
    [filteredGroups],
  )

  // Keep the active index in bounds when results change.
  React.useEffect(() => {
    setActiveIndex(0)
  }, [query, filter, flatHits.length])

  const hasQuery = query.trim().length > 0
  const showRecent = !hasQuery && recent.length > 0

  const handleSelectHit = React.useCallback(
    (hit: GraphSearchHit) => {
      pushRecent(query || hit.name)
      onNavigate(hit.fqn, hit)
      setOpen(false)
    },
    [onNavigate, pushRecent, query, setOpen],
  )

  const handleSelectRecent = React.useCallback(
    (q: string) => {
      setQuery(q)
      inputRef.current?.focus()
    },
    [setQuery],
  )

  // Keyboard navigation inside the dialog: arrow keys cycle active item,
  // Enter selects it, Escape closes. Dialog primitive already handles Escape
  // via Radix but we defensively implement it for parity with ShadCN Command.
  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      if (flatHits.length === 0) return
      setActiveIndex((prev) => (prev + 1) % flatHits.length)
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      if (flatHits.length === 0) return
      setActiveIndex((prev) => (prev - 1 + flatHits.length) % flatHits.length)
    } else if (e.key === "Enter") {
      if (flatHits.length > 0) {
        e.preventDefault()
        const hit = flatHits[activeIndex] ?? flatHits[0]
        if (hit) handleSelectHit(hit)
      } else if (showRecent && recent[0]) {
        e.preventDefault()
        handleSelectRecent(recent[0])
      }
    }
  }

  // Scroll the active item into view as arrow keys move it.
  React.useEffect(() => {
    if (!listRef.current) return
    const el = listRef.current.querySelector<HTMLElement>(
      `[data-index="${activeIndex}"]`,
    )
    el?.scrollIntoView({ block: "nearest" })
  }, [activeIndex])

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-lg">
        <DialogTitle className="sr-only">Search nodes</DialogTitle>

        {/* Search input */}
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
            onKeyDown={handleInputKeyDown}
            placeholder={
              projectId
                ? "Search classes, functions, tables..."
                : "Open a repository to enable search"
            }
            disabled={!projectId}
            className="h-8 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
          />
          <kbd className="pointer-events-none hidden h-5 select-none items-center gap-0.5 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground sm:flex">
            ESC
          </kbd>
        </div>

        {/* Type filter tabs */}
        <div
          className="flex items-center gap-1 border-b px-2 py-1.5"
          role="tablist"
          aria-label="Filter search results by type"
        >
          {FILTER_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              role="tab"
              aria-selected={filter === tab.value}
              onClick={() => setFilter(tab.value)}
              className={cn(
                "rounded px-2 py-0.5 text-xs font-medium transition-colors",
                filter === tab.value
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <ScrollArea className="max-h-80">
          <div ref={listRef}>
            {error ? (
              <div className="px-4 py-3 text-sm text-destructive">{error}</div>
            ) : null}

            {/* Disabled state — no project in scope */}
            {!projectId && !showRecent ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                Open a repository to search its architecture graph.
              </div>
            ) : null}

            {/* Recent searches (shown when input is empty) */}
            {showRecent ? (
              <div>
                <div className="flex items-center justify-between px-4 py-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <span className="flex items-center gap-2">
                    <History className="size-3" />
                    Recent
                  </span>
                  <button
                    type="button"
                    onClick={clearRecent}
                    className="text-[10px] font-normal normal-case hover:text-foreground"
                  >
                    Clear
                  </button>
                </div>
                {recent.map((q) => (
                  <div
                    key={q}
                    className="group flex items-center gap-2 px-4 py-1.5 text-sm hover:bg-muted"
                  >
                    <button
                      type="button"
                      onClick={() => handleSelectRecent(q)}
                      className="flex-1 truncate text-left"
                    >
                      {q}
                    </button>
                    <button
                      type="button"
                      onClick={() => removeRecent(q)}
                      aria-label={`Remove recent search ${q}`}
                      className="rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:bg-background hover:text-foreground group-hover:opacity-100"
                    >
                      <X className="size-3" />
                    </button>
                  </div>
                ))}
              </div>
            ) : null}

            {/* Annotation filter: not yet backed by the search API */}
            {filter === "annotation" && hasQuery ? (
              <div className="flex flex-col items-center gap-1 px-4 py-8 text-center text-sm text-muted-foreground">
                <MessageSquare className="size-4" />
                <p>Annotation search is coming soon.</p>
              </div>
            ) : null}

            {/* Empty state — query typed, no matches */}
            {!error &&
            hasQuery &&
            !isSearching &&
            filter !== "annotation" &&
            flatHits.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                No results found for &ldquo;{query}&rdquo;
              </div>
            ) : null}

            {/* Grouped results */}
            {!error && hasQuery && filter !== "annotation"
              ? (() => {
                  let flatIndex = 0
                  return filteredGroups.map((group) => {
                    const Icon = KIND_ICONS[group.kind] ?? Box
                    const label = KIND_LABELS[group.kind] ?? group.kind
                    return (
                      <div key={group.kind}>
                        <div className="flex items-center gap-2 px-4 py-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          <Icon className="size-3" />
                          {label}
                        </div>
                        {group.hits.map((hit) => {
                          const idx = flatIndex++
                          const isActive = idx === activeIndex
                          return (
                            <button
                              key={hit.fqn}
                              data-index={idx}
                              className={cn(
                                "flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors focus:outline-none",
                                isActive
                                  ? "bg-muted"
                                  : "hover:bg-muted/60 focus:bg-muted",
                              )}
                              onMouseEnter={() => setActiveIndex(idx)}
                              onClick={() => handleSelectHit(hit)}
                            >
                              <div className="min-w-0 flex-1">
                                <div className="truncate font-medium">
                                  {hit.name}
                                </div>
                                <div className="truncate text-xs text-muted-foreground">
                                  {hit.fqn}
                                </div>
                              </div>
                              {hit.language ? (
                                <Badge
                                  variant="outline"
                                  className="shrink-0 text-[10px]"
                                >
                                  {hit.language}
                                </Badge>
                              ) : null}
                            </button>
                          )
                        })}
                      </div>
                    )
                  })
                })()
              : null}
          </div>
        </ScrollArea>

        <div className="flex items-center justify-between border-t px-4 py-2 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1">
              <kbd className="rounded border bg-muted px-1 font-mono">↑</kbd>
              <kbd className="rounded border bg-muted px-1 font-mono">↓</kbd>
              navigate
            </span>
            <span className="inline-flex items-center gap-1">
              <kbd className="rounded border bg-muted px-1 font-mono">↵</kbd>
              select
            </span>
            <span className="inline-flex items-center gap-1">
              <kbd className="rounded border bg-muted px-1 font-mono">esc</kbd>
              close
            </span>
          </span>
        </div>
      </DialogContent>
    </Dialog>
  )
}
