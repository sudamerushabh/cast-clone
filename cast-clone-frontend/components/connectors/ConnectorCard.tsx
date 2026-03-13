"use client";

import * as React from "react";
import { GitBranch, Github, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ConnectorResponse } from "@/lib/types";

interface ConnectorCardProps {
  connector: ConnectorResponse;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
}

const providerLabels: Record<string, string> = {
  github: "GitHub",
  gitlab: "GitLab",
  gitea: "Gitea",
  bitbucket: "Bitbucket",
};

const statusColors: Record<string, string> = {
  connected: "bg-green-500/10 text-green-700 dark:text-green-400",
  expired: "bg-yellow-500/10 text-yellow-700 dark:text-yellow-400",
  revoked: "bg-red-500/10 text-red-700 dark:text-red-400",
  error: "bg-red-500/10 text-red-700 dark:text-red-400",
};

export function ConnectorCard({ connector, onDelete, onTest }: ConnectorCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base font-medium">{connector.name}</CardTitle>
        <Badge variant="outline" className={statusColors[connector.status] ?? ""}>
          {connector.status}
        </Badge>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-2 text-sm text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <GitBranch className="size-3.5" />
            <span>{providerLabels[connector.provider] ?? connector.provider}</span>
          </div>
          {connector.remote_username && (
            <div className="flex items-center gap-1.5">
              <Github className="size-3.5" />
              <span>{connector.remote_username}</span>
            </div>
          )}
          <div className="truncate text-xs">{connector.base_url}</div>
        </div>
        <div className="mt-3 flex gap-2">
          <Button variant="outline" size="sm" onClick={() => onTest(connector.id)}>
            Test
          </Button>
          <Button variant="ghost" size="sm" className="text-destructive" onClick={() => onDelete(connector.id)}>
            <Trash2 className="mr-1 size-3.5" />
            Delete
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
