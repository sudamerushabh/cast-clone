"use client";

import * as React from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConnectorCard } from "@/components/connectors/ConnectorCard";
import { listConnectors, deleteConnector, testConnector } from "@/lib/api";
import type { ConnectorResponse } from "@/lib/types";

export default function ConnectorsPage() {
  const [connectors, setConnectors] = React.useState<ConnectorResponse[]>([]);
  const [loading, setLoading] = React.useState(true);

  async function load() {
    try {
      const data = await listConnectors();
      setConnectors(data.connectors);
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => { load(); }, []);

  async function handleDelete(id: string) {
    await deleteConnector(id);
    setConnectors((prev) => prev.filter((c) => c.id !== id));
  }

  async function handleTest(id: string) {
    await testConnector(id);
    await load();
  }

  if (loading) {
    return <div className="p-6"><p className="text-muted-foreground">Loading connectors...</p></div>;
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Git Connectors</h1>
        <Button asChild>
          <Link href="/connectors/new"><Plus className="mr-1.5 size-4" />Add Connector</Link>
        </Button>
      </div>
      {connectors.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="text-muted-foreground">No connectors yet. Add one to start browsing repositories.</p>
          <Button asChild className="mt-4">
            <Link href="/connectors/new"><Plus className="mr-1.5 size-4" />Add Your First Connector</Link>
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {connectors.map((c) => (
            <ConnectorCard key={c.id} connector={c} onDelete={handleDelete} onTest={handleTest} />
          ))}
        </div>
      )}
    </div>
  );
}
