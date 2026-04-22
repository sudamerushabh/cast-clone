"use client";
import * as React from "react";
import { GitBranch, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { RepoCard } from "@/components/repositories/RepoCard";
import { AddSourceModal } from "@/components/repositories/AddSourceModal";
import { listRepositories, deleteRepository } from "@/lib/api";
import type { RepositoryResponse } from "@/lib/types";

export default function RepositoriesPage() {
  const [repos, setRepos] = React.useState<RepositoryResponse[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [showAddModal, setShowAddModal] = React.useState(false);

  async function load() {
    try {
      const data = await listRepositories();
      setRepos(data.repositories);
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => { load(); }, []);

  async function handleDelete(id: string) {
    await deleteRepository(id);
    setRepos((prev) => prev.filter((r) => r.id !== id));
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Repositories</h1>
        <Button onClick={() => setShowAddModal(true)}>
          <Plus className="mr-1.5 size-4" />Add Source
        </Button>
      </div>
      {loading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      ) : repos.length === 0 ? (
        <div className="rounded-lg border border-dashed">
          <EmptyState
            icon={GitBranch}
            title="No repositories yet"
            description="Connect a Git provider and add your first repository."
            action={
              <Button onClick={() => setShowAddModal(true)}>
                <Plus className="mr-1.5 size-4" />Add Your First Repository
              </Button>
            }
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {repos.map((r) => <RepoCard key={r.id} repo={r} onDelete={handleDelete} />)}
        </div>
      )}
      <AddSourceModal open={showAddModal} onClose={() => setShowAddModal(false)} onCreated={load} />
    </div>
  );
}
