"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  summary: string | null | undefined;
  onRegenerate?: () => void;
}

export function PrSummaryCard({ summary, onRegenerate }: Props) {
  if (!summary) return null;
  return (
    <div className="bg-white border rounded-lg p-6 mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold text-gray-900">
          AI Impact Summary
        </h2>
        {onRegenerate && (
          <button
            onClick={onRegenerate}
            className="text-xs text-blue-600 hover:text-blue-800"
          >
            Regenerate
          </button>
        )}
      </div>
      <div className="prose prose-sm prose-compact max-w-none text-gray-700 prose-headings:mt-4 prose-headings:mb-2 prose-p:my-1.5 prose-hr:my-3 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-h1:text-lg prose-h2:text-base prose-h3:text-sm prose-table:my-2 prose-th:px-3 prose-th:py-1.5 prose-td:px-3 prose-td:py-1.5 prose-table:text-xs">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary}</ReactMarkdown>
      </div>
    </div>
  );
}
