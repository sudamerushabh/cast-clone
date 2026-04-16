"use client";

import * as React from "react";
import Link from "next/link";
import {
  FolderGit2,
  GitBranch,
  Settings,
  ArrowRight,
  Activity,
  Heart,
  Loader2,
  GitPullRequest,
  Plus,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  listRepositories,
  listConnectors,
  getActivityFeed,
  getHealth,
} from "@/lib/api";
import type { HealthResponse } from "@/lib/api";
import type {
  RepositoryResponse,
  ActivityLogEntry,
} from "@/lib/types";

// ── Helpers ────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

const cloneStatusConfig: Record<string, { label: string; color: string }> = {
  pending: { label: "Pending", color: "bg-yellow-500/10 text-yellow-700 dark:text-yellow-400" },
  cloning: { label: "Cloning", color: "bg-blue-500/10 text-blue-700 dark:text-blue-400" },
  cloned: { label: "Ready", color: "bg-green-500/10 text-green-700 dark:text-green-400" },
  clone_failed: { label: "Failed", color: "bg-red-500/10 text-red-700 dark:text-red-400" },
};

function actionLabel(action: string): string {
  return action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Quick Links ────────────────────────────────────────────────

const quickLinks = [
  {
    label: "Repositories",
    description: "Browse and analyse connected codebases",
    href: "/repositories",
    icon: FolderGit2,
  },
  {
    label: "Connectors",
    description: "Manage Git source connections",
    href: "/connectors",
    icon: GitBranch,
  },
  {
    label: "Settings",
    description: "System and AI configuration",
    href: "/settings/system",
    icon: Settings,
  },
];

// ── Page Component ─────────────────────────────────────────────

export default function HomePage() {
  const [repos, setRepos] = React.useState<RepositoryResponse[]>([]);
  const [connectorCount, setConnectorCount] = React.useState<number>(0);
  const [activity, setActivity] = React.useState<ActivityLogEntry[]>([]);
  const [health, setHealth] = React.useState<HealthResponse | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    async function load() {
      const [reposResult, connectorsResult, activityResult, healthResult] =
        await Promise.allSettled([
          listRepositories(),
          listConnectors(),
          getActivityFeed({ limit: 8 }),
          getHealth(),
        ]);

      if (reposResult.status === "fulfilled") setRepos(reposResult.value.repositories);
      if (connectorsResult.status === "fulfilled") setConnectorCount(connectorsResult.value.total);
      if (activityResult.status === "fulfilled") setActivity(activityResult.value);
      if (healthResult.status === "fulfilled") setHealth(healthResult.value);

      setLoading(false);
    }
    load();
  }, []);

  const analyzedBranches = repos
    .flatMap((r) => r.projects)
    .filter((p) => p.status === "analyzed").length;

  const totalBranches = repos.flatMap((r) => r.projects).length;

  // ── Render ─────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-8 p-6">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight">Welcome to ChangeSafe</h1>
        <p className="text-sm text-muted-foreground">
          Your software architecture intelligence platform
        </p>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Link href="/repositories">
          <Card className="transition-colors hover:bg-accent/50 cursor-pointer">
            <CardContent className="flex items-center gap-3 p-4">
              <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
                <FolderGit2 className="size-4 text-primary" />
              </div>
              <div className="min-w-0">
                {loading ? (
                  <Loader2 className="size-4 animate-spin text-muted-foreground" />
                ) : (
                  <p className="text-xl font-bold">{repos.length}</p>
                )}
                <p className="text-xs text-muted-foreground truncate">Repositories</p>
              </div>
            </CardContent>
          </Card>
        </Link>

        <Link href="/connectors">
          <Card className="transition-colors hover:bg-accent/50 cursor-pointer">
            <CardContent className="flex items-center gap-3 p-4">
              <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
                <GitBranch className="size-4 text-primary" />
              </div>
              <div className="min-w-0">
                {loading ? (
                  <Loader2 className="size-4 animate-spin text-muted-foreground" />
                ) : (
                  <p className="text-xl font-bold">{connectorCount}</p>
                )}
                <p className="text-xs text-muted-foreground truncate">Connectors</p>
              </div>
            </CardContent>
          </Card>
        </Link>

        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
              <GitPullRequest className="size-4 text-primary" />
            </div>
            <div className="min-w-0">
              {loading ? (
                <Loader2 className="size-4 animate-spin text-muted-foreground" />
              ) : (
                <p className="text-xl font-bold">
                  {analyzedBranches}
                  <span className="text-sm font-normal text-muted-foreground">/{totalBranches}</span>
                </p>
              )}
              <p className="text-xs text-muted-foreground truncate">Analyzed Branches</p>
            </div>
          </CardContent>
        </Card>

        <Link href="/settings/system">
          <Card className="transition-colors hover:bg-accent/50 cursor-pointer">
            <CardContent className="flex items-center gap-3 p-4">
              <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
                <Heart className="size-4 text-primary" />
              </div>
              <div className="min-w-0">
                {loading ? (
                  <Loader2 className="size-4 animate-spin text-muted-foreground" />
                ) : health ? (
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`inline-block size-2 rounded-full ${
                        health.status === "healthy"
                          ? "bg-green-500"
                          : "bg-yellow-500"
                      }`}
                    />
                    <p className="text-sm font-semibold capitalize">{health.status}</p>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">Unavailable</p>
                )}
                <p className="text-xs text-muted-foreground truncate">System Health</p>
              </div>
            </CardContent>
          </Card>
        </Link>
      </div>

      {/* Repositories Section */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            Repositories
          </h2>
          <Link href="/repositories">
            <Button variant="ghost" size="sm" className="text-xs">
              View all <ArrowRight className="ml-1 size-3" />
            </Button>
          </Link>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
            <Loader2 className="size-4 animate-spin" /> Loading repositories...
          </div>
        ) : repos.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
              <FolderGit2 className="size-8 text-muted-foreground/40" />
              <div>
                <p className="text-sm font-medium">No repositories yet</p>
                <p className="text-xs text-muted-foreground">
                  Connect a Git provider and add your first repository to get started
                </p>
              </div>
              <Link href="/connectors/new">
                <Button size="sm">
                  <Plus className="mr-1.5 size-3.5" /> Add Connector
                </Button>
              </Link>
            </CardContent>
          </Card>
        ) : (
          <div className="rounded-lg border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Repository</th>
                  <th className="px-3 py-2 font-medium hidden sm:table-cell">Language</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium hidden sm:table-cell">Branches</th>
                  <th className="px-3 py-2 font-medium hidden md:table-cell">Last Synced</th>
                </tr>
              </thead>
              <tbody>
                {repos.slice(0, 6).map((repo) => {
                  const statusInfo = cloneStatusConfig[repo.clone_status] ?? cloneStatusConfig.pending;
                  return (
                    <tr key={repo.id} className="border-b last:border-b-0 hover:bg-accent/30 transition-colors">
                      <td className="px-3 py-2.5">
                        <Link
                          href={`/repositories/${repo.id}`}
                          className="font-medium hover:underline"
                        >
                          {repo.repo_full_name}
                        </Link>
                      </td>
                      <td className="px-3 py-2.5 hidden sm:table-cell">
                        {repo.language ? (
                          <Badge variant="secondary" className="text-xs">
                            {repo.language}
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge variant="outline" className={`text-xs ${statusInfo.color}`}>
                          {repo.clone_status === "cloning" && (
                            <Loader2 className="mr-1 size-3 animate-spin" />
                          )}
                          {statusInfo.label}
                        </Badge>
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground hidden sm:table-cell">
                        {repo.projects.length}
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground hidden md:table-cell">
                        {repo.last_synced_at ? relativeTime(repo.last_synced_at) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {repos.length > 6 && (
              <div className="border-t px-3 py-2 text-center">
                <Link href="/repositories" className="text-xs text-primary hover:underline">
                  View all {repos.length} repositories
                </Link>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Recent Activity / Onboarding */}
      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
          {activity.length > 0 ? "Recent Activity" : "How it works"}
        </h2>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
            <Loader2 className="size-4 animate-spin" /> Loading activity...
          </div>
        ) : activity.length > 0 ? (
          <div className="flex flex-col gap-1 max-h-[220px] overflow-y-auto rounded-lg border p-1">
            {activity.map((entry) => (
              <div
                key={entry.id}
                className="flex items-start gap-3 rounded-md px-3 py-2 text-sm hover:bg-accent/30 transition-colors"
              >
                <Activity className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                <div className="flex-1 min-w-0">
                  <span className="text-foreground">
                    {entry.user?.username && (
                      <span className="font-medium">{entry.user.username} </span>
                    )}
                    {actionLabel(entry.action)}
                    {entry.resource_type && (
                      <span className="text-muted-foreground"> {entry.resource_type}</span>
                    )}
                  </span>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {relativeTime(entry.created_at)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <ol className="flex flex-col gap-2 text-sm text-muted-foreground">
            <li className="flex gap-3">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                1
              </span>
              <span>Add a Git connector pointing to your source repository.</span>
            </li>
            <li className="flex gap-3">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                2
              </span>
              <span>Run an analysis — the pipeline parses code and builds a graph in Neo4j.</span>
            </li>
            <li className="flex gap-3">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                3
              </span>
              <span>Explore architecture views, transaction flows, and impact analysis.</span>
            </li>
          </ol>
        )}
      </div>

      {/* Quick Links */}
      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
          Quick actions
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {quickLinks.map(({ label, description, href, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="group flex flex-col gap-3 rounded-lg border bg-card p-4 transition-colors hover:bg-accent/50"
            >
              <div className="flex items-center justify-between">
                <div className="flex size-9 items-center justify-center rounded-md bg-primary/10">
                  <Icon className="size-4 text-primary" />
                </div>
                <ArrowRight className="size-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">{label}</span>
                <span className="text-xs text-muted-foreground">{description}</span>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
