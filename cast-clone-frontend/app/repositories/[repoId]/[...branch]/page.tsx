"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock,
  GitGraph,
  Loader2,
  Play,
  RefreshCw,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getRepository,
  triggerAnalysis,
  getAnalysisStatus,
} from "@/lib/api";
import type { RepositoryResponse, ProjectBranchResponse, AnalysisStatusResponse, AnalysisStageStatus } from "@/lib/types";

// ─── Status helpers ─────────────────────────────────────────────────────────

function StatusIcon({ status }: { status: string }) {
  if (status === "analyzing")
    return <Loader2 className="size-4 animate-spin text-blue-500" />;
  if (status === "analyzed")
    return <CheckCircle2 className="size-4 text-green-500" />;
  if (status === "failed")
    return <AlertCircle className="size-4 text-destructive" />;
  return <Clock className="size-4 text-muted-foreground" />;
}

function statusBadgeVariant(status: string) {
  if (status === "analyzed") return "bg-green-500/10 text-green-700 dark:text-green-400";
  if (status === "analyzing") return "bg-blue-500/10 text-blue-700 dark:text-blue-400";
  if (status === "failed") return "bg-destructive/10 text-destructive";
  return "";
}

function stageLabel(stage: string | null | undefined) {
  if (!stage) return null;
  return stage.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function BranchPage() {
  const params = useParams();
  const repoId = params.repoId as string;
  const branchSegments = params.branch as string[];
  const branchName = branchSegments.map(decodeURIComponent).join("/");

  const [repo, setRepo] = React.useState<RepositoryResponse | null>(null);
  const [project, setProject] = React.useState<ProjectBranchResponse | null>(null);
  const [analysisStatus, setAnalysisStatus] = React.useState<AnalysisStatusResponse | null>(null);
  const [triggering, setTriggering] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const pollingRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

  // Load repo + find the matching project for this branch
  async function loadRepo() {
    try {
      const data = await getRepository(repoId);
      setRepo(data);
      const p = data.projects.find((pr) => pr.branch === branchName) ?? null;
      setProject(p);
      return p;
    } catch {
      return null;
    }
  }

  // Poll analysis status while analyzing
  function startPolling(projectId: string) {
    if (pollingRef.current) return;
    pollingRef.current = setInterval(async () => {
      try {
        const s = await getAnalysisStatus(projectId);
        setAnalysisStatus(s);
        if (s.status !== "analyzing") {
          stopPolling();
          await loadRepo(); // refresh node/edge counts
        }
      } catch {
        stopPolling();
      }
    }, 2000);
  }

  function stopPolling() {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }

  React.useEffect(() => {
    loadRepo().then((p) => {
      if (p?.status === "analyzing") {
        startPolling(p.id);
      }
    });
    return () => stopPolling();
  }, [repoId, branchName]);

  async function handleAnalyze() {
    if (!project) return;
    setError(null);
    setTriggering(true);
    try {
      const resp = await triggerAnalysis(project.id);
      setAnalysisStatus({ project_id: project.id, status: "analyzing", current_stage: null, stages: [], started_at: null, completed_at: null });
      setProject((prev) => prev ? { ...prev, status: "analyzing" } : prev);
      startPolling(project.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start analysis");
    } finally {
      setTriggering(false);
    }
  }

  if (!repo || !project) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <p className="text-muted-foreground">
          {!repo ? "Loading…" : `No project found for branch "${branchName}"`}
        </p>
      </div>
    );
  }

  const isAnalyzing = project.status === "analyzing";
  const isAnalyzed = project.status === "analyzed";
  const currentStage = analysisStatus?.current_stage;

  return (
    <div className="flex flex-col gap-6 p-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">
            <Link href={`/repositories/${repoId}`} className="hover:underline">
              {repo.repo_full_name}
            </Link>
            {" / "}
            <span className="font-mono text-foreground">{branchName}</span>
          </p>
          <div className="mt-1 flex items-center gap-2">
            <StatusIcon status={project.status} />
            <Badge variant="outline" className={statusBadgeVariant(project.status)}>
              {isAnalyzing && currentStage ? stageLabel(currentStage) : project.status}
            </Badge>
          </div>
        </div>

        <Button
          onClick={handleAnalyze}
          disabled={isAnalyzing || triggering || repo.clone_status !== "cloned"}
          size="sm"
        >
          {isAnalyzing || triggering ? (
            <Loader2 className="mr-1.5 size-4 animate-spin" />
          ) : (
            <Play className="mr-1.5 size-4" />
          )}
          {isAnalyzed ? "Re-analyse" : "Analyse"}
        </Button>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Clone warning */}
      {repo.clone_status !== "cloned" && (
        <div className="rounded-md bg-yellow-500/10 px-4 py-3 text-sm text-yellow-700 dark:text-yellow-400">
          Repository is still being cloned ({repo.clone_status}). Analysis will be available once cloning is complete.
        </div>
      )}

      {/* Analyzing progress — stage stepper */}
      {isAnalyzing && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Activity className="size-4 text-blue-500" />
              Analysis in progress
            </CardTitle>
          </CardHeader>
          <CardContent>
            {analysisStatus?.stages && analysisStatus.stages.length > 0 ? (
              <div className="space-y-0">
                {analysisStatus.stages.map((stage, idx) => (
                  <div key={stage.name} className="flex items-start gap-3 relative">
                    {/* Vertical connector line */}
                    {idx < analysisStatus.stages.length - 1 && (
                      <div
                        className={`absolute left-[11px] top-[24px] w-[2px] h-[calc(100%-8px)] ${
                          stage.status === "completed"
                            ? "bg-green-500/40"
                            : "bg-border"
                        }`}
                      />
                    )}
                    {/* Stage icon */}
                    <div className="relative z-10 mt-0.5 shrink-0">
                      {stage.status === "completed" ? (
                        <CheckCircle2 className="size-6 text-green-500" />
                      ) : stage.status === "running" ? (
                        <Loader2 className="size-6 text-blue-500 animate-spin" />
                      ) : (
                        <div className="size-6 rounded-full border-2 border-muted-foreground/30 bg-background" />
                      )}
                    </div>
                    {/* Stage text */}
                    <div className={`pb-4 min-w-0 ${stage.status === "pending" ? "opacity-40" : ""}`}>
                      <p className={`text-sm font-medium leading-6 ${
                        stage.status === "running" ? "text-blue-600 dark:text-blue-400" : ""
                      }`}>
                        {stage.label}
                      </p>
                      {stage.status === "running" && (
                        <>
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {stage.description}
                          </p>
                          {stage.progress != null && stage.progress > 0 && (
                            <div className="mt-1.5 flex items-center gap-2">
                              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-blue-100 dark:bg-blue-950">
                                <div
                                  className="h-full rounded-full bg-blue-500 transition-all duration-700 ease-out"
                                  style={{ width: `${stage.progress}%` }}
                                />
                              </div>
                              <span className="text-xs tabular-nums text-muted-foreground">
                                {stage.progress}%
                              </span>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Starting pipeline…</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Stats */}
      {isAnalyzed && (project.node_count != null || project.edge_count != null) && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {project.node_count != null && (
            <Card>
              <CardContent className="pt-4">
                <p className="text-2xl font-bold">{project.node_count.toLocaleString()}</p>
                <p className="text-xs text-muted-foreground">Nodes</p>
              </CardContent>
            </Card>
          )}
          {project.edge_count != null && (
            <Card>
              <CardContent className="pt-4">
                <p className="text-2xl font-bold">{project.edge_count.toLocaleString()}</p>
                <p className="text-xs text-muted-foreground">Edges</p>
              </CardContent>
            </Card>
          )}
          {project.last_analyzed_at && (
            <Card className="col-span-2">
              <CardContent className="pt-4">
                <p className="text-sm font-medium">
                  {new Date(project.last_analyzed_at).toLocaleString()}
                </p>
                <p className="text-xs text-muted-foreground">Last analysed</p>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Navigation links */}
      {isAnalyzed && (
        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            Explore
          </h2>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Link
              href={`/repositories/${repoId}/graph/${encodeURIComponent(branchName)}`}
              className="group flex items-center gap-3 rounded-lg border bg-card p-4 transition-colors hover:bg-accent/50"
            >
              <GitGraph className="size-5 text-primary" />
              <div>
                <p className="text-sm font-medium">Architecture Graph</p>
                <p className="text-xs text-muted-foreground">Modules, classes, and call flows</p>
              </div>
            </Link>
            <Link
              href={`/repositories/${repoId}/transactions/${encodeURIComponent(branchName)}`}
              className="group flex items-center gap-3 rounded-lg border bg-card p-4 transition-colors hover:bg-accent/50"
            >
              <Activity className="size-5 text-primary" />
              <div>
                <p className="text-sm font-medium">Transaction Flows</p>
                <p className="text-xs text-muted-foreground">HTTP endpoint call chains</p>
              </div>
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
