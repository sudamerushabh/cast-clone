# Phase 4A M7a: Global Navigation Shell — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the project-scoped sidebar with a global navigation shell featuring a 48px icon rail, a 240px collapsible context panel, and a redesigned top bar with breadcrumbs — enabling app-level navigation between Repositories, Connectors, and Settings.

**Architecture:** GlobalShell wraps the entire app in `app/layout.tsx`. It renders an always-visible IconRail (48px) + a collapsible ContextPanel (240px) whose contents change based on the current route. The existing AppLayout and Sidebar are deprecated but preserved for legacy `/projects/[id]` routes. Route structure adds `/repositories`, `/connectors`, `/settings` at the top level. Project-level nav moves under `/repositories/[repoId]/[...branch]`.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS, lucide-react icons, shadcn/ui

**Dependencies:** Phase 2 M2 (frontend foundation — types, API client, shadcn components)

**Spec Reference:** `cast-clone-backend/docs/12-PHASE-4A-FRONTEND-DESIGN-GITCONNECTOR-REPO-ONBOARDING.MD` — Section 2

---

## File Structure

```
cast-clone-frontend/
├── app/
│   ├── layout.tsx                              # MODIFY — wrap children with GlobalShell
│   ├── page.tsx                                # MODIFY — home dashboard (recent activity)
│   ├── repositories/
│   │   ├── page.tsx                            # CREATE — repository list (placeholder)
│   │   └── [repoId]/
│   │       ├── page.tsx                        # CREATE — repo detail (placeholder)
│   │       └── [...branch]/
│   │           ├── layout.tsx                  # CREATE — project layout (context panel = project nav)
│   │           ├── page.tsx                    # CREATE — project overview (placeholder)
│   │           └── graph/
│   │               └── page.tsx                # CREATE — graph page (reuses existing GraphView)
│   ├── connectors/
│   │   └── page.tsx                            # CREATE — connector list (placeholder)
│   ├── settings/
│   │   ├── page.tsx                            # CREATE — redirect to /settings/system
│   │   └── system/
│   │       └── page.tsx                        # CREATE — system settings (placeholder)
│   └── projects/
│       └── [id]/
│           ├── layout.tsx                      # KEEP — legacy project layout (unchanged)
│           ├── page.tsx                        # KEEP — legacy dashboard (unchanged)
│           └── graph/
│               └── page.tsx                    # KEEP — legacy graph (unchanged)
├── components/
│   ├── layout/
│   │   ├── GlobalShell.tsx                     # CREATE — orchestrates IconRail + ContextPanel + TopBar
│   │   ├── IconRail.tsx                        # CREATE — 48px permanent sidebar with icons
│   │   ├── ContextPanel.tsx                    # CREATE — 240px collapsible panel, route-aware
│   │   ├── TopBar.tsx                          # CREATE — breadcrumbs + search trigger + theme toggle
│   │   ├── ProjectContextNav.tsx               # CREATE — project-level nav items (used inside ContextPanel)
│   │   ├── AppLayout.tsx                       # KEEP — deprecated, used by legacy /projects/[id]
│   │   └── Sidebar.tsx                         # KEEP — deprecated, used by legacy /projects/[id]
```

---

## Task 1: Create IconRail Component

**Files:**
- Create: `cast-clone-frontend/components/layout/IconRail.tsx`

- [ ] **Step 1: Create IconRail.tsx**

```tsx
// cast-clone-frontend/components/layout/IconRail.tsx
"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FolderGit2,
  GitBranch,
  LayoutDashboard,
  Settings,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
  matchPrefix: string;
}

const topItems: NavItem[] = [
  {
    label: "Home",
    href: "/",
    icon: LayoutDashboard,
    matchPrefix: "/__exact__",
  },
  {
    label: "Repositories",
    href: "/repositories",
    icon: FolderGit2,
    matchPrefix: "/repositories",
  },
  {
    label: "Connectors",
    href: "/connectors",
    icon: GitBranch,
    matchPrefix: "/connectors",
  },
  {
    label: "Settings",
    href: "/settings",
    icon: Settings,
    matchPrefix: "/settings",
  },
];

export function IconRail() {
  const pathname = usePathname();

  function isActive(item: NavItem): boolean {
    if (item.matchPrefix === "/__exact__") {
      return pathname === "/";
    }
    return pathname.startsWith(item.matchPrefix);
  }

  return (
    <TooltipProvider delayDuration={0}>
      <nav
        className="flex h-full w-12 shrink-0 flex-col items-center gap-1 border-r bg-sidebar py-2"
        aria-label="Global navigation"
      >
        {topItems.map((item) => (
          <Tooltip key={item.href}>
            <TooltipTrigger asChild>
              <Link
                href={item.href}
                className={cn(
                  "flex size-9 items-center justify-center rounded-md transition-colors",
                  isActive(item)
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                )}
                aria-label={item.label}
              >
                <item.icon className="size-5" />
              </Link>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={8}>
              {item.label}
            </TooltipContent>
          </Tooltip>
        ))}
      </nav>
    </TooltipProvider>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors related to IconRail.tsx

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add components/layout/IconRail.tsx
git commit -m "feat(nav-shell): add IconRail component with global nav icons"
```

