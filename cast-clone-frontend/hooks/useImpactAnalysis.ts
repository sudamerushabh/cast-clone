"use client";

import { useCallback, useState } from "react";
import { getImpactAnalysis } from "@/lib/api";
import type { ImpactAnalysisResponse } from "@/lib/types";

interface UseImpactAnalysisReturn {
  data: ImpactAnalysisResponse | null;
  isLoading: boolean;
  error: string | null;
  analyze: (
    projectId: string,
    nodeFqn: string,
    direction?: "downstream" | "upstream" | "both",
    maxDepth?: number,
  ) => Promise<void>;
  clear: () => void;
}

export function useImpactAnalysis(): UseImpactAnalysisReturn {
  const [data, setData] = useState<ImpactAnalysisResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = useCallback(
    async (
      projectId: string,
      nodeFqn: string,
      direction: "downstream" | "upstream" | "both" = "downstream",
      maxDepth: number = 5,
    ) => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await getImpactAnalysis(
          projectId,
          nodeFqn,
          direction,
          maxDepth,
        );
        setData(result);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Impact analysis failed",
        );
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

  return { data, isLoading, error, analyze, clear };
}
