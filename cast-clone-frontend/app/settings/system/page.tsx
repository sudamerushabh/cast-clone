"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Clock,
  Copy,
  Check,
  Database,
  GitFork,
  HardDrive,
  Cpu,
  RefreshCw,
  Server,
  Shield,
  Bot,
  Network,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { getSystemInfo } from "@/lib/api";
import type { SystemInfoResponse } from "@/lib/types";

// ── Helpers ──

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button
      onClick={handleCopy}
      className="ml-1.5 text-muted-foreground hover:text-foreground"
      title="Copy to clipboard"
    >
      {copied ? (
        <Check className="size-3 text-emerald-500" />
      ) : (
        <Copy className="size-3" />
      )}
    </button>
  );
}

function StatusDot({ status }: { status: "up" | "down" }) {
  return (
    <span
      className={`inline-block size-2 rounded-full ${
        status === "up" ? "bg-emerald-500" : "bg-red-500"
      }`}
    />
  );
}

function DetailRow({
  label,
  value,
  copyable,
  mono,
  icon: Icon,
}: {
  label: string;
  value: string | number | null;
  copyable?: boolean;
  mono?: boolean;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  const displayValue = value ?? "—";
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {Icon && <Icon className="size-3.5 shrink-0" />}
        {label}
      </div>
      <div className="flex items-center">
        <span
          className={`text-xs text-right ${mono ? "font-mono" : ""}`}
        >
          {displayValue}
        </span>
        {copyable && typeof value === "string" && <CopyButton value={value} />}
      </div>
    </div>
  );
}

function formatSeconds(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

const SERVICE_LABELS: Record<string, { label: string; description: string }> = {
  postgres: { label: "PostgreSQL", description: "Metadata & user storage" },
  neo4j: { label: "Neo4j", description: "Graph database" },
  redis: { label: "Redis", description: "Cache & pub/sub" },
  minio: { label: "MinIO", description: "Object storage" },
};

// ── Main Page ──

export default function SystemSettingsPage() {
  const [info, setInfo] = useState<SystemInfoResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await getSystemInfo();
      setInfo(data);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load system info");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function handleRefresh() {
    setRefreshing(true);
    load();
  }

  if (loading) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-semibold">System Settings</h1>
        <p className="mt-2 text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (error || !info) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-semibold">System Settings</h1>
        <div className="mt-4 rounded-lg border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">
          {error || "Unable to load system information"}
        </div>
      </div>
    );
  }

  const { health, instance, analysis, ai, connections } = info;
  const healthyCount = Object.values(health.services).filter(
    (s) => s === "up"
  ).length;
  const totalServices = Object.keys(health.services).length;

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">System Settings</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Infrastructure health, instance configuration, and analysis settings
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          <RefreshCw
            className={`mr-1.5 size-3 ${refreshing ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </div>

      {/* ── Infrastructure Health ── */}
      <section className="rounded-lg border p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="size-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold">Infrastructure Health</h2>
          </div>
          <Badge
            variant="outline"
            className={
              health.status === "healthy"
                ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
                : "bg-red-500/10 text-red-600 border-red-500/20"
            }
          >
            {healthyCount}/{totalServices} services up
          </Badge>
        </div>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {Object.entries(health.services).map(([key, status]) => {
            const meta = SERVICE_LABELS[key] ?? {
              label: key,
              description: "",
            };
            return (
              <div
                key={key}
                className="flex items-center gap-3 rounded-md border px-3 py-2.5"
              >
                <StatusDot status={status} />
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium">{meta.label}</div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    {meta.description}
                  </div>
                </div>
                <span className="text-[11px] text-muted-foreground capitalize">
                  {status}
                </span>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Instance Info ── */}
      <section className="rounded-lg border p-4">
        <div className="mb-3 flex items-center gap-2">
          <Server className="size-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Instance Information</h2>
        </div>
        <div className="divide-y">
          <DetailRow
            label="Installation ID"
            value={instance.installation_id}
            copyable
            mono
            icon={HardDrive}
          />
          <DetailRow
            label="Authentication"
            value={instance.auth_disabled ? "Disabled (dev mode)" : "Enabled"}
            icon={Shield}
          />
          <DetailRow
            label="License Enforcement"
            value={
              instance.license_disabled
                ? "Disabled (dev mode)"
                : "Enabled"
            }
            icon={Shield}
          />
          <DetailRow
            label="Python"
            value={instance.python_version}
            icon={Cpu}
          />
          <DetailRow
            label="OS"
            value={instance.os}
            icon={Server}
          />
          <DetailRow
            label="CPU Cores"
            value={instance.cpu_count}
            icon={Cpu}
          />
        </div>
      </section>

      {/* ── Connections ── */}
      <section className="rounded-lg border p-4">
        <div className="mb-3 flex items-center gap-2">
          <Network className="size-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Service Connections</h2>
        </div>
        <div className="divide-y">
          <DetailRow
            label="PostgreSQL"
            value={connections.database_host}
            mono
            copyable
            icon={Database}
          />
          <DetailRow
            label="Neo4j"
            value={connections.neo4j_uri}
            mono
            copyable
            icon={Database}
          />
          <DetailRow
            label="Redis"
            value={connections.redis_url}
            mono
            copyable
            icon={Database}
          />
          <DetailRow
            label="MinIO"
            value={connections.minio_endpoint}
            mono
            copyable
            icon={HardDrive}
          />
        </div>
      </section>

      {/* ── Analysis Pipeline ── */}
      <section className="rounded-lg border p-4">
        <div className="mb-3 flex items-center gap-2">
          <GitFork className="size-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Analysis Pipeline</h2>
        </div>
        <p className="mb-3 text-[11px] text-muted-foreground">
          These settings are configured via environment variables and require a
          restart to change.
        </p>
        <div className="divide-y">
          <DetailRow
            label="Total Analysis Timeout"
            value={formatSeconds(analysis.total_timeout_seconds)}
            icon={Clock}
          />
          <DetailRow
            label="SCIP Indexer Timeout"
            value={formatSeconds(analysis.scip_timeout_seconds)}
            icon={Clock}
          />
          <DetailRow
            label="Git Clone Timeout"
            value={formatSeconds(analysis.git_clone_timeout_seconds)}
            icon={Clock}
          />
          <DetailRow
            label="Max Traversal Depth"
            value={analysis.max_traversal_depth}
            icon={GitFork}
          />
          <DetailRow
            label="Tree-sitter Workers"
            value={`${analysis.treesitter_workers} threads`}
            icon={Cpu}
          />
          <DetailRow
            label="Repository Storage"
            value={analysis.repo_storage_path}
            mono
            icon={HardDrive}
          />
        </div>
      </section>

      {/* ── AI Configuration ── */}
      <section className="rounded-lg border p-4">
        <div className="mb-3 flex items-center gap-2">
          <Bot className="size-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">AI Configuration</h2>
        </div>
        <div className="divide-y">
          <DetailRow
            label="PR Analysis Model"
            value={ai.pr_analysis_model}
            mono
            icon={Bot}
          />
          <DetailRow
            label="Chat Model"
            value={ai.chat_model}
            mono
            icon={Bot}
          />
          <DetailRow
            label="Chat Timeout"
            value={formatSeconds(ai.chat_timeout_seconds)}
            icon={Clock}
          />
          <DetailRow
            label="Max Response Tokens"
            value={ai.chat_max_response_tokens.toLocaleString()}
            icon={Bot}
          />
          <DetailRow
            label="MCP Server Port"
            value={ai.mcp_port}
            icon={Network}
          />
        </div>
      </section>
    </div>
  );
}
