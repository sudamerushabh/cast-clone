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
      <div className="min-w-0 max-w-[85%] space-y-1 overflow-hidden">
        {/* Thinking block */}
        {(message.thinking || message.isStreaming) && message.thinking !== undefined && (
          <ThinkingBlock
            content={message.thinking ?? ""}
            isStreaming={message.isStreaming && !message.content && message.toolCalls.length === 0}
          />
        )}

        {/* Interleaved tool calls and intermediate text segments */}
        {message.contentSegments && message.contentSegments.length > 0 ? (
          <>
            {message.contentSegments.map((seg, idx) => {
              if (seg.type === "tool_group") {
                return seg.toolCallIds.map((tcId) => {
                  const tc = message.toolCalls.find((t) => t.id === tcId);
                  return tc ? <ToolCallCard key={tc.id} toolCall={tc} /> : null;
                });
              }
              // text segment
              return (
                <div key={`seg-${idx}`} className="rounded-2xl rounded-tl-md bg-muted/50 px-4 py-2.5">
                  <div className="prose prose-sm dark:prose-invert max-w-none text-sm leading-relaxed overflow-x-auto [&_pre]:bg-muted [&_pre]:text-foreground [&_pre]:overflow-x-auto [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_code]:before:content-[''] [&_code]:after:content-[''] [&_table]:text-xs [&_table]:block [&_table]:overflow-x-auto">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        code: ({ children, className, ...props }) => {
                          const isBlock = className?.includes("language-");
                          if (isBlock) return <code className={className} {...props}>{children}</code>;
                          const text = String(children);
                          if (FQN_REGEX.test(text) && onNavigateToNode) {
                            FQN_REGEX.lastIndex = 0;
                            return (
                              <button type="button" className="cursor-pointer rounded bg-violet-100 px-1 py-0.5 font-mono text-xs text-violet-700 underline decoration-violet-300 underline-offset-2 transition-colors hover:bg-violet-200 dark:bg-violet-900/30 dark:text-violet-300 dark:decoration-violet-700 dark:hover:bg-violet-900/50" onClick={() => onNavigateToNode(text)} title={`Navigate to ${text}`}>{children}</button>
                            );
                          }
                          FQN_REGEX.lastIndex = 0;
                          return <code {...props}>{children}</code>;
                        },
                        p: ({ children, ...props }) => <p {...props}>{processChildrenForFQNs(children, onNavigateToNode)}</p>,
                        li: ({ children, ...props }) => <li {...props}>{processChildrenForFQNs(children, onNavigateToNode)}</li>,
                      }}
                    >
                      {seg.text}
                    </ReactMarkdown>
                  </div>
                </div>
              );
            })}
          </>
        ) : (
          <>
            {/* Fallback: legacy single-content rendering */}
            {message.toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} toolCall={tc} />
            ))}

        {/* Response content */}
        {message.content && (
          <div className="rounded-2xl rounded-tl-md bg-muted/50 px-4 py-2.5">
            <div className="prose prose-sm dark:prose-invert max-w-none text-sm leading-relaxed overflow-x-auto [&_pre]:bg-muted [&_pre]:text-foreground [&_pre]:overflow-x-auto [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_code]:before:content-[''] [&_code]:after:content-[''] [&_table]:text-xs [&_table]:block [&_table]:overflow-x-auto">
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
          </>
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
