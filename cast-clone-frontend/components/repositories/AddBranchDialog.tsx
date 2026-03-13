"use client";
import * as React from "react";
import { GitBranch, Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { listRemoteBranches, addBranch, triggerAnalysis } from "@/lib/api";

interface AddBranchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  repoId: string;
  connectorId: string;
  repoFullName: string;
  existingBranches: string[];
  onBranchAdded: () => void;
}

export function AddBranchDialog({
  open,
  onOpenChange,
  repoId,
  connectorId,
  repoFullName,
  existingBranches,
  onBranchAdded,
}: AddBranchDialogProps) {
  const [branches, setBranches] = React.useState<string[]>([]);
  const [defaultBranch, setDefaultBranch] = React.useState<string>("");
  const [loading, setLoading] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [filter, setFilter] = React.useState("");

  // Fetch remote branches when dialog opens
  React.useEffect(() => {
    if (!open) {
      setSelected(null);
      setFilter("");
      setError(null);
      return;
    }
    setLoading(true);
    const [owner, repo] = repoFullName.split("/");
    listRemoteBranches(connectorId, owner, repo)
      .then((data) => {
        setBranches(data.branches);
        setDefaultBranch(data.default_branch);
      })
      .catch(() => setError("Failed to fetch branches"))
      .finally(() => setLoading(false));
  }, [open, connectorId, repoFullName]);

  const filtered = branches.filter((b) =>
    b.toLowerCase().includes(filter.toLowerCase()),
  );

  async function handleSubmit() {
    if (!selected) return;
    setSubmitting(true);
    setError(null);
    try {
      const project = await addBranch(repoId, selected);
      // Trigger analysis immediately
      await triggerAnalysis(project.id);
      onOpenChange(false);
      onBranchAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add branch");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Analyze a Branch</DialogTitle>
          <DialogDescription>
            Select a branch to add and analyze.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">Loading branches...</span>
          </div>
        ) : (
          <>
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                placeholder="Filter branches..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="pl-8"
              />
            </div>
            <div className="max-h-60 overflow-y-auto rounded-md border">
              {filtered.length === 0 ? (
                <p className="p-3 text-sm text-muted-foreground">No branches found.</p>
              ) : (
                filtered.map((branch) => {
                  const alreadyAdded = existingBranches.includes(branch);
                  const isSelected = selected === branch;
                  return (
                    <button
                      key={branch}
                      type="button"
                      disabled={alreadyAdded}
                      onClick={() => setSelected(branch)}
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors ${
                        alreadyAdded
                          ? "cursor-not-allowed text-muted-foreground opacity-50"
                          : isSelected
                            ? "bg-primary/10 text-primary"
                            : "hover:bg-muted"
                      }`}
                    >
                      <GitBranch className="size-3.5 shrink-0" />
                      <span className="truncate">{branch}</span>
                      {branch === defaultBranch && (
                        <span className="ml-auto shrink-0 text-xs text-muted-foreground">default</span>
                      )}
                      {alreadyAdded && (
                        <span className="ml-auto shrink-0 text-xs text-muted-foreground">Already added</span>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          </>
        )}

        {error && <p className="text-sm text-red-500">{error}</p>}

        <DialogFooter>
          <Button
            onClick={handleSubmit}
            disabled={!selected || submitting}
          >
            {submitting ? (
              <>
                <Loader2 className="mr-1.5 size-4 animate-spin" />
                Adding...
              </>
            ) : (
              "Add & Analyze"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
