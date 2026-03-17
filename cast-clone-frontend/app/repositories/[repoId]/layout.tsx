// app/repositories/[repoId]/layout.tsx
"use client";

import { useParams, usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getRepository } from "@/lib/api";
import { ChatProvider } from "@/components/chat/ChatProvider";
import { ChatDrawer } from "@/components/chat/ChatDrawer";
import type { RepositoryResponse } from "@/lib/types";

/**
 * Extracts the branch name from the current URL pathname.
 * Routes follow patterns like:
 *   /repositories/:repoId/:branch          (overview)
 *   /repositories/:repoId/graph/:branch    (graph)
 *   /repositories/:repoId/search/:branch   (search)
 *   /repositories/:repoId/pull-requests    (no branch)
 *
 * The branch can contain slashes (e.g. "feature/audit-log-api"),
 * which are encoded as separate path segments.
 */
function extractBranchFromPath(pathname: string, repoId: string): string | null {
  const repoPrefix = `/repositories/${repoId}`;
  const rest = pathname.slice(repoPrefix.length);
  if (!rest || rest === "/") return null;

  // Known sub-route prefixes that come before the branch segments
  const subRoutes = [
    "/graph/",
    "/search/",
    "/impact/",
    "/dependencies/",
    "/transactions/",
    "/views/",
    "/settings/",
    "/chat/",
  ];

  for (const prefix of subRoutes) {
    if (rest.startsWith(prefix)) {
      const branchPart = rest.slice(prefix.length);
      return branchPart ? decodeURIComponent(branchPart) : null;
    }
  }

  // Pages with no branch (repo-level)
  if (
    rest === "/pull-requests" ||
    rest.startsWith("/pull-requests/")
  ) {
    return null;
  }

  // The remaining case: /repositories/:repoId/:branch (overview)
  // rest starts with "/" followed by the branch segments
  const branchPart = rest.slice(1); // remove leading "/"
  return branchPart ? decodeURIComponent(branchPart) : null;
}

export default function RepoLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const pathname = usePathname();
  const repoId = params.repoId as string;

  const [repo, setRepo] = useState<RepositoryResponse | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);

  const branch = extractBranchFromPath(pathname, repoId);

  // Fetch repo to resolve branch → projectId
  useEffect(() => {
    let cancelled = false;
    getRepository(repoId).then((r) => {
      if (!cancelled) setRepo(r);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [repoId]);

  // Resolve projectId when branch or repo changes.
  // If no branch in URL, fall back to the first analyzed project in the repo
  // so the chat FAB is available on all repo-level pages too.
  useEffect(() => {
    if (!repo) {
      setProjectId(null);
      return;
    }
    if (branch) {
      const match = repo.projects.find((p) => p.branch === branch);
      setProjectId(match?.id ?? null);
    } else {
      // Fallback: pick first analyzed project, or first project
      const fallback =
        repo.projects.find((p) => p.status === "analyzed") ??
        repo.projects[0] ??
        null;
      setProjectId(fallback?.id ?? null);
    }
  }, [repo, branch]);

  const chatLabel = branch ?? repo?.projects.find((p) => p.id === projectId)?.branch ?? undefined;

  // If we have a projectId, wrap with ChatProvider
  if (projectId) {
    return (
      <ChatProvider projectId={projectId} projectName={chatLabel}>
        {children}
        <ChatDrawer projectName={chatLabel} />
      </ChatProvider>
    );
  }

  // No projects at all — render without chat
  return <>{children}</>;
}