---

## Task 2: Create ProjectContextNav Component

**Files:**
- Create: `cast-clone-frontend/components/layout/ProjectContextNav.tsx`

- [ ] **Step 1: Create ProjectContextNav.tsx**

This component renders project-level navigation items inside the ContextPanel when the user is inside a `/repositories/[repoId]/[...branch]` route.

```tsx
// cast-clone-frontend/components/layout/ProjectContextNav.tsx
"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  BookmarkPlus,
  FolderOpen,
  GitGraph,
  LayoutDashboard,
  MessageSquare,
  Route,
  Search,
  Settings,
  Zap,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface ProjectContextNavProps {
  repoId: string;
  branch: string;
}

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
}

export function ProjectContextNav({
  repoId,
  branch,
}: ProjectContextNavProps) {
  const pathname = usePathname();
  const basePath = `/repositories/${repoId}/${encodeURIComponent(branch)}`;

  const navItems: NavItem[] = [
    { label: "Overview", href: basePath, icon: LayoutDashboard },
    { label: "Architecture", href: `${basePath}/graph`, icon: GitGraph },
    {
      label: "Dependencies",
      href: `${basePath}/dependencies`,
      icon: FolderOpen,
    },
    { label: "Transactions", href: `${basePath}/transactions`, icon: Route },
    { label: "Search", href: `${basePath}/search`, icon: Search },
    { label: "Impact", href: `${basePath}/impact`, icon: Zap },
    { label: "Saved Views", href: `${basePath}/views`, icon: BookmarkPlus },
    {
      label: "AI Assistant",
      href: `${basePath}/chat`,
      icon: MessageSquare,
    },
    {
      label: "Project Settings",
      href: `${basePath}/settings`,
      icon: Settings,
    },
  ];

  return (
    <ScrollArea className="h-full">
      <div className="flex flex-col gap-1 p-2">
        {/* Back to repository */}
        <Link
          href={`/repositories/${repoId}`}
          className="mb-2 flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
        >
          <ArrowLeft className="size-3.5" />
          <span>Back to repository</span>
        </Link>

        {/* Branch label */}
        <div className="mb-1 px-2 text-xs font-medium text-sidebar-foreground/50">
          {decodeURIComponent(branch)}
        </div>

        {navItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== basePath && pathname.startsWith(item.href));

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
              )}
            >
              <item.icon className="size-4 shrink-0" />
              <span className="truncate">{item.label}</span>
            </Link>
          );
        })}
      </div>
    </ScrollArea>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add components/layout/ProjectContextNav.tsx
git commit -m "feat(nav-shell): add ProjectContextNav for project-level sidebar"
```

---

## Task 3: Create ContextPanel Component

**Files:**
- Create: `cast-clone-frontend/components/layout/ContextPanel.tsx`

- [ ] **Step 1: Create ContextPanel.tsx**

The ContextPanel renders different content based on the current route:
- Inside `/repositories/[repoId]/[...branch]/*` → ProjectContextNav
- Inside `/repositories` → repository list summary (placeholder)
- Inside `/connectors` → connector list summary (placeholder)
- Inside `/settings` → settings nav (placeholder)
- Home `/` → recent activity (placeholder)

