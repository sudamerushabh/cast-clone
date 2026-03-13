"use client"

import * as React from "react"
import type { RankedItem } from "@/lib/types"

interface TopTenTableProps {
  title: string
  items: RankedItem[]
  valueLabel: string
  onRowClick?: (fqn: string) => void
}

export function TopTenTable({ title, items, valueLabel, onRowClick }: TopTenTableProps) {
  return (
    <div className="rounded-lg border bg-card">
      <div className="px-4 py-3 border-b">
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="text-left px-4 py-2 font-medium">#</th>
              <th className="text-left px-4 py-2 font-medium">Name</th>
              <th className="text-right px-4 py-2 font-medium">{valueLabel}</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={3} className="px-4 py-4 text-center text-muted-foreground">
                  No data available
                </td>
              </tr>
            )}
            {items.map((item, idx) => (
              <tr
                key={item.fqn}
                className="border-b last:border-0 hover:bg-muted/50 cursor-pointer"
                onClick={() => onRowClick?.(item.fqn)}
              >
                <td className="px-4 py-2 text-muted-foreground">{idx + 1}</td>
                <td className="px-4 py-2">
                  <div className="font-medium">{item.name}</div>
                  <div className="text-xs text-muted-foreground font-mono truncate max-w-xs">{item.fqn}</div>
                </td>
                <td className="px-4 py-2 text-right font-mono font-medium">{item.value.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
