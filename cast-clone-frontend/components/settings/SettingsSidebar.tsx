"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Bot,
  Key,
  Mail,
  Monitor,
  Shield,
  Users,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

interface SettingsNavItem {
  label: string;
  href: string;
  icon: React.ElementType;
  adminOnly?: boolean;
}

const NAV_ITEMS: SettingsNavItem[] = [
  { label: "System", href: "/settings/system", icon: Monitor },
  { label: "License", href: "/settings/license", icon: Shield },
  { label: "AI Configuration", href: "/settings/ai", icon: Bot },
  { label: "Team", href: "/settings/team", icon: Users, adminOnly: true },
  { label: "API Keys", href: "/settings/api-keys", icon: Key, adminOnly: true },
  { label: "Activity", href: "/settings/activity", icon: Activity },
  { label: "Email", href: "/settings/email", icon: Mail },
];

export function SettingsSidebar() {
  const pathname = usePathname();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const visibleItems = NAV_ITEMS.filter(
    (item) => !item.adminOnly || isAdmin,
  );

  return (
    <ScrollArea className="h-full">
      <nav
        aria-label="Settings navigation"
        className="flex flex-col gap-1 p-2"
      >
        <div className="mb-1 px-2 text-xs font-medium text-sidebar-foreground/50">
          Settings
        </div>
        {visibleItems.map((item) => {
          const isActive =
            pathname === item.href || pathname.startsWith(item.href + "/");

          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
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
      </nav>
    </ScrollArea>
  );
}
