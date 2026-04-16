"use client";

import * as React from "react";
import { Check, Eye, EyeOff, Loader2, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { ProviderLogo, providerMeta } from "@/components/connectors/ProviderLogo";
import { createConnector } from "@/lib/api";
import type { ConnectorProvider } from "@/lib/types";

const providers: {
  value: ConnectorProvider;
  defaultUrl: string;
  description: string;
  tokenHint: string;
}[] = [
  {
    value: "github",
    defaultUrl: "https://github.com",
    description: "GitHub.com or GitHub Enterprise",
    tokenHint: "ghp_xxxxxxxxxxxx",
  },
  {
    value: "gitlab",
    defaultUrl: "https://gitlab.com",
    description: "GitLab.com or self-managed",
    tokenHint: "glpat-xxxxxxxxxxxx",
  },
  {
    value: "gitea",
    defaultUrl: "",
    description: "Self-hosted Gitea instance",
    tokenHint: "your-access-token",
  },
  {
    value: "bitbucket",
    defaultUrl: "https://bitbucket.org",
    description: "Bitbucket Cloud or Data Center",
    tokenHint: "app-password or token",
  },
];

interface AddConnectorFormProps {
  onSuccess: () => void;
  onCancel: () => void;
}

export function AddConnectorForm({ onSuccess, onCancel }: AddConnectorFormProps) {
  const [selectedProvider, setSelectedProvider] =
    React.useState<ConnectorProvider | null>(null);
  const [name, setName] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState("");
  const [token, setToken] = React.useState("");
  const [showToken, setShowToken] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  const selectedMeta = selectedProvider
    ? providerMeta[selectedProvider]
    : null;
  const selectedConfig = selectedProvider
    ? providers.find((p) => p.value === selectedProvider)
    : null;

  function handleProviderSelect(p: ConnectorProvider) {
    setSelectedProvider(p);
    const provider = providers.find((x) => x.value === p);
    if (provider?.defaultUrl) {
      setBaseUrl(provider.defaultUrl);
    } else {
      setBaseUrl("");
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
      onSuccess();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create connector"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      {/* ── Step 1: Provider selection ── */}
      <div>
        <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Step 1
        </div>
        <h3 className="mb-3 text-xs font-semibold">Choose a Git provider</h3>

        <div className="grid grid-cols-2 gap-2.5">
          {providers.map((p) => {
            const meta = providerMeta[p.value];
            const isSelected = selectedProvider === p.value;
            return (
              <button
                key={p.value}
                type="button"
                onClick={() => handleProviderSelect(p.value)}
                className={`group relative flex items-center gap-2.5 rounded-lg border p-3 text-left transition-all ${
                  isSelected
                    ? "border-foreground/20 ring-2 ring-foreground/10"
                    : "border-border hover:border-foreground/15 hover:bg-accent/50"
                }`}
              >
                {isSelected && (
                  <div className="absolute -right-1.5 -top-1.5 flex size-4 items-center justify-center rounded-full bg-foreground">
                    <Check className="size-2.5 text-background" />
                  </div>
                )}
                <div
                  className="flex size-8 shrink-0 items-center justify-center rounded-md"
                  style={{ backgroundColor: `${meta.color}10` }}
                >
                  <ProviderLogo
                    provider={p.value}
                    size={18}
                    className="dark:invert-0"
                    style={{ filter: "none" }}
                  />
                </div>
                <div className="min-w-0">
                  <div className="text-xs font-medium">{meta.label}</div>
                  <div className="truncate text-[10px] leading-tight text-muted-foreground">
                    {p.description}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Step 2: Configuration form ── */}
      {selectedProvider && selectedMeta && selectedConfig && (
        <>
          <Separator />

          <div>
            <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Step 2
            </div>
            <h3 className="mb-3 text-xs font-semibold">
              Configure {selectedMeta.label} connection
            </h3>

            <form onSubmit={handleSubmit} className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="conn-name" className="text-xs">
                  Connection Name
                </Label>
                <Input
                  id="conn-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={`My ${selectedMeta.label}`}
                  required
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="conn-url" className="text-xs">
                  Base URL
                </Label>
                <Input
                  id="conn-url"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://..."
                  required
                />
                {selectedConfig.defaultUrl && (
                  <p className="text-[10px] text-muted-foreground">
                    Default: {selectedConfig.defaultUrl} — change for
                    self-hosted
                  </p>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="conn-token" className="text-xs">
                  Personal Access Token
                </Label>
                <div className="relative">
                  <Input
                    id="conn-token"
                    type={showToken ? "text" : "password"}
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder={selectedConfig.tokenHint}
                    className="pr-8"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowToken(!showToken)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    tabIndex={-1}
                  >
                    {showToken ? (
                      <EyeOff className="size-3.5" />
                    ) : (
                      <Eye className="size-3.5" />
                    )}
                  </button>
                </div>
                <div className="flex items-start gap-1.5 text-[10px] text-muted-foreground">
                  <Shield className="mt-px size-3 shrink-0" />
                  <span>
                    Stored encrypted. Used only for repository access.
                  </span>
                </div>
              </div>

              {error && (
                <div className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  {error}
                </div>
              )}

              <Separator />

              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={onCancel}
                >
                  Cancel
                </Button>
                <Button type="submit" size="sm" disabled={loading}>
                  {loading ? (
                    <>
                      <Loader2 className="mr-1 size-3 animate-spin" />
                      Testing...
                    </>
                  ) : (
                    "Test & Save"
                  )}
                </Button>
              </div>
            </form>
          </div>
        </>
      )}
    </div>
  );
}
