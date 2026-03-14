// components/chat/ThinkingBlock.tsx
"use client";

import { useState } from "react";
import { Brain, ChevronDown, ChevronRight, Loader2 } from "lucide-react";

interface ThinkingBlockProps {
  content: string;
  isStreaming: boolean;
}

export function ThinkingBlock({ content, isStreaming }: ThinkingBlockProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!content && !isStreaming) return null;

  return (
    <div className="my-2">
      <button
        type="button"
        onClick={() => setIsExpanded((prev) => !prev)}
        className="group flex w-full items-center gap-2 rounded-lg border border-border/50 bg-muted/30 px-3 py-2 text-left transition-colors hover:bg-muted/50"
      >
        {isStreaming ? (
          <Loader2 className="size-3.5 shrink-0 animate-spin text-violet-500" />
        ) : (
          <Brain className="size-3.5 shrink-0 text-violet-500" />
        )}
        <span className="flex-1 text-xs font-medium text-muted-foreground">
          {isStreaming ? "Thinking..." : "Thought process"}
        </span>
        {!isStreaming && (
          <span className="text-muted-foreground/60">
            {isExpanded ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
          </span>
        )}
      </button>

      {(isExpanded || isStreaming) && content && (
        <div className="mt-1 rounded-b-lg border border-t-0 border-border/50 bg-muted/20 px-3 py-2">
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground/80">
            {content}
          </p>
        </div>
      )}
    </div>
  );
}
