"use client";

import { useCallback, useState } from "react";
import { getShortestPath } from "@/lib/api";
import type { PathFinderResponse } from "@/lib/types";

interface UsePathFinderReturn {
  data: PathFinderResponse | null;
  isLoading: boolean;
  error: string | null;
  findPath: (
    projectId: string,
    fromFqn: string,
    toFqn: string,
    maxDepth?: number,
  ) => Promise<void>;
  clear: () => void;
}

export function usePathFinder(): UsePathFinderReturn {
  const [data, setData] = useState<PathFinderResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const findPath = useCallback(
    async (
      projectId: string,
      fromFqn: string,
      toFqn: string,
      maxDepth: number = 10,
    ) => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await getShortestPath(
          projectId,
          fromFqn,
          toFqn,
          maxDepth,
        );
        setData(result);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Path finding failed",
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

  return { data, isLoading, error, findPath, clear };
}
