"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  BookmarkPlus,
  FolderOpen,
  GitGraph,
  LayoutDashboard,
  MessageSquare,
  Route,
  Search,
  Settings,
  Zap,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface ProjectContextNavProps {
  repoId: string;
  branch: string;
}

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
}

export function ProjectContextNav({
  repoId,
  branch,
}: ProjectContextNavProps) {
  const pathname = usePathname();
  const basePath = `/repositories/${repoId}/${branch}`;

  const navItems: NavItem[] = [
    { label: "Overview", href: basePath, icon: LayoutDashboard },
    { label: "Architecture", href: `/repositories/${repoId}/graph/${branch}`, icon: GitGraph },
    {
      label: "Dependencies",
      href: `/repositories/${repoId}/dependencies/${branch}`,
      icon: FolderOpen,
    },
    { label: "Transactions", href: `/repositories/${repoId}/transactions/${branch}`, icon: Route },
    { label: "Search", href: `/repositories/${repoId}/search/${branch}`, icon: Search },
    { label: "Impact", href: `/repositories/${repoId}/impact/${branch}`, icon: Zap },
    { label: "Saved Views", href: `/repositories/${repoId}/views/${branch}`, icon: BookmarkPlus },
    {
      label: "AI Assistant",
      href: `/repositories/${repoId}/chat/${branch}`,
      icon: MessageSquare,
    },
    {
      label: "Project Settings",
      href: `/repositories/${repoId}/settings/${branch}`,
      icon: Settings,
    },
  ];

  return (
    <ScrollArea className="h-full">
      <div className="flex flex-col gap-1 p-2">
        {/* Back to repository */}
        <Link
          href={`/repositories/${repoId}`}
          className="mb-2 flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
        >
          <ArrowLeft className="size-3.5" />
          <span>Back to repository</span>
        </Link>

        {/* Branch label */}
        <div className="mb-1 px-2 text-xs font-medium text-sidebar-foreground/50">
          {decodeURIComponent(branch)}
        </div>

        {navItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== basePath && pathname.startsWith(item.href));

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
