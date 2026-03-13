"use client"

import * as React from "react"
import { useParams, useRouter } from "next/navigation"
import {
  ArrowLeft,
  Box,
  Code2,
  FileCode2,
  Hash,
  Loader2,
  Palette,
  RefreshCcw,
  Trash2,
} from "lucide-react"

import { useAnalysisData } from "@/hooks/useAnalysisData"
import { MetricCard } from "@/components/metrics/MetricCard"
import { TopTenTable } from "@/components/metrics/TopTenTable"
import { Button } from "@/components/ui/button"

export default function MetricsDashboardPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const projectId = params.id

  const { metrics, isLoading, error, loadMetrics } = useAnalysisData()

  React.useEffect(() => {
    loadMetrics(projectId)
  }, [projectId, loadMetrics])

  function handleRowClick(fqn: string) {
    router.push(`/projects/${projectId}/graph?select=${encodeURIComponent(fqn)}`)
  }

  return (
    <div className="container mx-auto max-w-6xl px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <Button
          variant="ghost"
          size="sm"
          className="mb-4"
          onClick={() => router.push(`/projects/${projectId}`)}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Project
        </Button>
        <h1 className="text-2xl font-bold tracking-tight">Metrics Dashboard</h1>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6 rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Loading */}
      {isLoading && !metrics && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {metrics && (
        <>
          {/* Summary cards */}
          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="Modules"
              value={metrics.overview.modules}
              icon={Box}
              subtitle="Top-level packages"
            />
            <MetricCard
              title="Classes"
              value={metrics.overview.classes}
              icon={Code2}
              subtitle="Types and interfaces"
            />
            <MetricCard
              title="Functions"
              value={metrics.overview.functions}
              icon={FileCode2}
              subtitle="Methods and functions"
            />
            <MetricCard
              title="Total LOC"
              value={metrics.overview.total_loc}
              icon={Hash}
              subtitle="Lines of code"
            />
          </div>

          {/* Analysis cards */}
          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <MetricCard
              title="Communities"
              value={metrics.community_count}
              icon={Palette}
              subtitle="Detected clusters"
            />
            <MetricCard
              title="Circular Dependencies"
              value={metrics.circular_dependency_count}
              icon={RefreshCcw}
              subtitle="Dependency cycles"
              className={metrics.circular_dependency_count > 0 ? "border-red-500" : ""}
            />
            <MetricCard
              title="Dead Code Candidates"
              value={metrics.dead_code_count}
              icon={Trash2}
              subtitle="Unreferenced symbols"
            />
          </div>

          {/* Top-10 tables */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <TopTenTable
              title="Most Complex"
              items={metrics.most_complex}
              valueLabel="Complexity"
              onRowClick={handleRowClick}
            />
            <TopTenTable
              title="Highest Fan-In"
              items={metrics.highest_fan_in}
              valueLabel="Fan-In"
              onRowClick={handleRowClick}
            />
            <TopTenTable
              title="Highest Fan-Out"
              items={metrics.highest_fan_out}
              valueLabel="Fan-Out"
              onRowClick={handleRowClick}
            />
          </div>
        </>
      )}
    </div>
  )
}
