"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { getEmailConfig, updateEmailConfig, testSendEmail } from "@/lib/api";
import type { EmailConfigResponse } from "@/lib/types";
import { AlertTriangle } from "lucide-react";

// ── Helpers ──

const DAYS_OF_WEEK = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const INPUT_CLS = "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";
const SELECT_CLS = `${INPUT_CLS} max-w-xs`;
const BTN_PRIMARY = "rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors";

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="relative inline-flex cursor-pointer items-center">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
      <div className="h-6 w-11 rounded-full bg-muted peer-checked:bg-primary peer-focus-visible:ring-2 peer-focus-visible:ring-ring after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all peer-checked:after:translate-x-full" />
    </label>
  );
}

// ── BCC Disclosure Modal ──

function BccDisclosureModal({ open, onConfirm, onCancel }: { open: boolean; onConfirm: () => void; onCancel: () => void }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative z-10 w-full max-w-md rounded-lg border bg-background p-6 shadow-lg">
        <h3 className="text-lg font-semibold">Enable Flentas BCC</h3>
        <p className="mt-3 text-sm text-muted-foreground leading-relaxed">
          Enabling this sends a copy of each outbound report to Flentas at{" "}
          <span className="font-medium text-foreground">usage-reports@flentas.com</span>.
          The same report contents (tier, LOC usage, expiry, per-project breakdown) are
          included — no source code or analysis output.
        </p>
        <div className="mt-6 flex items-center justify-end gap-3">
          <button onClick={onCancel} className="rounded-md border px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors">Cancel</button>
          <button onClick={onConfirm} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">I understand</button>
        </div>
      </div>
    </div>
  );
}

// ── Page header (shared across states) ──

function PageHeader() {
  return (
    <div>
      <h1 className="text-2xl font-bold">Email Configuration</h1>
      <p className="mt-1 text-sm text-muted-foreground">Configure outbound email for usage reports.</p>
    </div>
  );
}

// ── Main Page ──

