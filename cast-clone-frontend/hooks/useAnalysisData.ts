"use client";

import { useCallback, useState } from "react";
import {
  getCommunities,
  getCircularDependencies,
  getDeadCode,
  getMetrics,
  getNodeDetails,
} from "@/lib/api";
import type {
  CommunitiesResponse,
  CircularDependenciesResponse,
  DeadCodeResponse,
  MetricsResponse,
  NodeDetailResponse,
} from "@/lib/types";

interface AnalysisDataState {
  communities: CommunitiesResponse | null;
  circularDeps: CircularDependenciesResponse | null;
  deadCode: DeadCodeResponse | null;
  metrics: MetricsResponse | null;
  nodeDetails: NodeDetailResponse | null;
}

interface UseAnalysisDataReturn extends AnalysisDataState {
  isLoading: boolean;
  error: string | null;
  loadCommunities: (projectId: string) => Promise<void>;
  loadCircularDeps: (
    projectId: string,
    level?: "module" | "class",
  ) => Promise<void>;
  loadDeadCode: (
    projectId: string,
    type?: "function" | "class",
    minLoc?: number,
  ) => Promise<void>;
  loadMetrics: (projectId: string) => Promise<void>;
  loadNodeDetails: (projectId: string, fqn: string) => Promise<void>;
}

export function useAnalysisData(): UseAnalysisDataReturn {
  const [state, setState] = useState<AnalysisDataState>({
    communities: null,
    circularDeps: null,
    deadCode: null,
    metrics: null,
    nodeDetails: null,
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wrapLoad = useCallback(
    async <K extends keyof AnalysisDataState>(
      key: K,
      fetcher: () => Promise<AnalysisDataState[K]>,
    ) => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await fetcher();
        setState((prev) => ({ ...prev, [key]: result }));
      } catch (err) {
        setError(
          err instanceof Error ? err.message : `Failed to load ${key}`,
        );
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  const loadCommunities = useCallback(
    (projectId: string) =>
      wrapLoad("communities", () => getCommunities(projectId)),
    [wrapLoad],
  );

  const loadCircularDeps = useCallback(
    (projectId: string, level: "module" | "class" = "module") =>
      wrapLoad("circularDeps", () =>
        getCircularDependencies(projectId, level),
      ),
    [wrapLoad],
  );

  const loadDeadCode = useCallback(
    (
      projectId: string,
      type: "function" | "class" = "function",
      minLoc = 5,
    ) => wrapLoad("deadCode", () => getDeadCode(projectId, type, minLoc)),
    [wrapLoad],
  );

  const loadMetrics = useCallback(
    (projectId: string) =>
      wrapLoad("metrics", () => getMetrics(projectId)),
    [wrapLoad],
  );

  const loadNodeDetails = useCallback(
    (projectId: string, fqn: string) =>
      wrapLoad("nodeDetails", () => getNodeDetails(projectId, fqn)),
    [wrapLoad],
  );

  return {
    ...state,
    isLoading,
    error,
    loadCommunities,
    loadCircularDeps,
    loadDeadCode,
    loadMetrics,
    loadNodeDetails,
  };
}
