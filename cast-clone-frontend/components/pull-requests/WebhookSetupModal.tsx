"use client";

import { useState } from "react";
import { Copy, Check, ExternalLink, Zap, X } from "lucide-react";
import { autoRegisterWebhook, type EnableWebhooksResponse } from "@/lib/api";

interface Props {
  data: EnableWebhooksResponse;
  repoId: string;
  onClose: () => void;
}

const PLATFORM_LABELS: Record<string, string> = {
  github: "GitHub",
  gitlab: "GitLab",
  bitbucket: "Bitbucket",
  gitea: "Gitea",
};

export function WebhookSetupModal({ data, repoId, onClose }: Props) {
  const [copied, setCopied] = useState<string | null>(null);
  const [autoRegState, setAutoRegState] = useState<
    "idle" | "loading" | "success" | "error"
  >(data.auto_registered ? "success" : "idle");
  const [autoRegError, setAutoRegError] = useState<string | null>(
    data.auto_register_error,
  );

  function copyToClipboard(text: string, label: string) {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 2000);
  }

  async function handleAutoRegister() {
    setAutoRegState("loading");
    setAutoRegError(null);
    try {
      const result = await autoRegisterWebhook(repoId);
      if (result.success) {
        setAutoRegState("success");
      } else {
        setAutoRegState("error");
        setAutoRegError(
          result.error || "Auto-registration failed. Please set up manually.",
        );
      }
    } catch (err) {
      setAutoRegState("error");
      setAutoRegError(
        err instanceof Error ? err.message : "Auto-registration failed",
      );
    }
  }

  const platform = data.platform;
  const label = PLATFORM_LABELS[platform] || platform;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b dark:border-gray-800">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Set Up {label} Webhook
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <X className="size-5 text-gray-400" />
          </button>
        </div>

        <div className="p-5 space-y-6">
          {/* Auto-register option */}
          {autoRegState === "success" ? (
            <div className="rounded-lg bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 p-4">
              <p className="text-sm font-medium text-green-800 dark:text-green-200">
                Webhook auto-registered successfully!
              </p>
              <p className="text-sm text-green-600 dark:text-green-400 mt-1">
                The webhook has been configured on {label}. No manual setup needed — PRs will be analyzed automatically.
              </p>
            </div>
          ) : (
            <div className="rounded-lg bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
                    Quick setup
                  </p>
                  <p className="text-sm text-blue-600 dark:text-blue-400 mt-1">
                    If your token has webhook admin permissions, we can register the webhook automatically.
                  </p>
                  {autoRegState === "error" && autoRegError && (
                    <p className="text-xs text-red-600 mt-2">
                      {autoRegError}
                    </p>
                  )}
                </div>
                <button
                  onClick={handleAutoRegister}
                  disabled={autoRegState === "loading"}
                  className="shrink-0 px-3 py-1.5 text-sm font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5"
                >
                  <Zap className="size-3.5" />
                  {autoRegState === "loading"
                    ? "Registering..."
                    : autoRegState === "error"
                      ? "Retry"
                      : "Auto-register"}
                </button>
              </div>
            </div>
          )}

          {/* Manual setup - always visible */}
          {autoRegState !== "success" && (
            <>
              <div>
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">
                  Or set up manually
                </h3>
                <p className="text-xs text-gray-500">
                  Copy the values below and follow the steps for {label}.
                </p>
              </div>

              {/* Webhook URL + Secret */}
              <div className="space-y-3">
                <CopyField
                  label="Payload URL"
                  value={data.webhook_url}
                  copied={copied}
                  onCopy={copyToClipboard}
                />
                <CopyField
                  label="Secret"
                  value={data.webhook_secret}
                  copied={copied}
                  onCopy={copyToClipboard}
                />
              </div>

              {/* Platform-specific instructions */}
              <PlatformGuide platform={platform} />
            </>
          )}

          {/* Monitoring info */}
          <div className="text-xs text-gray-500 border-t dark:border-gray-800 pt-4">
            <strong>Monitoring:</strong>{" "}
            {data.monitored_branches
              ? data.monitored_branches.join(", ")
              : "All branches"}
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end p-5 border-t dark:border-gray-800">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-md hover:bg-gray-800 dark:hover:bg-gray-200"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

