# Phase 5a M10 — Frontend PR Dashboard

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the PR Dashboard UI: Git Integration settings page, PR list view, and PR detail view with AI summary, impact visualization, cross-tech panel, and drift alerts.

**Architecture:** New pages under the project route (`/projects/[id]/pull-requests`), new components for PR list/detail, reuse existing Cytoscape graph overlay for impact visualization. TypeScript types mirror backend schemas. API client functions call the M9 endpoints. Follows existing patterns from Phase 2-4 frontend.

**Tech Stack:** Next.js App Router, TypeScript, Tailwind CSS, Cytoscape.js (reuse Phase 3 impact overlay).

**Depends On:** M9 (PR analysis API endpoints), M3 (git config API).

---

## File Structure

```
cast-clone-frontend/
├── app/
│   └── projects/
│       └── [id]/
│           ├── pull-requests/
│           │   ├── page.tsx                    # CREATE — PR list view
│           │   └── [analysisId]/
│           │       └── page.tsx                # CREATE — PR detail view
│           └── settings/
│               └── git-integration/
│                   └── page.tsx                # CREATE — Git Integration setup
├── components/
│   └── pull-requests/
│       ├── PrListTable.tsx                     # CREATE — sortable/filterable table
│       ├── PrRiskBadge.tsx                     # CREATE — High/Medium/Low badge
│       ├── PrStatusBadge.tsx                   # CREATE — status indicator
│       ├── PrSummaryCard.tsx                   # CREATE — AI summary display
│       ├── PrStatsRow.tsx                      # CREATE — statistics cards
│       ├── PrChangedNodesTable.tsx             # CREATE — changed nodes list
│       ├── PrCrossTechPanel.tsx                # CREATE — API/MQ/DB impacts
│       ├── PrDriftAlerts.tsx                   # CREATE — drift warnings
│       └── GitIntegrationForm.tsx              # CREATE — setup form
├── hooks/
│   └── usePullRequests.ts                      # CREATE — data fetching hooks
└── lib/
    ├── types.ts                                # MODIFY — add PR types
    └── api.ts                                  # MODIFY — add PR API functions
```

---

### Task 1: TypeScript Types + API Client

**Files:**
- Modify: `lib/types.ts`
- Modify: `lib/api.ts`
- Create: `hooks/usePullRequests.ts`

- [ ] **Step 1: Add TypeScript types**

Add to `lib/types.ts`:

```typescript
// ── Phase 5a: PR Analysis Types ──

export interface PrAnalysis {
  id: string;
  repository_id: string;
  platform: string;
  pr_number: number;
  pr_title: string;
  pr_description?: string;
  pr_author: string;
  source_branch: string;
  target_branch: string;
  commit_sha: string;
  pr_url?: string;
  status: "pending" | "analyzing" | "completed" | "failed" | "stale";
  risk_level?: "High" | "Medium" | "Low";
  changed_node_count?: number;
  blast_radius_total?: number;
  files_changed?: number;
  additions?: number;
  deletions?: number;
  ai_summary?: string;
  analysis_duration_ms?: number;
  created_at: string;
  updated_at: string;
}

export interface PrAnalysisList {
  items: PrAnalysis[];
  total: number;
  limit: number;
  offset: number;
}

export interface PrImpactDetail {
  pr_analysis_id: string;
  total_blast_radius: number;
  by_type: Record<string, number>;
  by_depth: Record<string, number>;
  by_layer: Record<string, number>;
  changed_nodes: Array<{
    fqn: string;
    name: string;
    type: string;
    change_type: string;
  }>;
  downstream_count: number;
  upstream_count: number;
  cross_tech: Array<{
    kind: string;
    name: string;
    detail: string;
  }>;
  transactions_affected: string[];
  new_files: string[];
  non_graph_files: string[];
}

export interface PrDriftDetail {
  pr_analysis_id: string;
  has_drift: boolean;
  potential_new_module_deps: Array<{
    from_module: string;
    to_module: string;
  }>;
  circular_deps_affected: string[][];
  new_files_outside_modules: string[];
}

export interface GitConfig {
  id: string;
  repository_id: string;
  platform: string;
  repo_url: string;
  monitored_branches: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface GitConfigCreateResponse extends GitConfig {
  webhook_url: string;
  webhook_secret: string;
}

export interface WebhookUrlInfo {
  webhook_url: string;
  webhook_secret: string;
}
```

