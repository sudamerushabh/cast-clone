// cast-clone-frontend/components/settings/CreateKeyModal.tsx
"use client";

import { useState } from "react";
import { createApiKey } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Copy, Check, AlertTriangle, X } from "lucide-react";

interface CreateKeyModalProps {
  open: boolean;
  onClose: () => void;
  onKeyCreated: () => void;
}

export function CreateKeyModal({ open, onClose, onKeyCreated }: CreateKeyModalProps) {
  const [name, setName] = useState("");
  const [rawKey, setRawKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const result = await createApiKey(name.trim());
      setRawKey(result.raw_key);
      onKeyCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create key");
    } finally {
      setCreating(false);
    }
  }

  async function handleCopy() {
    if (!rawKey) return;
    await navigator.clipboard.writeText(rawKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleClose() {
    setName("");
    setRawKey(null);
    setCopied(false);
    setError(null);
    onClose();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg bg-background p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {rawKey ? "API Key Created" : "Create API Key"}
          </h2>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        {rawKey ? (
          <div className="space-y-4">
            <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-950/30">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <p className="text-sm text-amber-800 dark:text-amber-300">
                Copy this key now. It will not be shown again.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 overflow-x-auto rounded border bg-muted p-3 font-mono text-sm">
                {rawKey}
              </code>
              <Button variant="outline" size="sm" onClick={handleCopy}>
                {copied ? (
                  <Check className="h-4 w-4 text-green-600" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
            <Button onClick={handleClose} className="w-full">
              Done
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label htmlFor="key-name" className="mb-1 block text-sm font-medium">
                Key Name
              </label>
              <input
                id="key-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Claude Code, Cursor, VS Code"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                autoFocus
              />
            </div>
            {error && (
              <p className="text-sm text-red-600">{error}</p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                onClick={handleCreate}
                disabled={!name.trim() || creating}
              >
                {creating ? "Creating..." : "Create Key"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
