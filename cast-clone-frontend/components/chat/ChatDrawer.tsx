// components/chat/ChatDrawer.tsx
"use client";

import { useCallback, useEffect, useRef } from "react";
import { MessageCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useChatContext } from "./ChatProvider";
import { ChatHeader } from "./ChatHeader";
import { ChatMessageComponent } from "./ChatMessage";
import { ChatInput } from "./ChatInput";
import { cn } from "@/lib/utils";

interface ChatDrawerProps {
  projectName?: string;
  onNavigateToNode?: (fqn: string) => void;
}

export function ChatDrawer({ projectName, onNavigateToNode }: ChatDrawerProps) {
  const {
    messages,
    isStreaming,
    error,
    isOpen,
    includePageContext,
    pageContext,
    sendMessage,
    clearMessages,
    stopStreaming,
    toggleOpen,
    setOpen,
    setIncludePageContext,
  } = useChatContext();

  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (scrollRef.current) {
      const el = scrollRef.current;
      // Use requestAnimationFrame to ensure DOM has updated
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
      {/* Floating trigger button */}
      {!isOpen && (
        <Button
          onClick={toggleOpen}
          size="icon-lg"
          className="fixed bottom-6 right-6 z-50 size-12 rounded-full bg-violet-600 shadow-lg shadow-violet-600/25 transition-transform hover:scale-105 hover:bg-violet-700 dark:bg-violet-600 dark:hover:bg-violet-500"
          aria-label="Open AI chat"
        >
          <MessageCircle className="size-5 text-white" />
          {/* Unread indicator when there's a streaming response */}
          {isStreaming && (
            <span className="absolute -right-0.5 -top-0.5 size-3 rounded-full border-2 border-background bg-emerald-500" />
          )}
        </Button>
      )}

      {/* Backdrop (mobile) */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/20 backdrop-blur-[1px] md:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Drawer */}
      <div
        className={cn(
          "fixed bottom-0 right-0 top-0 z-50 flex w-full flex-col border-l border-border/60 bg-background shadow-2xl transition-transform duration-300 ease-out md:w-[420px] lg:w-[460px]",
          isOpen ? "translate-x-0" : "translate-x-full",
        )}
      >
        {/* Header */}
        <ChatHeader
          projectName={projectName}
          includePageContext={includePageContext}
          onToggleContext={setIncludePageContext}
          pageContext={pageContext}
          messageCount={messages.length}
          onClear={clearMessages}
          onClose={() => setOpen(false)}
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
          <div className="mx-3 mb-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {/* Input */}
        <ChatInput
          onSend={handleSend}
          onStop={stopStreaming}
          isStreaming={isStreaming}
        />
      </div>
    </>
  );
}

// ─── Empty State ───────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-violet-100 dark:bg-violet-900/20">
        <MessageCircle className="size-6 text-violet-500" />
      </div>
      <div>
        <h3 className="text-sm font-semibold">Ask about your architecture</h3>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          I can analyze your code structure, find impact paths,
          explain components, and help you understand dependencies.
        </p>
      </div>
      <div className="w-full space-y-2">
        <SuggestionChip text="What are the main modules in this application?" />
        <SuggestionChip text="What would break if I changed OrderService?" />
        <SuggestionChip text="Show me the most complex classes" />
        <SuggestionChip text="Find the path between the API and database layers" />
      </div>
      <p className="text-[10px] text-muted-foreground/40">
        Ctrl+Shift+L to toggle chat
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
      className="w-full rounded-lg border border-border/50 bg-muted/30 px-3 py-2 text-left text-xs text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
    >
      {text}
    </button>
  );
}
