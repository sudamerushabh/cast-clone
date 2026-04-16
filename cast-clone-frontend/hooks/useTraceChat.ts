"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  clearTraceChatHistory,
  getTraceChatHistory,
  sendTraceChatMessage,
} from "@/lib/api";
import type { TraceChatMessage } from "@/lib/types";

interface UseTraceChatResult {
  messages: TraceChatMessage[];
  isLoadingHistory: boolean;
  isSending: boolean;
  error: string | null;
  errorStatus: number | null;
  load: (projectId: string, fqn: string) => Promise<void>;
  send: (
    projectId: string,
    fqn: string,
    question: string,
    maxDepth?: number,
  ) => Promise<void>;
  clear: () => void;
  clearServer: (projectId: string, fqn: string) => Promise<void>;
}

export function useTraceChat(): UseTraceChatResult {
  const [messages, setMessages] = useState<TraceChatMessage[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  // Track which (projectId, fqn) the current `messages` belongs to,
  // so stale responses from a prior node don't overwrite fresh state.
  const activeKeyRef = useRef<string | null>(null);

  const keyFor = (projectId: string, fqn: string) => `${projectId}::${fqn}`;

  const load = useCallback(async (projectId: string, fqn: string) => {
    const key = keyFor(projectId, fqn);
    activeKeyRef.current = key;
    setIsLoadingHistory(true);
    setError(null);
    setErrorStatus(null);
    try {
      const result = await getTraceChatHistory(projectId, fqn);
      if (activeKeyRef.current !== key) return; // user navigated away
      setMessages(result.messages);
    } catch (err) {
      if (activeKeyRef.current !== key) return;
      setError(err instanceof Error ? err.message : "Failed to load chat");
      setErrorStatus(err instanceof ApiError ? err.status : null);
    } finally {
      if (activeKeyRef.current === key) setIsLoadingHistory(false);
    }
  }, []);

  const send = useCallback(
    async (
      projectId: string,
      fqn: string,
      question: string,
      maxDepth: number = 5,
    ) => {
      const key = keyFor(projectId, fqn);
      activeKeyRef.current = key;
      setIsSending(true);
      setError(null);
      setErrorStatus(null);

      // Optimistic: append the user message immediately so the UI
      // updates before the API round-trip completes.
      const optimisticUser: TraceChatMessage = {
        id: `optimistic-${Date.now()}`,
        role: "user",
        content: question,
        created_at: new Date().toISOString(),
        model: null,
        tokens_used: null,
      };
      setMessages((prev) => [...prev, optimisticUser]);

      try {
        const result = await sendTraceChatMessage(
          projectId,
          fqn,
          question,
          maxDepth,
        );
        if (activeKeyRef.current !== key) return;
        // Replace the optimistic placeholder with the real persisted
        // user message + append the assistant reply.
        setMessages((prev) => [
          ...prev.filter((m) => m.id !== optimisticUser.id),
          result.user_message,
          result.assistant_message,
        ]);
      } catch (err) {
        if (activeKeyRef.current !== key) return;
        // Roll back the optimistic user message on failure.
        setMessages((prev) =>
          prev.filter((m) => m.id !== optimisticUser.id),
        );
        setError(err instanceof Error ? err.message : "Failed to send message");
        setErrorStatus(err instanceof ApiError ? err.status : null);
      } finally {
        if (activeKeyRef.current === key) setIsSending(false);
      }
    },
    [],
  );

  const clear = useCallback(() => {
    activeKeyRef.current = null;
    setMessages([]);
    setError(null);
    setErrorStatus(null);
    setIsLoadingHistory(false);
    setIsSending(false);
  }, []);

  const clearServer = useCallback(
    async (projectId: string, fqn: string) => {
      try {
        await clearTraceChatHistory(projectId, fqn);
        setMessages([]);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to clear chat history",
        );
      }
    },
    [],
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      activeKeyRef.current = null;
    };
  }, []);

  return {
    messages,
    isLoadingHistory,
    isSending,
    error,
    errorStatus,
    load,
    send,
    clear,
    clearServer,
  };
}
