"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchPrAnalyses,
  fetchPrAnalysis,
  fetchPrImpact,
  fetchPrDrift,
} from "@/lib/api";
import type {
  PrAnalysis,
  PrAnalysisList,
  PrImpactDetail,
  PrDriftDetail,
} from "@/lib/types";

export function usePrAnalyses(
  projectId: string,
  filters?: { status?: string; risk?: string },
) {
  const [data, setData] = useState<PrAnalysisList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchPrAnalyses(projectId, filters);
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [projectId, filters?.status, filters?.risk]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}

export function usePrDetail(projectId: string, analysisId: string) {
  const [analysis, setAnalysis] = useState<PrAnalysis | null>(null);
  const [impact, setImpact] = useState<PrImpactDetail | null>(null);
  const [drift, setDrift] = useState<PrDriftDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [a, i, d] = await Promise.all([
          fetchPrAnalysis(projectId, analysisId),
          fetchPrImpact(projectId, analysisId).catch(() => null),
          fetchPrDrift(projectId, analysisId).catch(() => null),
        ]);
        setAnalysis(a);
        setImpact(i);
        setDrift(d);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [projectId, analysisId]);

  return { analysis, impact, drift, loading };
}
