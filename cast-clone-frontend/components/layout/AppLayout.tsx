"use client";

import * as React from "react";
import Link from "next/link";
import { Network, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

interface AppLayoutProps {
  children: React.ReactNode;
  sidebar?: React.ReactNode;
  rightPanel?: React.ReactNode;
  /** Current project name shown in the top nav breadcrumb */
  projectName?: string;
}

export function AppLayout({
  children,
  sidebar,
  rightPanel,
  projectName,
}: AppLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = React.useState(true);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* ── Top Navigation Bar ─────────────────────────────────────────── */}
      <header className="flex h-11 shrink-0 items-center gap-2 border-b bg-background px-3">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setSidebarOpen((prev) => !prev)}
          aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
        >
          {sidebarOpen ? (
            <PanelLeftClose className="size-4" />
          ) : (
            <PanelLeftOpen className="size-4" />
          )}
        </Button>

        <Separator orientation="vertical" className="h-5" />

        <Link
          href="/"
          className="flex items-center gap-1.5 text-sm font-semibold"
        >
          <Network className="size-4 text-primary" />
          <span>CAST Clone</span>
        </Link>

        {projectName && (
          <>
            <span className="text-muted-foreground">/</span>
            <span className="truncate text-sm text-muted-foreground">
              {projectName}
            </span>
          </>
        )}

        {/* Spacer pushes future controls (search, theme toggle) right */}
        <div className="flex-1" />
      </header>

      {/* ── Body: Sidebar + Main + Right Panel ─────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar */}
        {sidebar && (
          <aside
            className={cn(
              "shrink-0 border-r bg-sidebar transition-[width] duration-200",
              sidebarOpen ? "w-60" : "w-0 overflow-hidden border-r-0",
            )}
          >
            {sidebar}
          </aside>
        )}

        {/* Main content area */}
        <main className="flex-1 overflow-auto">{children}</main>

        {/* Right panel (node properties, code viewer, etc.) */}
        {rightPanel && (
          <aside className="w-80 shrink-0 overflow-auto border-l bg-background">
            {rightPanel}
          </aside>
        )}
      </div>
    </div>
  );
}