function PlatformGuide({ platform }: { platform: string }) {
  const guides: Record<string, React.ReactNode> = {
    github: <GitHubGuide />,
    gitlab: <GitLabGuide />,
    bitbucket: <BitbucketGuide />,
    gitea: <GiteaGuide />,
  };
  return guides[platform] || <GenericGuide />;
}

function StepList({ children }: { children: React.ReactNode }) {
  return (
    <ol className="space-y-2 text-sm text-gray-700 dark:text-gray-300 list-none">
      {children}
    </ol>
  );
}

function Step({
  n,
  children,
}: {
  n: number;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-2.5">
      <span className="shrink-0 size-5 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-xs font-medium text-gray-600 dark:text-gray-400">
        {n}
      </span>
      <span>{children}</span>
    </li>
  );
}

function GitHubGuide() {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
          GitHub Setup Steps
        </h4>
        <a
          href="https://docs.github.com/en/webhooks/using-webhooks/creating-webhooks"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-0.5"
        >
          Docs <ExternalLink className="size-3" />
        </a>
      </div>
      <StepList>
        <Step n={1}>
          Go to your repository on GitHub and click{" "}
          <strong>Settings</strong> (top tab)
        </Step>
        <Step n={2}>
          In the left sidebar, click <strong>Webhooks</strong>, then{" "}
          <strong>Add webhook</strong>
        </Step>
        <Step n={3}>
          Paste the <strong>Payload URL</strong> from above
        </Step>
        <Step n={4}>
          Set <strong>Content type</strong> to{" "}
          <code className="px-1 py-0.5 bg-gray-100 dark:bg-gray-800 rounded text-xs">
            application/json
          </code>
        </Step>
        <Step n={5}>
          Paste the <strong>Secret</strong> from above
        </Step>
        <Step n={6}>
          Under <em>&quot;Which events would you like to trigger this webhook?&quot;</em>,
          select <strong>&quot;Let me select individual events&quot;</strong> and
          check only <strong>Pull requests</strong>
        </Step>
        <Step n={7}>
          Ensure <strong>Active</strong> is checked, then click{" "}
          <strong>Add webhook</strong>
        </Step>
      </StepList>
      <p className="text-xs text-gray-500">
        GitHub will send a ping event to verify connectivity. You can check delivery
        status under Settings &rarr; Webhooks &rarr; Recent Deliveries.
      </p>
    </div>
  );
}

function GitLabGuide() {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
          GitLab Setup Steps
        </h4>
        <a
          href="https://docs.gitlab.com/user/project/integrations/webhooks/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-0.5"
        >
          Docs <ExternalLink className="size-3" />
        </a>
      </div>
      <StepList>
        <Step n={1}>
          Go to your project on GitLab and click{" "}
          <strong>Settings</strong> in the left sidebar
        </Step>
        <Step n={2}>
          Click <strong>Webhooks</strong>, then{" "}
          <strong>Add new webhook</strong>
        </Step>
        <Step n={3}>
          Paste the <strong>Payload URL</strong> into the <strong>URL</strong> field
        </Step>
        <Step n={4}>
          Paste the <strong>Secret</strong> into the{" "}
          <strong>Secret token</strong> field
        </Step>
        <Step n={5}>
          Under <strong>Trigger</strong>, check only{" "}
          <strong>Merge request events</strong>
        </Step>
        <Step n={6}>
          Leave <strong>Enable SSL verification</strong> checked, then
          click <strong>Add webhook</strong>
        </Step>
      </StepList>
      <p className="text-xs text-gray-500">
        You need Maintainer or Owner role. Use the <strong>Test</strong> dropdown to send a test event after saving.
      </p>
    </div>
  );
}

