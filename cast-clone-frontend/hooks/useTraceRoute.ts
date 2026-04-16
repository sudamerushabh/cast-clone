// cast-clone-frontend/hooks/useTraceRoute.ts
"use client";

import { useCallback, useState } from "react";
import { getTraceRoute } from "@/lib/api";
import type { TraceRouteResponse } from "@/lib/types";

interface UseTraceRouteResult {
  data: TraceRouteResponse | null;
  isLoading: boolean;
  error: string | null;
  fetchTrace: (projectId: string, fqn: string, maxDepth?: number) => Promise<void>;
  clear: () => void;
}

export function useTraceRoute(): UseTraceRouteResult {
  const [data, setData] = useState<TraceRouteResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTrace = useCallback(
    async (projectId: string, fqn: string, maxDepth: number = 5) => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await getTraceRoute(projectId, fqn, maxDepth);
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Trace route failed");
        setData(null);
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  const clear = useCallback(() => {
    setData(null);
    setError(null);
  }, []);

  return { data, isLoading, error, fetchTrace, clear };
}
