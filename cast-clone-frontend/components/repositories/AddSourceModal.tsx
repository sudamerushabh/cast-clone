"use client";
import * as React from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BranchPicker } from "./BranchPicker";
import { CloneProgress } from "./CloneProgress";
import { listConnectors, listRemoteRepos, listRemoteBranches, createRepository } from "@/lib/api";
import type { ConnectorResponse, RemoteRepoResponse } from "@/lib/types";

interface AddSourceModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

type Step = "connector" | "repo" | "branches" | "progress";

export function AddSourceModal({ open, onClose, onCreated }: AddSourceModalProps) {
  const [step, setStep] = React.useState<Step>("connector");
  const [connectors, setConnectors] = React.useState<ConnectorResponse[]>([]);
  const [selectedConnector, setSelectedConnector] = React.useState<ConnectorResponse | null>(null);
  const [repos, setRepos] = React.useState<RemoteRepoResponse[]>([]);
  const [repoSearch, setRepoSearch] = React.useState("");
  const [selectedRepo, setSelectedRepo] = React.useState<RemoteRepoResponse | null>(null);
  const [branches, setBranches] = React.useState<string[]>([]);
  const [defaultBranch, setDefaultBranch] = React.useState("main");
  const [selectedBranches, setSelectedBranches] = React.useState<string[]>([]);
  const [createdRepoId, setCreatedRepoId] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setStep("connector");
      setSelectedConnector(null);
      setSelectedRepo(null);
      setError(null);
      listConnectors().then((data) => setConnectors(data.connectors));
    }
  }, [open]);

  async function handleSelectConnector(c: ConnectorResponse) {
    setSelectedConnector(c);
    setStep("repo");
    setLoading(true);
    try {
      const data = await listRemoteRepos(c.id, 1, 30, repoSearch || undefined);
      setRepos(data.repos);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load repos");
    } finally {
      setLoading(false);
    }
  }

  async function handleSearchRepos() {
    if (!selectedConnector) return;
    setLoading(true);
    try {
      const data = await listRemoteRepos(selectedConnector.id, 1, 30, repoSearch || undefined);
      setRepos(data.repos);
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectRepo(repo: RemoteRepoResponse) {
    if (!selectedConnector) return;
    setSelectedRepo(repo);
    setStep("branches");
    setLoading(true);
    try {
      const parts = repo.full_name.split("/");
      const owner = parts[0];
      const name = parts.length > 1 ? parts.slice(1).join("/") : parts[0];
      const data = await listRemoteBranches(selectedConnector.id, owner, name);
      setBranches(data.branches);
      setDefaultBranch(data.default_branch);
      setSelectedBranches([data.default_branch]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load branches");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate() {
    if (!selectedConnector || !selectedRepo || selectedBranches.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const result = await createRepository({
        connector_id: selectedConnector.id,
        repo_full_name: selectedRepo.full_name,
        branches: selectedBranches,
        auto_analyze: false,
      });
      setCreatedRepoId(result.id);
      setStep("progress");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create repository");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {step === "connector" && "Select Connector"}
            {step === "repo" && "Choose Repository"}
            {step === "branches" && "Select Branches"}
            {step === "progress" && "Cloning Repository"}
          </DialogTitle>
        </DialogHeader>
        {error && <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}

        {step === "connector" && (
          <div className="space-y-2">
            {connectors.length === 0 ? (
              <p className="text-sm text-muted-foreground">No connectors found. Add a connector first.</p>
            ) : (
              connectors.map((c) => (
                <button key={c.id} type="button" onClick={() => handleSelectConnector(c)}
                  className="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent">
                  <span className="font-medium">{c.name}</span>
                  <span className="text-xs text-muted-foreground">{c.provider}</span>
                </button>
              ))
            )}
          </div>
        )}

        {step === "repo" && (
          <div className="space-y-3">
            <div className="flex gap-2">
              <Input placeholder="Search repositories..." value={repoSearch}
                onChange={(e) => setRepoSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearchRepos()} />
              <Button variant="outline" onClick={handleSearchRepos} disabled={loading}>Search</Button>
            </div>
            <div className="max-h-64 space-y-1 overflow-auto">
              {repos.map((r) => (
                <button key={r.full_name} type="button" onClick={() => handleSelectRepo(r)}
                  className="flex w-full flex-col rounded-lg border p-2 text-left transition-colors hover:bg-accent">
                  <span className="text-sm font-medium">{r.full_name}</span>
                  {r.description && <span className="line-clamp-1 text-xs text-muted-foreground">{r.description}</span>}
                </button>
              ))}
            </div>
            <Button variant="outline" onClick={() => setStep("connector")}>Back</Button>
          </div>
        )}

        {step === "branches" && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Select branches to analyze for <strong>{selectedRepo?.full_name}</strong>:
            </p>
            <BranchPicker branches={branches} defaultBranch={defaultBranch} selected={selectedBranches} onChange={setSelectedBranches} />
            <div className="flex gap-2">
              <Button onClick={handleCreate} disabled={loading || selectedBranches.length === 0}>
                {loading ? "Creating..." : "Clone & Create"}
              </Button>
              <Button variant="outline" onClick={() => setStep("repo")}>Back</Button>
            </div>
          </div>
        )}

        {step === "progress" && createdRepoId && (
          <div className="space-y-4">
            <CloneProgress repoId={createdRepoId} onComplete={() => { onCreated(); onClose(); }} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
