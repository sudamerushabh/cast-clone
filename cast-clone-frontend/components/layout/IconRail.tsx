"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ChevronLeft,
  ChevronRight,
  FolderGit2,
  GitBranch,
  LayoutDashboard,
  Settings,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
  matchPrefix: string;
}

const topItems: NavItem[] = [
  {
    label: "Home",
    href: "/",
    icon: LayoutDashboard,
    matchPrefix: "/__exact__",
  },
  {
    label: "Repositories",
    href: "/repositories",
    icon: FolderGit2,
    matchPrefix: "/repositories",
  },
  {
    label: "Connectors",
    href: "/connectors",
    icon: GitBranch,
    matchPrefix: "/connectors",
  },
  {
    label: "Settings",
    href: "/settings",
    icon: Settings,
    matchPrefix: "/settings",
  },
];

const STORAGE_KEY = "icon-rail-expanded";

export function IconRail() {
  const pathname = usePathname();
  const [expanded, setExpanded] = React.useState(false);

  // Restore persisted state after mount to avoid SSR mismatch
  React.useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "true") setExpanded(true);
    } catch {
      // localStorage unavailable
    }
  }, []);

  function toggle() {
    setExpanded((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
      } catch {
        // ignore
      }
      return next;
    });
  }

  function isActive(item: NavItem): boolean {
    if (item.matchPrefix === "/__exact__") {
      return pathname === "/";
    }
    return pathname.startsWith(item.matchPrefix);
  }

  return (
    <TooltipProvider delayDuration={0}>
      <nav
        className={cn(
          "flex h-full shrink-0 flex-col border-r bg-sidebar py-2 transition-[width] duration-200",
          expanded ? "w-44" : "w-12",
        )}
        aria-label="Global navigation"
      >
        {/* Nav items */}
        <div className="flex flex-1 flex-col gap-1 px-1.5">
          {topItems.map((item) => {
            const active = isActive(item);
            const linkEl = (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2.5 rounded-md transition-colors",
                  expanded ? "px-2.5 py-1.5" : "size-9 justify-center",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                )}
                aria-label={item.label}
              >
                <item.icon className="size-4 shrink-0" />
                {expanded && (
                  <span className="truncate text-sm font-medium">{item.label}</span>
                )}
              </Link>
            );

            if (expanded) return linkEl;

            return (
              <Tooltip key={item.href}>
                <TooltipTrigger asChild>{linkEl}</TooltipTrigger>
                <TooltipContent side="right" sideOffset={8}>
                  {item.label}
                </TooltipContent>
              </Tooltip>
            );
          })}
        </div>

        {/* Expand / collapse toggle */}
        <div className="px-1.5 pb-1">
          <button
            onClick={toggle}
            className={cn(
              "flex items-center gap-2.5 rounded-md text-sidebar-foreground/50 transition-colors hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
              expanded ? "w-full px-2.5 py-1.5" : "size-9 justify-center",
            )}
            aria-label={expanded ? "Collapse navigation" : "Expand navigation"}
          >
            {expanded ? (
              <>
                <ChevronLeft className="size-4 shrink-0" />
                <span className="truncate text-sm">Collapse</span>
              </>
            ) : (
              <ChevronRight className="size-4" />
            )}
          </button>
        </div>
      </nav>
    </TooltipProvider>
  );
}
