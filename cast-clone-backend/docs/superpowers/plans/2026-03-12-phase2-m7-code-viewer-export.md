# Phase 2 M7: Code Viewer & Export — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Monaco Editor for source code viewing (triggered from node properties panel) and PNG/SVG/JSON export buttons in the graph toolbar.

**Architecture:** Monaco Editor in a togglable bottom panel, fetches code via API. Export uses Cytoscape's built-in png()/svg()/json() methods with browser download triggers.

**Tech Stack:** @monaco-editor/react, cytoscape-svg, React 19, TypeScript

---

## Dependencies

- **M4** (Cytoscape graph): `GraphView` provides `cy` instance ref via `cyRef`
- **M5** (properties panel): `NodeProperties` has a "View Source" button placeholder
- **M6** (toolbar): `GraphToolbar` exists with view switcher and layout controls

**Assumed existing files** (created by M2-M6):

| File | Provides |
|------|----------|
| `cast-clone-frontend/lib/api.ts` | API client with `API_BASE` constant |
| `cast-clone-frontend/lib/types.ts` | Shared TypeScript types |
| `cast-clone-frontend/components/graph/GraphView.tsx` | Cytoscape wrapper, exposes `cyRef` |
| `cast-clone-frontend/components/graph/GraphToolbar.tsx` | Toolbar with view/layout controls |
| `cast-clone-frontend/components/graph/NodeProperties.tsx` | Right sidebar, shows node data on select |
| `cast-clone-frontend/app/projects/[id]/graph/page.tsx` | Graph explorer page, manages state |
| `cast-clone-frontend/lib/cytoscape-setup.ts` | Extension registration (dagre, fcose, expand-collapse) |

---

## File Structure

```
cast-clone-frontend/
├── lib/
│   ├── api.ts                              # MODIFY — add getCode()
│   ├── types.ts                            # MODIFY — add CodeViewerResponse
│   └── cytoscape-setup.ts                  # MODIFY — register cytoscape-svg
├── components/
│   ├── code/
│   │   └── CodeViewer.tsx                  # CREATE — Monaco editor bottom panel
│   └── graph/
│       ├── ExportButtons.tsx               # CREATE — PNG/SVG/JSON export buttons
│       ├── GraphToolbar.tsx                # MODIFY — add ExportButtons
│       └── NodeProperties.tsx              # MODIFY — wire View Source callback
├── app/
│   └── projects/
│       └── [id]/
│           └── graph/
│               └── page.tsx                # MODIFY — add code viewer state + layout
```

---

## Task 1: Install npm Packages

**Files:** `cast-clone-frontend/package.json` (modified by npm)

- [ ] **Step 1.1: Install @monaco-editor/react and cytoscape-svg**

```bash
cd cast-clone-frontend && npm install @monaco-editor/react cytoscape-svg
```

- [ ] **Step 1.2: Install type declarations for cytoscape-svg**

The `cytoscape-svg` package does not ship types. Create a declaration file.

Create `cast-clone-frontend/types/cytoscape-svg.d.ts`:

```typescript
declare module "cytoscape-svg" {
  import cytoscape from "cytoscape"
  const cytoscapeSvg: cytoscape.Ext
  export default cytoscapeSvg
}
```

- [ ] **Step 1.3: Verify packages installed**

```bash
cd cast-clone-frontend && node -e "require('@monaco-editor/react'); require('cytoscape-svg'); console.log('OK')"
```

---

## Task 2: Register cytoscape-svg Extension

**Files:**
- Modify: `cast-clone-frontend/lib/cytoscape-setup.ts`

- [ ] **Step 2.1: Add cytoscape-svg import and registration**

Add the following import and registration call to `cast-clone-frontend/lib/cytoscape-setup.ts`, alongside the existing extension registrations (dagre, fcose, expand-collapse):

```typescript
import cytoscapeSvg from "cytoscape-svg"
```

Add to the registration block (inside the guard that prevents double-registration):

```typescript
cytoscape.use(cytoscapeSvg)
```

The file should already have a pattern like:

```typescript
import cytoscape from "cytoscape"
import dagre from "cytoscape-dagre"
import fcose from "cytoscape-fcose"
import expandCollapse from "cytoscape-expand-collapse"
import cytoscapeSvg from "cytoscape-svg"

let registered = false

export function registerCytoscapeExtensions() {
  if (registered) return
  cytoscape.use(dagre)
  cytoscape.use(fcose)
  cytoscape.use(expandCollapse)
  cytoscape.use(cytoscapeSvg)
  registered = true
}
```

