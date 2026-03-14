// components/chat/ChatHeader.tsx
"use client";

import { Bot, X, Trash2, Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { PageContextChip } from "./PageContextChip";
import type { PageContext } from "@/lib/chat-types";

interface ChatHeaderProps {
  projectName?: string;
  includePageContext: boolean;
  onToggleContext: (include: boolean) => void;
  pageContext: PageContext;
  messageCount: number;
  onClear: () => void;
  onClose: () => void;
}

export function ChatHeader({
  projectName,
  includePageContext,
  onToggleContext,
  pageContext,
  messageCount,
  onClear,
  onClose,
}: ChatHeaderProps) {
  return (
    <div className="flex flex-col gap-2 border-b border-border/60 bg-background px-4 py-3">
      {/* Top row: title + actions */}
      <div className="flex items-center gap-2">
        <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-violet-100 dark:bg-violet-900/30">
          <Bot className="size-3.5 text-violet-600 dark:text-violet-400" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold">AI Assistant</h2>
          {projectName && (
            <p className="truncate text-xs text-muted-foreground">
              {projectName}
            </p>
          )}
        </div>

        {/* Context-aware toggle */}
        <TooltipProvider delayDuration={300}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-xs"
                onClick={() => onToggleContext(!includePageContext)}
                className={
                  includePageContext
                    ? "text-violet-600 dark:text-violet-400"
                    : "text-muted-foreground"
                }
                aria-label={
                  includePageContext
                    ? "Disable context awareness"
                    : "Enable context awareness"
                }
              >
                {includePageContext ? (
                  <Eye className="size-3.5" />
                ) : (
                  <EyeOff className="size-3.5" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-52 text-xs">
              {includePageContext
                ? "Context-aware: The assistant knows what page and node you're viewing. Click to disable."
                : "Context-aware is off. The assistant won't see your current page. Click to enable."}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        {/* Clear button */}
        {messageCount > 0 && (
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={onClear}
                  className="text-muted-foreground hover:text-destructive"
                  aria-label="Clear conversation"
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">
                Clear conversation
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}

        {/* Close button */}
        <Button
          variant="ghost"
          size="icon-xs"
          onClick={onClose}
          className="text-muted-foreground"
          aria-label="Close chat"
        >
          <X className="size-3.5" />
        </Button>
      </div>

      {/* Context chip row */}
      {includePageContext && (
        <PageContextChip context={pageContext} isActive={includePageContext} />
      )}
    </div>
  );
}
