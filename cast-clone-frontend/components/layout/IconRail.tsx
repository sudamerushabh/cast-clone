"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
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

export function IconRail() {
  const pathname = usePathname();

  function isActive(item: NavItem): boolean {
    if (item.matchPrefix === "/__exact__") {
      return pathname === "/";
    }
    return pathname.startsWith(item.matchPrefix);
  }

  return (
    <TooltipProvider delayDuration={0}>
      <nav
        className="flex h-full w-12 shrink-0 flex-col items-center gap-1 border-r bg-sidebar py-2"
        aria-label="Global navigation"
      >
        {topItems.map((item) => (
          <Tooltip key={item.href}>
            <TooltipTrigger asChild>
              <Link
                href={item.href}
                className={cn(
                  "flex size-9 items-center justify-center rounded-md transition-colors",
                  isActive(item)
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                )}
                aria-label={item.label}
              >
                <item.icon className="size-5" />
              </Link>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={8}>
              {item.label}
            </TooltipContent>
          </Tooltip>
        ))}
      </nav>
    </TooltipProvider>
  );
}
