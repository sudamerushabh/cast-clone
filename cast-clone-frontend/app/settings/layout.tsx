"use client";

import * as React from "react";
import { SettingsSidebar } from "@/components/settings/SettingsSidebar";

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full min-h-0 flex-1">
      <aside
        className="hidden w-56 shrink-0 border-r bg-sidebar md:block"
        aria-label="Settings sidebar"
      >
        <SettingsSidebar />
      </aside>
      <div className="min-w-0 flex-1 overflow-auto">{children}</div>
    </div>
  );
}
