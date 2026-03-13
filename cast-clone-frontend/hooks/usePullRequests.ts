"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchRepoPrAnalyses,
  fetchRepoPrAnalysis,
  fetchRepoPrImpact,
  fetchRepoPrDrift,
} from "@/lib/api";
import type {
  PrAnalysis,
  PrAnalysisList,
  PrImpactDetail,
  PrDriftDetail,
} from "@/lib/types";

export function useRepoPrAnalyses(
  repoId: string,
  filters?: { status?: string; risk?: string },
) {
  const [data, setData] = useState<PrAnalysisList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchRepoPrAnalyses(repoId, filters);
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [repoId, filters?.status, filters?.risk]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}

export function useRepoPrDetail(repoId: string, analysisId: string) {
  const [analysis, setAnalysis] = useState<PrAnalysis | null>(null);
  const [impact, setImpact] = useState<PrImpactDetail | null>(null);
  const [drift, setDrift] = useState<PrDriftDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [a, i, d] = await Promise.all([
          fetchRepoPrAnalysis(repoId, analysisId),
          fetchRepoPrImpact(repoId, analysisId).catch(() => null),
          fetchRepoPrDrift(repoId, analysisId).catch(() => null),
        ]);
        setAnalysis(a);
        setImpact(i);
        setDrift(d);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [repoId, analysisId]);

  return { analysis, impact, drift, loading };
}
