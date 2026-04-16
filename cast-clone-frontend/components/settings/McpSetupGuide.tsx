// cast-clone-frontend/components/settings/McpSetupGuide.tsx
"use client";

import { useState } from "react";
import { Copy, Check, Terminal, Code, Wand2 } from "lucide-react";

const SETUP_SNIPPETS = [
  {
    id: "claude-code",
    name: "Claude Code",
    icon: Terminal,
    description: "Add ChangeSafe as an MCP server in Claude Code CLI.",
    command: `claude mcp add --transport sse changesafe http://localhost:8090/sse`,
    note: "Run this in your terminal. The MCP server uses SSE transport.",
  },
  {
    id: "vscode",
    name: "VS Code (Copilot)",
    icon: Code,
    description: "Add to your VS Code MCP configuration.",
    command: `{
  "servers": {
    "changesafe": {
      "type": "sse",
      "url": "http://localhost:8090/sse",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}`,
    note: "Add this to .vscode/mcp.json in your workspace.",
  },
  {
    id: "cursor",
    name: "Cursor",
    icon: Wand2,
    description: "Configure ChangeSafe MCP in Cursor settings.",
    command: `{
  "mcpServers": {
    "changesafe": {
      "url": "http://localhost:8090/sse",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}`,
    note: "Add to Cursor Settings > MCP > Add Server, or edit ~/.cursor/mcp.json.",
  },
];

export function McpSetupGuide() {
  const [copiedId, setCopiedId] = useState<string | null>(null);

  async function handleCopy(id: string, text: string) {
    await navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">MCP Setup Guide</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect external AI tools to ChangeSafe using the MCP protocol.
          Create an API key above, then use these snippets to configure your tool.
        </p>
      </div>

      <div className="space-y-3">
        {SETUP_SNIPPETS.map((snippet) => {
          const Icon = snippet.icon;
          return (
            <div
              key={snippet.id}
              className="rounded-lg border p-4"
            >
              <div className="mb-2 flex items-center gap-2">
                <Icon className="h-5 w-5 text-muted-foreground" />
                <h4 className="font-medium">{snippet.name}</h4>
              </div>
              <p className="mb-3 text-sm text-muted-foreground">
                {snippet.description}
              </p>
              <div className="relative">
                <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-sm">
                  {snippet.command}
                </pre>
                <button
                  onClick={() => handleCopy(snippet.id, snippet.command)}
                  className="absolute right-2 top-2 rounded p-1 hover:bg-background/80"
                  title="Copy to clipboard"
                >
                  {copiedId === snippet.id ? (
                    <Check className="h-4 w-4 text-green-600" />
                  ) : (
                    <Copy className="h-4 w-4 text-muted-foreground" />
                  )}
                </button>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">{snippet.note}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
