// hooks/useChat.ts
"use client";

import { useCallback, useRef, useState } from "react";
import type {
  ChatMessage,
  ChatRequest,
  ChatSSEEvent,
  ChatState,
  HistoryEntry,
  PageContext,
  ToolCallDisplay,
} from "@/lib/chat-types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const MAX_HISTORY_TURNS = 10;

function generateId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("auth_token");
}

/**
 * Parse a single SSE line like `data: {"content": "..."}` with a known event type.
 */
function parseSSEChunk(
  buffer: string,
): { events: ChatSSEEvent[]; remainder: string } {
  const events: ChatSSEEvent[] = [];
  const lines = buffer.split("\n");
  let remainder = "";
  let currentEventType: string | null = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // If the last line doesn't end with \n, it's an incomplete chunk
    if (i === lines.length - 1 && !buffer.endsWith("\n")) {
      remainder = line;
      break;
    }

    if (line.startsWith("event: ")) {
      currentEventType = line.slice(7).trim();
    } else if (line.startsWith("data: ") && currentEventType) {
      try {
        const data = JSON.parse(line.slice(6));
        events.push({ type: currentEventType, ...data } as ChatSSEEvent);
      } catch {
        // Skip malformed JSON
      }
      currentEventType = null;
    } else if (line === "") {
      // Empty line = event boundary, reset
      currentEventType = null;
    }
  }

  return { events, remainder };
}

interface UseChatReturn {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
  sendMessage: (
    projectId: string,
    message: string,
    pageContext: PageContext | null,
    includePageContext: boolean,
  ) => Promise<void>;
  clearMessages: () => void;
  stopStreaming: () => void;
}

export function useChat(): UseChatReturn {
  const [state, setState] = useState<ChatState>({
    messages: [],
    isStreaming: false,
    error: null,
  });

  const abortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);

  // Keep ref in sync with state so callbacks can read latest
  messagesRef.current = state.messages;

  const buildHistory = useCallback((): HistoryEntry[] => {
    const msgs = messagesRef.current;
    const history: HistoryEntry[] = [];
    for (const msg of msgs) {
      if (msg.role === "user") {
        history.push({ role: "user", content: msg.content });
      } else if (msg.role === "assistant" && msg.content) {
        history.push({ role: "assistant", content: msg.content });
      }
    }
    // Keep last N turns
    return history.slice(-MAX_HISTORY_TURNS);
  }, []);

  const sendMessage = useCallback(
    async (
      projectId: string,
      message: string,
      pageContext: PageContext | null,
      includePageContext: boolean,
    ) => {
      // Cancel any in-flight stream
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      // Add user message
      const userMsg: ChatMessage = {
        id: generateId(),
        role: "user",
        content: message,
        toolCalls: [],
        isStreaming: false,
        timestamp: Date.now(),
      };

      // Prepare assistant message placeholder
      const assistantMsg: ChatMessage = {
        id: generateId(),
        role: "assistant",
        content: "",
        thinking: "",
        toolCalls: [],
        isStreaming: true,
        timestamp: Date.now(),
      };

      setState((prev) => ({
        ...prev,
        messages: [...prev.messages, userMsg, assistantMsg],
        isStreaming: true,
        error: null,
      }));

      const history = buildHistory();

      const body: ChatRequest = {
        message,
        history,
        page_context: pageContext,
        include_page_context: includePageContext,
      };

      try {
        const token = getAuthToken();
        const response = await fetch(
          `${BASE_URL}/api/v1/projects/${projectId}/chat`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Accept: "text/event-stream",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify(body),
            signal: controller.signal,
          },
        );

        if (!response.ok) {
          const text = await response.text();
          let errMsg: string;
          try {
            const json = JSON.parse(text);
            errMsg = json.detail ?? json.message ?? text;
          } catch {
            errMsg = text;
          }
          throw new Error(errMsg || `Chat request failed (${response.status})`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let sseBuffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          sseBuffer += decoder.decode(value, { stream: true });
          const { events, remainder } = parseSSEChunk(sseBuffer);
          sseBuffer = remainder;

          for (const event of events) {
            setState((prev) => {
              const msgs = [...prev.messages];
              const lastIdx = msgs.length - 1;
              const current = { ...msgs[lastIdx] };

              switch (event.type) {
                case "thinking":
                  current.thinking =
                    (current.thinking ?? "") + event.content;
                  break;

                case "tool_use": {
                  const tc: ToolCallDisplay = {
                    id: event.id,
                    name: event.name,
                    input: event.input,
                    status: "running",
                  };
                  current.toolCalls = [...current.toolCalls, tc];
                  break;
                }

                case "tool_result": {
                  current.toolCalls = current.toolCalls.map((tc) =>
                    tc.id === event.tool_use_id
                      ? {
                          ...tc,
                          status: "complete" as const,
                          resultSummary: event.content_summary,
                        }
                      : tc,
                  );
                  break;
                }

                case "text":
                  current.content += event.content;
                  break;

                case "done":
                  current.isStreaming = false;
                  current.tokenUsage = {
                    input: event.input_tokens,
                    output: event.output_tokens,
                  };
                  break;

                case "error":
                  current.isStreaming = false;
                  current.content += `\n\n**Error:** ${event.message}`;
                  break;
              }

              msgs[lastIdx] = current;

              return {
                ...prev,
                messages: msgs,
                isStreaming: event.type !== "done" && event.type !== "error",
              };
            });
          }
        }

        // Ensure streaming is marked as complete
        setState((prev) => ({
          ...prev,
          isStreaming: false,
          messages: prev.messages.map((m, i) =>
            i === prev.messages.length - 1
              ? { ...m, isStreaming: false }
              : m,
          ),
        }));
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setState((prev) => ({
          ...prev,
          isStreaming: false,
          error:
            err instanceof Error ? err.message : "Chat request failed",
          messages: prev.messages.map((m, i) =>
            i === prev.messages.length - 1
              ? { ...m, isStreaming: false }
              : m,
          ),
        }));
      }
    },
    [buildHistory],
  );

  const clearMessages = useCallback(() => {
    abortRef.current?.abort();
    setState({ messages: [], isStreaming: false, error: null });
  }, []);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    setState((prev) => ({
      ...prev,
      isStreaming: false,
      messages: prev.messages.map((m) =>
        m.isStreaming ? { ...m, isStreaming: false } : m,
      ),
    }));
  }, []);

  return {
    messages: state.messages,
    isStreaming: state.isStreaming,
    error: state.error,
    sendMessage,
    clearMessages,
    stopStreaming,
  };
}
