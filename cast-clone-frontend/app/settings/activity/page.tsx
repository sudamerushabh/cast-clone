"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { getActivityFeed, getActivityStats } from "@/lib/api";
import type { ActivityLogEntry, ActivityStatsResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Activity,
  Bot,
  Clock,
  FolderPlus,
  GitFork,
  Key,
  LogIn,
  Mail,
  Play,
  RefreshCw,
  Settings,
  Shield,
  Trash2,
  Unplug,
  Users,
  Eye,
  Tag,
  MessageSquare,
  AlertTriangle,
  Check,
  X,
  ChevronDown,
} from "lucide-react";

// ── Action metadata ──

interface ActionMeta {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string; // tailwind bg- class
  category: string;
}

const ACTION_META: Record<string, ActionMeta> = {
  // Auth
  "user.login": { label: "Signed in", icon: LogIn, color: "bg-blue-500", category: "auth" },
  "user.created": { label: "User created (setup)", icon: Users, color: "bg-blue-500", category: "auth" },
  "user.admin_created": { label: "User created", icon: Users, color: "bg-blue-500", category: "user" },
  "user.updated": { label: "User updated", icon: Users, color: "bg-blue-500", category: "user" },
  "user.deactivated": { label: "User deactivated", icon: Users, color: "bg-red-500", category: "user" },
  // Projects
  "project.created": { label: "Project created", icon: FolderPlus, color: "bg-emerald-500", category: "project" },
  "project.deleted": { label: "Project deleted", icon: Trash2, color: "bg-red-500", category: "project" },
  // Analysis
  "analysis.started": { label: "Analysis started", icon: Play, color: "bg-amber-500", category: "analysis" },
  "analysis.completed": { label: "Analysis completed", icon: Check, color: "bg-emerald-500", category: "analysis" },
  "analysis.failed": { label: "Analysis failed", icon: X, color: "bg-red-500", category: "analysis" },
  // Repositories
  "repository.created": { label: "Repository onboarded", icon: GitFork, color: "bg-emerald-500", category: "repository" },
  "repository.deleted": { label: "Repository removed", icon: Trash2, color: "bg-red-500", category: "repository" },
  "repository.synced": { label: "Repository synced", icon: RefreshCw, color: "bg-blue-500", category: "repository" },
  // Connectors
  "connector.created": { label: "Connector added", icon: Unplug, color: "bg-indigo-500", category: "connector" },
  "connector.deleted": { label: "Connector removed", icon: Trash2, color: "bg-red-500", category: "connector" },
  // Git config
  "git_config.created": { label: "Git config created", icon: Settings, color: "bg-indigo-500", category: "git_config" },
  "git_config.updated": { label: "Git config updated", icon: Settings, color: "bg-indigo-500", category: "git_config" },
  "git_config.deleted": { label: "Git config deleted", icon: Trash2, color: "bg-red-500", category: "git_config" },
  // Annotations & tags
  "annotation.created": { label: "Annotation added", icon: MessageSquare, color: "bg-purple-500", category: "annotation" },
  "annotation.deleted": { label: "Annotation removed", icon: Trash2, color: "bg-red-500", category: "annotation" },
  "tag.created": { label: "Tag added", icon: Tag, color: "bg-orange-500", category: "tag" },
  "tag.deleted": { label: "Tag removed", icon: Trash2, color: "bg-red-500", category: "tag" },
  // Views
  "view.saved": { label: "View saved", icon: Eye, color: "bg-teal-500", category: "view" },
  "view.deleted": { label: "View deleted", icon: Trash2, color: "bg-red-500", category: "view" },
  // API keys
  "api_key.created": { label: "API key created", icon: Key, color: "bg-yellow-500", category: "api_key" },
  "api_key.revoked": { label: "API key revoked", icon: Shield, color: "bg-red-500", category: "api_key" },
  // Settings
  "settings.ai_updated": { label: "AI config updated", icon: Bot, color: "bg-violet-500", category: "settings" },
  "settings.email_updated": { label: "Email config updated", icon: Mail, color: "bg-cyan-500", category: "settings" },
  // PR Analysis
  "pr_analysis.completed": { label: "PR analysis done", icon: GitFork, color: "bg-emerald-500", category: "pr_analysis" },
  "pr_analysis.failed": { label: "PR analysis failed", icon: AlertTriangle, color: "bg-red-500", category: "pr_analysis" },
  "pr_analysis.deleted": { label: "PR analysis deleted", icon: Trash2, color: "bg-red-500", category: "pr_analysis" },
  "pr_analysis.reanalyzed": { label: "PR re-analyzed", icon: RefreshCw, color: "bg-amber-500", category: "pr_analysis" },
  // License
  "license.uploaded": { label: "License uploaded", icon: Shield, color: "bg-emerald-500", category: "license" },
};

