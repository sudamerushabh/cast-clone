"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  BookmarkPlus,
  ChevronDown,
  ChevronRight,
  FolderOpen,
  GitGraph,
  Layers,
  LayoutDashboard,
  MessageSquare,
  Network,
  Search,
  Settings,
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
  children?: NavItem[];
}

export function ProjectContextNav({
  repoId,
  branch,
}: ProjectContextNavProps) {
  const pathname = usePathname();
  const basePath = `/repositories/${repoId}/${branch}`;

  const graphBasePath = `/repositories/${repoId}/graph/${branch}`;
  const isGraphSection =
    pathname.startsWith(`/repositories/${repoId}/graph/`) ||
    pathname.startsWith(`/repositories/${repoId}/dependencies/`) ||
    pathname.startsWith(`/repositories/${repoId}/transactions/`);

  const [graphOpen, setGraphOpen] = React.useState(isGraphSection);

  // Keep submenu open when navigating into graph section
  React.useEffect(() => {
    if (isGraphSection) setGraphOpen(true);
  }, [isGraphSection]);

  const navItems: NavItem[] = [
    { label: "Overview", href: basePath, icon: LayoutDashboard },
    {
      label: "Graph",
      href: graphBasePath,
      icon: GitGraph,
      children: [
        { label: "Architecture", href: `/repositories/${repoId}/graph/${branch}`, icon: Layers },
        { label: "Dependencies", href: `/repositories/${repoId}/dependencies/${branch}`, icon: Network },
        { label: "Transactions", href: `/repositories/${repoId}/transactions/${branch}`, icon: ArrowRight },
      ],
    },
    { label: "Search", href: `/repositories/${repoId}/search/${branch}`, icon: Search },
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

  function isActive(href: string) {
    return (
      pathname === href ||
      (href !== basePath && pathname.startsWith(href))
    );
  }

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
          if (item.children) {
            const Chevron = graphOpen ? ChevronDown : ChevronRight;
            return (
              <div key={item.label}>
                <button
                  onClick={() => setGraphOpen((v) => !v)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                    isGraphSection
                      ? "font-medium text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                  )}
                >
                  <item.icon className="size-4 shrink-0" />
                  <span className="flex-1 truncate text-left">{item.label}</span>
                  <Chevron className="size-3.5 shrink-0 text-sidebar-foreground/40" />
                </button>
                {graphOpen && (
                  <div className="ml-3 flex flex-col gap-0.5 border-l border-sidebar-border pl-2 pt-0.5">
                    {item.children.map((child) => (
                      <Link
                        key={child.href}
                        href={child.href}
                        className={cn(
                          "flex items-center gap-2 rounded-md px-2 py-1 text-sm transition-colors",
                          isActive(child.href)
                            ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                            : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                        )}
                      >
                        <child.icon className="size-3.5 shrink-0" />
                        <span className="truncate">{child.label}</span>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            );
          }

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                isActive(item.href)
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
