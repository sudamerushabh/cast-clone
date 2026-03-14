# Phase 5b-M3: Chat Frontend

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished, production-quality chat drawer in the Next.js frontend that consumes SSE from the M1 backend, renders thinking blocks and tool call cards, supports page-context awareness, and persists state across page navigation within a repository.

**Architecture:** A `ChatProvider` React context wraps the repository branch layout (`app/repositories/[repoId]/[...branch]/layout.tsx`), holding conversation messages and settings so chat state survives Next.js App Router navigations. A `useChat` hook manages SSE consumption via `fetch` + `ReadableStream`, mapping server events to typed React state. A `usePageContext` hook reads the current route and graph selection state to build the `PageContext` payload. The `ChatDrawer` component slides in from the right edge, triggered by a floating button.

**Tech Stack:** Next.js 14+ (App Router), TypeScript, Tailwind CSS, React Context + hooks, `react-markdown` + `remark-gfm` (already in package.json), lucide-react icons.

---

## File Structure

```
cast-clone-frontend/
├── lib/
│   └── chat-types.ts                         # CREATE — TypeScript types for chat events, messages, page context
├── hooks/
│   ├── useChat.ts                            # CREATE — SSE streaming + conversation state management
│   └── usePageContext.ts                     # CREATE — Page context extraction from route/graph state
├── components/chat/
│   ├── ChatProvider.tsx                      # CREATE — React context provider for chat state
│   ├── ChatDrawer.tsx                        # CREATE — Slide-out drawer container + floating trigger button
│   ├── ChatHeader.tsx                        # CREATE — Header with project name, context toggle, clear button
│   ├── ChatMessage.tsx                       # CREATE — Message renderer (dispatches to sub-components)
│   ├── ThinkingBlock.tsx                     # CREATE — Collapsible thinking display with animation
│   ├── ToolCallCard.tsx                      # CREATE — Tool call visualization (spinner -> checkmark)
│   ├── ChatInput.tsx                         # CREATE — Input textarea with send button
│   └── PageContextChip.tsx                   # CREATE — Current context display chip
├── app/repositories/[repoId]/[...branch]/
│   └── layout.tsx                            # MODIFY — wrap children with ChatProvider + ChatDrawer
```

---

## Task 1: Chat Types

**Files:**
- Create: `cast-clone-frontend/lib/chat-types.ts`

- [ ] **Step 1: Create the types file**

