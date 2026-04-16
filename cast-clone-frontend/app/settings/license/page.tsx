"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { getLicenseStatus, uploadLicense } from "@/lib/api";
import type { LicenseStatusResponse, LicenseState, RepoLocBreakdown } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Copy, Check, Upload, Shield, AlertTriangle } from "lucide-react";

// ── Helpers ──

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function formatNumber(n: number): string {
  return n.toLocaleString();
}

function stateLabel(state: LicenseState): string {
  switch (state) {
    case "UNLICENSED":
      return "Unlicensed";
    case "LICENSED_HEALTHY":
      return "Healthy";
    case "LICENSED_WARN":
      return "Warning";
    case "LICENSED_GRACE":
      return "Grace Period";
    case "LICENSED_BLOCKED":
      return "Blocked";
  }
}

function stateBadgeClass(state: LicenseState): string {
  switch (state) {
    case "LICENSED_HEALTHY":
      return "bg-emerald-500/10 text-emerald-600 border-emerald-500/20";
    case "LICENSED_WARN":
      return "bg-yellow-500/10 text-yellow-600 border-yellow-500/20";
    case "LICENSED_GRACE":
      return "bg-orange-500/10 text-orange-600 border-orange-500/20";
    case "LICENSED_BLOCKED":
      return "bg-red-500/10 text-red-600 border-red-500/20";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
}

// ── Copy Button ──

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [value]);

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleCopy}
      className="shrink-0"
    >
      {copied ? (
        <Check className="mr-1.5 h-3.5 w-3.5" />
      ) : (
        <Copy className="mr-1.5 h-3.5 w-3.5" />
      )}
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

// ── LOC Progress Bar ──

