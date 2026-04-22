"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  FileSearch,
  GitGraph,
  GitPullRequest,
  LayoutDashboard,
  MessageSquare,
  Network,
  Save,
  Settings,
  Target,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface RepoTabsProps {
  repoId: string;
}

interface TabDef {
  slug: string; // empty string = overview (no sub-route)
  label: string;
  Icon: React.ComponentType<{ className?: string }>;
  /** If true, this tab lives at /repositories/:repoId/<slug> with no branch suffix. */
  noBranch?: boolean;
}

// Ordered list. Primary acceptance-criteria set first, existing extras preserved afterward.
const TABS: TabDef[] = [
  { slug: "", label: "Overview", Icon: LayoutDashboard },
  { slug: "search", label: "Search", Icon: FileSearch },
  { slug: "views", label: "Views", Icon: Save },
  { slug: "impact", label: "Impact", Icon: Target },
  { slug: "dependencies", label: "Dependencies", Icon: Network },
  { slug: "graph", label: "Graph", Icon: GitGraph },
  { slug: "transactions", label: "Transactions", Icon: Activity },
  { slug: "chat", label: "Chat", Icon: MessageSquare },
  { slug: "pull-requests", label: "Pull Requests", Icon: GitPullRequest, noBranch: true },
  { slug: "settings", label: "Settings", Icon: Settings },
];

// Sub-route slugs that carry a branch catch-all segment.
const BRANCHED_SLUGS = new Set([
  "search",
  "views",
  "impact",
  "dependencies",
  "graph",
  "transactions",
  "chat",
  "settings",
]);

/**
 * Extracts the branch segments (already URL-encoded path) from the current pathname.
 * Returns "" if no branch is present (e.g. on the repo root or pull-requests).
 *
 * Examples:
 *   /repositories/123                           -> ""
 *   /repositories/123/main                      -> "main"
 *   /repositories/123/feature/x                 -> "feature/x"
 *   /repositories/123/search/main               -> "main"
 *   /repositories/123/search/feature/x          -> "feature/x"
 *   /repositories/123/pull-requests             -> ""
 */
function extractBranchSegments(pathname: string, repoId: string): string {
  const prefix = `/repositories/${repoId}`;
  if (!pathname.startsWith(prefix)) return "";
  const rest = pathname.slice(prefix.length);
  if (!rest || rest === "/") return "";
  const trimmed = rest.replace(/^\//, "").replace(/\/$/, "");
  if (!trimmed) return "";

  const [first, ...tail] = trimmed.split("/");
  if (first === "pull-requests") return "";
  if (BRANCHED_SLUGS.has(first)) {
    return tail.join("/");
  }
  // Overview route: the whole remainder is the branch.
  return trimmed;
}

/**
 * Returns the top-level sub-route slug for the current pathname, or "" for the overview.
 */
function extractActiveSlug(pathname: string, repoId: string): string {
  const prefix = `/repositories/${repoId}`;
  if (!pathname.startsWith(prefix)) return "";
  const rest = pathname.slice(prefix.length).replace(/^\//, "");
  if (!rest) return "";
  const [first] = rest.split("/");
  if (first === "pull-requests") return "pull-requests";
  if (BRANCHED_SLUGS.has(first)) return first;
  return ""; // overview
}

function buildHref(repoId: string, tab: TabDef, branchSegments: string): string {
  const base = `/repositories/${repoId}`;
  if (tab.slug === "") {
    // Overview — append branch if we have one.
    return branchSegments ? `${base}/${branchSegments}` : base;
  }
  if (tab.noBranch) {
    return `${base}/${tab.slug}`;
  }
  return branchSegments ? `${base}/${tab.slug}/${branchSegments}` : `${base}/${tab.slug}`;
}

export function RepoTabs({ repoId }: RepoTabsProps) {
  const pathname = usePathname() ?? "";
  const branchSegments = extractBranchSegments(pathname, repoId);
  const activeSlug = extractActiveSlug(pathname, repoId);

  return (
    <nav
      aria-label="Repository sections"
      className="border-b border-border bg-background"
    >
      <ul className="flex flex-wrap items-center gap-0.5 px-4 pt-2">
        {TABS.map((tab) => {
          const href = buildHref(repoId, tab, branchSegments);
          const isActive = tab.slug === activeSlug;
          const { Icon } = tab;
          return (
            <li key={tab.slug || "overview"}>
              <Link
                href={href}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-t-md border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:border-border hover:text-foreground",
                )}
              >
                <Icon className="size-4" />
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
