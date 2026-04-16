"use client";

import * as React from "react";
import { ExternalLink, Loader2, MoreVertical, Trash2, Unplug, Zap } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardAction } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ProviderLogo, providerMeta } from "@/components/connectors/ProviderLogo";
import type { ConnectorResponse } from "@/lib/types";

interface ConnectorCardProps {
  connector: ConnectorResponse;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
}

const statusConfig: Record<
  string,
  { label: string; color: string; dot: string }
> = {
  connected: {
    label: "Connected",
    color: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
    dot: "bg-emerald-500",
  },
  expired: {
    label: "Expired",
    color: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
    dot: "bg-amber-500",
  },
  revoked: {
    label: "Revoked",
    color: "bg-red-500/10 text-red-700 dark:text-red-400",
    dot: "bg-red-500",
  },
  error: {
    label: "Error",
    color: "bg-red-500/10 text-red-700 dark:text-red-400",
    dot: "bg-red-500",
  },
};

export function ConnectorCard({
  connector,
  onDelete,
  onTest,
}: ConnectorCardProps) {
  const [testing, setTesting] = React.useState(false);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const meta = providerMeta[connector.provider];
  const status = statusConfig[connector.status] ?? statusConfig.error;

  async function handleTest() {
    setTesting(true);
    try {
      await onTest(connector.id);
    } finally {
      setTesting(false);
    }
  }

  return (
    <Card className="transition-shadow hover:shadow-md">
      <CardHeader>
        <div className="flex items-center gap-2.5">
          <div
            className="flex size-9 shrink-0 items-center justify-center rounded-md"
            style={{ backgroundColor: `${meta.color}10` }}
          >
            <ProviderLogo provider={connector.provider} size={20} className="dark:invert-0" style={{ filter: "none" }} />
          </div>
          <div className="min-w-0 flex-1">
            <CardTitle className="truncate">{connector.name}</CardTitle>
            <div className="text-[11px] text-muted-foreground">
              {meta.label}
            </div>
          </div>
        </div>
        <CardAction>
          <Badge
            variant="outline"
            className={`gap-1.5 ${status.color}`}
          >
            <span
              className={`inline-block size-1.5 rounded-full ${status.dot}`}
            />
            {status.label}
          </Badge>
        </CardAction>
      </CardHeader>

      <CardContent>
        <div className="space-y-2">
          {/* Details */}
          <div className="flex flex-col gap-1 text-xs text-muted-foreground">
            {connector.remote_username && (
              <div className="flex items-center gap-1.5">
                <span className="text-foreground/70">@{connector.remote_username}</span>
              </div>
            )}
            <div className="flex items-center gap-1.5 truncate">
              <ExternalLink className="size-3 shrink-0" />
              <span className="truncate">{connector.base_url}</span>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1.5 pt-1">
            <Button
              variant="outline"
              size="sm"
              onClick={handleTest}
              disabled={testing}
            >
              {testing ? (
                <Loader2 className="mr-1 size-3 animate-spin" />
              ) : (
                <Zap className="mr-1 size-3" />
              )}
              {testing ? "Testing..." : "Test"}
            </Button>

            {confirmDelete ? (
              <div className="flex items-center gap-1">
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => onDelete(connector.id)}
                >
                  Confirm
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmDelete(false)}
                >
                  No
                </Button>
              </div>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground hover:text-destructive"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="mr-1 size-3" />
                Delete
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