- [ ] **Step 2: Add API client functions**

Add to `lib/api.ts`:

```typescript
// ── Phase 5a: PR Analysis API ──

export async function fetchPrAnalyses(
  projectId: string,
  params?: { status?: string; risk?: string; limit?: number; offset?: number }
): Promise<PrAnalysisList> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.risk) searchParams.set("risk", params.risk);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  const url = `${API_BASE}/repositories/${projectId}/pull-requests${qs ? `?${qs}` : ""}`;
  const resp = await fetch(url, { headers: authHeaders() });
  if (!resp.ok) throw new Error("Failed to fetch PR analyses");
  return resp.json();
}

export async function fetchPrAnalysis(
  projectId: string,
  analysisId: string
): Promise<PrAnalysis> {
  const resp = await fetch(
    `${API_BASE}/repositories/${projectId}/pull-requests/${analysisId}`,
    { headers: authHeaders() }
  );
  if (!resp.ok) throw new Error("Failed to fetch PR analysis");
  return resp.json();
}

export async function fetchPrImpact(
  projectId: string,
  analysisId: string
): Promise<PrImpactDetail> {
  const resp = await fetch(
    `${API_BASE}/repositories/${projectId}/pull-requests/${analysisId}/impact`,
    { headers: authHeaders() }
  );
  if (!resp.ok) throw new Error("Failed to fetch PR impact");
  return resp.json();
}

export async function fetchPrDrift(
  projectId: string,
  analysisId: string
): Promise<PrDriftDetail> {
  const resp = await fetch(
    `${API_BASE}/repositories/${projectId}/pull-requests/${analysisId}/drift`,
    { headers: authHeaders() }
  );
  if (!resp.ok) throw new Error("Failed to fetch PR drift");
  return resp.json();
}

export async function reanalyzePr(
  projectId: string,
  analysisId: string
): Promise<void> {
  const resp = await fetch(
    `${API_BASE}/repositories/${projectId}/pull-requests/${analysisId}/reanalyze`,
    { method: "POST", headers: authHeaders() }
  );
  if (!resp.ok) throw new Error("Failed to queue re-analysis");
}

// Git Config
export async function fetchGitConfig(projectId: string): Promise<GitConfig | null> {
  const resp = await fetch(
    `${API_BASE}/repositories/${projectId}/git-config`,
    { headers: authHeaders() }
  );
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error("Failed to fetch git config");
  return resp.json();
}

export async function createGitConfig(
  projectId: string,
  body: { platform: string; repo_url: string; api_token: string; monitored_branches?: string[] }
): Promise<GitConfigCreateResponse> {
  const resp = await fetch(`${API_BASE}/repositories/${projectId}/git-config`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error("Failed to create git config");
  return resp.json();
}

export async function deleteGitConfig(projectId: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/repositories/${projectId}/git-config`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!resp.ok) throw new Error("Failed to delete git config");
}

export async function fetchWebhookUrl(projectId: string): Promise<WebhookUrlInfo> {
  const resp = await fetch(
    `${API_BASE}/repositories/${projectId}/git-config/webhook-url`,
    { headers: authHeaders() }
  );
  if (!resp.ok) throw new Error("Failed to fetch webhook URL");
  return resp.json();
}

