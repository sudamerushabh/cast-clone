// cast-clone-frontend/hooks/useTraceRoute.ts
"use client";

import { useCallback, useState } from "react";
import { getImpactAnalysis } from "@/lib/api";
import type { ImpactAnalysisResponse } from "@/lib/types";

interface UseTraceRouteResult {
  upstreamData: ImpactAnalysisResponse | null;
  downstreamData: ImpactAnalysisResponse | null;
  isLoading: boolean;
  error: string | null;
  fetchTrace: (projectId: string, fqn: string) => Promise<void>;
  clear: () => void;
}

export function useTraceRoute(): UseTraceRouteResult {
  const [upstreamData, setUpstreamData] =
    useState<ImpactAnalysisResponse | null>(null);
  const [downstreamData, setDownstreamData] =
    useState<ImpactAnalysisResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTrace = useCallback(async (projectId: string, fqn: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const [upstream, downstream] = await Promise.all([
        getImpactAnalysis(projectId, fqn, "upstream", 10),
        getImpactAnalysis(projectId, fqn, "downstream", 10),
      ]);
      setUpstreamData(upstream);
      setDownstreamData(downstream);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Trace route failed",
      );
      setUpstreamData(null);
      setDownstreamData(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setUpstreamData(null);
    setDownstreamData(null);
    setError(null);
  }, []);

  return { upstreamData, downstreamData, isLoading, error, fetchTrace, clear };
}
