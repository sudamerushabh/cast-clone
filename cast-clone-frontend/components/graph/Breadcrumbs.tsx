"use client"

import * as React from "react"
import { ChevronRight, Home } from "lucide-react"
import { cn } from "@/lib/utils"

export interface BreadcrumbSegment {
  level: "module" | "class"
  fqn: string
  name: string
}

interface BreadcrumbsProps {
  path: BreadcrumbSegment[]
  onNavigateHome: () => void
}

export function Breadcrumbs({ path, onNavigateHome }: BreadcrumbsProps) {
  return (
    <nav
      aria-label="Drill-down breadcrumbs"
      className="flex items-center gap-1 overflow-x-auto px-3 py-1.5 text-sm"
    >
      <button
        onClick={onNavigateHome}
        className={cn(
          "flex shrink-0 items-center gap-1 rounded-sm px-1.5 py-0.5 transition-colors",
          path.length === 0
            ? "font-medium text-foreground"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"
        )}
        disabled={path.length === 0}
      >
        <Home className="size-3" />
        <span>Application</span>
      </button>

      {path.map((segment, index) => {
        const isLast = index === path.length - 1
        return (
          <React.Fragment key={`${index}-${segment.fqn}`}>
            <ChevronRight className="size-3 shrink-0 text-muted-foreground/50" />
            <span
              className={cn(
                "shrink-0 truncate rounded-sm px-1.5 py-0.5",
                isLast
                  ? "font-medium text-foreground"
                  : "text-muted-foreground"
              )}
              title={segment.fqn}
            >
              {segment.name}
            </span>
          </React.Fragment>
        )
      })}
    </nav>
  )
}
