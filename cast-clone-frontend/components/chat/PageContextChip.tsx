// components/chat/PageContextChip.tsx
"use client";

import {
  GitGraph,
  Activity,
  LayoutDashboard,
  GitPullRequest,
  Search,
  Bookmark,
  Settings,
  MessageCircle,
  Network,
} from "lucide-react";
import type { PageContext } from "@/lib/chat-types";

const PAGE_LABELS: Record<string, { label: string; icon: React.ElementType }> = {
  graph_explorer: { label: "Graph Explorer", icon: GitGraph },
  impact_analysis: { label: "Impact Analysis", icon: Activity },
  transactions: { label: "Transactions", icon: Network },
  dependency_view: { label: "Dependencies", icon: GitGraph },
  pr_detail: { label: "PR Detail", icon: GitPullRequest },
  pr_list: { label: "Pull Requests", icon: GitPullRequest },
  search: { label: "Search", icon: Search },
  saved_views: { label: "Saved Views", icon: Bookmark },
  settings: { label: "Settings", icon: Settings },
  chat: { label: "Chat", icon: MessageCircle },
  dashboard: { label: "Dashboard", icon: LayoutDashboard },
};

interface PageContextChipProps {
  context: PageContext;
  isActive: boolean;
}

export function PageContextChip({ context, isActive }: PageContextChipProps) {
  if (!isActive) return null;

  const pageInfo = PAGE_LABELS[context.page] ?? {
    label: context.page,
    icon: LayoutDashboard,
  };
  const Icon = pageInfo.icon;

  // Build a short description of what the user is viewing
  let detail: string | null = null;
  if (context.selected_node_fqn) {
    const shortName = context.selected_node_fqn.includes(".")
      ? context.selected_node_fqn.split(".").pop()!
      : context.selected_node_fqn;
    detail = shortName;
  } else if (context.view) {
    detail = context.view;
    if (context.level) {
      detail += ` (${context.level})`;
    }
  }

  return (
    <div className="flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/50 px-2.5 py-0.5 text-xs text-muted-foreground">
      <Icon className="size-3 shrink-0" />
      <span className="truncate">
        {pageInfo.label}
        {detail && (
          <>
            <span className="mx-1 opacity-40">|</span>
            <span className="font-medium text-foreground/70">{detail}</span>
          </>
        )}
      </span>
    </div>
  );
}
