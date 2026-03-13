"use client"

import { useCallback, useRef, useState } from "react"
import type cytoscape from "cytoscape"

import {
  getModules,
  getModuleClasses,
  getClassMethods,
  getAggregatedEdges,
  getArchitecture,
} from "@/lib/api"
import {
  modulesToElements,
  classesToElements,
  methodsToElements,
  aggregatedEdgesToClassElements,
  architectureToElements,
  getPerformanceTier,
} from "@/lib/cytoscape-elements"

type ElementDefinition = cytoscape.ElementDefinition

interface DrilldownEntry {
  level: "module" | "class"
  fqn: string
  name: string
}

/** Signals how the graph layout should respond to an elements change. */
export type LayoutMode = "full" | "drill"

interface UseGraphReturn {
  elements: ElementDefinition[]
  isLoading: boolean
  error: string | null
  drilldownPath: DrilldownEntry[]
  performanceTier: "full" | "no-animation" | "simplified" | "force-drilldown"
  layoutMode: LayoutMode
  loadArchitecture: (projectId: string) => Promise<void>
  loadModules: (projectId: string) => Promise<void>
  drillIntoModule: (
    projectId: string,
    moduleFqn: string,
    moduleName: string
  ) => Promise<void>
  drillIntoClass: (
    projectId: string,
    classFqn: string,
    className: string
  ) => Promise<void>
  drillUp: (projectId: string) => Promise<void>
}

export function useGraph(): UseGraphReturn {
  const [elements, setElements] = useState<ElementDefinition[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [drilldownPath, setDrilldownPath] = useState<DrilldownEntry[]>([])
  const [performanceTier, setPerformanceTier] = useState<
    "full" | "no-animation" | "simplified" | "force-drilldown"
  >("full")
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("full")

  const cache = useRef(new Map<string, ElementDefinition[]>())

  const loadModules = useCallback(async (projectId: string) => {
    const cacheKey = `modules:${projectId}`

    setIsLoading(true)
    setError(null)
    setDrilldownPath([])
    setLayoutMode("full")

    try {
      if (cache.current.has(cacheKey)) {
        const cached = cache.current.get(cacheKey)!
        setElements(cached)
        setPerformanceTier(
          getPerformanceTier(cached.filter((e) => e.group === "nodes").length)
        )
        return
      }

      const moduleResp = await getModules(projectId)
      const edgeResp = await getAggregatedEdges(projectId, "module")
      const els = modulesToElements(moduleResp.modules, edgeResp.edges)

      cache.current.set(cacheKey, els)

      const nodeCount = els.filter((e) => e.group === "nodes").length
      setPerformanceTier(getPerformanceTier(nodeCount))
      setElements(els)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load modules")
    } finally {
      setIsLoading(false)
    }
  }, [])

  const loadArchitecture = useCallback(async (projectId: string) => {
    const cacheKey = `architecture:${projectId}`

    setIsLoading(true)
    setError(null)
    setDrilldownPath([])
    setLayoutMode("full")

    try {
      if (cache.current.has(cacheKey)) {
        const cached = cache.current.get(cacheKey)!
        setElements(cached)
        setPerformanceTier(
          getPerformanceTier(cached.filter((e) => e.group === "nodes").length)
        )
        return
      }

      const archResp = await getArchitecture(projectId)
      const els = architectureToElements(archResp)

      cache.current.set(cacheKey, els)

      const nodeCount = els.filter((e) => e.group === "nodes").length
      setPerformanceTier(getPerformanceTier(nodeCount))
      setElements(els)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load architecture")
    } finally {
      setIsLoading(false)
    }
  }, [])

  const drillIntoModule = useCallback(
    async (projectId: string, moduleFqn: string, moduleName: string) => {
      const cacheKey = `classes:${projectId}:${moduleFqn}`

      setIsLoading(true)
      setError(null)
      setLayoutMode("drill")

      try {
        let classElements: ElementDefinition[]

        if (cache.current.has(cacheKey)) {
          classElements = cache.current.get(cacheKey)!
        } else {
          const classResp = await getModuleClasses(projectId, moduleFqn)
          classElements = classesToElements(classResp.classes, moduleFqn)

          // Fetch aggregated CALLS edges between classes in this module
          const classFqns = new Set(classResp.classes.map((c) => c.fqn))
          const edgeResp = await getAggregatedEdges(
            projectId,
            "class",
            moduleFqn
          )
          // Only include edges where both endpoints are visible class nodes
          const safeEdges = edgeResp.edges.filter(
            (e) => classFqns.has(e.source) && classFqns.has(e.target)
          )
          const classEdgeElements = aggregatedEdgesToClassElements(safeEdges)

          classElements = [...classElements, ...classEdgeElements]
          cache.current.set(cacheKey, classElements)
        }

        setElements((prev) => [...prev, ...classElements])
        setDrilldownPath((prev) => [
          ...prev,
          { level: "module", fqn: moduleFqn, name: moduleName },
        ])
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load classes")
      } finally {
        setIsLoading(false)
      }
    },
    []
  )

  const drillIntoClass = useCallback(
    async (projectId: string, classFqn: string, className: string) => {
      const cacheKey = `methods:${projectId}:${classFqn}`

      setIsLoading(true)
      setError(null)
      setLayoutMode("drill")

      try {
        let methodElements: ElementDefinition[]

        if (cache.current.has(cacheKey)) {
          methodElements = cache.current.get(cacheKey)!
        } else {
          const methodResp = await getClassMethods(projectId, classFqn)
          methodElements = methodsToElements(methodResp.methods, classFqn)
          cache.current.set(cacheKey, methodElements)
        }

        setElements((prev) => [...prev, ...methodElements])
        setDrilldownPath((prev) => [
          ...prev,
          { level: "class", fqn: classFqn, name: className },
        ])
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load methods")
      } finally {
        setIsLoading(false)
      }
    },
    []
  )

  const drillUp = useCallback(
    async (projectId: string) => {
      if (drilldownPath.length === 0) return

      setLayoutMode("full")
      const newPath = drilldownPath.slice(0, -1)
      setDrilldownPath(newPath)

      if (newPath.length === 0) {
        // Back to module view
        const cacheKey = `modules:${projectId}`
        const cached = cache.current.get(cacheKey)
        if (cached) {
          setElements(cached)
        } else {
          await loadModules(projectId)
        }
      } else {
        // Rebuild elements up to this drilldown level
        const moduleCacheKey = `modules:${projectId}`
        let els = cache.current.get(moduleCacheKey) ?? []

        for (const entry of newPath) {
          if (entry.level === "module") {
            const classCacheKey = `classes:${projectId}:${entry.fqn}`
            const classEls = cache.current.get(classCacheKey) ?? []
            els = [...els, ...classEls]
          } else if (entry.level === "class") {
            const methodCacheKey = `methods:${projectId}:${entry.fqn}`
            const methodEls = cache.current.get(methodCacheKey) ?? []
            els = [...els, ...methodEls]
          }
        }

        setElements(els)
      }
    },
    [drilldownPath, loadModules]
  )

  return {
    elements,
    isLoading,
    error,
    drilldownPath,
    performanceTier,
    layoutMode,
    loadArchitecture,
    loadModules,
    drillIntoModule,
    drillIntoClass,
    drillUp,
  }
}