```typescript
// lib/chat-types.ts
/**
 * TypeScript types for the AI chat feature.
 * Maps to the SSE events produced by the M1 backend (POST /api/v1/projects/{project_id}/chat).
 */

// ─── Page Context ──────────────────────────────────────────────────────────

export interface PageContext {
  page: string; // "graph_explorer", "pr_detail", "dashboard", "impact", "transactions", etc.
  selected_node_fqn?: string | null;
  view?: string | null; // "architecture", "dependency", "transaction"
  level?: string | null; // "module", "class", "method"
  pr_analysis_id?: string | null;
}

// ─── Chat Request ──────────────────────────────────────────────────────────

export interface ChatRequest {
  message: string;
  history: HistoryEntry[];
  page_context?: PageContext | null;
  include_page_context: boolean;
}

// NOTE: History is flattened to text-only for simplicity. The agent won't
// remember which tools it called in prior turns, but can re-discover via tools.
// Sending full content blocks (tool_use/tool_result) would add significant
// complexity for marginal quality improvement.
export interface HistoryEntry {
  role: "user" | "assistant";
  content: string;
}

// ─── SSE Events (from backend) ─────────────────────────────────────────────

export type ChatSSEEventType =
  | "thinking"
  | "tool_use"
  | "tool_result"
  | "text"
  | "done"
  | "error";

export interface ThinkingEvent {
  type: "thinking";
  content: string;
}

export interface ToolUseEvent {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultEvent {
  type: "tool_result";
  tool_use_id: string;
  content_summary: string;
}

export interface TextEvent {
  type: "text";
  content: string;
}

export interface DoneEvent {
  type: "done";
  input_tokens: number;
  output_tokens: number;
  tool_calls?: number;
  duration_ms?: number;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type ChatSSEEvent =
  | ThinkingEvent
  | ToolUseEvent
  | ToolResultEvent
  | TextEvent
  | DoneEvent
  | ErrorEvent;

// ─── Message Display Model ────────────────────────────────────────────────

export type MessageRole = "user" | "assistant";

export interface ToolCallDisplay {
  id: string;
  name: string;
  input: Record<string, unknown>;
  status: "running" | "complete" | "error";
  resultSummary?: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string; // User text or streamed assistant markdown
  thinking?: string; // Collapsible thinking content
  toolCalls: ToolCallDisplay[];
  isStreaming: boolean;
  tokenUsage?: { input: number; output: number };
  timestamp: number;
}

// ─── Chat State ────────────────────────────────────────────────────────────

export interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
}

// ─── Tool name → human-readable description ────────────────────────────────

export const TOOL_DISPLAY_NAMES: Record<string, string> = {
  list_applications: "Listing applications",
  application_stats: "Fetching app statistics",
  get_architecture: "Loading architecture",
  search_objects: "Searching code objects",
  object_details: "Getting object details",
  impact_analysis: "Running impact analysis",
  find_path: "Finding path",
  list_transactions: "Listing transactions",
  transaction_graph: "Loading transaction graph",
  get_source_code: "Reading source code",
  get_or_generate_summary: "Generating summary",
};

/**
 * Build a human-readable description of what a tool call is doing.
 * e.g. "Querying impact for `OrderService`..."
 */
export function describeToolCall(name: string, input: Record<string, unknown>): string {
  const base = TOOL_DISPLAY_NAMES[name] ?? `Running ${name}`;
  // Extract the most meaningful input parameter for display
  const fqn = input.node_fqn ?? input.from_fqn ?? input.fqn ?? input.query ?? input.app_name;
  if (fqn && typeof fqn === "string") {
    // Show just the short name (last segment of FQN)
    const shortName = fqn.includes(".") ? fqn.split(".").pop() : fqn;
    return `${base} for \`${shortName}\``;
  }
  return base;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit --strict lib/chat-types.ts`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add lib/chat-types.ts
git commit -m "feat(5b-m3): add TypeScript types for chat SSE events and messages"
```

---

## Task 2: usePageContext Hook

**Files:**
- Create: `cast-clone-frontend/hooks/usePageContext.ts`

- [ ] **Step 1: Create the hook**

```typescript
// hooks/usePageContext.ts
"use client";

import { useMemo } from "react";
import { usePathname, useParams } from "next/navigation";
import type { PageContext } from "@/lib/chat-types";

/**
 * Reads the current route and extracts structured page context
 * for the AI chat assistant. This tells the agent what the user
 * is currently looking at so it can give contextual answers.
 *
 * The `selectedNodeFqn` must be passed in from the graph state
 * since it's not in the URL.
 */
export function usePageContext(opts?: {
  selectedNodeFqn?: string | null;
  view?: string | null;
  level?: string | null;
}): PageContext {
  const pathname = usePathname();
  const params = useParams();

  return useMemo(() => {
    const repoId = params?.repoId as string | undefined;
    const branchSegments = params?.branch as string[] | undefined;
    const analysisId = params?.analysisId as string | undefined;

    // Determine which page the user is on from the pathname
    let page = "dashboard";
    if (pathname.includes("/graph/")) {
      page = "graph_explorer";
    } else if (pathname.includes("/impact/")) {
      page = "impact_analysis";
    } else if (pathname.includes("/transactions/")) {
      page = "transactions";
    } else if (pathname.includes("/dependencies/")) {
      page = "dependency_view";
    } else if (pathname.includes("/pull-requests/") && analysisId) {
      page = "pr_detail";
    } else if (pathname.includes("/pull-requests")) {
      page = "pr_list";
    } else if (pathname.includes("/search/")) {
      page = "search";
    } else if (pathname.includes("/views/")) {
      page = "saved_views";
    } else if (pathname.includes("/settings/")) {
      page = "settings";
    } else if (pathname.includes("/chat/")) {
      page = "chat";
    } else if (repoId && branchSegments) {
      page = "dashboard";
    }

    return {
      page,
      selected_node_fqn: opts?.selectedNodeFqn ?? null,
      view: opts?.view ?? null,
      level: opts?.level ?? null,
      pr_analysis_id: analysisId ?? null,
    };
  }, [pathname, params, opts?.selectedNodeFqn, opts?.view, opts?.level]);
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add hooks/usePageContext.ts
git commit -m "feat(5b-m3): add usePageContext hook for route-based context extraction"
```

