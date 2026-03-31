"use client";

import { useCallback, useEffect, useState } from "react";
import { Webhook, Trash2, Settings2 } from "lucide-react";
import {
  enableWebhooks,
  disableWebhooks,
  fetchGitConfig,
  updateGitConfig,
  type EnableWebhooksResponse,
} from "@/lib/api";
import type { GitConfig } from "@/lib/types";
import { WebhookSetupModal } from "./WebhookSetupModal";

interface Props {
  repoId: string;
  defaultBranch: string;
}

type State =
  | { kind: "loading" }
  | { kind: "not-configured" }
  | { kind: "configured"; config: GitConfig };

export function WebhookSetup({ repoId, defaultBranch }: Props) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [monitorAll, setMonitorAll] = useState(true);
  const [branches, setBranches] = useState(defaultBranch);
  const [postPrComments, setPostPrComments] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalData, setModalData] = useState<EnableWebhooksResponse | null>(null);

  const load = useCallback(async () => {
    const config = await fetchGitConfig(repoId);
    if (config) {
      setState({ kind: "configured", config });
    } else {
      setState({ kind: "not-configured" });
    }
  }, [repoId]);

  useEffect(() => { load(); }, [load]);

  async function handleEnable() {
    setEnabling(true);
    setError(null);
    try {
      const monitoredBranches = monitorAll
        ? undefined
        : branches.split(",").map((b) => b.trim()).filter(Boolean);

      const data = await enableWebhooks(repoId, {
        monitorAll,
        monitoredBranches,
        postPrComments,
      });
      setModalData(data);
      // Reload config in background so UI updates after modal closes
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to enable webhooks");
    } finally {
      setEnabling(false);
    }
  }

  async function handleDisable() {
    if (!confirm("Disable PR analysis webhooks? Existing analyses will be preserved.")) return;
    await disableWebhooks(repoId);
    setState({ kind: "not-configured" });
  }

  function handleModalClose() {
    setModalData(null);
    load();
  }

  if (state.kind === "loading") return null;

  return (
    <>
      {/* Modal */}
      {modalData && (
        <WebhookSetupModal
          data={modalData}
          repoId={repoId}
          onClose={handleModalClose}
        />
      )}

      {/* Not configured — show enable CTA */}
      {state.kind === "not-configured" && (
        <div className="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 p-5 mb-4">
          <div className="flex items-start gap-3">
            <Webhook className="size-5 text-gray-400 mt-0.5 shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                Enable PR Analysis
              </p>
              <p className="text-sm text-gray-500 mt-1">
                Automatically analyze pull requests for architecture impact, risk, and test gaps.
              </p>

              {/* Branch monitoring toggle */}
              <div className="mt-3 space-y-2">
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="radio"
                      name="branchMode"
                      checked={monitorAll}
                      onChange={() => setMonitorAll(true)}
                      className="accent-blue-600"
                    />
                    All branches
                  </label>
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="radio"
                      name="branchMode"
                      checked={!monitorAll}
                      onChange={() => setMonitorAll(false)}
                      className="accent-blue-600"
                    />
                    Specific branches
                  </label>
                </div>

                {!monitorAll && (
                  <div className="max-w-sm">
                    <input
                      type="text"
                      value={branches}
                      onChange={(e) => setBranches(e.target.value)}
                      placeholder="main, master, develop"
                      className="w-full border rounded-md px-3 py-1.5 text-sm bg-white dark:bg-gray-900"
                    />
                    <p className="text-xs text-gray-400 mt-1">
                      Comma-separated. Only PRs targeting these branches are analyzed.
                    </p>
                  </div>
                )}
              </div>

              {/* PR comment toggle */}
              <div className="mt-3">
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={postPrComments}
                    onChange={(e) => setPostPrComments(e.target.checked)}
                    className="accent-blue-600"
                  />
                  Post analysis comment on PR
                </label>
                <p className="text-xs text-gray-400 mt-1 ml-5">
                  Automatically post architecture impact summary as a comment on each analyzed PR.
                </p>
              </div>

              <div className="mt-3">
                <button
                  onClick={handleEnable}
                  disabled={enabling}
                  className="px-4 py-1.5 text-sm font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
                >
                  {enabling ? "Enabling..." : "Enable"}
                </button>
              </div>
              {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
            </div>
          </div>
        </div>
      )}

      {/* Already configured — compact status bar */}
      {state.kind === "configured" && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-4 mb-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm">
              <Webhook className="size-4 text-green-600" />
              <span className="font-medium text-gray-700 dark:text-gray-300">
                PR Analysis Active
              </span>
              <span className="text-gray-400">|</span>
              <span className="text-gray-500">
                {state.config.platform}
              </span>
              <span className="text-gray-400">|</span>
              <span className="text-gray-500">
                {state.config.monitored_branches
                  ? `Branches: ${state.config.monitored_branches.join(", ")}`
                  : "All branches"}
              </span>
              <span className="text-gray-400">|</span>
              <label className="flex items-center gap-1.5 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={state.config.post_pr_comments}
                  onChange={async (e) => {
                    const newVal = e.target.checked;
                    try {
                      const updated = await updateGitConfig(repoId, { post_pr_comments: newVal });
                      setState({ kind: "configured", config: { ...state.config, post_pr_comments: updated.post_pr_comments } });
                    } catch {
                      // revert on failure
                    }
                  }}
                  className="accent-blue-600"
                />
                <span className="text-gray-500">PR comments</span>
              </label>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={async () => {
                  // Re-show setup modal with existing config data
                  const { fetchWebhookUrl } = await import("@/lib/api");
                  try {
                    const info = await fetchWebhookUrl(repoId);
                    setModalData({
                      webhook_url: info.webhook_url,
                      webhook_secret: info.webhook_secret,
                      platform: state.config.platform,
                      monitored_branches: state.config.monitored_branches,
                      is_active: state.config.is_active,
                      post_pr_comments: state.config.post_pr_comments,
                      auto_registered: false,
                      auto_register_error: null,
                    });
                  } catch {
                    // ignore
                  }
                }}
                className="text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400 flex items-center gap-1"
              >
                <Settings2 className="size-3" /> Setup guide
              </button>
              <button
                onClick={handleDisable}
                className="text-xs text-red-500 hover:text-red-700 flex items-center gap-1"
              >
                <Trash2 className="size-3" /> Disable
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
