"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter, useParams } from "next/navigation";
import { Moon, Network, Search, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { SearchDialog } from "@/components/search/SearchDialog";
import { getRepository } from "@/lib/api";
import { UserMenu } from "./UserMenu";

/**
 * Build breadcrumbs from the current pathname.
 * Examples:
 *   / -> [Home]
 *   /repositories -> [Home, Repositories]
 *   /repositories/abc123/main/graph -> [Home, Repositories, abc123, main, Architecture]
 */
function buildBreadcrumbs(pathname: string): { label: string; href: string }[] {
  const crumbs: { label: string; href: string }[] = [
    { label: "Home", href: "/" },
  ];

  if (pathname === "/") return crumbs;

  const segments = pathname.split("/").filter(Boolean);
  let currentPath = "";

  for (const segment of segments) {
    currentPath += `/${segment}`;
    const decoded = decodeURIComponent(segment);
    // Prettify known segments
    const label =
      decoded === "graph"
        ? "Architecture"
        : decoded === "repositories"
          ? "Repositories"
          : decoded === "connectors"
            ? "Connectors"
            : decoded === "settings"
              ? "Settings"
              : decoded === "system"
                ? "System"
                : decoded;
    crumbs.push({ label, href: currentPath });
  }

  return crumbs;
}

/**
 * Extract the branch name from a repo-scoped pathname (mirrors the logic in
 * app/repositories/[repoId]/layout.tsx).
 */
function extractBranchFromPath(pathname: string, repoId: string): string | null {
  const repoPrefix = `/repositories/${repoId}`;
  const rest = pathname.slice(repoPrefix.length);
  if (!rest || rest === "/") return null;

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

  if (rest === "/pull-requests" || rest.startsWith("/pull-requests/")) {
    return null;
  }

  const branchPart = rest.slice(1);
  return branchPart ? decodeURIComponent(branchPart) : null;
}

/**
 * Resolve the currently-scoped projectId from the URL. Returns null on any
 * page that is not tied to a specific repository/branch so the dialog renders
 * in a disabled state rather than breaking.
 */
function useCurrentProjectId(): { projectId: string | null; repoId: string | null; branch: string | null } {
  const params = useParams();
  const pathname = usePathname();
  const repoId = (params?.repoId as string | undefined) ?? null;
  const branch = repoId ? extractBranchFromPath(pathname, repoId) : null;

  const [projectId, setProjectId] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!repoId) {
      setProjectId(null);
      return;
    }
    let cancelled = false;
    getRepository(repoId)
      .then((repo) => {
        if (cancelled) return;
        if (branch) {
          const match = repo.projects.find((p) => p.branch === branch);
          setProjectId(match?.id ?? null);
          return;
        }
        // Fall back to first analyzed project so the user can still search
        // from repo-level pages (pull-requests, overview, etc.).
        const fallback =
          repo.projects.find((p) => p.status === "analyzed") ??
          repo.projects[0] ??
          null;
        setProjectId(fallback?.id ?? null);
      })
      .catch(() => {
        if (!cancelled) setProjectId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [repoId, branch]);

  return { projectId, repoId, branch };
}

export function TopBar() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const crumbs = buildBreadcrumbs(pathname);

  const { projectId, repoId, branch } = useCurrentProjectId();
  const [searchOpen, setSearchOpen] = React.useState(false);

  // Global Cmd/Ctrl+K — works on every page where the TopBar is mounted.
  React.useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const handleNavigate = React.useCallback(
    (fqn: string) => {
      if (!repoId) return;
      // Same URL shape the rest of the app uses for focusing a graph node.
      const branchSegment = branch ?? "main";
      router.push(
        `/repositories/${repoId}/graph/${branchSegment}?focus=${encodeURIComponent(fqn)}`,
      );
    },
    [router, repoId, branch],
  );

  return (
    <header className="flex h-11 shrink-0 items-center gap-2 border-b bg-background px-3">
      {/* Logo */}
      <Link
        href="/"
        className="flex items-center gap-1.5 text-sm font-semibold"
      >
        <Network className="size-4 text-primary" />
        <span>ChangeSafe</span>
      </Link>

      {/* Breadcrumbs */}
      <nav className="flex items-center gap-1 text-sm" aria-label="Breadcrumb">
        {crumbs.slice(1).map((crumb, i) => (
          <React.Fragment key={crumb.href}>
            <span className="text-muted-foreground">/</span>
            {i === crumbs.length - 2 ? (
              <span className="truncate text-muted-foreground">
                {crumb.label}
              </span>
            ) : (
              <Link
                href={crumb.href}
                className="truncate text-muted-foreground hover:text-foreground"
              >
                {crumb.label}
              </Link>
            )}
          </React.Fragment>
        ))}
      </nav>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Search trigger */}
      <button
        type="button"
        onClick={() => setSearchOpen(true)}
        aria-label="Open search"
        className="inline-flex h-7 items-center gap-2 rounded border bg-background px-2 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Search className="size-3.5" />
        <span className="hidden sm:inline">Search</span>
        <kbd className="pointer-events-none hidden h-4 select-none items-center gap-0.5 rounded border bg-muted px-1 font-mono text-[10px] font-medium sm:inline-flex">
          ⌘K
        </kbd>
      </button>

      <UserMenu />

      {/* Theme toggle */}
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        aria-label="Toggle theme"
      >
        <Sun className="size-4 dark:hidden" />
        <Moon className="hidden size-4 dark:block" />
      </Button>

      <SearchDialog
        projectId={projectId}
        onNavigate={handleNavigate}
        open={searchOpen}
        onOpenChange={setSearchOpen}
      />
    </header>
  );
}
