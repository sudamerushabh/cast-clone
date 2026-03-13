"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Download, FileSpreadsheet, FileJson, FileText } from "lucide-react";
import { downloadExport } from "@/lib/api";

interface ExportMenuProps {
  projectId: string;
  /** FQN of selected node for impact export, if any */
  selectedNodeFqn?: string;
}

export function ExportMenu({ projectId, selectedNodeFqn }: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  return (
    <div className="relative" ref={menuRef}>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(!open)}
        title="Export data"
        className="gap-1"
      >
        <Download className="h-4 w-4" />
        <span className="hidden sm:inline text-xs">Export</span>
      </Button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-52 rounded-md border bg-popover p-1 shadow-md">
          <button
            className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent"
            onClick={() => {
              downloadExport(projectId, "nodes.csv");
              setOpen(false);
            }}
          >
            <FileSpreadsheet className="h-4 w-4" />
            Nodes (CSV)
          </button>
          <button
            className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent"
            onClick={() => {
              downloadExport(projectId, "edges.csv");
              setOpen(false);
            }}
          >
            <FileSpreadsheet className="h-4 w-4" />
            Edges (CSV)
          </button>
          <button
            className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent"
            onClick={() => {
              downloadExport(projectId, "graph.json");
              setOpen(false);
            }}
          >
            <FileJson className="h-4 w-4" />
            Graph (JSON)
          </button>
          {selectedNodeFqn && (
            <>
              <div className="h-px bg-border my-1" />
              <button
                className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent"
                onClick={() => {
                  downloadExport(projectId, "impact.csv", {
                    node: selectedNodeFqn,
                  });
                  setOpen(false);
                }}
              >
                <FileText className="h-4 w-4" />
                Impact Analysis (CSV)
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