If the file uses a different pattern, match it. The key addition is importing `cytoscape-svg` and calling `cytoscape.use(cytoscapeSvg)`.

---

## Task 3: Add API Types and Client Function

**Files:**
- Modify: `cast-clone-frontend/lib/types.ts`
- Modify: `cast-clone-frontend/lib/api.ts`

- [ ] **Step 3.1: Add CodeViewerResponse type**

Add to `cast-clone-frontend/lib/types.ts`:

```typescript
/** Response from GET /api/v1/code/{project_id} */
export interface CodeViewerResponse {
  content: string
  language: string
  start_line: number
  highlight_line: number
}
```

- [ ] **Step 3.2: Add getCode() API function**

Add to `cast-clone-frontend/lib/api.ts`:

```typescript
import type { CodeViewerResponse } from "./types"

/**
 * Fetch source code for a file within a project.
 * @param projectId - Project UUID
 * @param file - Relative file path (e.g. "src/main/java/com/app/UserService.java")
 * @param line - Target line number to center on
 * @param context - Number of lines of context around the target line (default 30)
 */
export async function getCode(
  projectId: string,
  file: string,
  line: number,
  context: number = 30
): Promise<CodeViewerResponse> {
  const params = new URLSearchParams({
    file,
    line: String(line),
    context: String(context),
  })
  const res = await fetch(
    `${API_BASE}/api/v1/code/${projectId}?${params.toString()}`
  )
  if (!res.ok) {
    throw new Error(`Failed to fetch code: ${res.statusText}`)
  }
  return res.json()
}
```

Make sure `API_BASE` is already defined in the file (it should be from M2). If the file uses a different fetch wrapper or base URL variable name, match the existing pattern.

---

## Task 4: Create CodeViewer Component

**Files:**
- Create: `cast-clone-frontend/components/code/CodeViewer.tsx`

- [ ] **Step 4.1: Create the code directory**

```bash
mkdir -p cast-clone-frontend/components/code
```

- [ ] **Step 4.2: Create CodeViewer.tsx**

Create `cast-clone-frontend/components/code/CodeViewer.tsx`:

```tsx
"use client"

import * as React from "react"
import Editor, { type OnMount } from "@monaco-editor/react"
import { X, Loader2, FileCode } from "lucide-react"

import { getCode } from "@/lib/api"
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
  context?: number
  onClose: () => void
}

export function CodeViewer({
  projectId,
  file,
  line,
  context = 30,
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
        const result = await getCode(projectId, file, line, context)
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
  }, [projectId, file, line, context])

  // When editor mounts, scroll to and highlight the target line
  const handleEditorMount: OnMount = React.useCallback(
    (editor) => {
      if (!data) return

      const targetLine = data.highlight_line - data.start_line + 1

      // Scroll to the target line (centered in viewport)
      editor.revealLineInCenter(targetLine)

      // Add a background highlight decoration on the target line
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
          {data && (
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
```

---

## Task 5: Create ExportButtons Component

**Files:**
- Create: `cast-clone-frontend/components/graph/ExportButtons.tsx`

- [ ] **Step 5.1: Create ExportButtons.tsx**

Create `cast-clone-frontend/components/graph/ExportButtons.tsx`:

```tsx
"use client"

import * as React from "react"
import { Download, Image, FileJson, FileType } from "lucide-react"
import type cytoscape from "cytoscape"

import { Button } from "@/components/ui/button"

/**
 * Trigger a browser file download from a Blob.
 */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  // Clean up
  setTimeout(() => {
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, 100)
}

/**
 * Download a data URL (e.g., from cy.png()) as a file.
 */
function downloadDataUrl(dataUrl: string, filename: string) {
  const a = document.createElement("a")
  a.href = dataUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  setTimeout(() => {
    document.body.removeChild(a)
  }, 100)
}

interface ExportButtonsProps {
  cy: cytoscape.Core | null
}

export function ExportButtons({ cy }: ExportButtonsProps) {
  function handleExportPng() {
    if (!cy) return
    const dataUrl = cy.png({ full: true, scale: 2, bg: "#ffffff" })
    downloadDataUrl(dataUrl, "graph-export.png")
  }

  function handleExportSvg() {
    if (!cy) return
    // cytoscape-svg extension adds .svg() method to the core
    const svgContent = (cy as unknown as { svg: (opts: object) => string }).svg({
      full: true,
      bg: "#ffffff",
    })
    const blob = new Blob([svgContent], { type: "image/svg+xml;charset=utf-8" })
    downloadBlob(blob, "graph-export.svg")
  }

  function handleExportJson() {
    if (!cy) return
    const elements = cy.json().elements
    const json = JSON.stringify(elements, null, 2)
    const blob = new Blob([json], { type: "application/json" })
    downloadBlob(blob, "graph-export.json")
  }

  const disabled = !cy

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={handleExportPng}
        disabled={disabled}
        title="Export as PNG"
        aria-label="Export graph as PNG"
      >
        <Image />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={handleExportSvg}
        disabled={disabled}
        title="Export as SVG"
        aria-label="Export graph as SVG"
      >
        <FileType />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={handleExportJson}
        disabled={disabled}
        title="Export as JSON"
        aria-label="Export graph as JSON"
      >
        <FileJson />
      </Button>
    </div>
  )
}
```

