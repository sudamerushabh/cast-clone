// components/chat/ToolCallCard.tsx
"use client";

import { useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  AlertCircle,
  Wrench,
} from "lucide-react";
import type { ToolCallDisplay } from "@/lib/chat-types";
import { describeToolCall } from "@/lib/chat-types";

interface ToolCallCardProps {
  toolCall: ToolCallDisplay;
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const description = describeToolCall(toolCall.name, toolCall.input);

  return (
    <div className="my-1.5">
      <button
        type="button"
        onClick={() => {
          if (toolCall.status !== "running") {
            setIsExpanded((prev) => !prev);
          }
        }}
        className="group flex w-full items-center gap-2 rounded-md border border-border/40 bg-background px-3 py-1.5 text-left transition-colors hover:bg-muted/30"
        disabled={toolCall.status === "running"}
      >
        {/* Status icon */}
        {toolCall.status === "running" && (
          <Loader2 className="size-3.5 shrink-0 animate-spin text-blue-500" />
        )}
        {toolCall.status === "complete" && (
          <Check className="size-3.5 shrink-0 text-emerald-500" />
        )}
        {toolCall.status === "error" && (
          <AlertCircle className="size-3.5 shrink-0 text-red-500" />
        )}

        {/* Tool icon */}
        <Wrench className="size-3 shrink-0 text-muted-foreground/60" />

        {/* Description */}
        <span className="flex-1 truncate text-xs text-muted-foreground">
          {description}
          {toolCall.status === "running" && "..."}
        </span>

        {/* Expand chevron (only when complete) */}
        {toolCall.status !== "running" && toolCall.resultSummary && (
          <span className="text-muted-foreground/50">
            {isExpanded ? (
              <ChevronDown className="size-3" />
            ) : (
              <ChevronRight className="size-3" />
            )}
          </span>
        )}
      </button>

      {/* Expanded result */}
      {isExpanded && toolCall.resultSummary && (
        <div className="mt-0.5 rounded-b-md border border-t-0 border-border/40 bg-muted/20 px-3 py-2">
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground/80">
            {toolCall.resultSummary}
          </p>
        </div>
      )}
    </div>
  );
}
