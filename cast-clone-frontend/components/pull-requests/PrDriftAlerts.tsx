"use client";

import type { PrDriftDetail } from "@/lib/types";

export function PrDriftAlerts({ drift }: { drift: PrDriftDetail | null }) {
  if (!drift || !drift.has_drift) return null;

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-6">
      <h3 className="font-semibold text-amber-800 mb-2">
        Architecture Drift Detected
      </h3>
      <ul className="space-y-2">
        {drift.potential_new_module_deps.map((dep, i) => (
          <li key={i} className="text-sm text-amber-700">
            New dependency:{" "}
            <code className="bg-amber-100 px-1 rounded">
              {dep.from_module}
            </code>
            {" \u2192 "}
            <code className="bg-amber-100 px-1 rounded">{dep.to_module}</code>
          </li>
        ))}
        {drift.circular_deps_affected.map((cycle, i) => (
          <li key={`cycle-${i}`} className="text-sm text-amber-700">
            Circular dependency: {cycle.join(" \u2192 ")}
          </li>
        ))}
        {drift.new_files_outside_modules.length > 0 && (
          <li className="text-sm text-amber-700">
            {drift.new_files_outside_modules.length} new file(s) outside known
            modules
          </li>
        )}
      </ul>
    </div>
  );
}
