# Phase 2 M3: Frontend Pages — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build project list and dashboard pages so users can see projects, trigger analysis, and navigate to the graph explorer.

**Architecture:** Client components using the API client from M2. Project list as card grid, dashboard with status polling and action buttons.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind CSS, shadcn/ui

**Dependencies:** M2 (types, API client, layout). This plan assumes the following exist:
- `@/lib/types` — `Project`, `AnalysisTriggerResponse`, `AnalysisStatusResponse`
- `@/lib/api` — `listProjects()`, `getProject(id)`, `triggerAnalysis(id)`, `getAnalysisStatus(id)`
- `@/components/layout/AppLayout` — Shell layout with sidebar/header

---

## File Structure

```
cast-clone-frontend/
├── app/
│   ├── page.tsx                          # MODIFY — redirect to /projects
│   ├── projects/
│   │   ├── page.tsx                      # CREATE — project list page
│   │   └── [id]/
│   │       ├── layout.tsx                # CREATE — project layout wrapper
│   │       └── page.tsx                  # CREATE — project dashboard
├── components/
│   └── ui/
│       ├── badge.tsx                     # CREATE — shadcn badge component
│       ├── card.tsx                      # CREATE — shadcn card component
│       ├── input.tsx                     # CREATE — shadcn input component
│       ├── label.tsx                     # CREATE — shadcn label component
│       └── dialog.tsx                    # CREATE — shadcn dialog component
```

---

## Task 1: Install shadcn UI Components

**Files:**
- Create: `cast-clone-frontend/components/ui/badge.tsx`
- Create: `cast-clone-frontend/components/ui/card.tsx`
- Create: `cast-clone-frontend/components/ui/input.tsx`
- Create: `cast-clone-frontend/components/ui/label.tsx`
- Create: `cast-clone-frontend/components/ui/dialog.tsx`

- [ ] **Step 1.1: Add shadcn Badge component**

```bash
cd cast-clone-frontend && npx shadcn@latest add badge --yes
```

Verify `components/ui/badge.tsx` exists and exports `Badge` and `badgeVariants`.

- [ ] **Step 1.2: Add shadcn Card component**

```bash
cd cast-clone-frontend && npx shadcn@latest add card --yes
```

Verify `components/ui/card.tsx` exists and exports `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter`.

- [ ] **Step 1.3: Add shadcn Input component**

```bash
cd cast-clone-frontend && npx shadcn@latest add input --yes
```

Verify `components/ui/input.tsx` exists and exports `Input`.

- [ ] **Step 1.4: Add shadcn Label component**

```bash
cd cast-clone-frontend && npx shadcn@latest add label --yes
```

Verify `components/ui/label.tsx` exists and exports `Label`.

- [ ] **Step 1.5: Add shadcn Dialog component**

```bash
cd cast-clone-frontend && npx shadcn@latest add dialog --yes
```

Verify `components/ui/dialog.tsx` exists and exports `Dialog`, `DialogTrigger`, `DialogContent`, `DialogHeader`, `DialogTitle`, `DialogDescription`, `DialogFooter`, `DialogClose`.

---

## Task 2: Create Project List Page

**Files:**
- Create: `cast-clone-frontend/app/projects/page.tsx`

- [ ] **Step 2.1: Create the projects directory**

```bash
mkdir -p cast-clone-frontend/app/projects
```

- [ ] **Step 2.2: Create the project list page**

Create `cast-clone-frontend/app/projects/page.tsx`:

