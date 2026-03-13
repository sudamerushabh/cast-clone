"use client";
import * as React from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { GitBranch, GitPullRequest, Loader2, Plus, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getRepository, syncRepository, getAnalysisStatus } from "@/lib/api";
import { useRepoPrAnalyses } from "@/hooks/usePullRequests";
import { PrListTable } from "@/components/pull-requests/PrListTable";
import { WebhookSetup } from "@/components/pull-requests/WebhookSetup";
import { AddBranchDialog } from "@/components/repositories/AddBranchDialog";
import type { RepositoryResponse } from "@/lib/types";

export default function RepoDetailPage() {
  const params = useParams();
  const repoId = params.repoId as string;
  const [repo, setRepo] = React.useState<RepositoryResponse | null>(null);
  const [syncing, setSyncing] = React.useState(false);
  const [addBranchOpen, setAddBranchOpen] = React.useState(false);

  const { data: prData, loading: prLoading, refresh: refreshPrs } = useRepoPrAnalyses(repoId);

  React.useEffect(() => { getRepository(repoId).then(setRepo); }, [repoId]);

  // Poll analysis status for any "analyzing" branches
  React.useEffect(() => {
    if (!repo) return;
    const analyzingProjects = repo.projects.filter((p) => p.status === "analyzing");
    if (analyzingProjects.length === 0) return;

    const interval = setInterval(async () => {
      let changed = false;
      for (const proj of analyzingProjects) {
        try {
          const status = await getAnalysisStatus(proj.id);
          if (status.status !== "analyzing") {
            changed = true;
          }
        } catch {
          // ignore polling errors
        }
      }
      if (changed) {
        const updated = await getRepository(repoId);
        setRepo(updated);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [repo, repoId]);

  async function handleSync() {
    setSyncing(true);
    try {
      await syncRepository(repoId);
      const updated = await getRepository(repoId);
      setRepo(updated);
    } finally {
      setSyncing(false);
    }
  }

  async function handleBranchAdded() {
    const updated = await getRepository(repoId);
    setRepo(updated);
  }

  if (!repo) {
    return <div className="p-6"><p className="text-muted-foreground">Loading...</p></div>;
  }

  const existingBranches = repo.projects.map((p) => p.branch ?? "").filter(Boolean);

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{repo.repo_full_name}</h1>
          {repo.description && <p className="mt-1 text-muted-foreground">{repo.description}</p>}
        </div>
        <Button variant="outline" onClick={handleSync} disabled={syncing || repo.clone_status !== "cloned"}>
          <RefreshCw className={`mr-1.5 size-4 ${syncing ? "animate-spin" : ""}`} />
          {syncing ? "Syncing..." : "Sync"}
        </Button>
      </div>

      {/* Branches */}
      <h2 className="mb-3 text-lg font-semibold">Branches</h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 mb-8">
        {repo.projects.map((p) => (
          <Card key={p.id}>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <GitBranch className="size-4" />
                <Link href={`/repositories/${repoId}/${encodeURIComponent(p.branch ?? "main")}`} className="hover:underline">
                  {p.branch ?? "main"}
                </Link>
                <Badge variant="outline" className={
                  p.status === "analyzed"
                    ? "bg-green-500/10 text-green-700"
                    : p.status === "analyzing"
                      ? "bg-amber-500/10 text-amber-700"
                      : ""
                }>
                  {p.status === "analyzing" && <Loader2 className="mr-1 size-3 animate-spin" />}
                  {p.status}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex gap-4 text-sm text-muted-foreground">
                {p.status === "analyzing" ? (
                  <span>Analysis in progress...</span>
                ) : (
                  <>
                    {p.node_count != null && <span>{p.node_count} nodes</span>}
                    {p.edge_count != null && <span>{p.edge_count} edges</span>}
                    {p.last_analyzed_at && <span>Analyzed {new Date(p.last_analyzed_at).toLocaleDateString()}</span>}
                  </>
                )}
              </div>
            </CardContent>
          </Card>
        ))}

        {/* Add Branch card */}
        <button
          type="button"
          onClick={() => setAddBranchOpen(true)}
          className="flex min-h-[88px] items-center justify-center rounded-xl border-2 border-dashed border-muted-foreground/25 text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary"
        >
          <Plus className="mr-1.5 size-4" />
          <span className="text-sm font-medium">Add Branch</span>
        </button>
      </div>

      <AddBranchDialog
        open={addBranchOpen}
        onOpenChange={setAddBranchOpen}
        repoId={repoId}
        connectorId={repo.connector_id}
        repoFullName={repo.repo_full_name}
        existingBranches={existingBranches}
        onBranchAdded={handleBranchAdded}
      />

      {/* Pull Requests */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <GitPullRequest className="size-5" />
          Pull Requests
        </h2>
        {prData && prData.total > 0 && (
          <Link
            href={`/repositories/${repoId}/pull-requests`}
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            View all ({prData.total})
          </Link>
        )}
      </div>
      <WebhookSetup repoId={repoId} defaultBranch={repo.default_branch ?? "main"} />
      {prLoading && (
        <p className="text-sm text-muted-foreground py-4">Loading pull requests...</p>
      )}
      {prData && (
        <PrListTable items={prData.items} basePath={`/repositories/${repoId}`} />
      )}
    </div>
  );
}
