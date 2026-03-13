"use client";

interface CrossTech {
  kind: string;
  name: string;
  detail: string;
}

const KIND_LABELS: Record<string, string> = {
  api_endpoint: "API Endpoints",
  message_topic: "Message Topics",
  database_table: "Database Tables",
};

export function PrCrossTechPanel({ items }: { items: CrossTech[] }) {
  if (items.length === 0) return null;

  const grouped = items.reduce<Record<string, CrossTech[]>>((acc, item) => {
    (acc[item.kind] ??= []).push(item);
    return acc;
  }, {});

  return (
    <div className="bg-white border rounded-lg mb-6">
      <h3 className="px-4 py-3 font-semibold text-gray-900 border-b">
        Cross-Technology Impacts
      </h3>
      <div className="p-4 space-y-4">
        {Object.entries(grouped).map(([kind, groupItems]) => (
          <div key={kind}>
            <h4 className="text-sm font-medium text-gray-700 mb-2">
              {KIND_LABELS[kind] ?? kind}
            </h4>
            <ul className="space-y-1">
              {groupItems.map((item, i) => (
                <li
                  key={i}
                  className="text-sm text-gray-600 flex items-center gap-2"
                >
                  <span className="font-mono text-xs bg-gray-100 px-2 py-0.5 rounded">
                    {item.name}
                  </span>
                  <span className="text-gray-400">{item.detail}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
