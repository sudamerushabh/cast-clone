// cast-clone-frontend/app/settings/api-keys/page.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { listApiKeys } from "@/lib/api";
import type { ApiKeyResponse } from "@/lib/types";
import { ApiKeyTable } from "@/components/settings/ApiKeyTable";
import { CreateKeyModal } from "@/components/settings/CreateKeyModal";
import { McpSetupGuide } from "@/components/settings/McpSetupGuide";
import { AiUsageDashboard } from "@/components/admin/AiUsageDashboard";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Plus } from "lucide-react";

export default function ApiKeysSettingsPage() {
  const { user } = useAuth();
  const [keys, setKeys] = useState<ApiKeyResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);

  const loadKeys = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listApiKeys();
      setKeys(data);
    } catch {
      // User may not have access
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  const isAdmin = user?.role === "admin";

  return (
    <div className="space-y-8 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">API Keys</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage API keys for MCP server access by external AI tools.
          </p>
        </div>
        {isAdmin && (
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create Key
          </Button>
        )}
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : (
        <ApiKeyTable keys={keys} onKeyRevoked={loadKeys} />
      )}

      <hr className="my-8 border-border" />

      <McpSetupGuide />

      {isAdmin && (
        <>
          <hr className="my-8 border-border" />
          <AiUsageDashboard />
        </>
      )}

      <CreateKeyModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onKeyCreated={loadKeys}
      />
    </div>
  );
}
