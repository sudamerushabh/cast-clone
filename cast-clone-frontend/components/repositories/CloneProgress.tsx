"use client";
import * as React from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { getCloneStatus } from "@/lib/api";
import type { CloneStatus } from "@/lib/types";

interface CloneProgressProps {
  repoId: string;
  onComplete: () => void;
}

export function CloneProgress({ repoId, onComplete }: CloneProgressProps) {
  const [status, setStatus] = React.useState<CloneStatus>("pending");
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (status === "cloned" || status === "clone_failed") return;

    const interval = setInterval(async () => {
      try {
        const data = await getCloneStatus(repoId);
        setStatus(data.clone_status);
        setError(data.clone_error);
        if (data.clone_status === "cloned" || data.clone_status === "clone_failed") {
          clearInterval(interval);
          if (data.clone_status === "cloned") onComplete();
        }
      } catch {
        // Ignore polling errors
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [repoId, status, onComplete]);

  return (
    <div className="flex items-center gap-3 rounded-lg border p-4">
      {status === "pending" || status === "cloning" ? (
        <>
          <Loader2 className="size-5 animate-spin text-primary" />
          <div>
            <p className="text-sm font-medium">{status === "pending" ? "Preparing clone..." : "Cloning repository..."}</p>
            <p className="text-xs text-muted-foreground">This may take a few minutes for large repositories.</p>
          </div>
        </>
      ) : status === "cloned" ? (
        <>
          <CheckCircle2 className="size-5 text-green-600" />
          <p className="text-sm font-medium text-green-700 dark:text-green-400">Repository cloned successfully!</p>
        </>
      ) : (
        <>
          <XCircle className="size-5 text-red-600" />
          <div>
            <p className="text-sm font-medium text-red-700 dark:text-red-400">Clone failed</p>
            {error && <p className="text-xs text-muted-foreground">{error}</p>}
          </div>
        </>
      )}
    </div>
  );
}
