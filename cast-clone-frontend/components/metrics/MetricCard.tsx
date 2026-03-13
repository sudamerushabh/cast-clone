"use client"

import * as React from "react"
import type { LucideIcon } from "lucide-react"

interface MetricCardProps {
  title: string
  value: number | string
  icon: LucideIcon
  subtitle?: string
  className?: string
}

export function MetricCard({ title, value, icon: Icon, subtitle, className }: MetricCardProps) {
  return (
    <div className={`rounded-lg border bg-card p-4 ${className ?? ""}`}>
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">{title}</span>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-2 text-2xl font-bold">{typeof value === "number" ? value.toLocaleString() : value}</div>
      {subtitle && <div className="mt-1 text-xs text-muted-foreground">{subtitle}</div>}
    </div>
  )
}