export async function testGitConnectivity(projectId: string): Promise<{ status: string; username?: string; message?: string }> {
  const resp = await fetch(
    `${API_BASE}/repositories/${projectId}/git-config/test`,
    { method: "POST", headers: authHeaders() }
  );
  if (!resp.ok) throw new Error("Failed to test connectivity");
  return resp.json();
}
```

- [ ] **Step 3: Create hooks**

```typescript
// hooks/usePullRequests.ts
"use client";
import { useCallback, useEffect, useState } from "react";
import {
  fetchPrAnalyses,
  fetchPrAnalysis,
  fetchPrImpact,
  fetchPrDrift,
} from "@/lib/api";
import type { PrAnalysis, PrAnalysisList, PrImpactDetail, PrDriftDetail } from "@/lib/types";

export function usePrAnalyses(
  projectId: string,
  filters?: { status?: string; risk?: string }
) {
  const [data, setData] = useState<PrAnalysisList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchPrAnalyses(projectId, filters);
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [projectId, filters?.status, filters?.risk]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}

export function usePrDetail(projectId: string, analysisId: string) {
  const [analysis, setAnalysis] = useState<PrAnalysis | null>(null);
  const [impact, setImpact] = useState<PrImpactDetail | null>(null);
  const [drift, setDrift] = useState<PrDriftDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [a, i, d] = await Promise.all([
          fetchPrAnalysis(projectId, analysisId),
          fetchPrImpact(projectId, analysisId).catch(() => null),
          fetchPrDrift(projectId, analysisId).catch(() => null),
        ]);
        setAnalysis(a);
        setImpact(i);
        setDrift(d);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [projectId, analysisId]);

  return { analysis, impact, drift, loading };
}
```

- [ ] **Step 4: Verify typecheck passes**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
cd cast-clone-frontend
git add lib/types.ts lib/api.ts hooks/usePullRequests.ts
git commit -m "feat(phase5a): add PR analysis TypeScript types, API client, and hooks"
```

---

### Task 2: PR List Page + Components

**Files:**
- Create: `components/pull-requests/PrRiskBadge.tsx`
- Create: `components/pull-requests/PrStatusBadge.tsx`
- Create: `components/pull-requests/PrListTable.tsx`
- Create: `app/projects/[id]/pull-requests/page.tsx`

- [ ] **Step 1: Create badge components**

```tsx
// components/pull-requests/PrRiskBadge.tsx
"use client";

const RISK_COLORS: Record<string, string> = {
  High: "bg-red-100 text-red-800 border-red-200",
  Medium: "bg-yellow-100 text-yellow-800 border-yellow-200",
  Low: "bg-green-100 text-green-800 border-green-200",
};

export function PrRiskBadge({ level }: { level: string | null | undefined }) {
  if (!level) return <span className="text-gray-400 text-sm">—</span>;
  const colors = RISK_COLORS[level] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium border ${colors}`}>
      {level}
    </span>
  );
}
```

```tsx
// components/pull-requests/PrStatusBadge.tsx
"use client";

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-gray-100 text-gray-600",
  analyzing: "bg-blue-100 text-blue-700 animate-pulse",
  completed: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  stale: "bg-orange-100 text-orange-700",
};

export function PrStatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${style}`}>
      {status}
    </span>
  );
}
```

- [ ] **Step 2: Create PR list table**

```tsx
// components/pull-requests/PrListTable.tsx
"use client";
import Link from "next/link";
import type { PrAnalysis } from "@/lib/types";
import { PrRiskBadge } from "./PrRiskBadge";
import { PrStatusBadge } from "./PrStatusBadge";

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

interface Props {
  items: PrAnalysis[];
  projectId: string;
}

export function PrListTable({ items, projectId }: Props) {
  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        No pull request analyses yet. Configure Git integration to get started.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">PR</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Author</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Branch</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Risk</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Blast Radius</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {items.map((pr) => (
            <tr key={pr.id} className="hover:bg-gray-50">
              <td className="px-4 py-3">
                <Link
                  href={`/projects/${projectId}/pull-requests/${pr.id}`}
                  className="text-blue-600 hover:text-blue-800 font-medium"
                >
                  #{pr.pr_number}
                </Link>
                <span className="ml-2 text-sm text-gray-700">{pr.pr_title}</span>
              </td>
              <td className="px-4 py-3 text-sm text-gray-600">{pr.pr_author}</td>
              <td className="px-4 py-3 text-xs font-mono text-gray-500">
                {pr.source_branch} → {pr.target_branch}
              </td>
              <td className="px-4 py-3"><PrRiskBadge level={pr.risk_level} /></td>
              <td className="px-4 py-3 text-sm">
                {pr.blast_radius_total != null ? `${pr.blast_radius_total} nodes` : "—"}
              </td>
              <td className="px-4 py-3"><PrStatusBadge status={pr.status} /></td>
              <td className="px-4 py-3 text-xs text-gray-500">{timeAgo(pr.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: Create PR list page**

```tsx
// app/projects/[id]/pull-requests/page.tsx
"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import { usePrAnalyses } from "@/hooks/usePullRequests";
import { PrListTable } from "@/components/pull-requests/PrListTable";