---

## Task 3: useChat Hook (SSE Consumer)

**Files:**
- Create: `cast-clone-frontend/hooks/useChat.ts`

- [ ] **Step 1: Create the hook**

```typescript
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add hooks/useChat.ts
git commit -m "feat(5b-m3): add useChat hook with SSE streaming and conversation state"
```

---

## Task 4: ChatProvider Context

**Files:**
- Create: `cast-clone-frontend/components/chat/ChatProvider.tsx`

- [ ] **Step 1: Create the context provider**

```tsx
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
  projectName,
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
      setIncludePageContextState(stored === "true");
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/chat/ChatProvider.tsx
git commit -m "feat(5b-m3): add ChatProvider context for cross-page state persistence"
```

---

## Task 5: PageContextChip Component

**Files:**
- Create: `cast-clone-frontend/components/chat/PageContextChip.tsx`

- [ ] **Step 1: Create the component**

```tsx
// components/chat/PageContextChip.tsx
"use client";

import {
  GitGraph,
  Activity,
  LayoutDashboard,
  GitPullRequest,
  Search,
  Bookmark,
  Settings,
  MessageCircle,
  Network,
} from "lucide-react";
import type { PageContext } from "@/lib/chat-types";

const PAGE_LABELS: Record<string, { label: string; icon: React.ElementType }> = {
  graph_explorer: { label: "Graph Explorer", icon: GitGraph },
  impact_analysis: { label: "Impact Analysis", icon: Activity },
  transactions: { label: "Transactions", icon: Network },
  dependency_view: { label: "Dependencies", icon: GitGraph },
  pr_detail: { label: "PR Detail", icon: GitPullRequest },
  pr_list: { label: "Pull Requests", icon: GitPullRequest },
  search: { label: "Search", icon: Search },
  saved_views: { label: "Saved Views", icon: Bookmark },
  settings: { label: "Settings", icon: Settings },
  chat: { label: "Chat", icon: MessageCircle },
  dashboard: { label: "Dashboard", icon: LayoutDashboard },
};

interface PageContextChipProps {
  context: PageContext;
  isActive: boolean;
}

export function PageContextChip({ context, isActive }: PageContextChipProps) {
  if (!isActive) return null;

  const pageInfo = PAGE_LABELS[context.page] ?? {
    label: context.page,
    icon: LayoutDashboard,
  };
  const Icon = pageInfo.icon;

  // Build a short description of what the user is viewing
  let detail: string | null = null;
  if (context.selected_node_fqn) {
    const shortName = context.selected_node_fqn.includes(".")
      ? context.selected_node_fqn.split(".").pop()!
      : context.selected_node_fqn;
    detail = shortName;
  } else if (context.view) {
    detail = context.view;
    if (context.level) {
      detail += ` (${context.level})`;
    }
  }

  return (
    <div className="flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/50 px-2.5 py-0.5 text-xs text-muted-foreground">
      <Icon className="size-3 shrink-0" />
      <span className="truncate">
        {pageInfo.label}
        {detail && (
          <>
            <span className="mx-1 opacity-40">|</span>
            <span className="font-medium text-foreground/70">{detail}</span>
          </>
        )}
      </span>
    </div>
  );
}
```

- [ ] **Step 2: Verify the component renders correctly**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/chat/PageContextChip.tsx
git commit -m "feat(5b-m3): add PageContextChip for displaying current viewing context"
```

---

## Task 6: ThinkingBlock Component

**Files:**
- Create: `cast-clone-frontend/components/chat/ThinkingBlock.tsx`

- [ ] **Step 1: Create the component**

```tsx
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/chat/ThinkingBlock.tsx
git commit -m "feat(5b-m3): add ThinkingBlock component with collapsible thinking display"
```

---

## Task 7: ToolCallCard Component

**Files:**
- Create: `cast-clone-frontend/components/chat/ToolCallCard.tsx`

- [ ] **Step 1: Create the component**

```tsx
// components/chat/ToolCallCard.tsx
"use client";

import { useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  AlertCircle,
  Wrench,
} from "lucide-react";
import type { ToolCallDisplay } from "@/lib/chat-types";
import { describeToolCall } from "@/lib/chat-types";

interface ToolCallCardProps {
  toolCall: ToolCallDisplay;
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const description = describeToolCall(toolCall.name, toolCall.input);

