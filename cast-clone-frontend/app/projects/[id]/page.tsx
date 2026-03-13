"use client"

import * as React from "react"
import { useParams, useRouter } from "next/navigation"
import {
  ArrowLeft,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  ExternalLink,
} from "lucide-react"

import { getProject, triggerAnalysis, getAnalysisStatus } from "@/lib/api"
import type { ProjectResponse, AnalysisStatusResponse } from "@/lib/types"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"

const POLL_INTERVAL_MS = 2000

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function ProjectDashboardPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const projectId = params.id

  const [project, setProject] = React.useState<ProjectResponse | null>(null)
  const [analysisStatus, setAnalysisStatus] =
    React.useState<AnalysisStatusResponse | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [triggering, setTriggering] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const fetchProject = React.useCallback(async () => {
    try {
      setError(null)
      const data = await getProject(projectId)
      setProject(data)
      return data
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load project")
      return null
    } finally {
      setLoading(false)
    }
  }, [projectId])

  const fetchStatus = React.useCallback(async () => {
    try {
      const status = await getAnalysisStatus(projectId)
      setAnalysisStatus(status)
      return status
    } catch {
      // Status endpoint may 404 if no analysis has run
      return null
    }
  }, [projectId])

  // Initial load
  React.useEffect(() => {
    async function init() {
      const proj = await fetchProject()
      if (proj) {
        await fetchStatus()
      }
    }
    init()
  }, [fetchProject, fetchStatus])

  // Poll while analyzing
  React.useEffect(() => {
    if (project?.status !== "analyzing") return

    const interval = setInterval(async () => {
      const proj = await fetchProject()
      if (proj?.status === "analyzing") {
        await fetchStatus()
      }
    }, POLL_INTERVAL_MS)

    return () => clearInterval(interval)
  }, [project?.status, fetchProject, fetchStatus])

  async function handleTriggerAnalysis() {
    try {
      setTriggering(true)
      setError(null)
      await triggerAnalysis(projectId)
      await fetchProject()
      await fetchStatus()
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to trigger analysis"
      )
    } finally {
      setTriggering(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!project) {
    return (
      <div className="container mx-auto max-w-3xl px-4 py-8">
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error ?? "Project not found"}
        </div>
        <Button
          variant="ghost"
          className="mt-4"
          onClick={() => router.push("/projects")}
        >
          <ArrowLeft className="mr-2 size-4" />
          Back to Projects
        </Button>
      </div>
    )
  }

  const isAnalyzing = project.status === "analyzing"
  const isAnalyzed = project.status === "analyzed"
  const isFailed = project.status === "failed"

  return (
    <div className="container mx-auto max-w-3xl px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <Button
          variant="ghost"
          size="sm"
          className="mb-4"
          onClick={() => router.push("/projects")}
        >
          <ArrowLeft className="mr-2 size-4" />
          Back to Projects
        </Button>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {project.name}
            </h1>
            <p className="mt-1 font-mono text-sm text-muted-foreground">
              {project.source_path}
            </p>
          </div>
          <StatusBadgeLarge status={project.status} />
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Actions */}
      <div className="mb-6 flex gap-3">
        <Button
          size="lg"
          onClick={handleTriggerAnalysis}
          disabled={isAnalyzing || triggering}
        >
          {isAnalyzing || triggering ? (
            <Loader2 className="mr-2 size-4 animate-spin" />
          ) : (
            <Play className="mr-2 size-4" />
          )}
          {isAnalyzing ? "Analyzing..." : "Run Analysis"}
        </Button>

        {isAnalyzed && (
          <Button
            size="lg"
            variant="outline"
            onClick={() => router.push(`/projects/${projectId}/graph`)}
          >
            <ExternalLink className="mr-2 size-4" />
            View Graph
          </Button>
        )}
      </div>

      {/* Project Details */}
      <div className="grid gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Project Details</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">ID</dt>
              <dd className="font-mono text-xs">{project.id}</dd>
              <dt className="text-muted-foreground">Created</dt>
              <dd>{formatDate(project.created_at)}</dd>
              {project.updated_at && (
                <>
                  <dt className="text-muted-foreground">Last Updated</dt>
                  <dd>{formatDate(project.updated_at)}</dd>
                </>
              )}
              <dt className="text-muted-foreground">Status</dt>
              <dd className="capitalize">{project.status}</dd>
            </dl>
          </CardContent>
        </Card>

        {/* Analysis Status */}
        {analysisStatus && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Analysis Status</CardTitle>
              <CardDescription>
                {isAnalyzing
                  ? "Analysis is running..."
                  : isAnalyzed
                    ? "Analysis completed successfully"
                    : isFailed
                      ? "Analysis encountered an error"
                      : "Ready for analysis"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {analysisStatus.current_stage && (
                <div className="mb-4">
                  <p className="text-sm font-medium">
                    Current Stage:{" "}
                    <span className="font-mono">
                      {analysisStatus.current_stage}
                    </span>
                  </p>
                  {analysisStatus.progress !== undefined && (
                    <div className="mt-2">
                      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                        <div
                          className="h-full rounded-full bg-primary transition-all duration-500"
                          style={{
                            width: `${Math.round(analysisStatus.progress * 100)}%`,
                          }}
                        />
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {Math.round(analysisStatus.progress * 100)}% complete
                      </p>
                    </div>
                  )}
                </div>
              )}

              {analysisStatus.stages && analysisStatus.stages.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">Pipeline Stages</p>
                  <ul className="space-y-1">
                    {analysisStatus.stages.map((stage) => (
                      <li
                        key={stage.name}
                        className="flex items-center gap-2 text-sm"
                      >
                        {stage.status === "completed" ? (
                          <CheckCircle2 className="size-4 text-green-600" />
                        ) : stage.status === "running" ? (
                          <Loader2 className="size-4 animate-spin text-blue-600" />
                        ) : stage.status === "failed" ? (
                          <XCircle className="size-4 text-destructive" />
                        ) : (
                          <div className="size-4 rounded-full border" />
                        )}
                        <span className="font-mono text-xs">{stage.name}</span>
                        {stage.duration_ms !== undefined && (
                          <span className="text-xs text-muted-foreground">
                            ({(stage.duration_ms / 1000).toFixed(1)}s)
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Error Display */}
        {isFailed && analysisStatus?.error && (
          <Card className="border-destructive/50">
            <CardHeader>
              <CardTitle className="text-base text-destructive">
                Analysis Error
              </CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="overflow-x-auto rounded-md bg-destructive/5 p-3 font-mono text-xs text-destructive">
                {analysisStatus.error}
              </pre>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

function StatusBadgeLarge({ status }: { status: string }) {
  const map: Record<string, { label: string; className: string }> = {
    created: {
      label: "Created",
      className: "bg-secondary text-secondary-foreground",
    },
    analyzing: {
      label: "Analyzing",
      className: "animate-pulse bg-blue-600 text-white",
    },
    analyzed: {
      label: "Analyzed",
      className: "bg-green-600 text-white",
    },
    failed: {
      label: "Failed",
      className: "bg-destructive/10 text-destructive",
    },
  }
  const config = map[status] ?? {
    label: status,
    className: "bg-secondary text-secondary-foreground",
  }
  return (
    <span
      className={`inline-flex items-center rounded-md px-2.5 py-1 text-xs font-medium ${config.className}`}
    >
      {config.label}
    </span>
  )
}
