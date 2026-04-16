"use client";

import { useCallback, useRef, useState } from "react";
import { getTraceSummary } from "@/lib/api";
import type { TraceSummaryResponse } from "@/lib/types";

interface UseTraceSummaryResult {
  summary: TraceSummaryResponse | null;
  isLoading: boolean;
  error: string | null;
  fetch: (projectId: string, fqn: string, maxDepth?: number) => Promise<void>;
  retry: () => void;
  clear: () => void;
}

export function useTraceSummary(): UseTraceSummaryResult {
  const [summary, setSummary] = useState<TraceSummaryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastArgs = useRef<{ projectId: string; fqn: string; maxDepth: number } | null>(null);

  const fetch = useCallback(
    async (projectId: string, fqn: string, maxDepth: number = 5) => {
      lastArgs.current = { projectId, fqn, maxDepth };
      setIsLoading(true);
      setError(null);
      try {
        const result = await getTraceSummary(projectId, fqn, maxDepth);
        setSummary(result);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Summary generation failed";
        setError(msg);
        setSummary(null);
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  const retry = useCallback(() => {
    if (lastArgs.current) {
      const { projectId, fqn, maxDepth } = lastArgs.current;
      fetch(projectId, fqn, maxDepth);
    }
  }, [fetch]);

  const clear = useCallback(() => {
    setSummary(null);
    setError(null);
    lastArgs.current = null;
  }, []);

  return { summary, isLoading, error, fetch, retry, clear };
}
