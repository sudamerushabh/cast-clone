// components/chat/ChatHeader.tsx
"use client";

import { Bot, X, Trash2, Eye, EyeOff, Minimize2, Maximize2, ChevronsRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ChatDrawerSize, ChatTone } from "@/lib/chat-types";
import { CHAT_TONE_LABELS } from "@/lib/chat-types";

interface ChatHeaderProps {
  projectName?: string;
  includePageContext: boolean;
  onToggleContext: (include: boolean) => void;
  messageCount: number;
  onClear: () => void;
  onClose: () => void;
  tone: ChatTone;
  onToneChange: (tone: ChatTone) => void;
  drawerSize: ChatDrawerSize;
  onSizeChange: (size: ChatDrawerSize) => void;
}

const TONES: ChatTone[] = ["concise", "normal", "detailed_technical"];

export function ChatHeader({
  projectName,
  includePageContext,
  onToggleContext,
  messageCount,
  onClear,
  onClose,
  tone,
  onToneChange,
  drawerSize,
  onSizeChange,
}: ChatHeaderProps) {
  const nextSize = drawerSize === "normal" ? "wide" : "normal";

  return (
    <div className="flex flex-col gap-2 border-b border-border/60 bg-background px-3 py-2">
      {/* Top row: title + actions */}
      <div className="flex items-center gap-1.5">
        <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-violet-100 dark:bg-violet-900/30">
          <Bot className="size-3.5 text-violet-600 dark:text-violet-400" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold leading-tight">AI Assistant</h2>
          {projectName && (
            <p className="truncate text-[10px] text-muted-foreground leading-tight">
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
                aria-label={includePageContext ? "Disable context awareness" : "Enable context awareness"}
              >
                {includePageContext ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-52 text-xs">
              {includePageContext
                ? "Context-aware on. Click to disable."
                : "Context-aware off. Click to enable."}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        {/* Clear */}
        {messageCount > 0 && (
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-xs" onClick={onClear} className="text-muted-foreground hover:text-destructive" aria-label="Clear conversation">
                  <Trash2 className="size-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">Clear conversation</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}

        {/* Expand / Shrink toggle */}
        <TooltipProvider delayDuration={300}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-xs"
                onClick={() => onSizeChange(nextSize)}
                className="text-muted-foreground"
                aria-label={nextSize === "wide" ? "Expand chat" : "Shrink chat"}
              >
                {drawerSize === "wide" ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              {drawerSize === "wide" ? "Normal size" : "Wide mode"}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        {/* Minimize (close to FAB) */}
        <TooltipProvider delayDuration={300}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-xs"
                onClick={onClose}
                className="text-muted-foreground"
                aria-label="Minimize chat"
              >
                <ChevronsRight className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">Minimize</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      {/* Tone selector row */}
      <div className="flex items-center gap-1">
        {TONES.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => onToneChange(t)}
            className={`rounded-full px-2.5 py-0.5 text-[10px] font-medium transition-colors ${
              tone === t
                ? "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300"
                : "text-muted-foreground hover:bg-muted"
            }`}
          >
            {CHAT_TONE_LABELS[t]}
          </button>
        ))}
      </div>
    </div>
  );
}