```tsx
// cast-clone-frontend/components/layout/ContextPanel.tsx
"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  FolderGit2,
  GitBranch,
  LayoutDashboard,
  Settings,
  Monitor,
  Bot,
  Users,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ProjectContextNav } from "./ProjectContextNav";
import { cn } from "@/lib/utils";

/**
 * Parse the pathname to extract repoId and branch for project context.
 * Pattern: /repositories/[repoId]/[...branch]/...
 */
function parseProjectRoute(pathname: string): {
  repoId: string;
  branch: string;
} | null {
  const match = pathname.match(
    /^\/repositories\/([^/]+)\/([^/]+(?:\/[^/]+)*?)(?:\/graph|\/dependencies|\/transactions|\/search|\/impact|\/views|\/chat|\/settings)?$/,
  );
  if (!match) return null;
  return { repoId: match[1], branch: match[2] };
}

interface SectionNavItem {
  label: string;
  href: string;
  icon: React.ElementType;
}

function SectionNav({
  title,
  items,
  pathname,
}: {
  title: string;
  items: SectionNavItem[];
  pathname: string;
}) {
  return (
    <ScrollArea className="h-full">
      <div className="flex flex-col gap-1 p-2">
        <div className="mb-1 px-2 text-xs font-medium text-sidebar-foreground/50">
          {title}
        </div>
        {items.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
              )}
            >
              <item.icon className="size-4 shrink-0" />
              <span className="truncate">{item.label}</span>
            </Link>
          );
        })}
      </div>
    </ScrollArea>
  );
}

export function ContextPanel() {
  const pathname = usePathname();

  // Project context: /repositories/[repoId]/[branch]/*
  const projectCtx = parseProjectRoute(pathname);
  if (projectCtx) {
    return (
      <ProjectContextNav
        repoId={projectCtx.repoId}
        branch={projectCtx.branch}
      />
    );
  }

  // Settings section
  if (pathname.startsWith("/settings")) {
    return (
      <SectionNav
        title="Settings"
        pathname={pathname}
        items={[
          { label: "System", href: "/settings/system", icon: Monitor },
          { label: "AI Configuration", href: "/settings/ai", icon: Bot },
          { label: "Team", href: "/settings/team", icon: Users },
        ]}
      />
    );
  }

  // Connectors section
  if (pathname.startsWith("/connectors")) {
    return (
      <SectionNav
        title="Git Connectors"
        pathname={pathname}
        items={[
          { label: "All Connectors", href: "/connectors", icon: GitBranch },
        ]}
      />
    );
  }

  // Repositories section
  if (pathname.startsWith("/repositories")) {
    return (
      <SectionNav
        title="Repositories"
        pathname={pathname}
        items={[
          { label: "All Repositories", href: "/repositories", icon: FolderGit2 },
        ]}
      />
    );
  }

  // Home — default
  return (
    <SectionNav
      title="Home"
      pathname={pathname}
      items={[
        { label: "Dashboard", href: "/", icon: LayoutDashboard },
        { label: "Repositories", href: "/repositories", icon: FolderGit2 },
        { label: "Connectors", href: "/connectors", icon: GitBranch },
      ]}
    />
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add components/layout/ContextPanel.tsx
git commit -m "feat(nav-shell): add route-aware ContextPanel component"
```

---

## Task 4: Create TopBar Component

**Files:**
- Create: `cast-clone-frontend/components/layout/TopBar.tsx`

- [ ] **Step 1: Create TopBar.tsx**

