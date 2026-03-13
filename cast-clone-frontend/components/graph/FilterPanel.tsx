"use client"

import * as React from "react"
import { Filter } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { Separator } from "@/components/ui/separator"
import { ScrollArea } from "@/components/ui/scroll-area"
import type cytoscape from "cytoscape"

interface FilterItem {
  id: string
  label: string
}

const NODE_TYPE_FILTERS: FilterItem[] = [
  { id: "CLASS", label: "Classes" },
  { id: "INTERFACE", label: "Interfaces" },
  { id: "FUNCTION", label: "Functions" },
  { id: "TABLE", label: "Tables" },
  { id: "API_ENDPOINT", label: "Endpoints" },
  { id: "MODULE", label: "Modules" },
  { id: "ENUM", label: "Enums" },
]

const LANGUAGE_FILTERS: FilterItem[] = [
  { id: "java", label: "Java" },
  { id: "typescript", label: "TypeScript" },
  { id: "python", label: "Python" },
  { id: "csharp", label: "C#" },
]

interface FilterPanelProps {
  cy: cytoscape.Core | null
  /** Pass element count or a key that changes when graph data is replaced */
  elementKey?: number
}

export function FilterPanel({ cy, elementKey }: FilterPanelProps) {
  const [visibleKinds, setVisibleKinds] = React.useState<Set<string>>(
    () => new Set(NODE_TYPE_FILTERS.map((f) => f.id))
  )
  const [visibleLanguages, setVisibleLanguages] = React.useState<Set<string>>(
    () => new Set(LANGUAGE_FILTERS.map((f) => f.id))
  )

  // Reset filter state when graph elements change
  React.useEffect(() => {
    setVisibleKinds(new Set(NODE_TYPE_FILTERS.map((f) => f.id)))
    setVisibleLanguages(new Set(LANGUAGE_FILTERS.map((f) => f.id)))
  }, [elementKey])

  function toggleKind(kind: string, checked: boolean) {
    setVisibleKinds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(kind)
      else next.delete(kind)
      return next
    })
    if (!cy) return
    const nodes = cy.nodes(`[kind = "${kind}"]`) as unknown as { show(): void; hide(): void }
    if (checked) nodes.show()
    else nodes.hide()
  }

  function toggleLanguage(language: string, checked: boolean) {
    setVisibleLanguages((prev) => {
      const next = new Set(prev)
      if (checked) next.add(language)
      else next.delete(language)
      return next
    })
    if (!cy) return
    const nodes = cy.nodes(`[language = "${language}"]`) as unknown as { show(): void; hide(): void }
    if (checked) nodes.show()
    else nodes.hide()
  }

  function resetFilters() {
    setVisibleKinds(new Set(NODE_TYPE_FILTERS.map((f) => f.id)))
    setVisibleLanguages(new Set(LANGUAGE_FILTERS.map((f) => f.id)))
    if (cy) (cy.nodes() as unknown as { show(): void }).show()
  }

  const hasActiveFilters =
    visibleKinds.size < NODE_TYPE_FILTERS.length ||
    visibleLanguages.size < LANGUAGE_FILTERS.length

  return (
    <ScrollArea className="h-full">
      <div className="p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <Filter className="size-3" />
            Filters
          </div>
          {hasActiveFilters ? (
            <button onClick={resetFilters} className="text-xs text-primary hover:underline">
              Reset
            </button>
          ) : null}
        </div>

        <Separator className="my-3" />

        <div className="mb-1 text-xs font-medium text-muted-foreground">Node Type</div>
        <div className="space-y-2">
          {NODE_TYPE_FILTERS.map((filter) => (
            <label key={filter.id} className="flex cursor-pointer items-center gap-2 text-sm">
              <Checkbox
                checked={visibleKinds.has(filter.id)}
                onCheckedChange={(checked) => toggleKind(filter.id, checked === true)}
              />
              <span>{filter.label}</span>
            </label>
          ))}
        </div>

        <Separator className="my-3" />

        <div className="mb-1 text-xs font-medium text-muted-foreground">Language</div>
        <div className="space-y-2">
          {LANGUAGE_FILTERS.map((filter) => (
            <label key={filter.id} className="flex cursor-pointer items-center gap-2 text-sm">
              <Checkbox
                checked={visibleLanguages.has(filter.id)}
                onCheckedChange={(checked) => toggleLanguage(filter.id, checked === true)}
              />
              <span>{filter.label}</span>
            </label>
          ))}
        </div>
      </div>
    </ScrollArea>
  )
}
