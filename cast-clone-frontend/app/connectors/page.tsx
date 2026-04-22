"use client";

import * as React from "react";
import { Plus, Unplug } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ConnectorCard } from "@/components/connectors/ConnectorCard";
import { AddConnectorForm } from "@/components/connectors/AddConnectorForm";
import { listConnectors, deleteConnector, testConnector } from "@/lib/api";
import type { ConnectorResponse } from "@/lib/types";

export default function ConnectorsPage() {
  const [connectors, setConnectors] = React.useState<ConnectorResponse[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [dialogOpen, setDialogOpen] = React.useState(false);

  async function load() {
    try {
      const data = await listConnectors();
      setConnectors(data.connectors);
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    load();
  }, []);

  async function handleDelete(id: string) {
    await deleteConnector(id);
    setConnectors((prev) => prev.filter((c) => c.id !== id));
  }

  async function handleTest(id: string) {
    await testConnector(id);
    await load();
  }

  function handleAddSuccess() {
    setDialogOpen(false);
    load();
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Git Connectors</h1>
          <p className="text-xs text-muted-foreground">
            Connect to Git providers to browse and analyze repositories
          </p>
        </div>
        <Button size="sm" onClick={() => setDialogOpen(true)}>
          <Plus className="mr-1 size-3.5" />
          Add Connector
        </Button>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : connectors.length === 0 ? (
        <div className="rounded-lg border border-dashed">
          <EmptyState
            icon={Unplug}
            title="No connectors yet"
            description="Add a connector to start browsing and analyzing repositories from GitHub, GitLab, Gitea, or Bitbucket."
            action={
              <Button size="sm" onClick={() => setDialogOpen(true)}>
                <Plus className="mr-1 size-3.5" />
                Add Your First Connector
              </Button>
            }
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {connectors.map((c) => (
            <ConnectorCard
              key={c.id}
              connector={c}
              onDelete={handleDelete}
              onTest={handleTest}
            />
          ))}
        </div>
      )}

      {/* ── Add Connector Dialog ── */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Add Git Connector</DialogTitle>
            <DialogDescription>
              Connect to a Git provider to browse and import repositories
            </DialogDescription>
          </DialogHeader>
          <AddConnectorForm
            onSuccess={handleAddSuccess}
            onCancel={() => setDialogOpen(false)}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
