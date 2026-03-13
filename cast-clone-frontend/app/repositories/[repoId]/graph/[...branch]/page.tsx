"use client"

import { useParams } from "next/navigation"
import { Loader2 } from "lucide-react"
import { GraphExplorer } from "@/components/graph/GraphExplorer"
import { useRepoProject } from "@/hooks/useRepoProject"

export default function BranchGraphPage() {
  const params = useParams()
  const repoId = params.repoId as string
  const branchSegments = params.branch as string[]
  const branchName = branchSegments.map(decodeURIComponent).join("/")

  const { projectId, isLoading, error } = useRepoProject(repoId, branchName)

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !projectId) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-destructive">{error ?? "Project not found"}</p>
      </div>
    )
  }

  return <GraphExplorer projectId={projectId} defaultViewMode="architecture" />
}