```tsx
// cast-clone-frontend/components/layout/TopBar.tsx
"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Moon, Network, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";

/**
 * Build breadcrumbs from the current pathname.
 * Examples:
 *   / → [Home]
 *   /repositories → [Home, Repositories]
 *   /repositories/abc123/main/graph → [Home, Repositories, abc123, main, Architecture]
 */
function buildBreadcrumbs(pathname: string): { label: string; href: string }[] {
  const crumbs: { label: string; href: string }[] = [
    { label: "Home", href: "/" },
  ];

  if (pathname === "/") return crumbs;

  const segments = pathname.split("/").filter(Boolean);
  let currentPath = "";

  for (const segment of segments) {
    currentPath += `/${segment}`;
    const decoded = decodeURIComponent(segment);
    // Prettify known segments
    const label =
      decoded === "graph"
        ? "Architecture"
        : decoded === "repositories"
          ? "Repositories"
          : decoded === "connectors"
            ? "Connectors"
            : decoded === "settings"
              ? "Settings"
              : decoded === "system"
                ? "System"
                : decoded;
    crumbs.push({ label, href: currentPath });
  }

  return crumbs;
}

export function TopBar() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const crumbs = buildBreadcrumbs(pathname);

  return (
    <header className="flex h-11 shrink-0 items-center gap-2 border-b bg-background px-3">
      {/* Logo */}
      <Link
        href="/"
        className="flex items-center gap-1.5 text-sm font-semibold"
      >
        <Network className="size-4 text-primary" />
        <span>CodeLens</span>
      </Link>

      {/* Breadcrumbs */}
      <nav className="flex items-center gap-1 text-sm" aria-label="Breadcrumb">
        {crumbs.slice(1).map((crumb, i) => (
          <React.Fragment key={crumb.href}>
            <span className="text-muted-foreground">/</span>
            {i === crumbs.length - 2 ? (
              <span className="truncate text-muted-foreground">
                {crumb.label}
              </span>
            ) : (
              <Link
                href={crumb.href}
                className="truncate text-muted-foreground hover:text-foreground"
              >
                {crumb.label}
              </Link>
            )}
          </React.Fragment>
        ))}
      </nav>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Theme toggle */}
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        aria-label="Toggle theme"
      >
        <Sun className="size-4 dark:hidden" />
        <Moon className="hidden size-4 dark:block" />
      </Button>
    </header>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add components/layout/TopBar.tsx
git commit -m "feat(nav-shell): add TopBar with breadcrumbs and theme toggle"
```

---

## Task 5: Create GlobalShell Component

**Files:**
- Create: `cast-clone-frontend/components/layout/GlobalShell.tsx`

- [ ] **Step 1: Create GlobalShell.tsx**

GlobalShell orchestrates the three sub-components: TopBar, IconRail, ContextPanel.

```tsx
// cast-clone-frontend/components/layout/GlobalShell.tsx
"use client";

import * as React from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { IconRail } from "./IconRail";
import { ContextPanel } from "./ContextPanel";
import { TopBar } from "./TopBar";
import { cn } from "@/lib/utils";

interface GlobalShellProps {
  children: React.ReactNode;
}

export function GlobalShell({ children }: GlobalShellProps) {
  const [panelOpen, setPanelOpen] = React.useState(true);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Top bar */}
      <TopBar />

      {/* Body: IconRail + ContextPanel + Main */}
      <div className="flex flex-1 overflow-hidden">
        {/* Icon rail — always visible */}
        <IconRail />

        {/* Context panel — collapsible */}
        <aside
          className={cn(
            "relative shrink-0 border-r bg-sidebar transition-[width] duration-200",
            panelOpen ? "w-60" : "w-0 overflow-hidden border-r-0",
          )}
        >
          {/* Collapse/expand toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-1 top-1 z-10 size-6"
            onClick={() => setPanelOpen((prev) => !prev)}
            aria-label={panelOpen ? "Collapse panel" : "Expand panel"}
          >
            {panelOpen ? (
              <PanelLeftClose className="size-3.5" />
            ) : (
              <PanelLeftOpen className="size-3.5" />
            )}
          </Button>

          <ContextPanel />
        </aside>

        {/* Show expand button when panel is collapsed */}
        {!panelOpen && (
          <Button
            variant="ghost"
            size="icon"
            className="my-1 size-6 shrink-0"
            onClick={() => setPanelOpen(true)}
            aria-label="Expand panel"
          >
            <PanelLeftOpen className="size-3.5" />
          </Button>
        )}

        {/* Main content */}
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
cd cast-clone-frontend
git add components/layout/GlobalShell.tsx
git commit -m "feat(nav-shell): add GlobalShell orchestrating IconRail + ContextPanel + TopBar"
```

---

## Task 6: Integrate GlobalShell into Root Layout

**Files:**
- Modify: `cast-clone-frontend/app/layout.tsx`

- [ ] **Step 1: Wrap children with GlobalShell**

Modify `app/layout.tsx` to import and wrap `{children}` with `<GlobalShell>`:

```tsx
// cast-clone-frontend/app/layout.tsx
import { Geist_Mono, Inter } from "next/font/google";

import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { GlobalShell } from "@/components/layout/GlobalShell";
import { cn } from "@/lib/utils";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

const fontMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={cn(
        "antialiased",
        fontMono.variable,
        "font-sans",
        inter.variable,
      )}
    >
      <body>
        <ThemeProvider>
          <GlobalShell>{children}</GlobalShell>
        </ThemeProvider>
      </body>
    </html>
  );
}
```

