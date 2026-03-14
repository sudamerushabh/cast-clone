// cast-clone-frontend/components/settings/ApiKeyTable.tsx
"use client";

import { useState } from "react";
import type { ApiKeyResponse } from "@/lib/types";
import { revokeApiKey } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Trash2, Key } from "lucide-react";

interface ApiKeyTableProps {
  keys: ApiKeyResponse[];
  onKeyRevoked: () => void;
}

export function ApiKeyTable({ keys, onKeyRevoked }: ApiKeyTableProps) {
  const [revoking, setRevoking] = useState<string | null>(null);

  async function handleRevoke(id: string) {
    if (!confirm("Are you sure you want to revoke this API key? This action cannot be undone.")) {
      return;
    }
    setRevoking(id);
    try {
      await revokeApiKey(id);
      onKeyRevoked();
    } catch (err) {
      console.error("Failed to revoke key:", err);
    } finally {
      setRevoking(null);
    }
  }

  if (keys.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        <Key className="mx-auto mb-3 h-8 w-8 opacity-50" />
        <p>No API keys yet. Create one to connect external AI tools.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/50">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Name</th>
            <th className="px-4 py-3 text-left font-medium">Created</th>
            <th className="px-4 py-3 text-left font-medium">Last Used</th>
            <th className="px-4 py-3 text-left font-medium">Status</th>
            <th className="px-4 py-3 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key.id} className="border-b last:border-0">
              <td className="px-4 py-3 font-mono text-sm">{key.name}</td>
              <td className="px-4 py-3 text-muted-foreground">
                {new Date(key.created_at).toLocaleDateString()}
              </td>
              <td className="px-4 py-3 text-muted-foreground">
                {key.last_used_at
                  ? new Date(key.last_used_at).toLocaleDateString()
                  : "Never"}
              </td>
              <td className="px-4 py-3">
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                    key.is_active
                      ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                      : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                  }`}
                >
                  {key.is_active ? "Active" : "Revoked"}
                </span>
              </td>
              <td className="px-4 py-3 text-right">
                {key.is_active && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleRevoke(key.id)}
                    disabled={revoking === key.id}
                    className="text-red-600 hover:text-red-700"
                  >
                    <Trash2 className="mr-1 h-4 w-4" />
                    {revoking === key.id ? "Revoking..." : "Revoke"}
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