  return (
    <div className="my-1.5">
      <button
        type="button"
        onClick={() => {
          if (toolCall.status !== "running") {
            setIsExpanded((prev) => !prev);
          }
        }}
        className="group flex w-full items-center gap-2 rounded-md border border-border/40 bg-background px-3 py-1.5 text-left transition-colors hover:bg-muted/30"
        disabled={toolCall.status === "running"}
      >
        {/* Status icon */}
        {toolCall.status === "running" && (
          <Loader2 className="size-3.5 shrink-0 animate-spin text-blue-500" />
        )}
        {toolCall.status === "complete" && (
          <Check className="size-3.5 shrink-0 text-emerald-500" />
        )}
        {toolCall.status === "error" && (
          <AlertCircle className="size-3.5 shrink-0 text-red-500" />
        )}

        {/* Tool icon */}
        <Wrench className="size-3 shrink-0 text-muted-foreground/60" />

        {/* Description */}
        <span className="flex-1 truncate text-xs text-muted-foreground">
          {description}
          {toolCall.status === "running" && "..."}
        </span>

        {/* Expand chevron (only when complete) */}
        {toolCall.status !== "running" && toolCall.resultSummary && (
          <span className="text-muted-foreground/50">
            {isExpanded ? (
              <ChevronDown className="size-3" />
            ) : (
              <ChevronRight className="size-3" />
            )}
          </span>
        )}
      </button>

      {/* Expanded result */}
      {isExpanded && toolCall.resultSummary && (
        <div className="mt-0.5 rounded-b-md border border-t-0 border-border/40 bg-muted/20 px-3 py-2">
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground/80">
            {toolCall.resultSummary}
          </p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/chat/ToolCallCard.tsx
git commit -m "feat(5b-m3): add ToolCallCard component with spinner-to-checkmark transition"
```

---

## Task 8: ChatMessage Component

**Files:**
- Create: `cast-clone-frontend/components/chat/ChatMessage.tsx`

- [ ] **Step 1: Create the component**

```tsx
// components/chat/ChatMessage.tsx
"use client";

import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Bot } from "lucide-react";
import type { ChatMessage as ChatMessageType } from "@/lib/chat-types";
import { ThinkingBlock } from "./ThinkingBlock";
import { ToolCallCard } from "./ToolCallCard";

// Regex to detect FQNs: 2+ dot-separated segments, each starting with a letter or $
// e.g. com.app.OrderService, com.app.OrderService.processOrder
const FQN_REGEX =
  /\b(?:[a-zA-Z_$][\w$]*\.){1,}[a-zA-Z_$][\w$]*\b/g;

interface ChatMessageProps {
  message: ChatMessageType;
  onNavigateToNode?: (fqn: string) => void;
}

export function ChatMessageComponent({
  message,
  onNavigateToNode,
}: ChatMessageProps) {
  if (message.role === "user") {
    return <UserMessage content={message.content} />;
  }

  return (
    <AssistantMessage
      message={message}
      onNavigateToNode={onNavigateToNode}
    />
  );
}

// ─── User Message ──────────────────────────────────────────────────────────

function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end gap-2 px-4 py-2">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm text-primary-foreground">
        <p className="whitespace-pre-wrap">{content}</p>
      </div>
      <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
        <User className="size-3.5 text-primary" />
      </div>
    </div>
  );
}

// ─── Assistant Message ─────────────────────────────────────────────────────

function AssistantMessage({
  message,
  onNavigateToNode,
}: {
  message: ChatMessageType;
  onNavigateToNode?: (fqn: string) => void;
}) {
  // Check if the response references impact/path results for "Show in Graph"
  const hasGraphResults = useMemo(() => {
    const content = message.content.toLowerCase();
    return (
      message.toolCalls.some(
        (tc) =>
          tc.name === "impact_analysis" ||
          tc.name === "find_path" ||
          tc.name === "get_architecture",
      ) &&
      (content.includes("impact") ||
        content.includes("path") ||
        content.includes("affected") ||
        content.includes("downstream") ||
        content.includes("upstream"))
    );
  }, [message.content, message.toolCalls]);

  return (
    <div className="flex gap-2 px-4 py-2">
      <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-violet-100 dark:bg-violet-900/30">
        <Bot className="size-3.5 text-violet-600 dark:text-violet-400" />
      </div>
      <div className="min-w-0 max-w-[85%] space-y-1">
        {/* Thinking block */}
        {(message.thinking || message.isStreaming) && message.thinking !== undefined && (
          <ThinkingBlock
            content={message.thinking ?? ""}
            isStreaming={message.isStreaming && !message.content && message.toolCalls.length === 0}
          />
        )}

        {/* Tool calls */}
        {message.toolCalls.map((tc) => (
          <ToolCallCard key={tc.id} toolCall={tc} />
        ))}

        {/* Response content */}
        {message.content && (
          <div className="rounded-2xl rounded-tl-md bg-muted/50 px-4 py-2.5">
            <div className="prose prose-sm dark:prose-invert max-w-none text-sm leading-relaxed [&_pre]:bg-muted [&_pre]:text-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_code]:before:content-[''] [&_code]:after:content-['']">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  // Make FQNs in inline code clickable
                  code: ({ children, className, ...props }) => {
                    const isBlock = className?.includes("language-");
                    if (isBlock) {
                      return (
                        <code className={className} {...props}>
                          {children}
                        </code>
                      );
                    }
                    const text = String(children);
                    if (FQN_REGEX.test(text) && onNavigateToNode) {
                      // Reset regex state
                      FQN_REGEX.lastIndex = 0;
                      return (
                        <button
                          type="button"
                          className="cursor-pointer rounded bg-violet-100 px-1 py-0.5 font-mono text-xs text-violet-700 underline decoration-violet-300 underline-offset-2 transition-colors hover:bg-violet-200 dark:bg-violet-900/30 dark:text-violet-300 dark:decoration-violet-700 dark:hover:bg-violet-900/50"
                          onClick={() => onNavigateToNode(text)}
                          title={`Navigate to ${text}`}
                        >
                          {children}
                        </button>
                      );
                    }
                    FQN_REGEX.lastIndex = 0;
                    return <code {...props}>{children}</code>;
                  },
                  // Make plain-text FQNs clickable
                  p: ({ children, ...props }) => {
                    return (
                      <p {...props}>
                        {processChildrenForFQNs(children, onNavigateToNode)}
                      </p>
                    );
                  },
                  li: ({ children, ...props }) => {
                    return (
                      <li {...props}>
                        {processChildrenForFQNs(children, onNavigateToNode)}
                      </li>
                    );
                  },
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>

            {/* Show in Graph button */}
            {hasGraphResults && !message.isStreaming && onNavigateToNode && (
              <div className="mt-2 border-t border-border/30 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    // Find the first FQN from tool call inputs
                    const tc = message.toolCalls.find(
                      (t) =>
                        t.name === "impact_analysis" ||
                        t.name === "find_path",
                    );
                    const fqn =
                      (tc?.input?.node_fqn as string) ??
                      (tc?.input?.from_fqn as string);
                    if (fqn) onNavigateToNode(fqn);
                  }}
                  className="flex items-center gap-1.5 rounded-md bg-violet-100 px-3 py-1.5 text-xs font-medium text-violet-700 transition-colors hover:bg-violet-200 dark:bg-violet-900/30 dark:text-violet-300 dark:hover:bg-violet-900/50"
                >
                  Show in Graph
                </button>
              </div>
            )}
          </div>
        )}

