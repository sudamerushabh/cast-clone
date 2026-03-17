// components/chat/ChatDrawer.tsx
"use client";

import { useCallback, useEffect, useRef } from "react";
import { MessageCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useChatContext } from "./ChatProvider";
import { ChatHeader } from "./ChatHeader";
import { ChatMessageComponent } from "./ChatMessage";
import { ChatInput } from "./ChatInput";
import { PageContextChip } from "./PageContextChip";
import { cn } from "@/lib/utils";

interface ChatDrawerProps {
  projectName?: string;
  onNavigateToNode?: (fqn: string) => void;
}

/** Width/height classes per drawer size — use max-h to respect viewport */
const SIZE_CLASSES = {
  normal: "w-[380px] max-h-[min(560px,calc(100vh-40px))]",
  wide: "w-[680px] max-h-[min(700px,calc(100vh-40px))]",
} as const;

export function ChatDrawer({ projectName, onNavigateToNode }: ChatDrawerProps) {
  const {
    messages,
    isStreaming,
    error,
    isOpen,
    includePageContext,
    pageContext,
    tone,
    drawerSize,
    sendMessage,
    clearMessages,
    stopStreaming,
    toggleOpen,
    setOpen,
    setIncludePageContext,
    setTone,
    setDrawerSize,
  } = useChatContext();

  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (scrollRef.current) {
      const el = scrollRef.current;
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
    }
  }, [messages]);

  // Keyboard shortcut: Ctrl/Cmd + Shift + L to toggle chat
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "l") {
        e.preventDefault();
        toggleOpen();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleOpen]);

  const handleSend = useCallback(
    (message: string) => {
      sendMessage(message);
    },
    [sendMessage],
  );

  return (
    <>
      {/* Floating trigger button — bottom-right corner */}
      {!isOpen && (
        <Button
          onClick={toggleOpen}
          size="icon-lg"
          className="fixed bottom-5 right-5 z-50 size-11 rounded-full bg-violet-600 shadow-lg shadow-violet-600/25 transition-transform hover:scale-105 hover:bg-violet-700 dark:bg-violet-600 dark:hover:bg-violet-500"
          aria-label="Open AI chat"
        >
          <MessageCircle className="size-5 text-white" />
          {isStreaming && (
            <span className="absolute -right-0.5 -top-0.5 size-3 rounded-full border-2 border-background bg-emerald-500" />
          )}
        </Button>
      )}

      {/* Chat popup — anchored to bottom-right like a website chat widget */}
      {isOpen && (
        <div
          className={cn(
            "fixed bottom-5 right-5 z-50 flex h-[min(560px,calc(100vh-40px))] flex-col rounded-xl border border-border/60 bg-background shadow-2xl transition-all duration-200 ease-out",
            drawerSize === "wide" ? "w-[680px] h-[min(700px,calc(100vh-40px))]" : "w-[380px]",
            // On mobile, take full screen
            "max-md:inset-2 max-md:h-auto max-md:w-auto",
          )}
          onWheel={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <ChatHeader
            projectName={projectName}
            includePageContext={includePageContext}
            onToggleContext={setIncludePageContext}
            messageCount={messages.length}
            onClear={clearMessages}
            onClose={() => setOpen(false)}
            tone={tone}
            onToneChange={setTone}
            drawerSize={drawerSize}
            onSizeChange={setDrawerSize}
          />

          {/* Messages area */}
          <div className="relative flex-1 overflow-hidden">
            <div ref={scrollRef} className="h-full overflow-y-auto">
              {messages.length === 0 ? (
                <EmptyState />
              ) : (
                <div className="pb-4 pt-2">
                  {messages.map((msg) => (
                    <ChatMessageComponent
                      key={msg.id}
                      message={msg}
                      onNavigateToNode={onNavigateToNode}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Error display */}
          {error && (
            <div className="mx-3 mb-1 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs text-destructive">
              {error}
            </div>
          )}

          {/* Context chip — above input */}
          {includePageContext && (
            <div className="px-3 pb-1">
              <PageContextChip context={pageContext} isActive={includePageContext} />
            </div>
          )}

          {/* Input */}
          <ChatInput
            onSend={handleSend}
            onStop={stopStreaming}
            isStreaming={isStreaming}
          />
        </div>
      )}
    </>
  );
}

// ─── Empty State ───────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center">
      <div className="flex size-10 items-center justify-center rounded-full bg-violet-100 dark:bg-violet-900/20">
        <MessageCircle className="size-5 text-violet-500" />
      </div>
      <div>
        <h3 className="text-sm font-semibold">Ask about your architecture</h3>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Analyze code structure, find impact paths, explain components, and understand dependencies.
        </p>
      </div>
      <div className="w-full space-y-1.5">
        <SuggestionChip text="What are the main modules?" />
        <SuggestionChip text="What would break if I changed OrderService?" />
        <SuggestionChip text="Show me the most complex classes" />
        <SuggestionChip text="Find the path between API and database layers" />
      </div>
      <p className="text-[9px] text-muted-foreground/40">
        Ctrl+Shift+L to toggle
      </p>
    </div>
  );
}

function SuggestionChip({ text }: { text: string }) {
  const { sendMessage } = useChatContext();
  return (
    <button
      type="button"
      onClick={() => sendMessage(text)}
      className="w-full rounded-lg border border-border/50 bg-muted/30 px-2.5 py-1.5 text-left text-[11px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
    >
      {text}
    </button>
  );
}
