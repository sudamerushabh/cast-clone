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
  projectId?: string;
  /** Base path for detail links, e.g. "/repositories/abc" */
  basePath?: string;
}

export function PrListTable({ items, projectId, basePath }: Props) {
  const linkBase = basePath ?? `/projects/${projectId}`;
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
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {items.map((pr) => (
            <tr key={pr.id} className="hover:bg-gray-50">
              <td className="px-4 py-3">
                <Link
                  href={`${linkBase}/pull-requests/${pr.id}`}
                  className="text-blue-600 hover:text-blue-800 font-medium"
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
