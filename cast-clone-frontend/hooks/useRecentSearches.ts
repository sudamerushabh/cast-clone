"use client"

import { useCallback, useState } from "react"

const STORAGE_KEY = "changesafe:recentSearches"
const MAX_ENTRIES = 10

function readFromStorage(): string[] {
  if (typeof window === "undefined") return []
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((x): x is string => typeof x === "string" && x.length > 0)
      .slice(0, MAX_ENTRIES)
  } catch {
    return []
  }
}

/**
 * Persists the user's recent search queries to localStorage.
 * Entries are most-recent-first, de-duped by query string (case-sensitive),
 * and capped at 10.
 *
 * Safe to use from client components — localStorage access is guarded
 * so SSR does not crash.
 */
export function useRecentSearches(): {
  recent: string[]
  push: (query: string) => void
  clear: () => void
  remove: (query: string) => void
} {
  // Lazy initializer runs once on mount (client-only — this hook is
  // consumed from "use client" components).
  const [recent, setRecent] = useState<string[]>(() => readFromStorage())

  const persist = useCallback((next: string[]) => {
    setRecent(next)
    if (typeof window === "undefined") return
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      // Quota or privacy mode — silently ignore
    }
  }, [])

  const push = useCallback(
    (query: string) => {
      const trimmed = query.trim()
      if (!trimmed) return
      setRecent((prev) => {
        const deduped = prev.filter((q) => q !== trimmed)
        const next = [trimmed, ...deduped].slice(0, MAX_ENTRIES)
        if (typeof window !== "undefined") {
          try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
          } catch {
            // ignore
          }
        }
        return next
      })
    },
    [],
  )

  const clear = useCallback(() => {
    persist([])
  }, [persist])

  const remove = useCallback(
    (query: string) => {
      setRecent((prev) => {
        const next = prev.filter((q) => q !== query)
        if (typeof window !== "undefined") {
          try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
          } catch {
            // ignore
          }
        }
        return next
      })
    },
    [],
  )

  return { recent, push, clear, remove }
}
