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
      <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap">
        {summary}
      </div>
    </div>
  );
}
