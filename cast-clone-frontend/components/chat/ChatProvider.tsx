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
import type { ChatDrawerSize, ChatMessage, ChatTone, PageContext } from "@/lib/chat-types";

const STORAGE_KEY_CONTEXT_AWARE = "codelens-chat-context-aware";
const STORAGE_KEY_TONE = "codelens-chat-tone";

interface ChatContextValue {
  // State
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
  isOpen: boolean;
  includePageContext: boolean;
  pageContext: PageContext;
  tone: ChatTone;
  drawerSize: ChatDrawerSize;

  // Actions
  sendMessage: (message: string) => Promise<void>;
  clearMessages: () => void;
  stopStreaming: () => void;
  toggleOpen: () => void;
  setOpen: (open: boolean) => void;
  setIncludePageContext: (include: boolean) => void;
  setTone: (tone: ChatTone) => void;
  setDrawerSize: (size: ChatDrawerSize) => void;

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
  const [tone, setToneState] = useState<ChatTone>("normal");
  const [drawerSize, setDrawerSize] = useState<ChatDrawerSize>("normal");

  const chat = useChat();
  const pageContext = usePageContext({
    selectedNodeFqn,
    view,
    level,
  });

  // Restore persisted settings
  useEffect(() => {
    const storedCtx = localStorage.getItem(STORAGE_KEY_CONTEXT_AWARE);
    if (storedCtx !== null) {
      setTimeout(() => setIncludePageContextState(storedCtx === "true"), 0);
    }
    const storedTone = localStorage.getItem(STORAGE_KEY_TONE);
    if (storedTone) {
      setTimeout(() => setToneState(storedTone as ChatTone), 0);
    }
  }, []);

  const setIncludePageContext = useCallback((include: boolean) => {
    setIncludePageContextState(include);
    localStorage.setItem(STORAGE_KEY_CONTEXT_AWARE, String(include));
  }, []);

  const setTone = useCallback((t: ChatTone) => {
    setToneState(t);
    localStorage.setItem(STORAGE_KEY_TONE, t);
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
        tone,
      );
    },
    [chat, projectId, pageContext, includePageContext, tone],
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
      tone,
      drawerSize,
      sendMessage,
      clearMessages: chat.clearMessages,
      stopStreaming: chat.stopStreaming,
      toggleOpen,
      setOpen: setIsOpen,
      setIncludePageContext,
      setTone,
      setDrawerSize,
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
      tone,
      drawerSize,
      sendMessage,
      toggleOpen,
      setIncludePageContext,
      setTone,
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

/**
 * Safe version that returns null when outside a ChatProvider.
 * Use this in components that may render before the provider is ready.
 */
export function useChatContextSafe(): ChatContextValue | null {
  return useContext(ChatContext);
}