export default function EmailSettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [config, setConfig] = useState<EmailConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [newRecipient, setNewRecipient] = useState("");
  const [recipientError, setRecipientError] = useState("");
  const [showBccModal, setShowBccModal] = useState(false);
  const [testEmail, setTestEmail] = useState("");
  const [testSending, setTestSending] = useState(false);
  const [testResult, setTestResult] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setConfig(await getEmailConfig());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load email config");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadConfig(); }, [loadConfig]);

  function updateField<K extends keyof EmailConfigResponse>(key: K, value: EmailConfigResponse[K]) {
    if (!config) return;
    setConfig({ ...config, [key]: value });
  }

  function addRecipient() {
    if (!config) return;
    const email = newRecipient.trim();
    if (!email) return;
    if (!isValidEmail(email)) { setRecipientError("Invalid email address"); return; }
    if (config.recipients.includes(email)) { setRecipientError("Already in list"); return; }
    setConfig({ ...config, recipients: [...config.recipients, email] });
    setNewRecipient("");
    setRecipientError("");
  }

  function removeRecipient(email: string) {
    if (!config) return;
    setConfig({ ...config, recipients: config.recipients.filter((r) => r !== email) });
  }

  function handleBccToggle() {
    if (!config) return;
    if (!config.flentas_bcc_enabled) { setShowBccModal(true); } else { updateField("flentas_bcc_enabled", false); }
  }

  async function handleSave() {
    if (!config) return;
    setSaving(true);
    setSaveMessage(null);
    try {
      const updated = await updateEmailConfig({ ...config });
      setConfig(updated);
      setSaveMessage({ type: "success", text: "Configuration saved." });
    } catch (err: unknown) {
      setSaveMessage({ type: "error", text: err instanceof Error ? err.message : "Failed to save configuration" });
    } finally {
      setSaving(false);
    }
  }

  async function handleTestSend() {
    const email = testEmail.trim();
    if (!email || !isValidEmail(email)) { setTestResult({ type: "error", text: "Enter a valid email address" }); return; }
    setTestSending(true);
    setTestResult(null);
    try {
      const result = await testSendEmail(email);
      setTestResult(result.status === "ok"
        ? { type: "success", text: "Test email sent successfully." }
        : { type: "error", text: result.error ?? "Test send failed" });
    } catch (err: unknown) {
      setTestResult({ type: "error", text: err instanceof Error ? err.message : "Test send failed" });
    } finally {
      setTestSending(false);
    }
  }

  // ── Guards ──

  if (!isAdmin) {
    return (
      <div className="space-y-6 p-6">
        <PageHeader />
        <div className="flex items-center gap-2 rounded-md bg-muted p-4 text-sm text-muted-foreground">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>Admin access required to manage email settings.</span>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6 p-6">
        <PageHeader />
        <div className="py-12 text-center text-muted-foreground">Loading email configuration...</div>
      </div>
    );
  }

  if (error || !config) {
    return (
      <div className="space-y-6 p-6">
        <PageHeader />
        <div className="rounded-md bg-destructive/10 p-4 text-sm text-destructive">
          {error || "Failed to load email configuration."}
        </div>
      </div>
    );
  }

  // ── Render ──

  return (
    <div className="space-y-6 p-6">
      <PageHeader />

      {/* Master Toggle */}
      <section className="space-y-3 rounded-lg border p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Outbound Email</h2>
            <p className="text-sm text-muted-foreground">Enable or disable all outbound email from this instance.</p>
          </div>
          <Toggle checked={config.enabled} onChange={(v) => updateField("enabled", v)} />
        </div>
      </section>

      {/* SMTP Configuration */}
      <section className="space-y-4 rounded-lg border p-4">
        <h2 className="text-lg font-semibold">SMTP Configuration</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">SMTP Host</label>
            <input type="text" value={config.smtp_host} onChange={(e) => updateField("smtp_host", e.target.value)} placeholder="smtp.example.com" className={INPUT_CLS} />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">SMTP Port</label>
            <input type="number" value={config.smtp_port} onChange={(e) => updateField("smtp_port", parseInt(e.target.value, 10) || 0)} placeholder="587" className={INPUT_CLS} />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">Username</label>
            <input type="text" value={config.smtp_username} onChange={(e) => updateField("smtp_username", e.target.value)} placeholder="user@example.com" className={INPUT_CLS} />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">Password</label>
            <input type="password" value={config.smtp_password} onChange={(e) => updateField("smtp_password", e.target.value)} placeholder={config.smtp_password === "***" ? "***" : "Enter password"} className={INPUT_CLS} />
            {config.smtp_password === "***" && (
              <p className="text-xs text-muted-foreground">Password is stored. Clear and re-enter to change.</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Toggle checked={config.smtp_use_tls} onChange={(v) => updateField("smtp_use_tls", v)} />
          <span className="text-sm font-medium text-muted-foreground">Use TLS</span>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">From Address</label>
            <input type="email" value={config.from_address} onChange={(e) => updateField("from_address", e.target.value)} placeholder="noreply@example.com" className={INPUT_CLS} />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">From Name</label>
            <input type="text" value={config.from_name} onChange={(e) => updateField("from_name", e.target.value)} placeholder="ChangeSafe" className={INPUT_CLS} />
          </div>
        </div>
      </section>

      {/* Recipients */}
      <section className="space-y-4 rounded-lg border p-4">
        <h2 className="text-lg font-semibold">Recipients</h2>
        <p className="text-sm text-muted-foreground">Email addresses that will receive outbound reports.</p>
        {config.recipients.length > 0 && (
          <div className="space-y-2">
            {config.recipients.map((email) => (
              <div key={email} className="flex items-center justify-between rounded-md border px-3 py-2">
                <span className="text-sm">{email}</span>
                <button onClick={() => removeRecipient(email)} className="text-sm text-muted-foreground hover:text-destructive transition-colors">Remove</button>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-start gap-2">
          <div className="flex-1 space-y-1">
            <input
              type="email"
              value={newRecipient}
              onChange={(e) => { setNewRecipient(e.target.value); setRecipientError(""); }}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addRecipient(); } }}
              placeholder="email@example.com"
              className={INPUT_CLS}
            />
            {recipientError && <p className="text-xs text-destructive">{recipientError}</p>}
          </div>
          <button onClick={addRecipient} className={`h-9 ${BTN_PRIMARY}`}>Add</button>
        </div>
      </section>

      {/* Flentas BCC */}
      <section className="space-y-3 rounded-lg border p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Flentas BCC</h2>
            <p className="text-sm text-muted-foreground">Send a copy of each outbound report to Flentas.</p>
          </div>
          <Toggle checked={config.flentas_bcc_enabled} onChange={handleBccToggle} />
        </div>
      </section>

      <BccDisclosureModal open={showBccModal} onConfirm={() => { updateField("flentas_bcc_enabled", true); setShowBccModal(false); }} onCancel={() => setShowBccModal(false)} />

      {/* Report Cadence */}
      <section className="space-y-4 rounded-lg border p-4">
        <h2 className="text-lg font-semibold">Report Cadence</h2>
        <p className="text-sm text-muted-foreground">How often usage reports are sent.</p>
        <div className="flex items-center gap-6">
          {(["off", "weekly", "monthly"] as const).map((value) => (
            <label key={value} className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="cadence" value={value} checked={config.cadence === value} onChange={() => updateField("cadence", value)} className="h-4 w-4 accent-primary" />
              <span className="text-sm font-medium capitalize">{value}</span>
            </label>
          ))}
        </div>
        {config.cadence === "weekly" && (
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">Day of Week</label>
            <select value={config.cadence_day} onChange={(e) => updateField("cadence_day", parseInt(e.target.value, 10))} className={SELECT_CLS}>
              {DAYS_OF_WEEK.map((day, i) => <option key={i} value={i}>{day}</option>)}
            </select>
          </div>
        )}
        {config.cadence === "monthly" && (
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">Day of Month</label>
            <select value={config.cadence_day} onChange={(e) => updateField("cadence_day", parseInt(e.target.value, 10))} className={SELECT_CLS}>
              {Array.from({ length: 28 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}</option>)}
            </select>
          </div>
        )}
        {config.cadence !== "off" && (
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">Hour (UTC)</label>
            <select value={config.cadence_hour_utc} onChange={(e) => updateField("cadence_hour_utc", parseInt(e.target.value, 10))} className={SELECT_CLS}>
              {Array.from({ length: 24 }, (_, i) => <option key={i} value={i}>{String(i).padStart(2, "0")}:00 UTC</option>)}
            </select>
          </div>
        )}
      </section>

      {/* Save */}
      <div className="flex items-center gap-4">
        <button onClick={handleSave} disabled={saving} className={`px-6 py-2 disabled:opacity-50 ${BTN_PRIMARY}`}>
          {saving ? "Saving..." : "Save"}
        </button>
        {saveMessage && (
          <span className={`text-sm ${saveMessage.type === "success" ? "text-emerald-600" : "text-destructive"}`}>{saveMessage.text}</span>
        )}
      </div>

      {/* Test Send */}
      <section className="space-y-4 rounded-lg border p-4">
        <h2 className="text-lg font-semibold">Test Send</h2>
        <p className="text-sm text-muted-foreground">Send a test email to verify SMTP settings. Save your configuration first.</p>
        <div className="flex items-start gap-2">
          <div className="flex-1">
            <input type="email" value={testEmail} onChange={(e) => { setTestEmail(e.target.value); setTestResult(null); }} placeholder="test@example.com" className={INPUT_CLS} />
          </div>
          <button onClick={handleTestSend} disabled={testSending} className="h-9 rounded-md border px-4 text-sm font-medium hover:bg-muted disabled:opacity-50 transition-colors">
            {testSending ? "Sending..." : "Send Test"}
          </button>
        </div>
        {testResult && (
          <div className={`rounded-md p-3 text-sm ${testResult.type === "success" ? "bg-emerald-500/10 text-emerald-600" : "bg-destructive/10 text-destructive"}`}>
            {testResult.text}
          </div>
        )}
      </section>
    </div>
  );
}
