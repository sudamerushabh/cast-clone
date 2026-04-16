"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Cloud,
  DollarSign,
  Eye,
  EyeOff,
  Key,
  Loader2,
  MessageSquare,
  RefreshCw,
  Save,
  Search,
  Settings2,
  Shield,
  Sparkles,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth-context";
import {
  getAiConfig,
  getAiModels,
  testAiConnection,
  updateAiConfig,
} from "@/lib/api";
import type {
  AiConfigResponse,
  AiModelInfo,
  AiConfigUpdateRequest,
} from "@/lib/types";

// ── Constants ──

const AWS_REGIONS = [
  "us-east-1",
  "us-east-2",
  "us-west-2",
  "eu-west-1",
  "eu-west-2",
  "eu-west-3",
  "eu-central-1",
  "ap-southeast-1",
  "ap-southeast-2",
  "ap-northeast-1",
  "ap-northeast-2",
  "ap-south-1",
  "ca-central-1",
  "sa-east-1",
];

const INPUT_CLS =
  "flex h-8 w-full rounded-md border border-input bg-transparent px-3 py-1 text-xs shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50";
const SELECT_CLS = `${INPUT_CLS} appearance-none cursor-pointer`;

// ── Helpers ──

function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="relative inline-flex cursor-pointer items-center">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="peer sr-only"
        disabled={disabled}
      />
      <div className="h-5 w-9 rounded-full bg-muted peer-checked:bg-primary peer-focus-visible:ring-2 peer-focus-visible:ring-ring after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all peer-checked:after:translate-x-4" />
    </label>
  );
}

function SectionHeader({
  icon: Icon,
  title,
  description,
  badge,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description?: string;
  badge?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex items-start justify-between">
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 size-4 text-muted-foreground" />
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          {description && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {description}
            </p>
          )}
        </div>
      </div>
      {badge}
    </div>
  );
}

function FieldRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-6 py-2">
      <div className="min-w-0 shrink-0">
        <div className="text-xs font-medium">{label}</div>
        {description && (
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {description}
          </div>
        )}
      </div>
      <div className="flex-1 max-w-xs">{children}</div>
    </div>
  );
}

// ── Main Page ──

