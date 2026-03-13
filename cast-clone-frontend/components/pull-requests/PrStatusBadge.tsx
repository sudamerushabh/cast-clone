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
    <span
      className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${style}`}
    >
      {status}
    </span>
  );
}