- [ ] **Step 2: Update home page to remove old AppLayout wrapper**

Read `cast-clone-frontend/app/page.tsx`. If it wraps content in `<AppLayout>`, remove that wrapper since GlobalShell now provides the shell. The page should render only its content (the main area).

- [ ] **Step 3: Verify the dev server starts**

Run: `cd cast-clone-frontend && npm run dev`
Expected: App starts, home page renders with IconRail on the left, ContextPanel, and TopBar.

- [ ] **Step 4: Commit**

```bash
cd cast-clone-frontend
git add app/layout.tsx app/page.tsx
git commit -m "feat(nav-shell): integrate GlobalShell into root layout"
```

---

## Task 7: Create Placeholder Route Pages

**Files:**
- Create: `cast-clone-frontend/app/repositories/page.tsx`
- Create: `cast-clone-frontend/app/connectors/page.tsx`
- Create: `cast-clone-frontend/app/settings/page.tsx`
- Create: `cast-clone-frontend/app/settings/system/page.tsx`

- [ ] **Step 1: Create repositories page**

```tsx
// cast-clone-frontend/app/repositories/page.tsx
export default function RepositoriesPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">Repositories</h1>
      <p className="mt-2 text-muted-foreground">
        Your analyzed repositories will appear here. Add a Git connector to get
        started.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Create connectors page**

```tsx
// cast-clone-frontend/app/connectors/page.tsx
export default function ConnectorsPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">Git Connectors</h1>
      <p className="mt-2 text-muted-foreground">
        Connect to GitHub, GitLab, Gitea, or Bitbucket to browse and analyze
        repositories.
      </p>
    </div>
  );
}
```

- [ ] **Step 3: Create settings redirect page**

```tsx
// cast-clone-frontend/app/settings/page.tsx
import { redirect } from "next/navigation";