function LocProgressBar({
  used,
  limit,
}: {
  used: number;
  limit: number;
}) {
  const pct = Math.min((used / limit) * 100, 100);
  const barColor =
    pct >= 90 ? "bg-red-500" : pct >= 75 ? "bg-yellow-500" : "bg-emerald-500";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">Lines of Code</span>
        <span className="font-medium">
          {formatNumber(used)} / {formatNumber(limit)} ({pct.toFixed(1)}%)
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ── LOC Breakdown Table ──

function LocBreakdownTable({
  breakdown,
  totalUsed,
}: {
  breakdown: RepoLocBreakdown[];
  totalUsed: number;
}) {
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());

  if (breakdown.length === 0) return null;

  function toggleExpand(repoId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(repoId)) next.delete(repoId);
      else next.add(repoId);
      return next;
    });
  }

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium text-muted-foreground">
        LOC by Repository
      </h4>
      <div className="rounded-md border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="px-3 py-2 text-left font-medium">Repository</th>
              <th className="px-3 py-2 text-left font-medium">Max Branch</th>
              <th className="px-3 py-2 text-right font-medium">LOC</th>
              <th className="px-3 py-2 text-right font-medium">% of Total</th>
            </tr>
          </thead>
          <tbody>
            {breakdown.map((repo) => {
              const isExpanded = expanded.has(repo.repository_id);
              const pct =
                totalUsed > 0
                  ? ((repo.billable_loc / totalUsed) * 100).toFixed(1)
                  : "0.0";
              const branches = Object.entries(repo.branches).sort(
                ([, a], [, b]) => b - a
              );
              const hasMultipleBranches = branches.length > 1;

              return (
                <React.Fragment key={repo.repository_id}>
                  <tr
                    className={`border-b last:border-0 ${
                      hasMultipleBranches
                        ? "cursor-pointer hover:bg-muted/30"
                        : ""
                    }`}
                    onClick={() =>
                      hasMultipleBranches && toggleExpand(repo.repository_id)
                    }
                  >
                    <td className="px-3 py-2">
                      <span className="flex items-center gap-1">
                        {hasMultipleBranches && (
                          <span className="text-xs text-muted-foreground">
                            {isExpanded ? "▼" : "▶"}
                          </span>
                        )}
                        <span className="font-mono text-xs">
                          {repo.repo_full_name}
                        </span>
                      </span>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {repo.max_branch}
                    </td>
                    <td className="px-3 py-2 text-right font-medium tabular-nums">
                      {formatNumber(repo.billable_loc)}
                    </td>
                    <td className="px-3 py-2 text-right text-muted-foreground tabular-nums">
                      {pct}%
                    </td>
                  </tr>
                  {isExpanded &&
                    branches.map(([branch, loc]) => (
                      <tr
                        key={branch}
                        className="border-b last:border-0 bg-muted/20"
                      >
                        <td className="pl-8 pr-3 py-1.5 text-xs text-muted-foreground">
                          {branch}
                        </td>
                        <td className="px-3 py-1.5" />
                        <td className="px-3 py-1.5 text-right text-xs tabular-nums">
                          {formatNumber(loc)}
                          {branch === repo.max_branch && (
                            <span className="ml-1 text-emerald-600">← max</span>
                          )}
                        </td>
                        <td className="px-3 py-1.5" />
                      </tr>
                    ))}
                </React.Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t bg-muted/50 font-medium">
              <td className="px-3 py-2">Total</td>
              <td className="px-3 py-2" />
              <td className="px-3 py-2 text-right tabular-nums">
                {formatNumber(totalUsed)}
              </td>
              <td className="px-3 py-2" />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

// ── Upload Form ──

function UploadForm({
  onSuccess,
  isAdmin,
}: {
  onSuccess: () => void;
  isAdmin: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadSuccess, setUploadSuccess] = useState(false);

  const handleUpload = useCallback(async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadError("");
    setUploadSuccess(false);

    try {
      await uploadLicense(file);
      setUploadSuccess(true);
      if (fileRef.current) fileRef.current.value = "";
      onSuccess();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Upload failed";
      setUploadError(message);
    } finally {
      setUploading(false);
    }
  }, [onSuccess]);

  if (!isAdmin) {
    return (
      <div className="flex items-center gap-2 rounded-md bg-muted p-3 text-sm text-muted-foreground">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span>Only administrators can upload license files.</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <Label htmlFor="license-file">License File (.jwt)</Label>
      <div className="flex items-center gap-2">
        <Input
          id="license-file"
          ref={fileRef}
          type="file"
          accept=".jwt"
          className="flex-1"
        />
        <Button
          onClick={handleUpload}
          disabled={uploading}
        >
          <Upload className="mr-2 h-4 w-4" />
          {uploading ? "Uploading..." : "Upload"}
        </Button>
      </div>
      {uploadError && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {uploadError}
        </div>
      )}
      {uploadSuccess && (
        <div className="rounded-md bg-emerald-500/10 p-3 text-sm text-emerald-600">
          License uploaded successfully.
        </div>
      )}
    </div>
  );
}

// ── Detail Row ──

function DetailRow({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  if (!value) return null;
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-right">{value}</span>
    </div>
  );
}

// ── Main Page ──

export default function LicenseSettingsPage() {
  const { user } = useAuth();
  const [status, setStatus] = useState<LicenseStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getLicenseStatus();
      setStatus(data);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to load license status";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const isAdmin = user?.role === "admin";
  const isUnlicensed = status?.state === "UNLICENSED";
  const isLicensed = status && !isUnlicensed;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">License</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage your CodeLens license and view usage information.
        </p>
      </div>

      {loading && (
        <div className="py-12 text-center text-muted-foreground">
          Loading license status...
        </div>
      )}

      {error && !loading && (
        <div className="rounded-md bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {status && !loading && (
        <>
          {/* State Badge + Installation ID */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <Shield className="h-5 w-5" />
                  License Status
                </CardTitle>
                <Badge
                  variant="outline"
                  className={stateBadgeClass(status.state)}
                >
                  {stateLabel(status.state)}
                </Badge>
              </div>
              {status.license_disabled && (
                <CardDescription>
                  License enforcement is disabled on this instance.
                </CardDescription>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-muted-foreground">Installation ID</Label>
                <div className="flex items-center gap-2">
                  <code className="flex-1 rounded-md bg-muted px-3 py-2 text-sm font-mono select-all">
                    {status.installation_id}
                  </code>
                  <CopyButton value={status.installation_id} />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Unlicensed instructions */}
          {isUnlicensed && (
            <Card>
              <CardHeader>
                <CardTitle>Activate License</CardTitle>
                <CardDescription>
                  Contact your Flentas representative with the Installation ID
                  above to receive a license file.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <UploadForm onSuccess={loadStatus} isAdmin={isAdmin} />
              </CardContent>
            </Card>
          )}

          {/* Licensed details */}
          {isLicensed && (
            <>
              {/* Customer Info */}
              <Card>
                <CardHeader>
                  <CardTitle>Customer Information</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <DetailRow label="Name" value={status.customer_name} />
                  <DetailRow label="Email" value={status.customer_email} />
                  <DetailRow
                    label="Organization"
                    value={status.customer_organization}
                  />
                </CardContent>
              </Card>

              {/* License Details */}
              <Card>
                <CardHeader>
                  <CardTitle>License Details</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <DetailRow
                    label="Tier"
                    value={status.tier != null ? `Tier ${status.tier}` : null}
                  />
                  <DetailRow label="Issued By" value={status.issued_by} />
                  <DetailRow
                    label="Issued At"
                    value={
                      status.issued_at != null
                        ? formatDate(status.issued_at)
                        : null
                    }
                  />
                  <DetailRow
                    label="Expires At"
                    value={
                      status.expires_at != null
                        ? formatDate(status.expires_at)
                        : null
                    }
                  />
                  {status.notes && (
                    <>
                      <Separator />
                      <div className="space-y-1">
                        <span className="text-sm text-muted-foreground">
                          Notes
                        </span>
                        <p className="text-sm">{status.notes}</p>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>

              {/* LOC Usage */}
              {status.loc_limit != null && status.loc_used != null && (
                <Card>
                  <CardHeader>
                    <CardTitle>Usage</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <LocProgressBar
                      used={status.loc_used}
                      limit={status.loc_limit}
                    />
                    {status.loc_breakdown && status.loc_breakdown.length > 0 && (
                      <LocBreakdownTable
                        breakdown={status.loc_breakdown}
                        totalUsed={status.loc_used}
                      />
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Replace License */}
              <Card>
                <CardHeader>
                  <CardTitle>Replace License</CardTitle>
                  <CardDescription>
                    Upload a new license file to update your license.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <UploadForm onSuccess={loadStatus} isAdmin={isAdmin} />
                </CardContent>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
