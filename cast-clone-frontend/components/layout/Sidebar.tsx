"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FolderOpen,
  GitGraph,
  GitPullRequest,
  LayoutDashboard,
  Route,
  Search,
  Settings,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface SidebarProps {
  projectId: string;
}

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
}

export function Sidebar({ projectId }: SidebarProps) {
  const pathname = usePathname();

  const navItems: NavItem[] = [
    {
      label: "Dashboard",
      href: `/projects/${projectId}`,
      icon: LayoutDashboard,
    },
    {
      label: "Architecture",
      href: `/projects/${projectId}/graph`,
      icon: GitGraph,
    },
    {
      label: "Dependencies",
      href: `/projects/${projectId}/dependencies`,
      icon: FolderOpen,
    },
    {
      label: "Transactions",
      href: `/projects/${projectId}/transactions`,
      icon: Route,
    },
    {
      label: "Search",
      href: `/projects/${projectId}/search`,
      icon: Search,
    },
    {
      label: "Pull Requests",
      href: `/projects/${projectId}/pull-requests`,
      icon: GitPullRequest,
    },
    {
      label: "Git Integration",
      href: `/projects/${projectId}/settings/git-integration`,
      icon: Settings,
    },
  ];

  return (
    <ScrollArea className="h-full">
      <nav className="flex flex-col gap-1 p-2">
        {navItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== `/projects/${projectId}` &&
              pathname.startsWith(item.href));

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
      </nav>
    </ScrollArea>
  );
}