```tsx
"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { Plus, FolderOpen, Loader2 } from "lucide-react"

import { listProjects, createProject } from "@/lib/api"
import type { Project } from "@/lib/types"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

const STATUS_BADGE: Record<
  string,
  { label: string; variant: "secondary" | "default" | "destructive"; className?: string }
> = {
  created: { label: "Created", variant: "secondary" },
  analyzing: {
    label: "Analyzing",
    variant: "default",
    className: "animate-pulse bg-blue-600 text-white hover:bg-blue-600",
  },
  analyzed: {
    label: "Analyzed",
    variant: "default",
    className: "bg-green-600 text-white hover:bg-green-600",
  },
  failed: { label: "Failed", variant: "destructive" },
}

function StatusBadge({ status }: { status: string }) {
  const config = STATUS_BADGE[status] ?? {
    label: status,
    variant: "secondary" as const,
  }
  return (
    <Badge variant={config.variant} className={config.className}>
      {config.label}
    </Badge>
  )
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

export default function ProjectsPage() {
  const router = useRouter()
  const [projects, setProjects] = React.useState<Project[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [creating, setCreating] = React.useState(false)
  const [formName, setFormName] = React.useState("")
  const [formPath, setFormPath] = React.useState("")

  const fetchProjects = React.useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await listProjects()
      setProjects(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load projects")
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!formName.trim() || !formPath.trim()) return
    try {
      setCreating(true)
      const project = await createProject({
        name: formName.trim(),
        source_path: formPath.trim(),
      })
      setDialogOpen(false)
      setFormName("")
      setFormPath("")
      router.push(`/projects/${project.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create project")
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="container mx-auto max-w-5xl py-8 px-4">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Projects</h1>
          <p className="text-sm text-muted-foreground">
            Manage and analyze your software projects
          </p>
        </div>

        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="lg">
              <Plus data-icon="inline-start" />
              Create Project
            </Button>
          </DialogTrigger>
          <DialogContent>
            <form onSubmit={handleCreate}>
              <DialogHeader>
                <DialogTitle>Create Project</DialogTitle>
                <DialogDescription>
                  Point to a codebase directory to begin analysis.
                </DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 py-4">
                <div className="grid gap-2">
                  <Label htmlFor="project-name">Project Name</Label>
                  <Input
                    id="project-name"
                    placeholder="my-application"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    required
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="source-path">Source Path</Label>
                  <Input
                    id="source-path"
                    placeholder="/path/to/codebase"
                    value={formPath}
                    onChange={(e) => setFormPath(e.target.value)}
                    required
                  />
                </div>
              </div>
              <DialogFooter>
                <DialogClose asChild>
                  <Button type="button" variant="outline">
                    Cancel
                  </Button>
                </DialogClose>
                <Button type="submit" disabled={creating}>
                  {creating && <Loader2 className="animate-spin" data-icon="inline-start" />}
                  Create
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {error && (
        <div className="mb-6 rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : projects.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-20">
          <FolderOpen className="mb-4 size-12 text-muted-foreground" />
          <h2 className="mb-1 text-lg font-medium">No projects yet</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            Create your first project to get started.
          </p>
          <Button size="lg" onClick={() => setDialogOpen(true)}>
            <Plus data-icon="inline-start" />
            Create Project
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <Card
              key={project.id}
              className="cursor-pointer transition-colors hover:border-primary/30"
              onClick={() => router.push(`/projects/${project.id}`)}
            >
              <CardHeader>
                <div className="flex items-start justify-between">
                  <CardTitle className="text-base">{project.name}</CardTitle>
                  <StatusBadge status={project.status} />
                </div>
                <CardDescription className="truncate font-mono text-xs">
                  {project.source_path}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  Created {formatDate(project.created_at)}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2.3: Verify the page compiles**

```bash
cd cast-clone-frontend && npx tsc --noEmit 2>&1 | head -20
```

If there are type errors referencing `createProject` not existing in `@/lib/api`, add it to the API client (it takes `{ name: string; source_path: string }` and returns `Project`). This should have been part of M2 but may need to be added:

```typescript
// In lib/api.ts — add if missing:
export async function createProject(data: { name: string; source_path: string }): Promise<Project> {
  const res = await fetch(`${API_BASE}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to create project: ${res.statusText}`)
  return res.json()
}
```

---

## Task 3: Create Project Dashboard Page

**Files:**
- Create: `cast-clone-frontend/app/projects/[id]/page.tsx`

- [ ] **Step 3.1: Create the [id] directory**

```bash
mkdir -p cast-clone-frontend/app/projects/\[id\]
```

- [ ] **Step 3.2: Create the project dashboard page**

Create `cast-clone-frontend/app/projects/[id]/page.tsx`:

```tsx
"use client"

import * as React from "react"
import { useParams, useRouter } from "next/navigation"
import {
  ArrowLeft,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  ExternalLink,
} from "lucide-react"

import { getProject, triggerAnalysis, getAnalysisStatus } from "@/lib/api"
import type { Project, AnalysisStatusResponse } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"

const POLL_INTERVAL_MS = 2000

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function ProjectDashboardPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const projectId = params.id

  const [project, setProject] = React.useState<Project | null>(null)
  const [analysisStatus, setAnalysisStatus] =
    React.useState<AnalysisStatusResponse | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [triggering, setTriggering] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  // Fetch project data
  const fetchProject = React.useCallback(async () => {
    try {
      setError(null)
      const data = await getProject(projectId)
      setProject(data)
      return data
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load project")
      return null
    } finally {
      setLoading(false)
    }
  }, [projectId])

  // Fetch analysis status
  const fetchStatus = React.useCallback(async () => {
    try {
      const status = await getAnalysisStatus(projectId)
      setAnalysisStatus(status)
      return status
    } catch {
      // Status endpoint may 404 if no analysis has run — that is fine
      return null
    }
  }, [projectId])

  // Initial load
  React.useEffect(() => {
    async function init() {
      const proj = await fetchProject()
      if (proj) {
        await fetchStatus()
      }
    }
    init()
  }, [fetchProject, fetchStatus])

  // Poll while analyzing
  React.useEffect(() => {
    if (project?.status !== "analyzing") return

    const interval = setInterval(async () => {
      const proj = await fetchProject()
      if (proj?.status === "analyzing") {
        await fetchStatus()
      }
    }, POLL_INTERVAL_MS)

    return () => clearInterval(interval)
  }, [project?.status, fetchProject, fetchStatus])

  // Trigger analysis
  async function handleTriggerAnalysis() {
    try {
      setTriggering(true)
      setError(null)
      await triggerAnalysis(projectId)
      // Refetch to pick up new status
      await fetchProject()
      await fetchStatus()
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to trigger analysis"
      )
    } finally {
      setTriggering(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!project) {
    return (
      <div className="container mx-auto max-w-3xl py-8 px-4">
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error ?? "Project not found"}
        </div>
        <Button
          variant="ghost"
          className="mt-4"
          onClick={() => router.push("/projects")}
        >
          <ArrowLeft data-icon="inline-start" />
          Back to Projects
        </Button>
      </div>
    )
  }

  const isAnalyzing = project.status === "analyzing"
  const isAnalyzed = project.status === "analyzed"
  const isFailed = project.status === "failed"

  return (
    <div className="container mx-auto max-w-3xl py-8 px-4">
      {/* Header */}
      <div className="mb-6">
        <Button
          variant="ghost"
          size="sm"
          className="mb-4"
          onClick={() => router.push("/projects")}
        >
          <ArrowLeft data-icon="inline-start" />
          Back to Projects
        </Button>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {project.name}
            </h1>
            <p className="mt-1 font-mono text-sm text-muted-foreground">
              {project.source_path}
            </p>
          </div>
          <StatusBadgeLarge status={project.status} />
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Actions */}
      <div className="mb-6 flex gap-3">
        <Button
          size="lg"
          onClick={handleTriggerAnalysis}
          disabled={isAnalyzing || triggering}
        >
          {isAnalyzing || triggering ? (
            <Loader2 className="animate-spin" data-icon="inline-start" />
          ) : (
            <Play data-icon="inline-start" />
          )}
          {isAnalyzing ? "Analyzing..." : "Run Analysis"}
        </Button>

        {isAnalyzed && (
          <Button
            size="lg"
            variant="outline"
            onClick={() => router.push(`/projects/${projectId}/graph`)}
          >
            <ExternalLink data-icon="inline-start" />
            View Graph
          </Button>
        )}
      </div>

      {/* Project Details */}
      <div className="grid gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Project Details</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">ID</dt>
              <dd className="font-mono text-xs">{project.id}</dd>
              <dt className="text-muted-foreground">Created</dt>
              <dd>{formatDate(project.created_at)}</dd>
              {project.updated_at && (
                <>
                  <dt className="text-muted-foreground">Last Updated</dt>
                  <dd>{formatDate(project.updated_at)}</dd>
                </>
              )}
              <dt className="text-muted-foreground">Status</dt>
              <dd className="capitalize">{project.status}</dd>
            </dl>
          </CardContent>
        </Card>

        {/* Analysis Status */}
        {analysisStatus && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Analysis Status</CardTitle>
              <CardDescription>
                {isAnalyzing
                  ? "Analysis is running..."
                  : isAnalyzed
                    ? "Analysis completed successfully"
                    : isFailed
                      ? "Analysis encountered an error"
                      : "Ready for analysis"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {analysisStatus.current_stage && (
                <div className="mb-4">
                  <p className="text-sm font-medium">
                    Current Stage:{" "}
                    <span className="font-mono">
                      {analysisStatus.current_stage}
                    </span>
                  </p>
                  {analysisStatus.progress !== undefined && (
                    <div className="mt-2">
                      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                        <div
                          className="h-full rounded-full bg-primary transition-all duration-500"
                          style={{
                            width: `${Math.round(analysisStatus.progress * 100)}%`,
                          }}
                        />
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {Math.round(analysisStatus.progress * 100)}% complete
                      </p>
                    </div>
                  )}
                </div>
              )}

              {analysisStatus.stages && analysisStatus.stages.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">Pipeline Stages</p>
                  <ul className="space-y-1">
                    {analysisStatus.stages.map((stage) => (
                      <li
                        key={stage.name}
                        className="flex items-center gap-2 text-sm"
                      >
                        {stage.status === "completed" ? (
                          <CheckCircle2 className="size-4 text-green-600" />
                        ) : stage.status === "running" ? (
                          <Loader2 className="size-4 animate-spin text-blue-600" />
                        ) : stage.status === "failed" ? (
                          <XCircle className="size-4 text-destructive" />
                        ) : (
                          <div className="size-4 rounded-full border" />
                        )}
                        <span className="font-mono text-xs">{stage.name}</span>
                        {stage.duration_ms !== undefined && (
                          <span className="text-xs text-muted-foreground">
                            ({(stage.duration_ms / 1000).toFixed(1)}s)
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Error Display */}
        {isFailed && analysisStatus?.error && (
          <Card className="border-destructive/50">
            <CardHeader>
              <CardTitle className="text-base text-destructive">
                Analysis Error
              </CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="overflow-x-auto rounded-md bg-destructive/5 p-3 font-mono text-xs text-destructive">
                {analysisStatus.error}
              </pre>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

function StatusBadgeLarge({ status }: { status: string }) {
  const map: Record<string, { label: string; className: string }> = {
    created: {
      label: "Created",
      className: "bg-secondary text-secondary-foreground",
    },
    analyzing: {
      label: "Analyzing",
      className: "animate-pulse bg-blue-600 text-white",
    },
    analyzed: {
      label: "Analyzed",
      className: "bg-green-600 text-white",
    },
    failed: {
      label: "Failed",
      className: "bg-destructive/10 text-destructive",
    },
  }
  const config = map[status] ?? {
    label: status,
    className: "bg-secondary text-secondary-foreground",
  }
  return (
    <span
      className={`inline-flex items-center rounded-md px-2.5 py-1 text-xs font-medium ${config.className}`}
    >
      {config.label}
    </span>
  )
}
```

---

## Task 4: Create Project Layout Wrapper

**Files:**
- Create: `cast-clone-frontend/app/projects/[id]/layout.tsx`

- [ ] **Step 4.1: Create the project layout**

Create `cast-clone-frontend/app/projects/[id]/layout.tsx`:

```tsx
export default function ProjectLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
```

This is intentionally minimal. It exists so that navigating between `/projects/[id]` and `/projects/[id]/graph` does not re-mount the root layout. Future milestones will add a project-level sidebar or breadcrumb here.

---

## Task 5: Update Landing Page to Redirect

**Files:**
- Modify: `cast-clone-frontend/app/page.tsx`

- [ ] **Step 5.1: Replace the landing page with a redirect to /projects**

Replace the contents of `cast-clone-frontend/app/page.tsx` with:

```tsx
import { redirect } from "next/navigation"

export default function Page() {
  redirect("/projects")
}
```

This is a server-side redirect (HTTP 307) so users hitting `/` are immediately sent to the project list.

---

## Task 6: Verify Navigation Flow

- [ ] **Step 6.1: Run TypeScript type-check**

```bash
cd cast-clone-frontend && npx tsc --noEmit
```

Fix any type errors. Common issues:
- `createProject` missing from `@/lib/api` — add it per the snippet in Step 2.3.
- `AnalysisStatusResponse.stages` or `.current_stage` fields may not match `@/lib/types` — update the type to include:

```typescript
// In lib/types.ts — ensure these fields exist on AnalysisStatusResponse:
export interface AnalysisStageStatus {
  name: string
  status: "pending" | "running" | "completed" | "failed"
  duration_ms?: number
}

export interface AnalysisStatusResponse {
  project_id: string
  status: string
  current_stage?: string
  progress?: number
  stages?: AnalysisStageStatus[]
  error?: string
}
```

- [ ] **Step 6.2: Run the dev server and test navigation**

```bash
cd cast-clone-frontend && npm run dev
```

Test the following flow manually:
1. Navigate to `http://localhost:3000` — should redirect to `/projects`
2. See the empty state with "No projects yet" message
3. Click "Create Project" — dialog opens with name and path fields
4. Fill in a name and path, click "Create" — navigates to `/projects/[id]`
5. See the project dashboard with details and "Run Analysis" button
6. Click "Back to Projects" — returns to project list
7. Click a project card — navigates to dashboard

- [ ] **Step 6.3: Run lint**

```bash
cd cast-clone-frontend && npm run lint
```

Fix any lint errors.

- [ ] **Step 6.4: Run format**

```bash
cd cast-clone-frontend && npm run format
```

---

## Summary

| Task | Files | Steps | Estimated Time |
|------|-------|-------|----------------|
| Task 1: shadcn components | 5 created | 5 | 5 min |
| Task 2: Project list page | 1 created | 3 | 10 min |
| Task 3: Project dashboard | 1 created | 2 | 10 min |
| Task 4: Project layout | 1 created | 1 | 2 min |
| Task 5: Landing redirect | 1 modified | 1 | 2 min |
| Task 6: Verify | 0 | 4 | 5 min |
| **Total** | **9 files (8 new, 1 modified)** | **16 steps** | **~34 min** |
