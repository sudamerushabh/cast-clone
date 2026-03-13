// cast-clone-frontend/hooks/useTraceRoute.ts
"use client";

import { useCallback, useState } from "react";
import { getImpactAnalysis, getShortestPath } from "@/lib/api";
import type { ImpactAnalysisResponse, PathEdge } from "@/lib/types";

export interface TraceEdge {
  source: string;
  target: string;
  type: string;
}

// Edge types that represent actual call/dependency flow (not structural containment)
const CALL_FLOW_EDGE_TYPES = new Set([
  "CALLS", "IMPLEMENTS", "INHERITS", "DEPENDS_ON", "STARTS_AT",
  "INJECTS", "PRODUCES", "CONSUMES", "READS", "WRITES",
]);

function isCallFlowEdge(edgeType: string): boolean {
  return CALL_FLOW_EDGE_TYPES.has(edgeType);
}

interface UseTraceRouteResult {
  upstreamData: ImpactAnalysisResponse | null;
  downstreamData: ImpactAnalysisResponse | null;
  edges: TraceEdge[];
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
  const [edges, setEdges] = useState<TraceEdge[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTrace = useCallback(async (projectId: string, fqn: string) => {
    setIsLoading(true);
    setError(null);
    try {
      // Step 1: Get affected nodes (upstream + downstream)
      const [upstream, downstream] = await Promise.all([
        getImpactAnalysis(projectId, fqn, "upstream", 10),
        getImpactAnalysis(projectId, fqn, "downstream", 10),
      ]);
      setUpstreamData(upstream);
      setDownstreamData(downstream);

      // Step 2: Fetch actual paths for each affected node via path finder
      // This gives us real edges instead of guessing from depth
      const edgeMap = new Map<string, TraceEdge>();

      const pathPromises: Promise<void>[] = [];

      // Upstream: path from each caller → center node
      for (const node of upstream.affected) {
        pathPromises.push(
          getShortestPath(projectId, node.fqn, fqn, 10)
            .then((pathResult) => {
              for (const edge of pathResult.edges) {
                // Filter out structural edges (INCLUDES, CONTAINS) that create
                // shortcuts through Transaction nodes. Only keep actual call-flow edges.
                if (!isCallFlowEdge(edge.type)) continue;
                const key = `${edge.source}->${edge.target}`;
                if (!edgeMap.has(key)) {
                  edgeMap.set(key, { source: edge.source, target: edge.target, type: edge.type });
                }
              }
            })
            .catch(() => {
              // Path not found for this node — skip silently
            }),
        );
      }

      // Downstream: path from center node → each callee
      for (const node of downstream.affected) {
        pathPromises.push(
          getShortestPath(projectId, fqn, node.fqn, 10)
            .then((pathResult) => {
              for (const edge of pathResult.edges) {
                if (!isCallFlowEdge(edge.type)) continue;
                const key = `${edge.source}->${edge.target}`;
                if (!edgeMap.has(key)) {
                  edgeMap.set(key, { source: edge.source, target: edge.target, type: edge.type });
                }
              }
            })
            .catch(() => {
              // Path not found for this node — skip silently
            }),
        );
      }

      await Promise.all(pathPromises);
      setEdges([...edgeMap.values()]);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Trace route failed",
      );
      setUpstreamData(null);
      setDownstreamData(null);
      setEdges([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setUpstreamData(null);
    setDownstreamData(null);
    setEdges([]);
    setError(null);
  }, []);

  return { upstreamData, downstreamData, edges, isLoading, error, fetchTrace, clear };
}
