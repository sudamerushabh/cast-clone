"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createConnector } from "@/lib/api";
import type { ConnectorProvider } from "@/lib/types";

const providers: { value: ConnectorProvider; label: string; defaultUrl: string }[] = [
  { value: "github", label: "GitHub", defaultUrl: "https://github.com" },
  { value: "gitlab", label: "GitLab", defaultUrl: "https://gitlab.com" },
  { value: "gitea", label: "Gitea", defaultUrl: "" },
  { value: "bitbucket", label: "Bitbucket", defaultUrl: "https://bitbucket.org" },
];

export function AddConnectorForm() {
  const router = useRouter();
  const [selectedProvider, setSelectedProvider] = React.useState<ConnectorProvider | null>(null);
  const [name, setName] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState("");
  const [token, setToken] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  function handleProviderSelect(p: ConnectorProvider) {
    setSelectedProvider(p);
    const provider = providers.find((x) => x.value === p);
    if (provider?.defaultUrl) {
      setBaseUrl(provider.defaultUrl);
    }
    setName("");
    setToken("");
    setError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedProvider) return;
    setLoading(true);
    setError(null);
    try {
      await createConnector({
        name,
        provider: selectedProvider,
        base_url: baseUrl,
        token,
      });
      router.push("/connectors");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create connector");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <div>
        <h2 className="mb-3 text-sm font-medium">Select Provider</h2>
        <div className="grid grid-cols-2 gap-3">
          {providers.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => handleProviderSelect(p.value)}
              className={`rounded-lg border p-3 text-left text-sm transition-colors ${
                selectedProvider === p.value
                  ? "border-primary bg-primary/5"
                  : "hover:border-muted-foreground/30"
              }`}
            >
              <span className="font-medium">{p.label}</span>
            </button>
          ))}
        </div>
      </div>

      {selectedProvider && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Configure Connection</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <Label htmlFor="conn-name">Connection Name</Label>
                <Input id="conn-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={`My ${providers.find((p) => p.value === selectedProvider)?.label}`} required />
              </div>
              <div>
                <Label htmlFor="conn-url">Base URL</Label>
                <Input id="conn-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://github.com" required />
              </div>
              <div>
                <Label htmlFor="conn-token">Personal Access Token</Label>
                <Input id="conn-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="ghp_xxxxxxxxxxxx" required />
              </div>
              {error && (
                <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>
              )}
              <div className="flex gap-2">
                <Button type="submit" disabled={loading}>
                  {loading ? "Testing & Saving..." : "Test & Save"}
                </Button>
                <Button type="button" variant="outline" onClick={() => router.push("/connectors")}>
                  Cancel
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
