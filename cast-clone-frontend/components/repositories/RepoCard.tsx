"use client";

import * as React from "react";
import Link from "next/link";
import { GitBranch, Loader2, Lock, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { RepositoryResponse } from "@/lib/types";

interface RepoCardProps {
  repo: RepositoryResponse;
  onDelete: (id: string) => void;
}

const cloneStatusConfig: Record<string, { label: string; color: string }> = {
  pending: { label: "Pending", color: "bg-yellow-500/10 text-yellow-700 dark:text-yellow-400" },
  cloning: { label: "Cloning...", color: "bg-blue-500/10 text-blue-700 dark:text-blue-400" },
  cloned: { label: "Ready", color: "bg-green-500/10 text-green-700 dark:text-green-400" },
  clone_failed: { label: "Failed", color: "bg-red-500/10 text-red-700 dark:text-red-400" },
};

export function RepoCard({ repo, onDelete }: RepoCardProps) {
  const statusInfo = cloneStatusConfig[repo.clone_status] ?? cloneStatusConfig.pending;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base font-medium">
          <Link href={`/repositories/${repo.id}`} className="hover:underline">
            {repo.repo_full_name}
          </Link>
        </CardTitle>
        <div className="flex items-center gap-1.5">
          {repo.is_private && <Lock className="size-3.5 text-muted-foreground" />}
          <Badge variant="outline" className={statusInfo.color}>
            {repo.clone_status === "cloning" && <Loader2 className="mr-1 size-3 animate-spin" />}
            {statusInfo.label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {repo.description && (
          <p className="mb-2 line-clamp-2 text-sm text-muted-foreground">{repo.description}</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {repo.language && <Badge variant="secondary" className="text-xs">{repo.language}</Badge>}
          {repo.projects.map((p) => (
            <Link key={p.id} href={`/repositories/${repo.id}/${encodeURIComponent(p.branch ?? "main")}`}>
              <Badge variant="outline" className="text-xs hover:bg-accent">
                <GitBranch className="mr-0.5 size-3" />
                {p.branch ?? "main"}
              </Badge>
            </Link>
          ))}
        </div>
        {/* LOC billing info */}
        {repo.billable_loc != null && repo.billable_loc > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            Billable: {repo.billable_loc.toLocaleString()} LOC
            {repo.max_loc_branch && (
              <span className="ml-1">({repo.max_loc_branch})</span>
            )}
          </p>
        )}
        {repo.clone_error && <p className="mt-2 text-xs text-destructive">{repo.clone_error}</p>}
        <div className="mt-3 flex justify-end">
          <Button variant="ghost" size="sm" className="text-destructive" onClick={() => onDelete(repo.id)}>
            <Trash2 className="mr-1 size-3.5" />Delete
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
