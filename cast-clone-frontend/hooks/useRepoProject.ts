"use client"

import { useEffect, useState } from "react"
import { getRepository } from "@/lib/api"
import type { ProjectBranchResponse } from "@/lib/types"

interface UseRepoProjectReturn {
  projectId: string | null
  project: ProjectBranchResponse | null
  isLoading: boolean
  error: string | null
}

/**
 * Resolves a repository ID + branch name into the corresponding project ID.
 * All graph/analysis APIs use projectId — this hook bridges the repository URL
 * structure to the project-based API layer.
 */
export function useRepoProject(
  repoId: string,
  branch: string,
): UseRepoProjectReturn {
  const [projectId, setProjectId] = useState<string | null>(null)
  const [project, setProject] = useState<ProjectBranchResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function resolve() {
      setIsLoading(true)
      setError(null)
      try {
        const repo = await getRepository(repoId)
        if (cancelled) return
        const match = repo.projects.find((p) => p.branch === branch) ?? null
        if (!match) {
          setError(`No project found for branch "${branch}"`)
          setProjectId(null)
          setProject(null)
        } else {
          setProjectId(match.id)
          setProject(match)
        }
      } catch (err) {
        if (cancelled) return
        setError(
          err instanceof Error ? err.message : "Failed to load repository",
        )
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    resolve()
    return () => {
      cancelled = true
    }
  }, [repoId, branch])

  return { projectId, project, isLoading, error }
}