---

## Task 6: Wire CodeViewer into Graph Page

**Files:**
- Modify: `cast-clone-frontend/app/projects/[id]/graph/page.tsx`

- [ ] **Step 6.1: Add code viewer state variables**

Add these state declarations to the graph page component (next to existing state like `selectedNode`, `currentView`, etc.):

```typescript
const [codeViewerOpen, setCodeViewerOpen] = React.useState(false)
const [codeViewerFile, setCodeViewerFile] = React.useState<string>("")
const [codeViewerLine, setCodeViewerLine] = React.useState<number>(1)
```

- [ ] **Step 6.2: Add the onViewSource handler**

Add this callback function inside the component:

```typescript
const handleViewSource = React.useCallback(
  (file: string, line: number) => {
    setCodeViewerFile(file)
    setCodeViewerLine(line)
    setCodeViewerOpen(true)
  },
  []
)

const handleCloseCodeViewer = React.useCallback(() => {
  setCodeViewerOpen(false)
}, [])
```

- [ ] **Step 6.3: Add CodeViewer import**

Add at the top of the file:

```typescript
import { CodeViewer } from "@/components/code/CodeViewer"
```

- [ ] **Step 6.4: Update layout to include CodeViewer**

The graph page should render with a flex-column layout. The graph area takes remaining space, and the CodeViewer sits at the bottom when open.

Find the JSX return section. It currently likely looks something like:

```tsx
return (
  <div className="flex h-screen">
    {/* sidebar / filters */}
    <div className="flex flex-1 flex-col">
      <GraphToolbar ... />
      <div className="relative flex-1">
        <GraphView ... />
      </div>
      {selectedNode && <NodeProperties ... />}
    </div>
  </div>
)
```

Wrap the graph area and code viewer in a flex column so the code viewer takes fixed space at the bottom:

```tsx
return (
  <div className="flex h-screen">
    {/* sidebar / filters */}
    <div className="flex flex-1 flex-col">
      <GraphToolbar ... />
      <div className="relative min-h-0 flex-1">
        <GraphView ... />
        {selectedNode && <NodeProperties ... />}
      </div>
      {codeViewerOpen && codeViewerFile && (
        <CodeViewer
          projectId={projectId}
          file={codeViewerFile}
          line={codeViewerLine}
          onClose={handleCloseCodeViewer}
        />
      )}
    </div>
  </div>
)
```

The key structural change: the graph area gets `min-h-0 flex-1` so it shrinks to accommodate the 300px CodeViewer below it. The CodeViewer has `h-[300px]` set internally.

---

## Task 7: Wire ExportButtons into GraphToolbar

**Files:**
- Modify: `cast-clone-frontend/components/graph/GraphToolbar.tsx`

- [ ] **Step 7.1: Add ExportButtons import**

Add at the top of `cast-clone-frontend/components/graph/GraphToolbar.tsx`:

```typescript
import { ExportButtons } from "./ExportButtons"
```

- [ ] **Step 7.2: Accept cy prop in GraphToolbar**

The `GraphToolbar` component needs to receive the `cy` instance. Add it to the props interface:

```typescript
interface GraphToolbarProps {
  // ... existing props (currentView, onViewChange, etc.)
  cy: cytoscape.Core | null
}
```

If `GraphToolbar` does not already import cytoscape types, add:

```typescript
import type cytoscape from "cytoscape"
```

- [ ] **Step 7.3: Render ExportButtons in the toolbar**

Add `<ExportButtons cy={cy} />` to the toolbar JSX. Place it at the right end of the toolbar, separated from other controls with a divider:

```tsx
{/* Inside the toolbar's right-side controls area */}
<div className="h-4 w-px bg-border" /> {/* vertical divider */}
<ExportButtons cy={cy} />
```

- [ ] **Step 7.4: Pass cy to GraphToolbar from graph page**