        {/* Streaming cursor */}
        {message.isStreaming && !message.content && message.toolCalls.every((tc) => tc.status === "complete") && (
          <div className="rounded-2xl rounded-tl-md bg-muted/50 px-4 py-3">
            <div className="flex items-center gap-1">
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/40 [animation-delay:0ms]" />
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/40 [animation-delay:150ms]" />
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/40 [animation-delay:300ms]" />
            </div>
          </div>
        )}

        {/* Token usage */}
        {message.tokenUsage && !message.isStreaming && (
          <p className="mt-1 text-[10px] tabular-nums text-muted-foreground/50">
            {message.tokenUsage.input.toLocaleString()} in / {message.tokenUsage.output.toLocaleString()} out tokens
          </p>
        )}
      </div>
    </div>
  );
}

// ─── FQN detection in plain text ───────────────────────────────────────────

/**
 * Scans React children for text nodes containing FQN patterns
 * and wraps them in clickable buttons.
 */
function processChildrenForFQNs(
  children: React.ReactNode,
  onNavigateToNode?: (fqn: string) => void,
): React.ReactNode {
  if (!onNavigateToNode) return children;

  if (typeof children === "string") {
    return processTextForFQNs(children, onNavigateToNode);
  }

  if (Array.isArray(children)) {
    return children.map((child, i) => {
      if (typeof child === "string") {
        return (
          <span key={i}>
            {processTextForFQNs(child, onNavigateToNode)}
          </span>
        );
      }
      return child;
    });
  }

  return children;
}

