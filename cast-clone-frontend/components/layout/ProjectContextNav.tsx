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
  const basePath = `/repositories/${repoId}/${encodeURIComponent(branch)}`;

  const navItems: NavItem[] = [
    { label: "Overview", href: basePath, icon: LayoutDashboard },
    { label: "Architecture", href: `${basePath}/graph`, icon: GitGraph },
    {
      label: "Dependencies",
      href: `${basePath}/dependencies`,
      icon: FolderOpen,
    },
    { label: "Transactions", href: `${basePath}/transactions`, icon: Route },
    { label: "Search", href: `${basePath}/search`, icon: Search },
    { label: "Impact", href: `${basePath}/impact`, icon: Zap },
    { label: "Saved Views", href: `${basePath}/views`, icon: BookmarkPlus },
    {
      label: "AI Assistant",
      href: `${basePath}/chat`,
      icon: MessageSquare,
    },
    {
      label: "Project Settings",
      href: `${basePath}/settings`,
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
