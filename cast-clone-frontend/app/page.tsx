import Link from "next/link";
import { FolderGit2, GitBranch, Settings, ArrowRight } from "lucide-react";

const quickLinks = [
  {
    label: "Repositories",
    description: "Browse and analyse connected codebases",
    href: "/repositories",
    icon: FolderGit2,
  },
  {
    label: "Connectors",
    description: "Manage Git source connections",
    href: "/connectors",
    icon: GitBranch,
  },
  {
    label: "Settings",
    description: "System and AI configuration",
    href: "/settings/system",
    icon: Settings,
  },
];

export default function HomePage() {
  return (
    <div className="flex flex-col gap-10 p-8 max-w-3xl">
      {/* Hero */}
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight">Welcome to CodeLens</h1>
        <p className="text-muted-foreground text-base">
          An on-premise software intelligence platform. Connect a codebase, run
          analysis, and explore its architecture as an interactive graph.
        </p>
      </div>

      {/* Quick links */}
      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
          Get started
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {quickLinks.map(({ label, description, href, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="group flex flex-col gap-3 rounded-lg border bg-card p-4 transition-colors hover:bg-accent/50"
            >
              <div className="flex items-center justify-between">
                <div className="flex size-9 items-center justify-center rounded-md bg-primary/10">
                  <Icon className="size-4 text-primary" />
                </div>
                <ArrowRight className="size-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">{label}</span>
                <span className="text-xs text-muted-foreground">{description}</span>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* How it works */}
      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
          How it works
        </h2>
        <ol className="flex flex-col gap-2 text-sm text-muted-foreground">
          <li className="flex gap-3">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
              1
            </span>
            <span>Add a Git connector pointing to your source repository.</span>
          </li>
          <li className="flex gap-3">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
              2
            </span>
            <span>Run an analysis — the pipeline parses code and builds a graph in Neo4j.</span>
          </li>
          <li className="flex gap-3">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
              3
            </span>
            <span>Explore architecture views, transaction flows, and impact analysis.</span>
          </li>
        </ol>
      </div>
    </div>
  );
}