const CATEGORIES = [
  { value: "", label: "All Activity" },
  { value: "project", label: "Projects" },
  { value: "repository", label: "Repositories" },
  { value: "analysis", label: "Analysis" },
  { value: "connector", label: "Connectors" },
  { value: "git_config", label: "Git Config" },
  { value: "user", label: "User Management" },
  { value: "auth", label: "Authentication" },
  { value: "settings", label: "Settings" },
  { value: "license", label: "License" },
  { value: "api_key", label: "API Keys" },
  { value: "pr_analysis", label: "PR Analysis" },
  { value: "annotation", label: "Annotations" },
  { value: "tag", label: "Tags" },
  { value: "view", label: "Saved Views" },
];

// ── Helpers ──

function getActionMeta(action: string): ActionMeta {
  return ACTION_META[action] ?? {
    label: action.replace(".", " ").replace(/_/g, " "),
    icon: Activity,
    color: "bg-muted-foreground",
    category: "other",
  };
}

function relativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = now - then;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

function getDetailText(entry: ActivityLogEntry): string | null {
  if (!entry.details) return null;
  const d = entry.details;
  // Show the most meaningful detail (skip username — shown separately)
  if (d.name) return String(d.name);
  if (d.project_name) return String(d.project_name);
  if (d.full_name) return String(d.full_name);
  if (d.tag_name) return String(d.tag_name);
  if (d.provider && !d.name) return String(d.provider);
  if (d.pr_number) return `PR #${d.pr_number}`;
  if (d.state) return String(d.state);
  if (d.chat_model) return String(d.chat_model);
  if (d.run_id) return `Run ${String(d.run_id).slice(0, 8)}`;
  return null;
}

// ── Components ──

function StatCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <Icon className="size-3.5 text-muted-foreground" />
        <span className="text-[11px] text-muted-foreground">{label}</span>
      </div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function resolveUsername(entry: ActivityLogEntry): string {
  if (entry.user?.username) return entry.user.username;
  // Fall back to username stored in details (e.g. anonymous auth mode)
  const d = entry.details;
  if (d?.username) return String(d.username);
  return "System";
}

function ActivityEntry({ entry }: { entry: ActivityLogEntry }) {
  const meta = getActionMeta(entry.action);
  const Icon = meta.icon;
  const detail = getDetailText(entry);
  const username = resolveUsername(entry);

  return (
    <div className="flex items-start gap-3 py-2.5">
      {/* Icon */}
      <div
        className={`mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full ${meta.color}/15`}
      >
        <Icon className={`size-3.5 ${meta.color.replace("bg-", "text-")}`} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge
            variant="outline"
            className="text-[10px] h-4 px-1.5 font-medium"
          >
            {username}
          </Badge>
          <span className="text-xs text-muted-foreground">{meta.label}</span>
          {detail && (
            <Badge variant="secondary" className="text-[10px] font-mono h-4 px-1.5">
              {detail}
            </Badge>
          )}
        </div>
        {entry.resource_type && (
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {entry.resource_type}
            {entry.resource_id ? ` ${entry.resource_id.slice(0, 8)}...` : ""}
          </div>
        )}
      </div>

      {/* Timestamp */}
      <span
        className="shrink-0 text-[11px] text-muted-foreground"
        title={new Date(entry.created_at).toLocaleString()}
      >
        {relativeTime(entry.created_at)}
      </span>
    </div>
  );
}

