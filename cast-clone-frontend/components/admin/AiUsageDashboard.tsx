// cast-clone-frontend/components/admin/AiUsageDashboard.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { getAiUsageSummary } from "@/lib/api";
import type { UsageSummaryResponse } from "@/lib/types";
import { Activity, DollarSign, Zap, BarChart3 } from "lucide-react";

function formatTokens(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
  return String(count);
}

function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    chat: "AI Chat",
    summary: "AI Summaries",
    pr_analysis: "PR Analysis",
    mcp: "MCP Server",
  };
  return labels[source] || source;
}

interface StatCardProps {
  label: string;
  value: string;
  icon: React.ReactNode;
}

function StatCard({ label, value, icon }: StatCardProps) {
  return (
    <div className="rounded-lg border p-4">
      <div className="flex items-center gap-2 text-muted-foreground">
        {icon}
        <span className="text-sm font-medium">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-bold">{value}</p>
    </div>
  );
}

interface AiUsageDashboardProps {
  className?: string;
}

export function AiUsageDashboard({ className }: AiUsageDashboardProps) {
  const [data, setData] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getAiUsageSummary(days);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load usage data");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return <div className="py-12 text-center text-muted-foreground">Loading usage data...</div>;
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
        {error}
      </div>
    );
  }

  if (!data) return null;

  const totalTokens = data.total_input_tokens + data.total_output_tokens;

  return (
    <div className={className}>
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold">AI Usage</h3>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded-md border bg-background px-2 py-1 text-sm"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      {/* Summary Cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard
          label="Total Tokens"
          value={formatTokens(totalTokens)}
          icon={<Zap className="h-4 w-4" />}
        />
        <StatCard
          label="Estimated Cost"
          value={formatCost(data.total_estimated_cost_usd)}
          icon={<DollarSign className="h-4 w-4" />}
        />
        <StatCard
          label="API Calls"
          value={String(data.by_source.reduce((sum, s) => sum + s.count, 0))}
          icon={<Activity className="h-4 w-4" />}
        />
      </div>

      {/* Breakdown by Source */}
      {data.by_source.length > 0 && (
        <div className="mb-6">
          <h4 className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <BarChart3 className="h-4 w-4" />
            Breakdown by Source
          </h4>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Source</th>
                  <th className="px-4 py-2 text-right font-medium">Calls</th>
                  <th className="px-4 py-2 text-right font-medium">Input Tokens</th>
                  <th className="px-4 py-2 text-right font-medium">Output Tokens</th>
                  <th className="px-4 py-2 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.by_source.map((s) => (
                  <tr key={s.source} className="border-b last:border-0">
                    <td className="px-4 py-2">{sourceLabel(s.source)}</td>
                    <td className="px-4 py-2 text-right">{s.count}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {formatTokens(s.input_tokens)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {formatTokens(s.output_tokens)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {formatCost(s.estimated_cost_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Breakdown by Project */}
      {data.by_project.length > 0 && (
        <div>
          <h4 className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <BarChart3 className="h-4 w-4" />
            Usage by Project
          </h4>
          <div className="space-y-2">
            {data.by_project.map((p) => {
              const pct =
                data.total_estimated_cost_usd > 0
                  ? (p.estimated_cost_usd / data.total_estimated_cost_usd) * 100
                  : 0;
              return (
                <div key={p.project_id} className="rounded-lg border p-3">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-sm font-medium">{p.project_name}</span>
                    <span className="text-sm font-mono text-muted-foreground">
                      {formatCost(p.estimated_cost_usd)}
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-muted">
                    <div
                      className="h-2 rounded-full bg-primary"
                      style={{ width: `${Math.max(pct, 1)}%` }}
                    />
                  </div>
                  <div className="mt-1 flex justify-between text-xs text-muted-foreground">
                    <span>{p.count} calls</span>
                    <span>
                      {formatTokens(p.input_tokens)} in / {formatTokens(p.output_tokens)} out
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {data.by_source.length === 0 && data.by_project.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          No AI usage recorded in this time period.
        </div>
      )}
    </div>
  );
}