export default function AiSettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [config, setConfig] = useState<AiConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  // Form state
  const [provider, setProvider] = useState<"bedrock" | "openai">("bedrock");
  const [awsRegion, setAwsRegion] = useState("us-east-1");
  const [bedrockUseIamRole, setBedrockUseIamRole] = useState(true);
  const [awsAccessKeyId, setAwsAccessKeyId] = useState("");
  const [awsSecretAccessKey, setAwsSecretAccessKey] = useState("");
  const [showAwsSecret, setShowAwsSecret] = useState(false);
  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [showOpenaiKey, setShowOpenaiKey] = useState(false);
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState("");

  // Model assignments
  const [chatModel, setChatModel] = useState("");
  const [prAnalysisModel, setPrAnalysisModel] = useState("");
  const [summaryModel, setSummaryModel] = useState("");

  // Advanced params
  const [temperature, setTemperature] = useState(1.0);
  const [topP, setTopP] = useState(1.0);
  const [maxResponseTokens, setMaxResponseTokens] = useState(4096);
  const [thinkingBudgetTokens, setThinkingBudgetTokens] = useState(2048);
  const [chatTimeoutSeconds, setChatTimeoutSeconds] = useState(120);
  const [maxToolCalls, setMaxToolCalls] = useState(15);

  // Cost
  const [costInputPerMtok, setCostInputPerMtok] = useState(3.0);
  const [costOutputPerMtok, setCostOutputPerMtok] = useState(15.0);

  // Models list
  const [models, setModels] = useState<AiModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const [modelSearch, setModelSearch] = useState("");

  // Connection test
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  // Advanced section toggle
  const [showAdvanced, setShowAdvanced] = useState(false);

  // ── Load config ──

  const loadConfig = useCallback(async () => {
    try {
      const data = await getAiConfig();
      setConfig(data);
      // Populate form
      setProvider(data.provider);
      setAwsRegion(data.aws_region);
      setBedrockUseIamRole(data.bedrock_use_iam_role);
      setAwsAccessKeyId(data.aws_access_key_id || "");
      setAwsSecretAccessKey(data.has_aws_secret_key ? "***" : "");
      setOpenaiApiKey(data.has_openai_api_key ? "***" : "");
      setOpenaiBaseUrl(data.openai_base_url || "");
      setChatModel(data.chat_model);
      setPrAnalysisModel(data.pr_analysis_model);
      setSummaryModel(data.summary_model);
      setTemperature(data.temperature);
      setTopP(data.top_p);
      setMaxResponseTokens(data.max_response_tokens);
      setThinkingBudgetTokens(data.thinking_budget_tokens);
      setChatTimeoutSeconds(data.chat_timeout_seconds);
      setMaxToolCalls(data.max_tool_calls);
      setCostInputPerMtok(data.cost_input_per_mtok);
      setCostOutputPerMtok(data.cost_output_per_mtok);
      setError("");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load AI configuration"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  // ── Load models ──

  const loadModels = useCallback(async () => {
    setModelsLoading(true);
    setModelsError("");
    try {
      const data = await getAiModels();
      setModels(data.models);
    } catch (err) {
      setModelsError(
        err instanceof Error ? err.message : "Failed to load models"
      );
    } finally {
      setModelsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (config) {
      loadModels();
    }
  }, [config, loadModels]);

  // ── Save ──

  async function handleSave() {
    setSaving(true);
    setSaveMessage(null);
    try {
      const body: AiConfigUpdateRequest = {
        provider,
        aws_region: awsRegion,
        bedrock_use_iam_role: bedrockUseIamRole,
        aws_access_key_id: awsAccessKeyId || null,
        aws_secret_access_key: awsSecretAccessKey || null,
        openai_api_key: openaiApiKey || null,
        openai_base_url: openaiBaseUrl || null,
        chat_model: chatModel,
        pr_analysis_model: prAnalysisModel,
        summary_model: summaryModel,
        temperature,
        top_p: topP,
        max_response_tokens: maxResponseTokens,
        thinking_budget_tokens: thinkingBudgetTokens,
        chat_timeout_seconds: chatTimeoutSeconds,
        max_tool_calls: maxToolCalls,
        cost_input_per_mtok: costInputPerMtok,
        cost_output_per_mtok: costOutputPerMtok,
      };
      await updateAiConfig(body);
      setSaveMessage({ type: "success", text: "Configuration saved" });
      // Reload to pick up fresh state
      await loadConfig();
      // Reload models in case provider changed
      await loadModels();
    } catch (err) {
      setSaveMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to save",
      });
    } finally {
      setSaving(false);
    }
  }

  // ── Test connection ──

  async function handleTestConnection() {
    setTestLoading(true);
    setTestResult(null);
    try {
      const result = await testAiConnection({
        provider,
        aws_region: awsRegion,
        bedrock_use_iam_role: bedrockUseIamRole,
        aws_access_key_id: awsAccessKeyId || null,
        aws_secret_access_key: awsSecretAccessKey || null,
        openai_api_key: openaiApiKey || null,
        openai_base_url: openaiBaseUrl || null,
      });
      setTestResult(result);
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Test failed",
      });
    } finally {
      setTestLoading(false);
    }
  }

  // ── Model dropdown filter ──

  const filteredModels = models.filter(
    (m) =>
      m.model_id.toLowerCase().includes(modelSearch.toLowerCase()) ||
      m.name.toLowerCase().includes(modelSearch.toLowerCase()) ||
      m.provider_name.toLowerCase().includes(modelSearch.toLowerCase())
  );

  // ── Render ──

  if (!isAdmin) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-semibold">AI Configuration</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Admin access required to modify AI settings.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-semibold">AI Configuration</h1>
        <p className="mt-2 text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-semibold">AI Configuration</h1>
        <div className="mt-4 rounded-lg border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">AI Configuration</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Configure AI provider, models, and inference parameters used across
            the platform
          </p>
        </div>
        <Button
          variant="default"
          size="sm"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? (
            <Loader2 className="mr-1.5 size-3 animate-spin" />
          ) : (
            <Save className="mr-1.5 size-3" />
          )}
          Save Changes
        </Button>
      </div>

      {/* Save feedback */}
      {saveMessage && (
        <div
          className={`rounded-md px-3 py-2 text-xs ${
            saveMessage.type === "success"
              ? "bg-emerald-500/10 text-emerald-600 border border-emerald-500/20"
              : "bg-destructive/10 text-destructive border border-destructive/20"
          }`}
        >
          {saveMessage.text}
        </div>
      )}

      {/* ── Provider Selection ── */}
      <section className="rounded-lg border p-4">
        <SectionHeader
          icon={Cloud}
          title="AI Provider"
          description="Select the AI provider for all model inference"
          badge={
            <Badge
              variant="outline"
              className={
                provider === "bedrock"
                  ? "bg-amber-500/10 text-amber-600 border-amber-500/20"
                  : "bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
              }
            >
              {provider === "bedrock" ? "AWS Bedrock" : "OpenAI"}
            </Badge>
          }
        />

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {/* Bedrock card */}
          <button
            type="button"
            onClick={() => setProvider("bedrock")}
            className={`relative rounded-lg border p-4 text-left transition-all ${
              provider === "bedrock"
                ? "border-amber-500/40 bg-amber-500/5 ring-1 ring-amber-500/20"
                : "hover:border-muted-foreground/30"
            }`}
          >
            {provider === "bedrock" && (
              <div className="absolute right-3 top-3">
                <Check className="size-4 text-amber-600" />
              </div>
            )}
            <div className="flex items-center gap-2.5">
              <div className="flex size-8 items-center justify-center rounded-md bg-amber-500/10">
                <Cloud className="size-4 text-amber-600" />
              </div>
              <div>
                <div className="text-sm font-medium">AWS Bedrock</div>
                <div className="text-[11px] text-muted-foreground">
                  Claude, Llama, Mistral via AWS
                </div>
              </div>
            </div>
            <p className="mt-2.5 text-[11px] text-muted-foreground leading-relaxed">
              Access foundation models through your AWS account. Supports IAM
              role authentication or explicit access keys.
            </p>
          </button>

          {/* OpenAI card */}
          <button
            type="button"
            onClick={() => setProvider("openai")}
            className={`relative rounded-lg border p-4 text-left transition-all ${
              provider === "openai"
                ? "border-emerald-500/40 bg-emerald-500/5 ring-1 ring-emerald-500/20"
                : "hover:border-muted-foreground/30"
            }`}
          >
            {provider === "openai" && (
              <div className="absolute right-3 top-3">
                <Check className="size-4 text-emerald-600" />
              </div>
            )}
            <div className="flex items-center gap-2.5">
              <div className="flex size-8 items-center justify-center rounded-md bg-emerald-500/10">
                <Sparkles className="size-4 text-emerald-600" />
              </div>
              <div>
                <div className="text-sm font-medium">OpenAI</div>
                <div className="text-[11px] text-muted-foreground">
                  GPT-4o, o1, o3 via API
                </div>
              </div>
            </div>
            <p className="mt-2.5 text-[11px] text-muted-foreground leading-relaxed">
              Use OpenAI models directly via API key. Also supports Azure
              OpenAI and compatible endpoints.
            </p>
          </button>
        </div>
      </section>

      {/* ── Credentials ── */}
      <section className="rounded-lg border p-4">
        <SectionHeader
          icon={Key}
          title="Credentials"
          description={
            provider === "bedrock"
              ? "AWS authentication for Bedrock access"
              : "API key for OpenAI access"
          }
        />

        {provider === "bedrock" ? (
          <div className="space-y-1 divide-y">
            <FieldRow label="AWS Region" description="Bedrock endpoint region">
              <select
                value={awsRegion}
                onChange={(e) => setAwsRegion(e.target.value)}
                className={SELECT_CLS}
              >
                {AWS_REGIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </FieldRow>

            <FieldRow
              label="Use IAM Role"
              description="Recommended for EC2/ECS deployments"
            >
              <Toggle
                checked={bedrockUseIamRole}
                onChange={setBedrockUseIamRole}
              />
            </FieldRow>

            {!bedrockUseIamRole && (
              <>
                <FieldRow label="Access Key ID">
                  <input
                    type="text"
                    value={awsAccessKeyId}
                    onChange={(e) => setAwsAccessKeyId(e.target.value)}
                    placeholder="AKIA..."
                    className={INPUT_CLS}
                  />
                </FieldRow>

                <FieldRow label="Secret Access Key">
                  <div className="relative">
                    <input
                      type={showAwsSecret ? "text" : "password"}
                      value={awsSecretAccessKey}
                      onChange={(e) => setAwsSecretAccessKey(e.target.value)}
                      placeholder={
                        config?.has_aws_secret_key
                          ? "Enter new key to change"
                          : "Enter secret key"
                      }
                      className={`${INPUT_CLS} pr-8`}
                    />
                    <button
                      type="button"
                      onClick={() => setShowAwsSecret(!showAwsSecret)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      {showAwsSecret ? (
                        <EyeOff className="size-3.5" />
                      ) : (
                        <Eye className="size-3.5" />
                      )}
                    </button>
                  </div>
                </FieldRow>
              </>
            )}

            <div className="flex items-start gap-2 pt-3">
              <Shield className="mt-0.5 size-3 text-muted-foreground" />
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {bedrockUseIamRole
                  ? "Using the instance's IAM role for authentication. Ensure the role has bedrock:InvokeModel and bedrock:ListFoundationModels permissions."
                  : "Access keys are encrypted at rest using AES-256. Consider using IAM roles for production deployments."}
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-1 divide-y">
            <FieldRow label="API Key">
              <div className="relative">
                <input
                  type={showOpenaiKey ? "text" : "password"}
                  value={openaiApiKey}
                  onChange={(e) => setOpenaiApiKey(e.target.value)}
                  placeholder={
                    config?.has_openai_api_key
                      ? "Enter new key to change"
                      : "sk-..."
                  }
                  className={`${INPUT_CLS} pr-8`}
                />
                <button
                  type="button"
                  onClick={() => setShowOpenaiKey(!showOpenaiKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showOpenaiKey ? (
                    <EyeOff className="size-3.5" />
                  ) : (
                    <Eye className="size-3.5" />
                  )}
                </button>
              </div>
            </FieldRow>

            <FieldRow
              label="Base URL"
              description="Override for Azure OpenAI or compatible APIs"
            >
              <input
                type="text"
                value={openaiBaseUrl}
                onChange={(e) => setOpenaiBaseUrl(e.target.value)}
                placeholder="https://api.openai.com/v1"
                className={INPUT_CLS}
              />
            </FieldRow>

            <div className="flex items-start gap-2 pt-3">
              <Shield className="mt-0.5 size-3 text-muted-foreground" />
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                API key is encrypted at rest. Set a custom base URL to use Azure
                OpenAI Service or any OpenAI-compatible endpoint.
              </p>
            </div>
          </div>
        )}

        {/* Connection test */}
        <div className="mt-4 flex items-center gap-3 border-t pt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={handleTestConnection}
            disabled={testLoading}
          >
            {testLoading ? (
              <Loader2 className="mr-1.5 size-3 animate-spin" />
            ) : (
              <Zap className="mr-1.5 size-3" />
            )}
            Test Connection
          </Button>
          {testResult && (
            <span
              className={`text-xs ${
                testResult.success
                  ? "text-emerald-600"
                  : "text-destructive"
              }`}
            >
              {testResult.message}
            </span>
          )}
        </div>
      </section>

      {/* ── Model Assignments ── */}
      <section className="rounded-lg border p-4">
        <SectionHeader
          icon={Bot}
          title="Model Assignments"
          description="Assign models to each AI feature across the platform"
          badge={
            <Button
              variant="ghost"
              size="sm"
              onClick={loadModels}
              disabled={modelsLoading}
              className="h-6 px-2 text-xs"
            >
              {modelsLoading ? (
                <Loader2 className="mr-1 size-3 animate-spin" />
              ) : (
                <RefreshCw className="mr-1 size-3" />
              )}
              Refresh Models
            </Button>
          }
        />

        {modelsError && (
          <div className="mb-3 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {modelsError}
          </div>
        )}

        {/* Model search */}
        {models.length > 0 && (
          <div className="relative mb-3">
            <Search className="absolute left-2.5 top-1/2 size-3 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={modelSearch}
              onChange={(e) => setModelSearch(e.target.value)}
              placeholder="Filter models..."
              className={`${INPUT_CLS} pl-7`}
            />
          </div>
        )}

        <div className="space-y-1 divide-y">
          <ModelSelect
            label="Chat Model"
            description="Used for the AI architecture assistant"
            icon={MessageSquare}
            value={chatModel}
            onChange={setChatModel}
            models={filteredModels}
            loading={modelsLoading}
          />
          <ModelSelect
            label="PR Analysis Model"
            description="Used for automated pull request reviews"
            icon={Search}
            value={prAnalysisModel}
            onChange={setPrAnalysisModel}
            models={filteredModels}
            loading={modelsLoading}
          />
          <ModelSelect
            label="Summary Model"
            description="Used for code object summary generation"
            icon={Sparkles}
            value={summaryModel}
            onChange={setSummaryModel}
            models={filteredModels}
            loading={modelsLoading}
          />
        </div>

        {models.length > 0 && (
          <p className="mt-3 text-[11px] text-muted-foreground">
            {models.length} models available from{" "}
            {provider === "bedrock" ? "Bedrock" : "OpenAI"}.{" "}
            {filteredModels.length !== models.length &&
              `Showing ${filteredModels.length} filtered.`}
          </p>
        )}
      </section>

      {/* ── Advanced Parameters ── */}
      <section className="rounded-lg border p-4">
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex w-full items-center justify-between"
        >
          <div className="flex items-start gap-2">
            <Settings2 className="mt-0.5 size-4 text-muted-foreground" />
            <div className="text-left">
              <h2 className="text-sm font-semibold">Advanced Parameters</h2>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Fine-tune inference behavior, token limits, and timeouts
              </p>
            </div>
          </div>
          {showAdvanced ? (
            <ChevronDown className="size-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-4 text-muted-foreground" />
          )}
        </button>

        {showAdvanced && (
          <div className="mt-4 space-y-1 divide-y">
            {/* Temperature */}
            <FieldRow
              label="Temperature"
              description="Controls randomness (0 = deterministic, 2 = very creative)"
            >
              <div className="space-y-1">
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.05}
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="h-1.5 w-full cursor-pointer accent-primary"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>Precise</span>
                  <span className="font-mono font-medium text-foreground">
                    {temperature.toFixed(2)}
                  </span>
                  <span>Creative</span>
                </div>
              </div>
            </FieldRow>

            {/* Top P */}
            <FieldRow
              label="Top P"
              description="Nucleus sampling threshold"
            >
              <div className="space-y-1">
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={topP}
                  onChange={(e) => setTopP(parseFloat(e.target.value))}
                  className="h-1.5 w-full cursor-pointer accent-primary"
                />
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>Focused</span>
                  <span className="font-mono font-medium text-foreground">
                    {topP.toFixed(2)}
                  </span>
                  <span>Diverse</span>
                </div>
              </div>
            </FieldRow>

            {/* Max Response Tokens */}
            <FieldRow
              label="Max Response Tokens"
              description="Maximum tokens in model response"
            >
              <input
                type="number"
                min={256}
                max={65536}
                step={256}
                value={maxResponseTokens}
                onChange={(e) =>
                  setMaxResponseTokens(parseInt(e.target.value) || 4096)
                }
                className={INPUT_CLS}
              />
            </FieldRow>

            {/* Thinking Budget (Claude-specific) */}
            {provider === "bedrock" && (
              <FieldRow
                label="Thinking Budget"
                description="Extended thinking token budget (Claude only)"
              >
                <input
                  type="number"
                  min={0}
                  max={32768}
                  step={256}
                  value={thinkingBudgetTokens}
                  onChange={(e) =>
                    setThinkingBudgetTokens(parseInt(e.target.value) || 2048)
                  }
                  className={INPUT_CLS}
                />
              </FieldRow>
            )}

            {/* Chat Timeout */}
            <FieldRow
              label="Chat Timeout"
              description="Maximum seconds for a chat session"
            >
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={30}
                  max={600}
                  step={10}
                  value={chatTimeoutSeconds}
                  onChange={(e) =>
                    setChatTimeoutSeconds(parseInt(e.target.value) || 120)
                  }
                  className={INPUT_CLS}
                />
                <span className="text-xs text-muted-foreground whitespace-nowrap">
                  seconds
                </span>
              </div>
            </FieldRow>

            {/* Max Tool Calls */}
            <FieldRow
              label="Max Tool Calls"
              description="Tool call limit per chat turn"
            >
              <input
                type="number"
                min={1}
                max={50}
                value={maxToolCalls}
                onChange={(e) =>
                  setMaxToolCalls(parseInt(e.target.value) || 15)
                }
                className={INPUT_CLS}
              />
            </FieldRow>
          </div>
        )}
      </section>

      {/* ── Cost Tracking ── */}
      <section className="rounded-lg border p-4">
        <SectionHeader
          icon={DollarSign}
          title="Cost Tracking"
          description="Token pricing for usage cost estimation (USD per million tokens)"
        />
        <div className="space-y-1 divide-y">
          <FieldRow label="Input Cost" description="Per million input tokens">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">$</span>
              <input
                type="number"
                min={0}
                step={0.5}
                value={costInputPerMtok}
                onChange={(e) =>
                  setCostInputPerMtok(parseFloat(e.target.value) || 0)
                }
                className={INPUT_CLS}
              />
            </div>
          </FieldRow>
          <FieldRow label="Output Cost" description="Per million output tokens">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">$</span>
              <input
                type="number"
                min={0}
                step={0.5}
                value={costOutputPerMtok}
                onChange={(e) =>
                  setCostOutputPerMtok(parseFloat(e.target.value) || 0)
                }
                className={INPUT_CLS}
              />
            </div>
          </FieldRow>
        </div>
      </section>
    </div>
  );
}

// ── Model Select Component ──

function ModelSelect({
  label,
  description,
  icon: Icon,
  value,
  onChange,
  models,
  loading,
}: {
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  value: string;
  onChange: (v: string) => void;
  models: AiModelInfo[];
  loading: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <div className="flex items-start gap-2 min-w-0">
        <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
        <div>
          <div className="text-xs font-medium">{label}</div>
          <div className="text-[11px] text-muted-foreground">{description}</div>
        </div>
      </div>
      <div className="w-64 shrink-0">
        {loading ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            Loading models...
          </div>
        ) : models.length > 0 ? (
          <select
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className={SELECT_CLS}
          >
            {/* Keep current value even if not in the list */}
            {!models.some((m) => m.model_id === value) && value && (
              <option value={value}>{value}</option>
            )}
            {models.map((m) => (
              <option key={m.model_id} value={m.model_id}>
                {m.name}
                {m.provider_name ? ` (${m.provider_name})` : ""}
              </option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Enter model ID"
            className={INPUT_CLS}
          />
        )}
      </div>
    </div>
  );
}