// ── Main Page ──

export default function ActivityPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [entries, setEntries] = useState<ActivityLogEntry[]>([]);
  const [stats, setStats] = useState<ActivityStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("");
  const [days, setDays] = useState(30);
  const [showMore, setShowMore] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [feed, statsData] = await Promise.all([
        getActivityFeed({ limit: 200, category: category || undefined, days }),
        getActivityStats(days),
      ]);
      setEntries(feed);
      setStats(statsData);
    } catch {
      setEntries([]);
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, [category, days]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (!isAdmin) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Admin access required
      </div>
    );
  }

  const displayEntries = showMore ? entries : entries.slice(0, 50);
  const hasMore = entries.length > 50 && !showMore;

  // Group entries by date
  const grouped: Record<string, ActivityLogEntry[]> = {};
  for (const entry of displayEntries) {
    const date = new Date(entry.created_at).toLocaleDateString("en-US", {
      weekday: "long",
      month: "short",
      day: "numeric",
    });
    if (!grouped[date]) grouped[date] = [];
    grouped[date].push(entry);
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Activity Log</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Audit trail of actions across the platform
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={loadData}
          disabled={loading}
        >
          <RefreshCw
            className={`mr-1.5 size-3 ${loading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Total Events" value={stats.total} icon={Activity} />
          <StatCard
            label="Active Users"
            value={stats.unique_users}
            icon={Users}
          />
          <StatCard
            label="Event Types"
            value={stats.by_action.length}
            icon={Tag}
          />
          <StatCard
            label="Time Range"
            value={`${days}d`}
            icon={Clock}
          />
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Category filter */}
        <div className="relative">
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="h-7 appearance-none rounded-md border border-input bg-transparent pl-2.5 pr-7 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring cursor-pointer"
          >
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 size-3 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        </div>

        {/* Time range */}
        <div className="flex items-center gap-1">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                days === d
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>

        {/* Count */}
        <span className="text-[11px] text-muted-foreground ml-auto">
          {entries.length} events
        </span>
      </div>

      {/* Activity breakdown mini-bar (top actions) */}
      {stats && stats.by_action.length > 0 && (
        <div className="flex gap-1.5 flex-wrap">
          {stats.by_action.slice(0, 8).map((a) => {
            const meta = getActionMeta(a.action);
            return (
              <button
                key={a.action}
                onClick={() => {
                  // Set category from action
                  const cat = CATEGORIES.find(
                    (c) => c.value && a.action.startsWith(c.value + ".")
                  );
                  if (cat) setCategory(cat.value);
                }}
                className="flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] hover:bg-muted transition-colors"
              >
                <span
                  className={`inline-block size-1.5 rounded-full ${meta.color}`}
                />
                {meta.label}
                <span className="font-medium">{a.count}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Timeline */}
      <div className="rounded-lg border">
        {loading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : entries.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No activity recorded yet"
            description="Actions like creating projects, triggering analyses, and changing settings will appear here."
          />
        ) : (
          <div>
            {Object.entries(grouped).map(([date, dayEntries], groupIdx) => (
              <div key={date}>
                {/* Date separator */}
                <div
                  className={`sticky top-0 z-10 bg-muted/50 backdrop-blur-sm px-4 py-1.5 text-[11px] font-medium text-muted-foreground ${
                    groupIdx > 0 ? "border-t" : ""
                  }`}
                >
                  {date}
                </div>

                {/* Entries */}
                <div className="divide-y px-4">
                  {dayEntries.map((entry) => (
                    <ActivityEntry key={entry.id} entry={entry} />
                  ))}
                </div>
              </div>
            ))}

            {/* Load more */}
            {hasMore && (
              <div className="border-t p-3 text-center">
                <button
                  onClick={() => setShowMore(true)}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  Show {entries.length - 50} more events
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