export default function PullRequestsPage() {
  const params = useParams();
  const projectId = params.id as string;
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [riskFilter, setRiskFilter] = useState<string>("");

  const { data, loading, error, refresh } = usePrAnalyses(projectId, {
    status: statusFilter || undefined,
    risk: riskFilter || undefined,
  });

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Pull Requests</h1>
        <button
          onClick={refresh}
          className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-md"
        >
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-4 mb-4">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="border rounded-md px-3 py-1.5 text-sm"
        >
          <option value="">All statuses</option>
          <option value="completed">Completed</option>
          <option value="analyzing">Analyzing</option>
          <option value="pending">Pending</option>
          <option value="failed">Failed</option>
          <option value="stale">Stale</option>
        </select>
        <select
          value={riskFilter}
          onChange={(e) => setRiskFilter(e.target.value)}
          className="border rounded-md px-3 py-1.5 text-sm"
        >
          <option value="">All risk levels</option>
          <option value="High">High</option>
          <option value="Medium">Medium</option>
          <option value="Low">Low</option>
        </select>
      </div>

      {loading && <div className="py-8 text-center text-gray-500">Loading...</div>}
      {error && <div className="py-4 text-red-600">{error}</div>}
      {data && <PrListTable items={data.items} projectId={projectId} />}
      {data && (
        <div className="mt-4 text-sm text-gray-500">
          Showing {data.items.length} of {data.total} analyses
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify typecheck**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
cd cast-clone-frontend
git add components/pull-requests/ app/projects/\[id\]/pull-requests/page.tsx
git commit -m "feat(phase5a): add PR list page with risk/status badges and filters"
```

---

### Task 3: PR Detail Page + Components

**Files:**
- Create: `components/pull-requests/PrSummaryCard.tsx`
- Create: `components/pull-requests/PrStatsRow.tsx`
- Create: `components/pull-requests/PrChangedNodesTable.tsx`
- Create: `components/pull-requests/PrCrossTechPanel.tsx`
- Create: `components/pull-requests/PrDriftAlerts.tsx`
- Create: `app/projects/[id]/pull-requests/[analysisId]/page.tsx`

- [ ] **Step 1: Create detail components**

```tsx
// components/pull-requests/PrSummaryCard.tsx
"use client";

interface Props {
  summary: string | null | undefined;
  onRegenerate?: () => void;
}

export function PrSummaryCard({ summary, onRegenerate }: Props) {
  if (!summary) return null;
  return (
    <div className="bg-white border rounded-lg p-6 mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold text-gray-900">AI Impact Summary</h2>
        {onRegenerate && (
          <button
            onClick={onRegenerate}
            className="text-xs text-blue-600 hover:text-blue-800"
          >
            Regenerate
          </button>
        )}
      </div>
      <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap">
        {summary}
      </div>
    </div>
  );
}
```

```tsx
// components/pull-requests/PrStatsRow.tsx
"use client";

interface StatCardProps {
  label: string;
  value: string | number;
  detail?: string;
}

function StatCard({ label, value, detail }: StatCardProps) {
  return (
    <div className="bg-white border rounded-lg p-4">
      <div className="text-sm text-gray-500">{label}</div>
      <div className="text-2xl font-bold text-gray-900 mt-1">{value}</div>
      {detail && <div className="text-xs text-gray-400 mt-1">{detail}</div>}
    </div>
  );
}

interface Props {
  changedNodes: number;
  blastRadius: number;
  layersAffected: number;
  transactionsAffected: number;
}

export function PrStatsRow({ changedNodes, blastRadius, layersAffected, transactionsAffected }: Props) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <StatCard label="Changed Nodes" value={changedNodes} />
      <StatCard label="Blast Radius" value={blastRadius} detail="unique affected nodes" />
      <StatCard label="Layers Affected" value={layersAffected} />
      <StatCard label="Transactions" value={transactionsAffected} />
    </div>
  );
}
```

```tsx
// components/pull-requests/PrChangedNodesTable.tsx
"use client";

interface ChangedNode {
  fqn: string;
  name: string;
  type: string;
  change_type: string;
}

interface Props {
  nodes: ChangedNode[];
  projectId: string;
}

const TYPE_COLORS: Record<string, string> = {
  Function: "text-blue-600",
  Class: "text-purple-600",
  Interface: "text-green-600",
  Field: "text-orange-600",
  APIEndpoint: "text-red-600",
};

export function PrChangedNodesTable({ nodes, projectId }: Props) {
  if (nodes.length === 0) return null;
  return (
    <div className="bg-white border rounded-lg mb-6">
      <h3 className="px-4 py-3 font-semibold text-gray-900 border-b">Changed Nodes</h3>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Name</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Type</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">FQN</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Change</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {nodes.map((n) => (
              <tr key={n.fqn} className="hover:bg-gray-50">
                <td className="px-4 py-2 text-sm font-medium">{n.name}</td>
                <td className={`px-4 py-2 text-xs ${TYPE_COLORS[n.type] ?? "text-gray-600"}`}>
                  {n.type}
                </td>
                <td className="px-4 py-2 text-xs font-mono text-gray-500 truncate max-w-xs">
                  {n.fqn}
                </td>
                <td className="px-4 py-2 text-xs text-gray-500">{n.change_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

```tsx
// components/pull-requests/PrCrossTechPanel.tsx
"use client";

interface CrossTech {
  kind: string;
  name: string;
  detail: string;
}

const KIND_LABELS: Record<string, string> = {
  api_endpoint: "API Endpoints",
  message_topic: "Message Topics",
  database_table: "Database Tables",
};

const KIND_ICONS: Record<string, string> = {
  api_endpoint: "globe",
  message_topic: "arrow-right-arrow-left",
  database_table: "table",
};

export function PrCrossTechPanel({ items }: { items: CrossTech[] }) {
  if (items.length === 0) return null;

  const grouped = items.reduce<Record<string, CrossTech[]>>((acc, item) => {
    (acc[item.kind] ??= []).push(item);
    return acc;
  }, {});

  return (
    <div className="bg-white border rounded-lg mb-6">
      <h3 className="px-4 py-3 font-semibold text-gray-900 border-b">Cross-Technology Impacts</h3>
      <div className="p-4 space-y-4">
        {Object.entries(grouped).map(([kind, groupItems]) => (
          <div key={kind}>
            <h4 className="text-sm font-medium text-gray-700 mb-2">
              {KIND_LABELS[kind] ?? kind}
            </h4>
            <ul className="space-y-1">
              {groupItems.map((item, i) => (
                <li key={i} className="text-sm text-gray-600 flex items-center gap-2">
                  <span className="font-mono text-xs bg-gray-100 px-2 py-0.5 rounded">
                    {item.name}
                  </span>
                  <span className="text-gray-400">{item.detail}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
```

```tsx
// components/pull-requests/PrDriftAlerts.tsx
"use client";
import type { PrDriftDetail } from "@/lib/types";

export function PrDriftAlerts({ drift }: { drift: PrDriftDetail | null }) {
  if (!drift || !drift.has_drift) return null;

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-6">
      <h3 className="font-semibold text-amber-800 mb-2">Architecture Drift Detected</h3>
      <ul className="space-y-2">
        {drift.potential_new_module_deps.map((dep, i) => (
          <li key={i} className="text-sm text-amber-700">
            New dependency: <code className="bg-amber-100 px-1 rounded">{dep.from_module}</code>
            {" → "}
            <code className="bg-amber-100 px-1 rounded">{dep.to_module}</code>
          </li>
        ))}
        {drift.circular_deps_affected.map((cycle, i) => (
          <li key={`cycle-${i}`} className="text-sm text-amber-700">
            Circular dependency: {cycle.join(" → ")}
          </li>
        ))}
        {drift.new_files_outside_modules.length > 0 && (
          <li className="text-sm text-amber-700">
            {drift.new_files_outside_modules.length} new file(s) outside known modules
          </li>
        )}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Create PR detail page**

```tsx
// app/projects/[id]/pull-requests/[analysisId]/page.tsx
"use client";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { usePrDetail } from "@/hooks/usePullRequests";
import { reanalyzePr } from "@/lib/api";
import { PrRiskBadge } from "@/components/pull-requests/PrRiskBadge";
import { PrStatusBadge } from "@/components/pull-requests/PrStatusBadge";
import { PrSummaryCard } from "@/components/pull-requests/PrSummaryCard";
import { PrStatsRow } from "@/components/pull-requests/PrStatsRow";
import { PrChangedNodesTable } from "@/components/pull-requests/PrChangedNodesTable";
import { PrCrossTechPanel } from "@/components/pull-requests/PrCrossTechPanel";
import { PrDriftAlerts } from "@/components/pull-requests/PrDriftAlerts";

export default function PrDetailPage() {
  const params = useParams();
  const projectId = params.id as string;
  const analysisId = params.analysisId as string;
  const router = useRouter();

  const { analysis, impact, drift, loading } = usePrDetail(projectId, analysisId);

  if (loading) {
    return <div className="p-6 text-gray-500">Loading analysis...</div>;
  }

  if (!analysis) {
    return <div className="p-6 text-red-600">Analysis not found</div>;
  }

  const handleReanalyze = async () => {
    await reanalyzePr(projectId, analysisId);
    router.refresh();
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <Link
          href={`/projects/${projectId}/pull-requests`}
          className="text-sm text-blue-600 hover:text-blue-800 mb-2 inline-block"
        >
          ← Back to PR list
        </Link>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              #{analysis.pr_number}: {analysis.pr_title}
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              by {analysis.pr_author} · {analysis.source_branch} → {analysis.target_branch}
              · <code className="text-xs">{analysis.commit_sha.slice(0, 8)}</code>
            </p>
          </div>
          <div className="flex items-center gap-3">
            <PrRiskBadge level={analysis.risk_level} />
            <PrStatusBadge status={analysis.status} />
            {analysis.status === "stale" && (
              <button
                onClick={handleReanalyze}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                Re-analyze
              </button>
            )}
            {analysis.pr_url && (
              <a
                href={analysis.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-600 hover:text-blue-800"
              >
                View PR ↗
              </a>
            )}
          </div>
        </div>
      </div>

      {/* Stale banner */}
      {analysis.status === "stale" && (
        <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 mb-6 text-sm text-orange-700">
          This analysis was computed against an older version of the architecture graph.
          Click "Re-analyze" to update.
        </div>
      )}

      {/* AI Summary */}
      <PrSummaryCard summary={analysis.ai_summary} />

      {/* Stats */}
      {impact && (
        <PrStatsRow
          changedNodes={analysis.changed_node_count ?? 0}
          blastRadius={impact.total_blast_radius}
          layersAffected={Object.keys(impact.by_layer).length}
          transactionsAffected={impact.transactions_affected.length}
        />
      )}

      {/* Drift alerts */}
      <PrDriftAlerts drift={drift} />

      {/* Changed nodes */}
      {impact && (
        <PrChangedNodesTable
          nodes={impact.changed_nodes}
          projectId={projectId}
        />
      )}

      {/* Cross-tech impacts */}
      {impact && <PrCrossTechPanel items={impact.cross_tech} />}

      {/* Analysis metadata */}
      <div className="text-xs text-gray-400 mt-8">
        Analysis completed in {analysis.analysis_duration_ms ?? 0}ms
        {analysis.ai_summary_tokens ? ` · ${analysis.ai_summary_tokens} AI tokens` : ""}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify typecheck**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 4: Commit**

```bash
cd cast-clone-frontend
git add components/pull-requests/ app/projects/\[id\]/pull-requests/
git commit -m "feat(phase5a): add PR detail page with AI summary, stats, drift, and cross-tech panels"
```

---

### Task 4: Git Integration Settings Page

**Files:**
- Create: `components/pull-requests/GitIntegrationForm.tsx`
- Create: `app/projects/[id]/settings/git-integration/page.tsx`

- [ ] **Step 1: Create form component**

```tsx
// components/pull-requests/GitIntegrationForm.tsx
"use client";
import { useState } from "react";
import { createGitConfig, deleteGitConfig, testGitConnectivity, fetchWebhookUrl } from "@/lib/api";
import type { GitConfig, WebhookUrlInfo } from "@/lib/types";

interface Props {
  projectId: string;
  existing: GitConfig | null;
  onSaved: () => void;
}

export function GitIntegrationForm({ projectId, existing, onSaved }: Props) {
  const [platform, setPlatform] = useState(existing?.platform ?? "github");
  const [repoUrl, setRepoUrl] = useState(existing?.repo_url ?? "");
  const [apiToken, setApiToken] = useState("");
  const [branches, setBranches] = useState(
    existing?.monitored_branches?.join(", ") ?? "main, master, develop"
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [webhookInfo, setWebhookInfo] = useState<WebhookUrlInfo | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const result = await createGitConfig(projectId, {
        platform,
        repo_url: repoUrl,
        api_token: apiToken,
        monitored_branches: branches.split(",").map((b) => b.trim()).filter(Boolean),
      });
      setWebhookInfo({
        webhook_url: result.webhook_url,
        webhook_secret: result.webhook_secret,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTestResult(null);
    try {
      const result = await testGitConnectivity(projectId);
      setTestResult(
        result.status === "ok"
          ? `Connected as ${result.username}`
          : `Error: ${result.message}`
      );
    } catch {
      setTestResult("Connection test failed");
    }
  };

  const handleDelete = async () => {
    if (!confirm("Remove Git integration?")) return;
    await deleteGitConfig(projectId);
    onSaved();
  };

  if (existing && !webhookInfo) {
    return (
      <div className="bg-white border rounded-lg p-6">
        <h2 className="text-lg font-semibold mb-4">Git Integration</h2>
        <div className="space-y-2 text-sm">
          <p><span className="font-medium">Platform:</span> {existing.platform}</p>
          <p><span className="font-medium">Repository:</span> {existing.repo_url}</p>
          <p><span className="font-medium">Monitored branches:</span> {existing.monitored_branches?.join(", ")}</p>
          <p><span className="font-medium">Active:</span> {existing.is_active ? "Yes" : "No"}</p>
        </div>
        <div className="mt-4 flex gap-3">
          <button onClick={handleTest} className="px-3 py-1.5 text-sm bg-blue-100 text-blue-700 rounded-md">
            Test Connection
          </button>
          <button
            onClick={async () => {
              const info = await fetchWebhookUrl(projectId);
              setWebhookInfo(info);
            }}
            className="px-3 py-1.5 text-sm bg-gray-100 rounded-md"
          >
            Show Webhook URL
          </button>
          <button onClick={handleDelete} className="px-3 py-1.5 text-sm text-red-600 hover:text-red-800">
            Remove
          </button>
        </div>
        {testResult && <p className="mt-2 text-sm text-gray-600">{testResult}</p>}
      </div>
    );
  }

  return (
    <div className="bg-white border rounded-lg p-6">
      <h2 className="text-lg font-semibold mb-4">
        {webhookInfo ? "Webhook Configuration" : "Configure Git Integration"}
      </h2>

      {webhookInfo ? (
        <div className="space-y-4">
          <p className="text-sm text-green-600 font-medium">Git integration configured successfully!</p>
          <div>
            <label className="block text-sm font-medium text-gray-700">Webhook URL</label>
            <code className="block mt-1 p-2 bg-gray-100 rounded text-sm break-all">
              {webhookInfo.webhook_url}
            </code>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Webhook Secret</label>
            <code className="block mt-1 p-2 bg-gray-100 rounded text-sm break-all">
              {webhookInfo.webhook_secret}
            </code>
          </div>
          <p className="text-xs text-gray-500">
            Copy these values into your Git platform's webhook settings.
          </p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">Platform</label>
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="mt-1 block w-full border rounded-md px-3 py-2"
            >
              <option value="github">GitHub</option>
              <option value="gitlab">GitLab</option>
              <option value="bitbucket">Bitbucket</option>
              <option value="gitea">Gitea</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Repository URL</label>
            <input
              type="url"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/org/repo"
              required
              className="mt-1 block w-full border rounded-md px-3 py-2"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">API Token</label>
            <input
              type="password"
              value={apiToken}
              onChange={(e) => setApiToken(e.target.value)}
              placeholder="ghp_... or personal access token"
              required
              className="mt-1 block w-full border rounded-md px-3 py-2"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Monitored Branches</label>
            <input
              type="text"
              value={branches}
              onChange={(e) => setBranches(e.target.value)}
              className="mt-1 block w-full border rounded-md px-3 py-2"
            />
            <p className="text-xs text-gray-500 mt-1">Comma-separated list</p>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Configure"}
          </button>
        </form>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create settings page**

```tsx
// app/projects/[id]/settings/git-integration/page.tsx
"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchGitConfig } from "@/lib/api";
import { GitIntegrationForm } from "@/components/pull-requests/GitIntegrationForm";
import type { GitConfig } from "@/lib/types";

export default function GitIntegrationPage() {
  const params = useParams();
  const projectId = params.id as string;
  const [config, setConfig] = useState<GitConfig | null | undefined>(undefined);

  const loadConfig = async () => {
    const cfg = await fetchGitConfig(projectId);
    setConfig(cfg);
  };

  useEffect(() => {
    loadConfig();
  }, [projectId]);

  if (config === undefined) {
    return <div className="p-6 text-gray-500">Loading...</div>;
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Git Integration</h1>
      <GitIntegrationForm
        projectId={projectId}
        existing={config}
        onSaved={loadConfig}
      />
    </div>
  );
}
```

- [ ] **Step 3: Add "Pull Requests" nav link**

Add a "Pull Requests" link to the project-level sidebar/navigation. The exact location depends on existing nav component structure — look for the project sidebar and add after "Impact Analysis":

```tsx
// In the existing project navigation component, add:
<NavLink href={`/projects/${projectId}/pull-requests`} icon={GitPullRequestIcon}>
  Pull Requests
</NavLink>
```

Also add a "Git Integration" link under Settings.

- [ ] **Step 4: Verify typecheck**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
cd cast-clone-frontend
git add components/pull-requests/ app/projects/
git commit -m "feat(phase5a): add Git Integration settings page and project navigation links"
```

---

## Success Criteria

- [ ] TypeScript types for all PR analysis API responses compile without errors
- [ ] API client functions cover all M9 endpoints
- [ ] `usePrAnalyses` and `usePrDetail` hooks fetch and expose data
- [ ] PR list page shows filterable, sortable table with risk/status badges
- [ ] PR detail page shows AI summary, stats, changed nodes, cross-tech, and drift
- [ ] Stale analyses show banner + re-analyze button
- [ ] Git Integration settings page allows create/view/delete/test
- [ ] Webhook URL displayed after config creation
- [ ] "Pull Requests" link in project navigation
- [ ] `npx tsc --noEmit` passes without errors
