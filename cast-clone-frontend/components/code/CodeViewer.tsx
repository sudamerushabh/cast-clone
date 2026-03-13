"use client"

import * as React from "react"
import Editor, { type OnMount } from "@monaco-editor/react"
import { X, Loader2, FileCode } from "lucide-react"

import { getCodeView } from "@/lib/api"
import type { CodeViewerResponse } from "@/lib/types"
import { Button } from "@/components/ui/button"

/** Map backend language strings to Monaco language IDs */
const LANGUAGE_MAP: Record<string, string> = {
  java: "java",
  typescript: "typescript",
  javascript: "javascript",
  python: "python",
  csharp: "csharp",
  sql: "sql",
  xml: "xml",
  json: "json",
  yaml: "yaml",
  properties: "ini",
  kotlin: "kotlin",
  go: "go",
}

function toMonacoLanguage(lang: string): string {
  return LANGUAGE_MAP[lang.toLowerCase()] ?? "plaintext"
}

interface CodeViewerProps {
  projectId: string
  file: string
  line: number
  onClose: () => void
}

export function CodeViewer({
  projectId,
  file,
  line,
  onClose,
}: CodeViewerProps) {
  const [data, setData] = React.useState<CodeViewerResponse | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)

  // Fetch code when props change
  React.useEffect(() => {
    let cancelled = false

    async function fetchCode() {
      setLoading(true)
      setError(null)
      try {
        const result = await getCodeView(projectId, file, line)
        if (!cancelled) {
          setData(result)
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load source code"
          )
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    fetchCode()
    return () => {
      cancelled = true
    }
  }, [projectId, file, line])

  // When editor mounts, scroll to and highlight the target line
  const handleEditorMount: OnMount = React.useCallback(
    (editor) => {
      if (!data) return

      const targetLine = data.highlight_line
        ? data.highlight_line - data.start_line + 1
        : 1

      // Scroll to the target line (centered in viewport)
      editor.revealLineInCenter(targetLine)

      // Add a background highlight decoration on the target line
      if (data.highlight_line) {
        editor.createDecorationsCollection([
          {
            range: {
              startLineNumber: targetLine,
              startColumn: 1,
              endLineNumber: targetLine,
              endColumn: 1,
            },
            options: {
              isWholeLine: true,
              className: "code-viewer-highlight-line",
              glyphMarginClassName: "code-viewer-highlight-glyph",
            },
          },
        ])
      }
    },
    [data]
  )

  // File name for display (last segment of path)
  const fileName = file.split("/").pop() ?? file

  return (
    <div className="flex h-[300px] flex-col border-t bg-background">
      {/* Header bar */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b bg-muted/50 px-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <FileCode className="size-3.5" />
          <span className="font-medium text-foreground">{fileName}</span>
          <span className="truncate">{file}</span>
          {data?.highlight_line && (
            <span>
              (line {data.highlight_line})
            </span>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon-xs"
          onClick={onClose}
          aria-label="Close code viewer"
        >
          <X />
        </Button>
      </div>

      {/* Editor area */}
      <div className="relative min-h-0 flex-1">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">
              Loading source code...
            </span>
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-destructive">{error}</p>
          </div>
        ) : data ? (
          <Editor
            height="100%"
            language={toMonacoLanguage(data.language)}
            value={data.content}
            onMount={handleEditorMount}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              lineNumbers: (lineNumber) =>
                String(lineNumber + (data.start_line - 1)),
              scrollBeyondLastLine: false,
              renderLineHighlight: "none",
              fontSize: 13,
              fontFamily:
                "var(--font-mono), ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              padding: { top: 8 },
              domReadOnly: true,
              contextmenu: false,
              folding: true,
              glyphMargin: true,
              automaticLayout: true,
            }}
            theme="vs-dark"
          />
        ) : null}
      </div>

      {/* Inline styles for highlight decoration */}
      <style>{`
        .code-viewer-highlight-line {
          background-color: rgba(255, 213, 79, 0.15) !important;
          border-left: 3px solid #ffd54f !important;
        }
        .code-viewer-highlight-glyph {
          background-color: #ffd54f;
          width: 3px !important;
          margin-left: 3px;
        }
      `}</style>
    </div>
  )
}
