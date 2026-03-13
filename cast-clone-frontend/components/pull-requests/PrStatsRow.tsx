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

export function PrStatsRow({
  changedNodes,
  blastRadius,
  layersAffected,
  transactionsAffected,
}: Props) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <StatCard label="Changed Nodes" value={changedNodes} />
      <StatCard
        label="Blast Radius"
        value={blastRadius}
        detail="unique affected nodes"
      />
      <StatCard label="Layers Affected" value={layersAffected} />
      <StatCard label="Transactions" value={transactionsAffected} />
    </div>
  );
}
