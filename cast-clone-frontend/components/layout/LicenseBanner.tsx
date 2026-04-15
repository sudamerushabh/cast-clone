"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, Info, ShieldX, X } from "lucide-react";
import { getLicenseStatus } from "@/lib/api";
import type { LicenseState } from "@/lib/types";

const POLL_INTERVAL_MS = 300_000; // 5 minutes

interface BannerConfig {
  icon: React.ElementType;
  message: string;
  bg: string;
  text: string;
}

const BANNER_CONFIG: Record<string, BannerConfig> = {
  UNLICENSED: {
    icon: Info,
    message: "No license installed. Go to Settings to activate.",
    bg: "bg-blue-500/10",
    text: "text-blue-700 dark:text-blue-400",
  },
  LICENSED_WARN: {
    icon: AlertTriangle,
    message: "License nearing limits. Review your license status.",
    bg: "bg-yellow-500/10",
    text: "text-yellow-700 dark:text-yellow-400",
  },
  LICENSED_GRACE: {
    icon: AlertTriangle,
    message: "License expired. You have a 14-day grace period remaining.",
    bg: "bg-orange-500/10",
    text: "text-orange-700 dark:text-orange-400",
  },
  LICENSED_BLOCKED: {
    icon: ShieldX,
    message: "License expired or limits exceeded. Write operations are blocked.",
    bg: "bg-red-500/10",
    text: "text-red-700 dark:text-red-400",
  },
};

const VISIBLE_STATES: LicenseState[] = [
  "UNLICENSED",
  "LICENSED_WARN",
  "LICENSED_GRACE",
  "LICENSED_BLOCKED",
];

function isDismissed(state: LicenseState): boolean {
  if (typeof window === "undefined") return false;
  return sessionStorage.getItem(`license-banner-dismissed-${state}`) === "1";
}

function dismiss(state: LicenseState): void {
  sessionStorage.setItem(`license-banner-dismissed-${state}`, "1");
}

export function LicenseBanner() {
  const [state, setState] = React.useState<LicenseState | null>(null);
  const [licenseDisabled, setLicenseDisabled] = React.useState(false);
  const [dismissed, setDismissed] = React.useState(false);

  const fetchStatus = React.useCallback(async () => {
    try {
      const status = await getLicenseStatus();
      setLicenseDisabled(status.license_disabled);
      setState(status.state);
      setDismissed(isDismissed(status.state));
    } catch {
      // Silently ignore — banner is non-critical
    }
  }, []);

  React.useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  if (!state || licenseDisabled || dismissed) return null;
  if (!VISIBLE_STATES.includes(state)) return null;

  const config = BANNER_CONFIG[state];
  if (!config) return null;

  const Icon = config.icon;

  return (
    <div
      className={`flex items-center justify-center gap-2 px-4 py-1.5 text-sm ${config.bg} ${config.text}`}
      role="alert"
    >
      <Icon className="size-4 shrink-0" />
      <span>{config.message}</span>
      <Link
        href="/settings/license"
        className="ml-1 underline underline-offset-2 hover:opacity-80"
      >
        Manage License
      </Link>
      <button
        type="button"
        className="ml-auto shrink-0 rounded p-0.5 hover:opacity-70"
        aria-label="Dismiss banner"
        onClick={() => {
          dismiss(state);
          setDismissed(true);
        }}
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}
