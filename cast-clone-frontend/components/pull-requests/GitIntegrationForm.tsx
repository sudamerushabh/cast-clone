"use client";

import { useState } from "react";
import {
  createGitConfig,
  deleteGitConfig,
  testGitConnectivity,
  fetchWebhookUrl,
} from "@/lib/api";
import type { GitConfig, WebhookUrlInfo } from "@/lib/types";

interface Props {
  projectId: string;
  existing: GitConfig | null;
  onSaved: () => void;
}

export function GitIntegrationForm({ projectId, existing, onSaved }: Props) {
  const [platform, setPlatform] = useState(existing?.platform ?? "github");
  const [repoUrl, setRepoUrl] = useState(existing?.repo_url ?? "");
  const [apiToken, setApiToken] = useState("");
  const [branches, setBranches] = useState(
    existing?.monitored_branches?.join(", ") ?? "main, master, develop",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [webhookInfo, setWebhookInfo] = useState<WebhookUrlInfo | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const result = await createGitConfig(projectId, {
        platform,
        repo_url: repoUrl,
        api_token: apiToken,
        monitored_branches: branches
          .split(",")
          .map((b) => b.trim())
          .filter(Boolean),
      });
      setWebhookInfo({
        webhook_url: result.webhook_url,
        webhook_secret: result.webhook_secret,
      });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTestResult(null);
    try {
      const result = await testGitConnectivity(projectId);
      setTestResult(
        result.status === "ok"
          ? `Connected as ${result.username}`
          : `Error: ${result.message}`,
      );
    } catch {
      setTestResult("Connection test failed");
    }
  };

  const handleDelete = async () => {
    if (!confirm("Remove Git integration?")) return;
    await deleteGitConfig(projectId);
    onSaved();
  };

  if (existing && !webhookInfo) {
    return (
      <div className="bg-white border rounded-lg p-6">
        <h2 className="text-lg font-semibold mb-4">Git Integration</h2>
        <div className="space-y-2 text-sm">
          <p>
            <span className="font-medium">Platform:</span> {existing.platform}
          </p>
          <p>
            <span className="font-medium">Repository:</span>{" "}
            {existing.repo_url}
          </p>
          <p>
            <span className="font-medium">Monitored branches:</span>{" "}
            {existing.monitored_branches?.join(", ")}
          </p>
          <p>
            <span className="font-medium">Active:</span>{" "}
            {existing.is_active ? "Yes" : "No"}
          </p>
        </div>
        <div className="mt-4 flex gap-3">
          <button
            onClick={handleTest}
            className="px-3 py-1.5 text-sm bg-blue-100 text-blue-700 rounded-md"
          >
            Test Connection
          </button>
          <button
            onClick={async () => {
              const info = await fetchWebhookUrl(projectId);
              setWebhookInfo(info);
            }}
            className="px-3 py-1.5 text-sm bg-gray-100 rounded-md"
          >
            Show Webhook URL
          </button>
          <button
            onClick={handleDelete}
            className="px-3 py-1.5 text-sm text-red-600 hover:text-red-800"
          >
            Remove
          </button>
        </div>
        {testResult && (
          <p className="mt-2 text-sm text-gray-600">{testResult}</p>
        )}
      </div>
    );
  }

  return (
    <div className="bg-white border rounded-lg p-6">
      <h2 className="text-lg font-semibold mb-4">
        {webhookInfo ? "Webhook Configuration" : "Configure Git Integration"}
      </h2>

      {webhookInfo ? (
        <div className="space-y-4">
          <p className="text-sm text-green-600 font-medium">
            Git integration configured successfully!
          </p>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Webhook URL
            </label>
            <code className="block mt-1 p-2 bg-gray-100 rounded text-sm break-all">
              {webhookInfo.webhook_url}
            </code>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Webhook Secret
            </label>
            <code className="block mt-1 p-2 bg-gray-100 rounded text-sm break-all">
              {webhookInfo.webhook_secret}
            </code>
          </div>
          <p className="text-xs text-gray-500">
            Copy these values into your Git platform&apos;s webhook settings.
          </p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Platform
            </label>
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="mt-1 block w-full border rounded-md px-3 py-2"
            >
              <option value="github">GitHub</option>
              <option value="gitlab">GitLab</option>
              <option value="bitbucket">Bitbucket</option>
              <option value="gitea">Gitea</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Repository URL
            </label>
            <input
              type="url"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/org/repo"
              required
              className="mt-1 block w-full border rounded-md px-3 py-2"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              API Token
            </label>
            <input
              type="password"
              value={apiToken}
              onChange={(e) => setApiToken(e.target.value)}
              placeholder="ghp_... or personal access token"
              required
              className="mt-1 block w-full border rounded-md px-3 py-2"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Monitored Branches
            </label>
            <input
              type="text"
              value={branches}
              onChange={(e) => setBranches(e.target.value)}
              className="mt-1 block w-full border rounded-md px-3 py-2"
            />
            <p className="text-xs text-gray-500 mt-1">Comma-separated list</p>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Configure"}
          </button>
        </form>
      )}
    </div>
  );
}
