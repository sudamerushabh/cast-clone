"use client";

import type { ActivityLogEntry } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

const ACTION_LABELS: Record<string, string> = {
  "user.login": "Signed in",
  "user.created": "User created",
  "project.created": "Project created",
  "project.deleted": "Project deleted",
  "analysis.started": "Analysis started",
  "analysis.completed": "Analysis completed",
  "analysis.failed": "Analysis failed",
  "annotation.created": "Annotation added",
  "annotation.deleted": "Annotation removed",
  "view.saved": "View saved",
  "view.deleted": "View deleted",
  "tag.added": "Tag added",
  "tag.removed": "Tag removed",
};

interface ActivityFeedProps {
  entries: ActivityLogEntry[];
  loading: boolean;
}

export function ActivityFeed({ entries, loading }: ActivityFeedProps) {
  if (loading) {
    return (
      <div className="text-center text-sm text-muted-foreground py-8">
        Loading activity...
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="text-center text-sm text-muted-foreground py-8">
        No activity recorded yet
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {entries.map((entry) => (
        <div
          key={entry.id}
          className="flex items-start gap-3 rounded-md border px-4 py-3"
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">
                {entry.user?.username ?? "System"}
              </span>
              <Badge variant="outline" className="text-xs">
                {ACTION_LABELS[entry.action] ?? entry.action}
              </Badge>
            </div>
            {entry.resource_type && (
              <p className="text-xs text-muted-foreground mt-0.5">
                {entry.resource_type}
                {entry.resource_id ? `: ${entry.resource_id.slice(0, 8)}...` : ""}
              </p>
            )}
          </div>
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            {new Date(entry.created_at).toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}
