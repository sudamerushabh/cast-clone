"use client";

import type { SavedViewListItem } from "@/lib/types";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Trash2, Link2 } from "lucide-react";

interface ViewsListProps {
  views: SavedViewListItem[];
  loading: boolean;
  onLoad: (viewId: string) => void;
  onDelete: (viewId: string) => void;
}

export function ViewsList({
  views,
  loading,
  onLoad,
  onDelete,
}: ViewsListProps) {
  const { user } = useAuth();

  if (loading) {
    return (
      <div className="text-center text-sm text-muted-foreground py-4">
        Loading views...
      </div>
    );
  }

  if (views.length === 0) {
    return (
      <div className="text-center text-sm text-muted-foreground py-4">
        No saved views yet. Save the current graph state to share with your
        team.
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {views.map((view) => (
        <div
          key={view.id}
          className="group flex items-center justify-between rounded-md border px-3 py-2 hover:bg-accent cursor-pointer"
          onClick={() => onLoad(view.id)}
        >
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium truncate">{view.name}</p>
            {view.description && (
              <p className="text-xs text-muted-foreground truncate">
                {view.description}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              {view.author.username} &middot;{" "}
              {new Date(view.updated_at).toLocaleDateString()}
            </p>
          </div>
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              onClick={(e) => {
                e.stopPropagation();
                const url = `${window.location.origin}/projects/${view.project_id}/views/${view.id}`;
                navigator.clipboard.writeText(url);
              }}
              title="Copy shareable link"
            >
              <Link2 className="h-3.5 w-3.5" />
            </Button>
            {(user?.id === view.author.id || user?.role === "admin") && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0 text-destructive"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(view.id);
                }}
                title="Delete view"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
