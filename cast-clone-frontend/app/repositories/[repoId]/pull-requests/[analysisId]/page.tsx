"use client";

import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useRepoPrDetail } from "@/hooks/usePullRequests";
import { reanalyzeRepoPr } from "@/lib/api";
import { PrRiskBadge } from "@/components/pull-requests/PrRiskBadge";
import { PrStatusBadge } from "@/components/pull-requests/PrStatusBadge";
import { PrSummaryCard } from "@/components/pull-requests/PrSummaryCard";
import { PrStatsRow } from "@/components/pull-requests/PrStatsRow";
import { PrChangedNodesTable } from "@/components/pull-requests/PrChangedNodesTable";
import { PrCrossTechPanel } from "@/components/pull-requests/PrCrossTechPanel";
import { PrDriftAlerts } from "@/components/pull-requests/PrDriftAlerts";
import { Download } from "lucide-react";

export default function RepoPrDetailPage() {
  const params = useParams();
  const repoId = params.repoId as string;
  const analysisId = params.analysisId as string;
  const router = useRouter();

  const { analysis, impact, drift, loading } = useRepoPrDetail(
    repoId,
    analysisId,
  );

  if (loading) {
    return <div className="p-6 text-gray-500">Loading analysis...</div>;
  }

  if (!analysis) {
    return <div className="p-6 text-red-600">Analysis not found</div>;
  }

  const handleReanalyze = async () => {
    await reanalyzeRepoPr(repoId, analysisId);
    router.refresh();
  };

  const handleDownload = (format: "md" | "json") => {
    let content: string;
    let filename: string;
    let mime: string;

    if (format === "json") {
      content = JSON.stringify({ analysis, impact, drift }, null, 2);
      filename = `pr-${analysis.pr_number}-analysis.json`;
      mime = "application/json";
    } else {
      const lines: string[] = [
        `# PR #${analysis.pr_number}: ${analysis.pr_title}`,
        "",
        `**Author:** ${analysis.pr_author}`,
        `**Branch:** ${analysis.source_branch} → ${analysis.target_branch}`,
        `**Commit:** ${analysis.commit_sha}`,
        `**Risk Level:** ${analysis.risk_level ?? "N/A"}`,
        `**Status:** ${analysis.status}`,
        "",
        "---",
        "",
        "## Stats",
        "",
        `| Metric | Value |`,
        `|--------|-------|`,
        `| Files Changed | ${analysis.files_changed ?? "—"} |`,
        `| Additions | ${analysis.additions ?? "—"} |`,
        `| Deletions | ${analysis.deletions ?? "—"} |`,
        `| Changed Nodes | ${analysis.changed_node_count ?? "—"} |`,
        `| Blast Radius | ${impact?.total_blast_radius ?? "—"} nodes |`,
        `| Layers Affected | ${impact ? Object.keys(impact.by_layer).length : "—"} |`,
        `| Transactions Affected | ${impact?.transactions_affected.length ?? "—"} |`,
        "",
      ];

      if (drift?.has_drift) {
        lines.push("## Architecture Drift", "");
        if (drift.potential_new_module_deps.length > 0) {
          lines.push("### New Module Dependencies", "");
          drift.potential_new_module_deps.forEach((d) =>
            lines.push(`- ${d.from_module} → ${d.to_module}`)
          );
          lines.push("");
        }
        if (drift.new_files_outside_modules.length > 0) {
          lines.push("### Files Outside Modules", "");
          drift.new_files_outside_modules.forEach((f) => lines.push(`- ${f}`));
          lines.push("");
        }
      }

      if (impact?.changed_nodes.length) {
        lines.push("## Changed Nodes", "");
        lines.push("| Name | Type | Change |");
        lines.push("|------|------|--------|");
        impact.changed_nodes.forEach((n) =>
          lines.push(`| ${n.name} | ${n.type} | ${n.change_type} |`)
        );
        lines.push("");
      }

      if (analysis.ai_summary) {
        lines.push("---", "", "## AI Impact Summary", "", analysis.ai_summary);
      }

      content = lines.join("\n");
      filename = `pr-${analysis.pr_number}-analysis.md`;
      mime = "text/markdown";
    }

    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <Link
          href={`/repositories/${repoId}/pull-requests`}
          className="text-sm text-blue-600 hover:text-blue-800 mb-2 inline-block"
        >
          &larr; Back to PR list
        </Link>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              #{analysis.pr_number}: {analysis.pr_title}
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              by {analysis.pr_author} &middot; {analysis.source_branch} &rarr;{" "}
              {analysis.target_branch} &middot;{" "}
              <code className="text-xs">
                {analysis.commit_sha.slice(0, 8)}
              </code>
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
            <div className="relative group">
              <button className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-gray-50 text-gray-700">
                <Download className="size-3.5" />
                Export
              </button>
              <div className="hidden group-hover:block absolute right-0 mt-1 bg-white border rounded-md shadow-lg z-10 min-w-[140px]">
                <button
                  onClick={() => handleDownload("md")}
                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-50"
                >
                  Markdown (.md)
                </button>
                <button
                  onClick={() => handleDownload("json")}
                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-50"
                >
                  JSON (.json)
                </button>
              </div>
            </div>
            {analysis.pr_url && (
              <a
                href={analysis.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-600 hover:text-blue-800"
              >
                View PR &nearr;
              </a>
            )}
          </div>
        </div>
      </div>

      {/* Stale banner */}
      {analysis.status === "stale" && (
        <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 mb-6 text-sm text-orange-700">
          This analysis was computed against an older version of the
          architecture graph. Click &quot;Re-analyze&quot; to update.
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
        <PrChangedNodesTable nodes={impact.changed_nodes} />
      )}

      {/* Cross-tech impacts */}
      {impact && <PrCrossTechPanel items={impact.cross_tech} />}

      {/* Analysis metadata */}
      <div className="text-xs text-gray-400 mt-8">
        Analysis completed in {analysis.analysis_duration_ms ?? 0}ms
        {analysis.ai_summary_tokens
          ? ` \u00b7 ${analysis.ai_summary_tokens} AI tokens`
          : ""}
      </div>
    </div>
  );
}
