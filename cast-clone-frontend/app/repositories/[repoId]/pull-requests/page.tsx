"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useRepoPrAnalyses } from "@/hooks/usePullRequests";
import { PrListTable } from "@/components/pull-requests/PrListTable";

export default function RepoPullRequestsPage() {
  const params = useParams();
  const repoId = params.repoId as string;
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [riskFilter, setRiskFilter] = useState<string>("");

  const { data, loading, error, refresh } = useRepoPrAnalyses(repoId, {
    status: statusFilter || undefined,
    risk: riskFilter || undefined,
  });

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Pull Requests</h1>
        <button
          onClick={refresh}
          className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 rounded-md"
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

      {loading && (
        <div className="py-8 text-center text-gray-500">Loading...</div>
      )}
      {error && <div className="py-4 text-red-600">{error}</div>}
      {data && (
        <PrListTable items={data.items} basePath={`/repositories/${repoId}`} repoId={repoId} onDeleted={refresh} />
      )}
      {data && (
        <div className="mt-4 text-sm text-gray-500">
          Showing {data.items.length} of {data.total} analyses
        </div>
      )}
    </div>
  );
}
