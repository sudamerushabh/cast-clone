"use client";
import * as React from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { GitBranch, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getRepository, syncRepository } from "@/lib/api";
import type { RepositoryResponse } from "@/lib/types";

export default function RepoDetailPage() {
  const params = useParams();
  const repoId = params.repoId as string;
  const [repo, setRepo] = React.useState<RepositoryResponse | null>(null);
  const [syncing, setSyncing] = React.useState(false);

  React.useEffect(() => { getRepository(repoId).then(setRepo); }, [repoId]);

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

  if (!repo) {
    return <div className="p-6"><p className="text-muted-foreground">Loading...</p></div>;
  }

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

      <h2 className="mb-3 text-lg font-semibold">Branches</h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {repo.projects.map((p) => (
          <Card key={p.id}>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <GitBranch className="size-4" />
                <Link href={`/repositories/${repoId}/${encodeURIComponent(p.branch ?? "main")}`} className="hover:underline">
                  {p.branch ?? "main"}
                </Link>
                <Badge variant="outline" className={p.status === "analyzed" ? "bg-green-500/10 text-green-700" : ""}>
                  {p.status}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex gap-4 text-sm text-muted-foreground">
                {p.node_count != null && <span>{p.node_count} nodes</span>}
                {p.edge_count != null && <span>{p.edge_count} edges</span>}
                {p.last_analyzed_at && <span>Analyzed {new Date(p.last_analyzed_at).toLocaleDateString()}</span>}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
