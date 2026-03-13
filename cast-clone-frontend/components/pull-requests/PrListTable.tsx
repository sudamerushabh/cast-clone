"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import type { PrAnalysis } from "@/lib/types";
import { deleteRepoPrAnalysis } from "@/lib/api";
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
  projectId?: string;
  /** Base path for detail links, e.g. "/repositories/abc" */
  basePath?: string;
  /** Repo ID needed for delete calls */
  repoId?: string;
  /** Called after a successful delete */
  onDeleted?: () => void;
}

export function PrListTable({ items, projectId, basePath, repoId, onDeleted }: Props) {
  const router = useRouter();
  const linkBase = basePath ?? `/projects/${projectId}`;
  const [deletingId, setDeletingId] = React.useState<string | null>(null);
  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        No pull request analyses yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              PR
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Author
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Branch
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Risk
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Blast Radius
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Status
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Time
            </th>
            {repoId && (
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
              </th>
            )}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {items.map((pr) => {
            const detailHref = `${linkBase}/pull-requests/${pr.id}`;
            return (
              <tr
                key={pr.id}
                className="hover:bg-gray-50 cursor-pointer transition-colors"
                onClick={() => router.push(detailHref)}
              >
                <td className="px-4 py-3">
                  <Link
                    href={detailHref}
                    className="text-blue-600 hover:text-blue-800 font-medium"
                    onClick={(e) => e.stopPropagation()}
                  >
                    #{pr.pr_number}
                  </Link>
                  <span className="ml-2 text-sm text-gray-700">
                    {pr.pr_title}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">
                  {pr.pr_author}
                </td>
                <td className="px-4 py-3 text-xs font-mono text-gray-500">
                  {pr.source_branch} → {pr.target_branch}
                </td>
                <td className="px-4 py-3">
                  <PrRiskBadge level={pr.risk_level} />
                </td>
                <td className="px-4 py-3 text-sm">
                  {pr.blast_radius_total != null
                    ? `${pr.blast_radius_total} nodes`
                    : "—"}
                </td>
                <td className="px-4 py-3">
                  <PrStatusBadge status={pr.status} />
                </td>
                <td className="px-4 py-3 text-xs text-gray-500">
                  {timeAgo(pr.created_at)}
                </td>
                {repoId && (
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      title="Delete PR analysis"
                      disabled={deletingId === pr.id}
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (!confirm("Delete this PR analysis? This cannot be undone.")) return;
                        setDeletingId(pr.id);
                        try {
                          await deleteRepoPrAnalysis(repoId, pr.id);
                          onDeleted?.();
                        } catch {
                          alert("Failed to delete PR analysis");
                        } finally {
                          setDeletingId(null);
                        }
                      }}
                      className="inline-flex items-center justify-center rounded p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
