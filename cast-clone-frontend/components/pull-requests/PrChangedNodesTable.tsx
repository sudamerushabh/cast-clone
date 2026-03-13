"use client";

interface ChangedNode {
  fqn: string;
  name: string;
  type: string;
  change_type: string;
}

interface Props {
  nodes: ChangedNode[];
}

const TYPE_COLORS: Record<string, string> = {
  Function: "text-blue-600",
  Class: "text-purple-600",
  Interface: "text-green-600",
  Field: "text-orange-600",
  APIEndpoint: "text-red-600",
};

export function PrChangedNodesTable({ nodes }: Props) {
  if (nodes.length === 0) return null;
  return (
    <div className="bg-white border rounded-lg mb-6">
      <h3 className="px-4 py-3 font-semibold text-gray-900 border-b">
        Changed Nodes
      </h3>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">
                Name
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">
                Type
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">
                FQN
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">
                Change
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {nodes.map((n) => (
              <tr key={n.fqn} className="hover:bg-gray-50">
                <td className="px-4 py-2 text-sm font-medium">{n.name}</td>
                <td
                  className={`px-4 py-2 text-xs ${TYPE_COLORS[n.type] ?? "text-gray-600"}`}
                >
                  {n.type}
                </td>
                <td className="px-4 py-2 text-xs font-mono text-gray-500 truncate max-w-xs">
                  {n.fqn}
                </td>
                <td className="px-4 py-2 text-xs text-gray-500">
                  {n.change_type}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
