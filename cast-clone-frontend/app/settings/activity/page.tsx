"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { getActivityFeed } from "@/lib/api";
import type { ActivityLogEntry } from "@/lib/types";
import { ActivityFeed } from "@/components/activity/ActivityFeed";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

export default function ActivityPage() {
  const { user } = useAuth();
  const [entries, setEntries] = useState<ActivityLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const loadActivity = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getActivityFeed({ limit: 100 });
      setEntries(data);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadActivity();
  }, [loadActivity]);

  if (!user || user.role !== "admin") {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Admin access required
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Activity Log</h1>
          <p className="text-sm text-muted-foreground">
            Recent actions across the platform
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={loadActivity}
          className="gap-1.5"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
      </div>

      <ActivityFeed entries={entries} loading={loading} />
    </div>
  );
}