export default function SettingsPage() {
  redirect("/settings/system");
}
```

- [ ] **Step 4: Create system settings page**

```tsx
// cast-clone-frontend/app/settings/system/page.tsx
export default function SystemSettingsPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">System Settings</h1>
      <p className="mt-2 text-muted-foreground">
        System configuration will be available here.
      </p>
    </div>
  );
}
```

- [ ] **Step 5: Verify navigation works**

Run: `cd cast-clone-frontend && npm run dev`
Navigate to `/repositories`, `/connectors`, `/settings`. Each should render its placeholder and highlight the correct icon in the IconRail.

- [ ] **Step 6: Commit**

```bash
cd cast-clone-frontend
git add app/repositories/page.tsx app/connectors/page.tsx app/settings/page.tsx app/settings/system/page.tsx
git commit -m "feat(nav-shell): add placeholder pages for repositories, connectors, settings"
```

---

## Task 8: Create Branch Route Layout and Graph Page

**Files:**
- Create: `cast-clone-frontend/app/repositories/[repoId]/page.tsx`
- Create: `cast-clone-frontend/app/repositories/[repoId]/[...branch]/layout.tsx`
- Create: `cast-clone-frontend/app/repositories/[repoId]/[...branch]/page.tsx`
- Create: `cast-clone-frontend/app/repositories/[repoId]/[...branch]/graph/page.tsx`

- [ ] **Step 1: Create repo detail page**

```tsx
// cast-clone-frontend/app/repositories/[repoId]/page.tsx
export default async function RepoDetailPage({
  params,
}: {
  params: Promise<{ repoId: string }>;
}) {
  const { repoId } = await params;
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">Repository: {repoId}</h1>
      <p className="mt-2 text-muted-foreground">
        Branches and analysis history will appear here.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Create branch layout**

This layout doesn't add any extra UI — it just passes children through. The ContextPanel already detects the route and shows project nav.

```tsx
// cast-clone-frontend/app/repositories/[repoId]/[...branch]/layout.tsx
export default function BranchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
```

- [ ] **Step 3: Create branch overview page**

```tsx
// cast-clone-frontend/app/repositories/[repoId]/[...branch]/page.tsx
export default async function BranchOverviewPage({
  params,
}: {
  params: Promise<{ repoId: string; branch: string[] }>;
}) {
  const { repoId, branch } = await params;
  const branchName = branch.join("/");
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">
        {decodeURIComponent(branchName)}
      </h1>
      <p className="mt-1 text-muted-foreground">
        Project overview for repository {repoId}, branch{" "}
        {decodeURIComponent(branchName)}.
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Create graph page under branch route**

This page will eventually reuse the existing GraphView component. For now, a placeholder that confirms the routing works.

```tsx
// cast-clone-frontend/app/repositories/[repoId]/[...branch]/graph/page.tsx
export default async function BranchGraphPage({
  params,
}: {
  params: Promise<{ repoId: string; branch: string[] }>;
}) {
  const { repoId, branch } = await params;
  const branchName = branch.join("/");
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">Architecture Graph</h1>
      <p className="mt-1 text-muted-foreground">
        Graph explorer for {repoId} / {decodeURIComponent(branchName)}.
      </p>
    </div>
  );
}
```

- [ ] **Step 5: Verify routing**

Run: `cd cast-clone-frontend && npm run dev`
Navigate to `/repositories/test-repo/main/graph`. The ContextPanel should show project-level nav with "Architecture" highlighted.

- [ ] **Step 6: Commit**

```bash
cd cast-clone-frontend
git add app/repositories/
git commit -m "feat(nav-shell): add repository/branch route structure with catch-all branch"
```

---

## Task 9: Verify Legacy Routes Still Work

**Files:**
- Modify: `cast-clone-frontend/app/projects/[id]/layout.tsx` (if needed)

- [ ] **Step 1: Check that /projects/[id] still renders**

The existing `/projects/[id]` pages use `AppLayout` + `Sidebar`. Since we wrapped the root layout in `GlobalShell`, legacy pages will now have BOTH GlobalShell and AppLayout. We need to ensure the legacy layout doesn't double-render the nav.

Read `cast-clone-frontend/app/projects/[id]/layout.tsx`. If it wraps children in `<AppLayout>`, remove the AppLayout wrapper since GlobalShell now provides the shell. The legacy Sidebar can be rendered inside the ContextPanel or kept as-is if the project pages are still functional.

**Decision:** For backward compatibility, remove `AppLayout` from the legacy project layout and let GlobalShell handle the outer shell. The legacy sidebar items (Dashboard, Architecture, Dependencies, Transactions, Search) are already present in the old `Sidebar` component. Since the legacy routes use `/projects/[id]` (not `/repositories/...`), the ContextPanel won't show ProjectContextNav — so we should render the legacy `Sidebar` as the content area's own sidebar if needed, OR just let the pages render without a sidebar for now.

- [ ] **Step 2: Test legacy route**

Run: `cd cast-clone-frontend && npm run dev`
Navigate to `/projects/some-id`. Verify the page renders without errors.

- [ ] **Step 3: Commit if changes were needed**

```bash
cd cast-clone-frontend
git add app/projects/
git commit -m "fix(nav-shell): ensure legacy /projects routes work with GlobalShell"
```

---

## Task 10: Run Full TypeScript Check + Lint

- [ ] **Step 1: TypeScript check**

Run: `cd cast-clone-frontend && npx tsc --noEmit --pretty`
Expected: No errors

- [ ] **Step 2: Lint**

Run: `cd cast-clone-frontend && npm run lint`
Expected: No errors

- [ ] **Step 3: Fix any issues and commit**

```bash
cd cast-clone-frontend
git add -A
git commit -m "fix(nav-shell): address lint/typecheck issues"
```

---

## Verification Checklist

After all tasks are complete, confirm:

- [ ] `components/layout/GlobalShell.tsx` exists and exports `GlobalShell`
- [ ] `components/layout/IconRail.tsx` exists with 4 nav items (Home, Repositories, Connectors, Settings)
- [ ] `components/layout/ContextPanel.tsx` exists and switches content by route
- [ ] `components/layout/TopBar.tsx` exists with breadcrumbs and theme toggle
- [ ] `components/layout/ProjectContextNav.tsx` exists with 9 project-level nav items
- [ ] `app/layout.tsx` wraps children in `<GlobalShell>`
- [ ] `/repositories`, `/connectors`, `/settings` placeholder pages render
- [ ] `/repositories/[repoId]/[...branch]/graph` route renders with project nav in ContextPanel
- [ ] Legacy `/projects/[id]` routes still work
- [ ] `npx tsc --noEmit` passes
- [ ] `npm run lint` passes
