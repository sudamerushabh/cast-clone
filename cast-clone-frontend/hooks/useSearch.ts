"use client"

import { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { searchGraph } from "@/lib/api"
import type { GraphSearchHit } from "@/lib/types"

const DEBOUNCE_MS = 300

export interface GroupedResults {
  kind: string
  hits: GraphSearchHit[]
}

export interface UseSearchReturn {
  query: string
  setQuery: (q: string) => void
  results: GraphSearchHit[]
  groupedResults: GroupedResults[]
  isSearching: boolean
  error: string | null
  clear: () => void
}

export function useSearch(projectId: string): UseSearchReturn {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<GraphSearchHit[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
    }

    if (!query.trim()) {
      setResults([])
      setIsSearching(false)
      setError(null)
      return
    }

    setIsSearching(true)

    // Track whether this effect has been superseded
    let stale = false

    timerRef.current = setTimeout(async () => {
      try {
        const response = await searchGraph(projectId, query.trim())
        if (stale) return
        setResults(response.hits)
        setError(null)
      } catch (err) {
        if (stale) return
        setError(err instanceof Error ? err.message : "Search failed")
        setResults([])
      } finally {
        if (!stale) {
          setIsSearching(false)
        }
      }
    }, DEBOUNCE_MS)

    return () => {
      stale = true
      if (timerRef.current) {
        clearTimeout(timerRef.current)
      }
    }
  }, [query, projectId])

  const groupedResults: GroupedResults[] = useMemo(() => {
    const groups = new Map<string, GraphSearchHit[]>()
    for (const hit of results) {
      const existing = groups.get(hit.kind) ?? []
      existing.push(hit)
      groups.set(hit.kind, existing)
    }
    const ORDER = ["CLASS", "INTERFACE", "FUNCTION", "TABLE", "API_ENDPOINT"]
    return Array.from(groups.entries())
      .sort(([a], [b]) => {
        const ai = ORDER.indexOf(a)
        const bi = ORDER.indexOf(b)
        return (ai === -1 ? ORDER.length : ai) - (bi === -1 ? ORDER.length : bi)
      })
      .map(([kind, hits]) => ({ kind, hits }))
  }, [results])

  const clear = useCallback(() => {
    setQuery("")
    setResults([])
    setError(null)
    setIsSearching(false)
  }, [])

  return { query, setQuery, results, groupedResults, isSearching, error, clear }
}
