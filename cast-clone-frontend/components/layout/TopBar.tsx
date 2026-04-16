"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Moon, Network, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { UserMenu } from "./UserMenu";

/**
 * Build breadcrumbs from the current pathname.
 * Examples:
 *   / -> [Home]
 *   /repositories -> [Home, Repositories]
 *   /repositories/abc123/main/graph -> [Home, Repositories, abc123, main, Architecture]
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
        <span>ChangeSafe</span>
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

      <UserMenu />

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
