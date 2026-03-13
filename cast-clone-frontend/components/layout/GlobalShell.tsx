"use client";

import * as React from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { IconRail } from "./IconRail";
import { ContextPanel } from "./ContextPanel";
import { TopBar } from "./TopBar";
import { cn } from "@/lib/utils";

interface GlobalShellProps {
  children: React.ReactNode;
}

export function GlobalShell({ children }: GlobalShellProps) {
  const [panelOpen, setPanelOpen] = React.useState(true);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Top bar */}
      <TopBar />

      {/* Body: IconRail + ContextPanel + Main */}
      <div className="flex flex-1 overflow-hidden">
        {/* Icon rail — always visible */}
        <IconRail />

        {/* Context panel — collapsible */}
        <aside
          className={cn(
            "relative shrink-0 border-r bg-sidebar transition-[width] duration-200",
            panelOpen ? "w-60" : "w-0 overflow-hidden border-r-0",
          )}
        >
          {/* Collapse/expand toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-1 top-1 z-10 size-6"
            onClick={() => setPanelOpen((prev) => !prev)}
            aria-label={panelOpen ? "Collapse panel" : "Expand panel"}
          >
            {panelOpen ? (
              <PanelLeftClose className="size-3.5" />
            ) : (
              <PanelLeftOpen className="size-3.5" />
            )}
          </Button>

          <ContextPanel />
        </aside>

        {/* Show expand button when panel is collapsed */}
        {!panelOpen && (
          <Button
            variant="ghost"
            size="icon"
            className="my-1 size-6 shrink-0"
            onClick={() => setPanelOpen(true)}
            aria-label="Expand panel"
          >
            <PanelLeftOpen className="size-3.5" />
          </Button>
        )}

        {/* Main content */}
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
