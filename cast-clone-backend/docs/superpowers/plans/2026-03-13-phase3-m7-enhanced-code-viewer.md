# Phase 3 M7: Enhanced Code Viewer — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the existing Monaco code viewer with clickable references — when viewing source code, clicking a function call or class reference navigates to that node in the graph.

**Architecture:** The existing CodeViewer (Phase 2 M7) uses Monaco Editor in read-only mode. Phase 3 enhances it by overlaying clickable decorations on call sites. When the user opens source for a node, we fetch the node's callers/callees via the enhanced node details API (M2), then use Monaco's `deltaDecorations` and `onMouseDown` to make references clickable. Clicking navigates to the target node in the graph.

**Tech Stack:** TypeScript, React 18, Monaco Editor (`@monaco-editor/react`), Next.js 14

**Dependencies:** Phase 3 M2 (node details API), Phase 2 M7 (existing CodeViewer)

---

## File Structure

```
cast-clone-frontend/
├── components/
│   └── code/
│       └── CodeViewer.tsx           # MODIFY — add clickable reference decorations
└── hooks/
    └── useAnalysisData.ts           # FROM M3 — loadNodeDetails
```

---

## Task 1: Read Existing CodeViewer

**Files:**
- Read: `cast-clone-frontend/components/code/CodeViewer.tsx`

- [ ] **Step 1: Read the current implementation to understand its props and structure**

Read the existing CodeViewer file. Understand:
- What props it accepts (file content, language, highlight line, etc.)
- How Monaco is initialized
- How it's mounted in the graph page

---

## Task 2: Add Clickable Reference Decorations

**Files:**
- Modify: `cast-clone-frontend/components/code/CodeViewer.tsx`

- [ ] **Step 1: Add new props for callees**

Extend the CodeViewer props:

```typescript
interface CodeViewerProps {
  // ... existing props ...
  callees?: Array<{
    fqn: string
    name: string
    line?: number
  }>
  onNavigateToNode?: (fqn: string) => void
}
```

- [ ] **Step 2: Add decoration logic after Monaco mounts**

Add a `useEffect` that, when `callees` are provided, creates decorations for each callee that appears in the code. Use Monaco's `deltaDecorations` to highlight call sites:

```typescript
const editorRef = React.useRef<monaco.editor.IStandaloneCodeEditor | null>(null)
const decorationsRef = React.useRef<string[]>([])

const handleEditorDidMount = (editor: monaco.editor.IStandaloneCodeEditor) => {
  editorRef.current = editor

  // Add click handler for navigating to referenced nodes
  editor.onMouseDown((e) => {
    if (e.target.type === monaco.editor.MouseTargetType.CONTENT_TEXT) {
      const position = e.target.position
      if (!position || !callees?.length) return

      // Check if the click is on a decorated line
      const lineContent = editor.getModel()?.getLineContent(position.lineNumber) || ""
      const clickedCallee = callees.find(
        (callee) => lineContent.includes(callee.name)
      )

      if (clickedCallee) {
        onNavigateToNode?.(clickedCallee.fqn)
      }
    }
  })
}

// Apply decorations when callees change
React.useEffect(() => {
  const editor = editorRef.current
  if (!editor || !callees?.length) return

  const model = editor.getModel()
  if (!model) return

  const newDecorations: monaco.editor.IModelDeltaDecoration[] = []

  callees.forEach((callee) => {
    // Search the content for occurrences of the callee name
    const matches = model.findMatches(
      callee.name,
      true,   // searchOnlyEditableRange = true (full content)
      false,  // isRegex
      true,   // matchCase
      null,   // wordSeparators
      false   // captureMatches
    )

    matches.forEach((match) => {
      newDecorations.push({
        range: match.range,
        options: {
          inlineClassName: "code-reference-link",
          hoverMessage: {
            value: `**${callee.name}** — Click to navigate to this node in the graph\n\n\`${callee.fqn}\``,
          },
        },
      })
    })
  })

  decorationsRef.current = editor.deltaDecorations(
    decorationsRef.current,
    newDecorations
  )
}, [callees])
```

- [ ] **Step 3: Add CSS for clickable references**

Add a style tag or modify the global CSS to style the reference links:

```css
.code-reference-link {
  text-decoration: underline;
  text-decoration-color: #3b82f6;
  text-decoration-style: dotted;
  cursor: pointer;
}

.code-reference-link:hover {
  background-color: rgba(59, 130, 246, 0.1);
  text-decoration-style: solid;
}
```

This can be added as a `<style>` tag in the component or in a global CSS file.

- [ ] **Step 4: Verify compilation**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 5: Commit**

```bash
cd cast-clone-frontend
git add components/code/CodeViewer.tsx
git commit -m "feat(phase3): add clickable reference decorations to code viewer"
```

---

## Task 3: Wire Enhanced Code Viewer in Graph Page

**Files:**
- Modify: `cast-clone-frontend/app/projects/[id]/graph/page.tsx`

- [ ] **Step 1: Fetch node details when code viewer opens**

When the user opens the code viewer for a node, also load that node's callees:

```typescript
const handleViewSource = React.useCallback(
  async (file: string, line: number) => {
    setCodeViewerOpen(true)
    setCodeViewerFile(file)
    setCodeViewerLine(line)

    // Also load callees for clickable references
    if (selectedNode?.fqn) {
      await analysisData.loadNodeDetails(params.id, selectedNode.fqn as string)
    }
  },
  [selectedNode, analysisData, params.id]
)
```

- [ ] **Step 2: Pass callees to CodeViewer**

```tsx
<CodeViewer
  // ...existing props...
  callees={analysisData.nodeDetails?.callees?.map((c) => ({
    fqn: c.fqn,
    name: c.name,
  }))}
  onNavigateToNode={(fqn) => {
    // Close code viewer and select the node in the graph
    setCodeViewerOpen(false)
    const node = cyRef.current?.getElementById(fqn)
    if (node?.length) {
      node.select()
      cyRef.current?.animate({ center: { eles: node }, duration: 300 })
    }
  }}
/>
```

- [ ] **Step 3: Verify compilation**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 4: Commit**

```bash
cd cast-clone-frontend
git add app/projects/[id]/graph/page.tsx
git commit -m "feat(phase3): wire clickable code references to graph navigation"
```
