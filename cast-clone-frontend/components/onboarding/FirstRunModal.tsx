"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowRight,
  FolderGit2,
  GitBranch,
  Play,
  Sparkles,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth-context";
import { useFirstRunOnboarding } from "@/hooks/useFirstRunOnboarding";

// Auth / setup routes where the modal must never render.
const EXCLUDED_PATH_PREFIXES = ["/login", "/setup"];

interface OnboardingStep {
  id: string;
  title: string;
  description: string;
  href: string;
  cta: string;
  icon: React.ComponentType<{ className?: string }>;
}

const STEPS: ReadonlyArray<OnboardingStep> = [
  {
    id: "connector",
    title: "Add a Git connector",
    description:
      "Point ChangeSafe at GitHub, GitLab, or Bitbucket so we can discover repositories.",
    href: "/connectors/new",
    cta: "Add connector",
    icon: GitBranch,
  },
  {
    id: "repo",
    title: "Import a repository",
    description:
      "Pick a codebase to analyse — we clone it locally and prepare it for parsing.",
    href: "/repositories/new",
    cta: "Import repo",
    icon: FolderGit2,
  },
  {
    id: "analysis",
    title: "Run your first analysis",
    description:
      "Kick off the pipeline — tree-sitter + SCIP + framework plugins build the graph in Neo4j.",
    href: "/repositories",
    cta: "Go to repositories",
    icon: Play,
  },
];

/**
 * First-run onboarding dialog. Appears once per user (keyed by user id in
 * localStorage) when they have zero connectors AND zero repositories.
 * Dismissal is sticky — dismiss once, never see it again on that account.
 */
export function FirstRunModal() {
  const { user, isLoading: authLoading } = useAuth();
  const pathname = usePathname();

  const onExcludedRoute = EXCLUDED_PATH_PREFIXES.some((prefix) =>
    pathname?.startsWith(prefix),
  );

  const enabled = !authLoading && !!user && !onExcludedRoute;

  const { shouldShow, dismiss } = useFirstRunOnboarding({
    userId: user?.id ?? null,
    enabled,
  });

  if (!enabled || !shouldShow) return null;

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      // Any close path (overlay click, Esc, X, footer button) dismisses —
      // shouldShow flips false and the modal unmounts on the next render.
      dismiss();
    }
  };

  const handleDismiss = () => {
    dismiss();
  };

  const handleTryDemo = () => {
    // No demo-project flow exists yet. Send the operator down the standard
    // connector path — the natural first step anyway — and dismiss the modal.
    dismiss();
  };

  return (
    <Dialog open onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-base">
            Welcome to ChangeSafe
          </DialogTitle>
          <DialogDescription>
            Three quick steps to get your first architecture graph up and
            running.
          </DialogDescription>
        </DialogHeader>

        <ol className="flex flex-col gap-3">
          {STEPS.map((step, index) => {
            const Icon = step.icon;
            return (
              <li
                key={step.id}
                className="flex items-start gap-3 rounded-md border bg-card/50 p-3"
              >
                <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                  {index + 1}
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex items-center gap-1.5">
                    <Icon className="size-3.5 text-muted-foreground" />
                    <p className="text-xs font-medium text-foreground">
                      {step.title}
                    </p>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {step.description}
                  </p>
                  <Link
                    href={step.href}
                    onClick={() => dismiss()}
                    className="mt-1 inline-flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline"
                  >
                    {step.cta}
                    <ArrowRight className="size-3" />
                  </Link>
                </div>
              </li>
            );
          })}
        </ol>

        <DialogFooter className="sm:justify-between">
          <Button
            variant="outline"
            size="sm"
            onClick={handleTryDemo}
            className="gap-1.5"
          >
            <Sparkles className="size-3.5" />
            Try a demo project
          </Button>
          <Button variant="ghost" size="sm" onClick={handleDismiss}>
            Dismiss for now
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
