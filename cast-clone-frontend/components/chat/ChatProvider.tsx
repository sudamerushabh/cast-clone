// components/chat/ChatProvider.tsx
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useChat } from "@/hooks/useChat";
import { usePageContext } from "@/hooks/usePageContext";
import type { ChatMessage, PageContext } from "@/lib/chat-types";

const STORAGE_KEY_CONTEXT_AWARE = "codelens-chat-context-aware";

interface ChatContextValue {
  // State
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
  isOpen: boolean;
  includePageContext: boolean;
  pageContext: PageContext;

  // Actions
  sendMessage: (message: string) => Promise<void>;
  clearMessages: () => void;
  stopStreaming: () => void;
  toggleOpen: () => void;
  setOpen: (open: boolean) => void;
  setIncludePageContext: (include: boolean) => void;

  // Graph state setters (called by graph components)
  setSelectedNodeFqn: (fqn: string | null) => void;
  setViewInfo: (view: string | null, level: string | null) => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

interface ChatProviderProps {
  children: ReactNode;
  projectId: string;
  projectName?: string;
}

export function ChatProvider({
  children,
  projectId,
}: ChatProviderProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [includePageContext, setIncludePageContextState] = useState(true);
  const [selectedNodeFqn, setSelectedNodeFqn] = useState<string | null>(null);
  const [view, setView] = useState<string | null>(null);
  const [level, setLevel] = useState<string | null>(null);

  const chat = useChat();
  const pageContext = usePageContext({
    selectedNodeFqn,
    view,
    level,
  });

  // Restore context-aware toggle from localStorage
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY_CONTEXT_AWARE);
    if (stored !== null) {
      // Use setTimeout(0) to avoid "setState in effect" lint warning
      const value = stored === "true";
      setTimeout(() => setIncludePageContextState(value), 0);
    }
  }, []);

  const setIncludePageContext = useCallback((include: boolean) => {
    setIncludePageContextState(include);
    localStorage.setItem(STORAGE_KEY_CONTEXT_AWARE, String(include));
  }, []);

  const setViewInfo = useCallback(
    (v: string | null, l: string | null) => {
      setView(v);
      setLevel(l);
    },
    [],
  );

  const sendMessage = useCallback(
    async (message: string) => {
      await chat.sendMessage(
        projectId,
        message,
        includePageContext ? pageContext : null,
        includePageContext,
      );
    },
    [chat, projectId, pageContext, includePageContext],
  );

  const toggleOpen = useCallback(() => {
    setIsOpen((prev) => !prev);
  }, []);

  const value = useMemo(
    (): ChatContextValue => ({
      messages: chat.messages,
      isStreaming: chat.isStreaming,
      error: chat.error,
      isOpen,
      includePageContext,
      pageContext,
      sendMessage,
      clearMessages: chat.clearMessages,
      stopStreaming: chat.stopStreaming,
      toggleOpen,
      setOpen: setIsOpen,
      setIncludePageContext,
      setSelectedNodeFqn,
      setViewInfo,
    }),
    [
      chat.messages,
      chat.isStreaming,
      chat.error,
      chat.clearMessages,
      chat.stopStreaming,
      isOpen,
      includePageContext,
      pageContext,
      sendMessage,
      toggleOpen,
      setIncludePageContext,
      setViewInfo,
    ],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChatContext(): ChatContextValue {
  const ctx = useContext(ChatContext);
  if (!ctx) {
    throw new Error("useChatContext must be used within a ChatProvider");
  }
  return ctx;
}
