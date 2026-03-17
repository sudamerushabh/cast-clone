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

// ─── Tone & Drawer Size ───────────────────────────────────────────────────

export type ChatTone = "detailed_technical" | "normal" | "concise";

export const CHAT_TONE_LABELS: Record<ChatTone, string> = {
  detailed_technical: "Detailed Technical",
  normal: "Normal",
  concise: "Concise",
};

export type ChatDrawerSize = "minimized" | "normal" | "wide";

// ─── Chat Request ──────────────────────────────────────────────────────────

export interface ChatRequest {
  message: string;
  history: HistoryEntry[];
  page_context?: PageContext | null;
  include_page_context: boolean;
  tone: ChatTone;
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

/** A segment in the interleaved content stream. */
export type ContentSegment =
  | { type: "text"; text: string }
  | { type: "tool_group"; toolCallIds: string[] };

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string; // User text or streamed assistant markdown (full concat)
  thinking?: string; // Collapsible thinking content
  toolCalls: ToolCallDisplay[];
  /** Ordered segments of text and tool-call groups for correct interleaving. */
  contentSegments?: ContentSegment[];
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