function processTextForFQNs(
  text: string,
  onNavigateToNode: (fqn: string) => void,
): React.ReactNode {
  const regex = new RegExp(FQN_REGEX.source, "g");
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;

  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    // Skip common false positives
    const fqn = match[0];
    if (isLikelyFQN(fqn)) {
      if (match.index > lastIndex) {
        parts.push(text.slice(lastIndex, match.index));
      }
      parts.push(
        <button
          key={match.index}
          type="button"
          className="cursor-pointer rounded font-mono text-xs text-violet-600 underline decoration-violet-300 underline-offset-2 transition-colors hover:text-violet-800 dark:text-violet-400 dark:decoration-violet-700 dark:hover:text-violet-300"
          onClick={() => onNavigateToNode(fqn)}
          title={`Navigate to ${fqn}`}
        >
          {fqn}
        </button>,
      );
      lastIndex = match.index + fqn.length;
    }
  }

  if (lastIndex === 0) return text;
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

/**
 * Heuristic to filter out false FQN matches.
 * A "likely FQN" has at least 2 dots and doesn't look like a URL or version.
 */
function isLikelyFQN(candidate: string): boolean {
  const dots = candidate.split(".").length - 1;
  if (dots < 2) return false;
  // Filter out URLs, file extensions, version numbers
  if (candidate.endsWith(".md") || candidate.endsWith(".json") || candidate.endsWith(".yaml")) return false;
  if (candidate.match(/^\d/)) return false; // Starts with number
  if (candidate.includes("http") || candidate.includes("www")) return false;
  return true;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/chat/ChatMessage.tsx
git commit -m "feat(5b-m3): add ChatMessage component with markdown rendering and FQN links"
```

---

## Task 9: ChatInput Component

**Files:**
- Create: `cast-clone-frontend/components/chat/ChatInput.tsx`

- [ ] **Step 1: Create the component**

```tsx
// components/chat/ChatInput.tsx
"use client";

import { useCallback, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ChatInputProps {
  onSend: (message: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export function ChatInput({
  onSend,
  onStop,
  isStreaming,
  disabled,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setValue("");
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, isStreaming, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setValue(e.target.value);
      // Auto-resize textarea
      const ta = e.target;
      ta.style.height = "auto";
      ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
    },
    [],
  );

  return (
    <div className="border-t border-border/60 bg-background p-3">
      <div className="flex items-end gap-2 rounded-xl border border-border/60 bg-muted/30 px-3 py-2 transition-colors focus-within:border-ring/50 focus-within:bg-background">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Ask about the architecture..."
          disabled={disabled}
          rows={1}
          className="max-h-40 min-h-[24px] flex-1 resize-none bg-transparent text-sm leading-relaxed text-foreground placeholder:text-muted-foreground/60 focus:outline-none disabled:opacity-50"
        />
        {isStreaming ? (
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={onStop}
            className="shrink-0 text-muted-foreground hover:text-foreground"
            aria-label="Stop generating"
          >
            <Square className="size-3 fill-current" />
          </Button>
        ) : (
          <Button
            variant="default"
            size="icon-xs"
            onClick={handleSubmit}
            disabled={!value.trim() || disabled}
            className="shrink-0"
            aria-label="Send message"
          >
            <ArrowUp className="size-3" />
          </Button>
        )}
      </div>
      <p className="mt-1.5 text-center text-[10px] text-muted-foreground/40">
        AI can make mistakes. Verify important information.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/chat/ChatInput.tsx
git commit -m "feat(5b-m3): add ChatInput component with auto-resize and keyboard shortcuts"
```

---

## Task 10: ChatHeader Component

**Files:**
- Create: `cast-clone-frontend/components/chat/ChatHeader.tsx`

- [ ] **Step 1: Create the component**

```tsx
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/chat/ChatHeader.tsx
git commit -m "feat(5b-m3): add ChatHeader with context toggle, clear, and close buttons"
```

---

## Task 11: ChatDrawer Component

**Files:**
- Create: `cast-clone-frontend/components/chat/ChatDrawer.tsx`

- [ ] **Step 1: Create the component**

```tsx
// components/chat/ChatDrawer.tsx
"use client";

import { useCallback, useEffect, useRef } from "react";
import { MessageCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add components/chat/ChatDrawer.tsx
git commit -m "feat(5b-m3): add ChatDrawer with slide-out panel, floating trigger, and empty state"
```

---

## Task 12: Integrate ChatProvider into Branch Layout

**Files:**
- Modify: `cast-clone-frontend/app/repositories/[repoId]/[...branch]/layout.tsx`

- [ ] **Step 1: Update the layout to wrap children with ChatProvider and ChatDrawer**

Replace the entire contents of `app/repositories/[repoId]/[...branch]/layout.tsx`:

```tsx
// app/repositories/[repoId]/[...branch]/layout.tsx
"use client";

import { useParams } from "next/navigation";
import { useRepoProject } from "@/hooks/useRepoProject";
import { ChatProvider } from "@/components/chat/ChatProvider";
import { ChatDrawer } from "@/components/chat/ChatDrawer";

export default function BranchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const repoId = params.repoId as string;
  const branchSegments = params.branch as string[];
  const branchName = branchSegments
    ?.map(decodeURIComponent)
    .join("/") ?? "main";

  const { projectId } = useRepoProject(repoId, branchName);

  // If projectId isn't resolved yet, render without chat
  // (the page components handle their own loading states)
  if (!projectId) {
    return <>{children}</>;
  }

  return (
    <ChatProvider projectId={projectId} projectName={branchName}>
      {children}
      <ChatDrawer projectName={branchName} />
    </ChatProvider>
  );
}
```

- [ ] **Step 2: Verify the app compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Manual verification**

Start the dev server and navigate to any repository branch page:
Run: `cd cast-clone-frontend && npm run dev`

1. Verify the floating chat button appears in the bottom-right corner
2. Click it to open the drawer
3. Verify the drawer slides in from the right with header, empty state, and input
4. Verify suggestion chips are clickable
5. Verify the context-aware toggle works (eye icon)
6. Verify Ctrl+Shift+L toggles the drawer
7. Close and reopen the drawer to verify state persistence
8. Navigate between pages within the same repository and verify chat state survives

- [ ] **Step 4: Commit**

```bash
cd cast-clone-frontend && git add app/repositories/\[repoId\]/\[...branch\]/layout.tsx
git commit -m "feat(5b-m3): integrate ChatProvider and ChatDrawer into branch layout"
```

---

## Task 13: Update Chat Page to Use Drawer

**Files:**
- Modify: `cast-clone-frontend/app/repositories/[repoId]/chat/[...branch]/page.tsx`

The dedicated chat page should auto-open the drawer and provide a landing experience.

- [ ] **Step 1: Update the chat page**

Replace the entire contents:

```tsx
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend && git add app/repositories/\[repoId\]/chat/\[...branch\]/page.tsx
git commit -m "feat(5b-m3): update chat page to auto-open drawer with landing content"
```

---

## Task 14: Final Integration Verification

- [ ] **Step 1: Full TypeScript check**

Run: `cd cast-clone-frontend && npx tsc --noEmit`

- [ ] **Step 2: Lint check**

Run: `cd cast-clone-frontend && npm run lint`

- [ ] **Step 3: Build check**

Run: `cd cast-clone-frontend && npm run build`

- [ ] **Step 4: Manual end-to-end verification**

With both the backend (`uv run uvicorn app.main:app --reload`) and frontend (`npm run dev`) running:

1. Navigate to a repository branch page (e.g., `/repositories/{repoId}/main`)
2. Click the floating chat button in the bottom-right
3. Type a message and press Enter (or click send)
4. Verify SSE streaming works: thinking block appears, tool call cards animate, response streams in
5. Verify FQNs in responses are clickable (rendered as violet links)
6. Toggle context-aware off/on and verify the chip updates
7. Refresh the page and verify context-aware toggle persists (localStorage)
8. Navigate to the graph page, select a node, then open chat and verify the page context chip shows the node
9. Clear the conversation and verify messages are removed
10. Use Ctrl+Shift+L to toggle the drawer open/closed

- [ ] **Step 5: Commit (if any fixes were needed)**

```bash
cd cast-clone-frontend && git add -A
git commit -m "fix(5b-m3): integration fixes for chat frontend"
```
