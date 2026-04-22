"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { Plus, FolderOpen, Loader2 } from "lucide-react"

import { listProjects, createProject } from "@/lib/api"
import type { ProjectResponse } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/ui/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
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
  {
    label: string
    variant: "secondary" | "default" | "destructive"
    className?: string
  }
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
  const [projects, setProjects] = React.useState<ProjectResponse[]>([])
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
      setProjects(data.projects)
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
    <div className="container mx-auto max-w-5xl px-4 py-8">
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
              <Plus className="mr-2 size-4" />
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
                  {creating && <Loader2 className="mr-2 size-4 animate-spin" />}
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
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <div className="rounded-lg border border-dashed">
          <EmptyState
            icon={FolderOpen}
            title="No projects yet"
            description="Create your first project to get started."
            action={
              <Button size="lg" onClick={() => setDialogOpen(true)}>
                <Plus className="mr-2 size-4" />
                Create Project
              </Button>
            }
          />
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
