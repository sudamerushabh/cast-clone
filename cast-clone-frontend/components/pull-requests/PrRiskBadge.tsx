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
    <span
      className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium border ${colors}`}
    >
      {level}
    </span>
  );
}
