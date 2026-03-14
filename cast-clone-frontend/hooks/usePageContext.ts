// hooks/usePageContext.ts
"use client";

import { useMemo } from "react";
import { usePathname, useParams } from "next/navigation";
import type { PageContext } from "@/lib/chat-types";

/**
 * Reads the current route and extracts structured page context
 * for the AI chat assistant. This tells the agent what the user
 * is currently looking at so it can give contextual answers.
 *
 * The `selectedNodeFqn` must be passed in from the graph state
 * since it's not in the URL.
 */
export function usePageContext(opts?: {
  selectedNodeFqn?: string | null;
  view?: string | null;
  level?: string | null;
}): PageContext {
  const pathname = usePathname();
  const params = useParams();

  return useMemo(() => {
    const repoId = params?.repoId as string | undefined;
    const branchSegments = params?.branch as string[] | undefined;
    const analysisId = params?.analysisId as string | undefined;

    // Determine which page the user is on from the pathname
    let page = "dashboard";
    if (pathname.includes("/graph/")) {
      page = "graph_explorer";
    } else if (pathname.includes("/impact/")) {
      page = "impact_analysis";
    } else if (pathname.includes("/transactions/")) {
      page = "transactions";
    } else if (pathname.includes("/dependencies/")) {
      page = "dependency_view";
    } else if (pathname.includes("/pull-requests/") && analysisId) {
      page = "pr_detail";
    } else if (pathname.includes("/pull-requests")) {
      page = "pr_list";
    } else if (pathname.includes("/search/")) {
      page = "search";
    } else if (pathname.includes("/views/")) {
      page = "saved_views";
    } else if (pathname.includes("/settings/")) {
      page = "settings";
    } else if (pathname.includes("/chat/")) {
      page = "chat";
    } else if (repoId && branchSegments) {
      page = "dashboard";
    }

    return {
      page,
      selected_node_fqn: opts?.selectedNodeFqn ?? null,
      view: opts?.view ?? null,
      level: opts?.level ?? null,
      pr_analysis_id: analysisId ?? null,
    };
  }, [pathname, params, opts?.selectedNodeFqn, opts?.view, opts?.level]);
}