function BitbucketGuide() {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
          Bitbucket Setup Steps
        </h4>
        <a
          href="https://support.atlassian.com/bitbucket-cloud/docs/manage-webhooks/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-0.5"
        >
          Docs <ExternalLink className="size-3" />
        </a>
      </div>
      <StepList>
        <Step n={1}>
          Go to your repository and click{" "}
          <strong>Repository settings</strong> in the left sidebar
        </Step>
        <Step n={2}>
          Under <strong>Workflow</strong>, click <strong>Webhooks</strong>,
          then <strong>Add webhook</strong>
        </Step>
        <Step n={3}>
          Enter a <strong>Title</strong> (e.g., &quot;ChangeSafe PR Analysis&quot;)
        </Step>
        <Step n={4}>
          Paste the <strong>Payload URL</strong> into the <strong>URL</strong> field
        </Step>
        <Step n={5}>
          Paste the <strong>Secret</strong> into the{" "}
          <strong>Secret</strong> field
        </Step>
        <Step n={6}>
          Select <strong>&quot;Choose from a full list of triggers&quot;</strong>
          and check <strong>Pull Request: Created</strong> and{" "}
          <strong>Pull Request: Updated</strong>
        </Step>
        <Step n={7}>
          Click <strong>Save</strong>
        </Step>
      </StepList>
      <p className="text-xs text-gray-500">
        You need admin permissions on the repository. There is no test button — create a
        test PR to verify delivery.
      </p>
    </div>
  );
}

function GiteaGuide() {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
          Gitea Setup Steps
        </h4>
        <a
          href="https://docs.gitea.com/usage/webhooks"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-0.5"
        >
          Docs <ExternalLink className="size-3" />
        </a>
      </div>
      <StepList>
        <Step n={1}>
          Go to your repository and click <strong>Settings</strong> (top tab)
        </Step>
        <Step n={2}>
          Click <strong>Webhooks</strong>, then <strong>Add Webhook</strong>{" "}
          &rarr; <strong>Gitea</strong>
        </Step>
        <Step n={3}>
          Paste the <strong>Payload URL</strong> into{" "}
          <strong>Target URL</strong>
        </Step>
        <Step n={4}>
          Set <strong>Content Type</strong> to{" "}
          <code className="px-1 py-0.5 bg-gray-100 dark:bg-gray-800 rounded text-xs">
            application/json
          </code>
        </Step>
        <Step n={5}>
          Paste the <strong>Secret</strong> into the{" "}
          <strong>Secret</strong> field
        </Step>
        <Step n={6}>
          Select <strong>&quot;Custom Events...&quot;</strong> and check only{" "}
          <strong>Pull Request</strong>
        </Step>
        <Step n={7}>
          Ensure <strong>Active</strong> is checked, then click{" "}
          <strong>Add Webhook</strong>
        </Step>
      </StepList>
      <p className="text-xs text-gray-500">
        Use the <strong>Test Delivery</strong> button after saving to verify
        connectivity.
      </p>
    </div>
  );
}

function GenericGuide() {
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
        Manual Setup
      </h4>
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Configure a webhook in your Git platform&apos;s settings with the Payload URL
        and Secret above. Set the content type to{" "}
        <code className="px-1 py-0.5 bg-gray-100 dark:bg-gray-800 rounded text-xs">
          application/json
        </code>{" "}
        and trigger on <strong>Pull Request</strong> events only.
      </p>
    </div>
  );
}

function CopyField({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string;
  value: string;
  copied: string | null;
  onCopy: (text: string, label: string) => void;
}) {
  const isCopied = copied === label;
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400">
        {label}
      </label>
      <div className="flex items-center gap-2 mt-0.5">
        <code className="flex-1 text-xs bg-gray-50 dark:bg-gray-800 border dark:border-gray-700 rounded px-2.5 py-2 break-all select-all font-mono">
          {value}
        </code>
        <button
          onClick={() => onCopy(value, label)}
          className="shrink-0 p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-800 border dark:border-gray-700"
          title={`Copy ${label}`}
        >
          {isCopied ? (
            <Check className="size-3.5 text-green-600" />
          ) : (
            <Copy className="size-3.5 text-gray-400" />
          )}
        </button>
      </div>
    </div>
  );
}