In `cast-clone-frontend/app/projects/[id]/graph/page.tsx`, make sure the `<GraphToolbar>` receives the `cy` prop:

```tsx
<GraphToolbar
  /* ...existing props... */
  cy={cyRef.current}
/>
```

Where `cyRef` is the ref to the Cytoscape instance provided by `GraphView`. If the graph page accesses it differently (e.g., via a state variable or callback), use the existing pattern.

---

## Task 8: Wire "View Source" in NodeProperties

**Files:**
- Modify: `cast-clone-frontend/components/graph/NodeProperties.tsx`

- [ ] **Step 8.1: Accept onViewSource callback**

Update the `NodeProperties` props interface to include the callback:

```typescript
interface NodePropertiesProps {
  // ... existing props (node, onClose, etc.)
  onViewSource?: (file: string, line: number) => void
}
```

- [ ] **Step 8.2: Add View Source button**

In the `NodeProperties` component JSX, find the section that displays the file path and line number. Add a "View Source" button that calls the callback:

```tsx
import { FileCode } from "lucide-react"

{/* Inside NodeProperties, near the file path display */}
{node.data.file && (
  <Button
    variant="ghost"
    size="sm"
    className="mt-1 gap-1.5"
    onClick={() =>
      onViewSource?.(node.data.file, node.data.line ?? 1)
    }
  >
    <FileCode className="size-3.5" />
    View Source
  </Button>
)}
```

The node data should have `file` (relative path) and `line` (line number) fields from the graph. If `line` is not present, default to 1.

- [ ] **Step 8.3: Pass onViewSource from graph page to NodeProperties**

In `cast-clone-frontend/app/projects/[id]/graph/page.tsx`, pass the handler:

```tsx
{selectedNode && (
  <NodeProperties
    node={selectedNode}
    onClose={() => setSelectedNode(null)}
    onViewSource={handleViewSource}
  />
)}
```

---

## Task 9: Verify Code Viewing and Export

- [ ] **Step 9.1: Run TypeScript type-check**

```bash
cd cast-clone-frontend && npx tsc --noEmit
```

Fix any type errors. Common issues:
- `cytoscape.Core` not recognizing `.svg()` method -- this is expected since it's added by the extension. The type cast in `ExportButtons.tsx` handles this.
- Missing `file` or `line` on node data types -- add to the graph node type in `lib/types.ts` if missing:

```typescript
// In the GraphNode or CytoscapeNodeData type:
export interface GraphNodeData {
  // ... existing fields
  file?: string
  line?: number
}
```

- [ ] **Step 9.2: Run lint**

```bash
cd cast-clone-frontend && npm run lint
```

Fix any lint errors.

- [ ] **Step 9.3: Run format**

```bash
cd cast-clone-frontend && npm run format
```

- [ ] **Step 9.4: Manual smoke test**

```bash
cd cast-clone-frontend && npm run dev
```

Test the following:

1. Navigate to a project graph page (`/projects/{id}/graph`)
2. Click a node to open properties panel
3. Click "View Source" in the properties panel -- the code viewer should appear as a 300px panel at the bottom
4. Monaco editor should show the source code with the target line highlighted in yellow
5. Line numbers in the editor should match the original file (not start at 1)
6. Click the X button on the code viewer -- it should close and the graph expands back
7. Click the PNG export button in the toolbar -- a `graph-export.png` file should download
8. Click the SVG export button -- a `graph-export.svg` file should download
9. Click the JSON export button -- a `graph-export.json` file should download with the graph elements

Note: Steps 1-6 require the backend API to be running with a project that has been analyzed. If the backend is not available, verify that the CodeViewer renders the loading state and then shows an error message when the fetch fails.

---

## Summary

| Task | Files | Steps | Estimated Time |
|------|-------|-------|----------------|
| Task 1: Install npm packages | 1 created, package.json modified | 3 | 3 min |
| Task 2: Register cytoscape-svg | 1 modified | 1 | 2 min |
| Task 3: API types and client | 2 modified | 2 | 3 min |
| Task 4: CodeViewer component | 1 created | 2 | 5 min |
| Task 5: ExportButtons component | 1 created | 1 | 4 min |
| Task 6: Wire CodeViewer into graph page | 1 modified | 4 | 5 min |
| Task 7: Wire ExportButtons into toolbar | 2 modified | 4 | 5 min |
| Task 8: Wire View Source in NodeProperties | 2 modified | 3 | 4 min |
| Task 9: Verify | 0 | 4 | 5 min |
| **Total** | **3 new, 6 modified** | **24 steps** | **~36 min** |
