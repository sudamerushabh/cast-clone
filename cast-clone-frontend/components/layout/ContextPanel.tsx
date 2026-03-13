"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  FolderGit2,
  GitBranch,
  LayoutDashboard,
  Monitor,
  Bot,
  Users,
  Activity,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ProjectContextNav } from "./ProjectContextNav";
import { cn } from "@/lib/utils";

/**
 * Parse the pathname to extract repoId and branch for project context.
 * Supports both overview (/repositories/[repoId]/[branch]) and
 * view-prefix patterns (/repositories/[repoId]/graph/[branch], etc.).
 */
function parseProjectRoute(pathname: string): {
  repoId: string;
  branch: string;
} | null {
  // Exclude pull-requests routes — they are not branch/project pages
  if (pathname.match(/^\/repositories\/[^/]+\/pull-requests/)) return null;

  const match = pathname.match(
    /^\/repositories\/([^/]+)\/(?:(?:graph|dependencies|transactions|search|impact|views|chat|settings)\/)?(.+)$/,
  );
  if (!match) return null;
  return { repoId: match[1], branch: match[2] };
}

interface SectionNavItem {
  label: string;
  href: string;
  icon: React.ElementType;
}

function SectionNav({
  title,
  items,
  pathname,
}: {
  title: string;
  items: SectionNavItem[];
  pathname: string;
}) {
  return (
    <ScrollArea className="h-full">
      <div className="flex flex-col gap-1 p-2">
        <div className="mb-1 px-2 text-xs font-medium text-sidebar-foreground/50">
          {title}
        </div>
        {items.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
              )}
            >
              <item.icon className="size-4 shrink-0" />
              <span className="truncate">{item.label}</span>
            </Link>
          );
        })}
      </div>
    </ScrollArea>
  );
}

/**
 * Hook to check if the current route has a context panel.
 * Used by GlobalShell to conditionally render the aside.
 */
export function useHasContextPanel(): boolean {
  const pathname = usePathname();

  // Branch/project pages have the ProjectContextNav
  if (pathname.match(/^\/repositories\/[^/]+\/pull-requests/)) return false;
  const projectMatch = pathname.match(
    /^\/repositories\/([^/]+)\/(?:(?:graph|dependencies|transactions|search|impact|views|chat|settings)\/)?(.+)$/,
  );
  if (projectMatch) return true;

  // Settings has sub-navigation
  if (pathname.startsWith("/settings")) return true;

  return false;
}

export function ContextPanel() {
  const pathname = usePathname();

  // Project context: /repositories/[repoId]/[branch]/*
  const projectCtx = parseProjectRoute(pathname);
  if (projectCtx) {
    return (
      <ProjectContextNav
        repoId={projectCtx.repoId}
        branch={projectCtx.branch}
      />
    );
  }

  // Settings section — has multiple sub-pages worth navigating
  if (pathname.startsWith("/settings")) {
    return (
      <SectionNav
        title="Settings"
        pathname={pathname}
        items={[
          { label: "System", href: "/settings/system", icon: Monitor },
          { label: "AI Configuration", href: "/settings/ai", icon: Bot },
          { label: "Team", href: "/settings/team", icon: Users },
          { label: "Activity", href: "/settings/activity", icon: Activity },
        ]}
      />
    );
  }

  // All other pages (Home, Repositories list, Repository detail,
  // Connectors, PR analysis) — the main sidebar is sufficient.
  return null;
}
