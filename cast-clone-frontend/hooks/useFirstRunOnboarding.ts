"use client";

import { useCallback, useEffect, useState } from "react";
import { listConnectors, listRepositories } from "@/lib/api";

interface UseFirstRunOnboardingArgs {
  userId: string | null;
  enabled: boolean;
}

interface UseFirstRunOnboardingReturn {
  /** True only when counts are loaded, user is present, both counts are zero, and dismiss is not set. */
  shouldShow: boolean;
  isLoading: boolean;
  dismiss: () => void;
}

const STORAGE_PREFIX = "changesafe:onboarding-dismissed:";

function dismissKey(userId: string): string {
  return `${STORAGE_PREFIX}${userId}`;
}

function readDismissed(userId: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(dismissKey(userId)) === "1";
  } catch {
    return false;
  }
}

interface CountsState {
  loaded: boolean;
  connectorCount: number | null;
  repoCount: number | null;
}

const INITIAL_COUNTS: CountsState = {
  loaded: false,
  connectorCount: null,
  repoCount: null,
};

/**
 * Determines whether the first-run onboarding modal should appear for the
 * current user. Counts both connectors and repositories and reads a
 * per-user dismiss flag from localStorage. Keyed by user id so switching
 * accounts does not leak dismiss state across users.
 */
export function useFirstRunOnboarding({
  userId,
  enabled,
}: UseFirstRunOnboardingArgs): UseFirstRunOnboardingReturn {
  const [counts, setCounts] = useState<CountsState>(INITIAL_COUNTS);
  const [lastUserId, setLastUserId] = useState<string | null>(userId);
  const [dismissOverride, setDismissOverride] = useState<boolean>(false);

  // Reset counts synchronously during render when the active user changes,
  // per the "resetting state when a prop changes" pattern. This avoids a
  // setState-in-effect and prevents stale counts from leaking across users.
  if (lastUserId !== userId) {
    setLastUserId(userId);
    setCounts(INITIAL_COUNTS);
    setDismissOverride(false);
  }

  // Derive dismissed directly from storage via userId — avoids a setState
  // in an effect just to mirror localStorage. dismissOverride handles
  // in-session dismiss clicks without needing a reload.
  const persistedDismissed = userId ? readDismissed(userId) : false;
  const dismissed = persistedDismissed || dismissOverride;

  useEffect(() => {
    if (!enabled || !userId) return;
    if (persistedDismissed) return;

    let cancelled = false;

    async function load() {
      const [connectorsResult, reposResult] = await Promise.allSettled([
        listConnectors(),
        listRepositories(),
      ]);
      if (cancelled) return;
      setCounts({
        loaded: true,
        connectorCount:
          connectorsResult.status === "fulfilled"
            ? connectorsResult.value.total
            : null,
        repoCount:
          reposResult.status === "fulfilled" ? reposResult.value.total : null,
      });
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [enabled, userId, persistedDismissed]);

  const dismiss = useCallback(() => {
    if (!userId) return;
    try {
      window.localStorage.setItem(dismissKey(userId), "1");
    } catch {
      // Ignore quota / privacy-mode failures; in-session override below
      // still closes the dialog.
    }
    setDismissOverride(true);
  }, [userId]);

  const isLoading = enabled && !!userId && !dismissed && !counts.loaded;

  const shouldShow =
    enabled &&
    !!userId &&
    !dismissed &&
    counts.loaded &&
    counts.connectorCount === 0 &&
    counts.repoCount === 0;

  return { shouldShow, isLoading, dismiss };
}
