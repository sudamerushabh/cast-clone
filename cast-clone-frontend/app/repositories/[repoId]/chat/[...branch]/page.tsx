// app/repositories/[repoId]/chat/[...branch]/page.tsx
"use client";

import { useEffect } from "react";
import { Bot } from "lucide-react";
import { useChatContext } from "@/components/chat/ChatProvider";

export default function BranchChatPage() {
  const { setOpen } = useChatContext();

  // Auto-open the chat drawer when navigating to the chat page
  useEffect(() => {
    setOpen(true);
  }, [setOpen]);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
      <div className="flex size-16 items-center justify-center rounded-full bg-violet-100 dark:bg-violet-900/20">
        <Bot className="size-8 text-violet-500" />
      </div>
      <div className="max-w-md">
        <h1 className="text-xl font-bold">AI Assistant</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Ask natural language questions about your architecture. The assistant
          has access to your entire code graph and can run impact analysis,
          find paths, and explain components.
        </p>
        <p className="mt-4 text-xs text-muted-foreground/60">
          The chat drawer is open on the right. You can also access it from any
          page using the floating button or <kbd className="rounded border border-border px-1 py-0.5 text-[10px] font-mono">Ctrl+Shift+L</kbd>.
        </p>
      </div>
    </div>
  );
}
