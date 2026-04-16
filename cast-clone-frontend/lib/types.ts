// ─── Enums ──────────────────────────────────────────────────────────────────

export type ProjectStatus = "created" | "analyzing" | "analyzed" | "failed";

// ─── Project types ──────────────────────────────────────────────────────────

export interface ProjectResponse {
  id: string;
  name: string;
  source_path: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
}

export interface ProjectListResponse {
  projects: ProjectResponse[];
  total: number;
}

export interface CreateProjectRequest {
  name: string;
  source_path: string;
}

// ─── Analysis types ─────────────────────────────────────────────────────────

export interface AnalysisTriggerResponse {
  project_id: string;
  run_id: string;
  status: string;
  message: string;
}

export interface AnalysisStageStatus {
  name: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  description: string;
  progress?: number | null; // 0-100, only set for running stage
}

export interface AnalysisStatusResponse {
  project_id: string;
  status: string;
  current_stage: string | null;
  stages: AnalysisStageStatus[];
  error?: string;
  started_at: string | null;
  completed_at: string | null;
}

// ─── Graph types ────────────────────────────────────────────────────────────

export interface GraphNodeResponse {
  fqn: string;
  name: string;
  kind: string;
  language: string | null;
  path: string | null;
  line: number | null;
  end_line: number | null;
  loc: number | null;
  complexity: number | null;
  visibility: string | null;
  properties: Record<string, unknown>;
}

export interface GraphEdgeResponse {
  source_fqn: string;
  target_fqn: string;
  kind: string;
  confidence: string;
  evidence: string;
  properties: Record<string, unknown>;
}

export interface GraphNodeListResponse {
  nodes: GraphNodeResponse[];
  total: number;
  offset: number;
  limit: number;
}

export interface GraphEdgeListResponse {
  edges: GraphEdgeResponse[];
  total: number;
  offset: number;
  limit: number;
}

export interface NodeWithNeighborsResponse {
  node: GraphNodeResponse;
  incoming_edges: GraphEdgeResponse[];
  outgoing_edges: GraphEdgeResponse[];
  neighbors: GraphNodeResponse[];
}

export interface GraphSearchHit {
  fqn: string;
  name: string;
  kind: string;
  language: string | null;
  score: number;
}

export interface GraphSearchResponse {
  query: string;
  hits: GraphSearchHit[];
  total: number;
}

// ─── Node Ancestry types ─────────────────────────────────────────────────────

export interface NodeAncestor {
  fqn: string;
  name: string;
  kind: string;
}

export interface NodeAncestryResponse {
  fqn: string;
  ancestors: NodeAncestor[];
}

// ─── Phase 2 M1: Module / Drill-down types ──────────────────────────────────

export interface ModuleResponse {
  fqn: string;
  name: string;
  kind: string;
  language: string | null;
  loc: number | null;
  file_count: number | null;
  class_count: number | null;
  properties: Record<string, unknown>;
}

export interface ModuleListResponse {
  modules: ModuleResponse[];
  total: number;
}

export interface ClassListResponse {
  classes: GraphNodeResponse[];
  total: number;
  parent_fqn: string;
}

export interface MethodListResponse {
  methods: GraphNodeResponse[];
  total: number;
  parent_fqn: string;
}

export interface AggregatedEdgeResponse {
  source: string;
  target: string;
  weight: number;
  kind: string;
}

export interface AggregatedEdgeListResponse {
  edges: AggregatedEdgeResponse[];
  total: number;
  level: string;
}

// ─── Phase 2 M1: Transaction types ──────────────────────────────────────────

export interface TransactionSummary {
  fqn: string;
  name: string;
  kind: string;
  properties: Record<string, unknown>;
}

export interface TransactionListResponse {
  transactions: TransactionSummary[];
  total: number;
}

export interface TransactionDetailResponse {
  fqn: string;
  name: string;
  nodes: GraphNodeResponse[];
  edges: GraphEdgeResponse[];
}

// ─── Phase 2: Code viewer ───────────────────────────────────────────────────

export interface CodeViewerResponse {
  content: string;
  language: string;
  start_line: number;
  highlight_line: number | null;
  total_lines: number;
}

// ─── Phase 2 M4: Graph visualization types ─────────────────────────────────

export type ViewMode = "architecture" | "dependency" | "transaction";
export type DrilldownLevel = "module" | "class" | "method";

// ── Architecture View types ──────────────────────────────

export interface TechnologyNode {
  fqn: string;
  name: string;
  category: string;
  language: string | null;
  layer: string;
  class_count: number;
  loc_total: number;
  endpoint_count: number;
  table_count: number;
  properties: Record<string, unknown>;
}

export interface ArchitectureLayer {
  fqn: string;
  name: string;
  technologies: TechnologyNode[];
  total_classes: number;
  total_loc: number;
}

export interface ArchitectureLink {
  source: string;
  target: string;
  weight: number;
  kinds: string[];
}

export interface ArchitectureResponse {
  app_name: string;
  languages: string[];
  frameworks: string[];
  layers: ArchitectureLayer[];
  links: ArchitectureLink[];
}

// ── Phase 3: Impact Analysis ────────────────────────────

export interface AffectedNode {
  fqn: string;
  name: string;
  type: string;
  file: string | null;
  depth: number;
}

export interface ImpactSummary {
  total: number;
  by_type: Record<string, number>;
  by_depth: Record<string, number>;
}

export interface ImpactAnalysisResponse {
  node: string;
  direction: string;
  max_depth: number;
  summary: ImpactSummary;
  affected: AffectedNode[];
}

// ── Phase 3: Trace Route ───────────────────────────────

export interface TraceNode {
  fqn: string;
  name: string;
  kind: string;
  file: string | null;
  language: string | null;
  depth: number;
  sequence: number;
  direction: "upstream" | "downstream";
  layer: "api" | "service" | "repository" | "database" | "other";
}

export interface TraceEdge {
  source: string;
  target: string;
  type: string;
  sequence: number | null;
}

export interface TraceRouteResponse {
  center_fqn: string;
  center_name: string;
  center_kind: string;
  center_layer: string;
  max_depth: number;
  upstream: TraceNode[];
  downstream: TraceNode[];
  edges: TraceEdge[];
  upstream_count: number;
  downstream_count: number;
  layers_present: string[];
}

export interface TraceSummaryResponse {
  fqn: string;
  summary: string;
  layers_involved: string[];
  tables_touched: string[];
  cached: boolean;
  model: string | null;
  tokens_used: number | null;
}

// ── Trace follow-up chat ────────────────────────────────

export interface TraceChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  model: string | null;
  tokens_used: number | null;
}

export interface TraceChatHistoryResponse {
  fqn: string;
  messages: TraceChatMessage[];
}

export interface TraceChatSendResponse {
  fqn: string;
  user_message: TraceChatMessage;
  assistant_message: TraceChatMessage;
}

// ── Phase 3: Path Finder ────────────────────────────────

export interface PathNode {
  fqn: string;
  name: string;
  type: string;
}

export interface PathEdge {
  type: string;
  source: string;
  target: string;
}

export interface PathFinderResponse {
  from_fqn: string;
  to_fqn: string;
  nodes: PathNode[];
  edges: PathEdge[];
  path_length: number;
}

// ── Phase 3: Communities ────────────────────────────────

export interface CommunityInfo {
  community_id: number;
  size: number;
  members: string[];
}

export interface CommunitiesResponse {
  communities: CommunityInfo[];
  total: number;
  modularity: number | null;
}

// ── Phase 3: Circular Dependencies ──────────────────────

export interface CircularDependency {
  cycle: string[];
  cycle_length: number;
}

export interface CircularDependenciesResponse {
  cycles: CircularDependency[];
  total: number;
  level: string;
}

// ── Phase 3: Dead Code ──────────────────────────────────

export interface DeadCodeCandidate {
  fqn: string;
  name: string;
  path: string | null;
  line: number | null;
  loc: number | null;
}

export interface DeadCodeResponse {
  candidates: DeadCodeCandidate[];
  total: number;
  type_filter: string;
}

// ── Phase 3: Metrics Dashboard ──────────────────────────

export interface OverviewStats {
  modules: number;
  classes: number;
  functions: number;
  total_loc: number;
}

export interface RankedItem {
  fqn: string;
  name: string;
  value: number;
}

export interface MetricsResponse {
  overview: OverviewStats;
  most_complex: RankedItem[];
  highest_fan_in: RankedItem[];
  highest_fan_out: RankedItem[];
  community_count: number;
  circular_dependency_count: number;
  dead_code_count: number;
}

// ── Phase 3: Enhanced Node Details ──────────────────────

export interface NodeDetailResponse {
  fqn: string;
  name: string;
  type: string;
  language: string | null;
  path: string | null;
  line: number | null;
  loc: number | null;
  complexity: number | null;
  fan_in: number;
  fan_out: number;
  community_id: number | null;
  callers: PathNode[];
  callees: PathNode[];
}

// ─── Phase 4A: Git Connector types ──────────────────────────────────────────

export type ConnectorProvider = "github" | "gitlab" | "gitea" | "bitbucket";
export type ConnectorStatus = "connected" | "expired" | "revoked" | "error";

export interface ConnectorResponse {
  id: string;
  name: string;
  provider: ConnectorProvider;
  base_url: string;
  auth_method: string;
  status: ConnectorStatus;
  remote_username: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectorListResponse {
  connectors: ConnectorResponse[];
  total: number;
}

export interface CreateConnectorRequest {
  name: string;
  provider: ConnectorProvider;
  base_url: string;
  token: string;
}

export interface ConnectorTestResponse {
  status: string;
  remote_username: string | null;
  error: string | null;
}

export interface RemoteRepoResponse {
  full_name: string;
  clone_url: string;
  default_branch: string;
  description: string | null;
  language: string | null;
  is_private: boolean;
}

export interface RemoteRepoListResponse {
  repos: RemoteRepoResponse[];
  has_more: boolean;
  page: number;
  per_page: number;
}

export interface BranchListResponse {
  branches: string[];
  default_branch: string;
}

// ─── Phase 4A: Repository types ─────────────────────────────────────────────

export type CloneStatus = "pending" | "cloning" | "cloned" | "clone_failed";

export interface ProjectBranchResponse {
  id: string;
  branch: string | null;
  status: ProjectStatus;
  last_analyzed_at: string | null;
  node_count: number | null;
  edge_count: number | null;
}

export interface RepositoryResponse {
  id: string;
  connector_id: string;
  repo_full_name: string;
  default_branch: string;
  description: string | null;
  language: string | null;
  is_private: boolean;
  clone_status: CloneStatus;
  clone_error: string | null;
  local_path: string | null;
  last_synced_at: string | null;
  created_at: string;
  projects: ProjectBranchResponse[];
  billable_loc: number | null;
  max_loc_branch: string | null;
}

export interface RepositoryListResponse {
  repositories: RepositoryResponse[];
  total: number;
}

export interface CreateRepositoryRequest {
  connector_id: string;
  repo_full_name: string;
  branches: string[];
  auto_analyze: boolean;
}

export interface CloneStatusResponse {
  clone_status: CloneStatus;
  clone_error: string | null;
}

export interface SnapshotPoint {
  run_id: string;
  analyzed_at: string;
  commit_sha: string | null;
  summary: Record<string, number>;
}

export interface EvolutionTimelineResponse {
  repo_id: string;
  branch: string;
  snapshots: SnapshotPoint[];
}

// ── Phase 4: Auth & User Management ──

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface UserResponse {
  id: string;
  username: string;
  email: string;
  role: "admin" | "member";
  is_active: boolean;
  created_at: string;
  last_login: string | null;
}

export interface SetupStatusResponse {
  needs_setup: boolean;
  auth_disabled: boolean;
}

export interface SetupRequest {
  username: string;
  email: string;
  password: string;
}

export interface UserCreateRequest {
  username: string;
  email: string;
  password: string;
  role?: "admin" | "member";
}

export interface UserUpdateRequest {
  username?: string;
  email?: string;
  password?: string;
  role?: "admin" | "member";
  is_active?: boolean;
}

// ── Phase 4: Annotations & Tags ──

export const PREDEFINED_TAGS = [
  "deprecated",
  "tech-debt",
  "critical-path",
  "security-sensitive",
  "needs-review",
] as const;

export type TagName = (typeof PREDEFINED_TAGS)[number];

export interface AnnotationAuthor {
  id: string;
  username: string;
}

export interface AnnotationResponse {
  id: string;
  project_id: string;
  node_fqn: string;
  content: string;
  author: AnnotationAuthor;
  created_at: string;
  updated_at: string;
}

export interface TagResponse {
  id: string;
  project_id: string;
  node_fqn: string;
  tag_name: TagName;
  author: AnnotationAuthor;
  created_at: string;
}

// ── Phase 4: Export ──

// Export endpoints return file downloads, no response types needed.

// ── Phase 4: Activity Log ──

export interface ActivityAuthor {
  id: string;
  username: string;
}

export interface ActivityLogEntry {
  id: string;
  user: ActivityAuthor | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface ActivityActionCount {
  action: string;
  count: number;
}

export interface ActivityDailyCount {
  date: string;
  count: number;
}

export interface ActivityStatsResponse {
  total: number;
  by_action: ActivityActionCount[];
  by_day: ActivityDailyCount[];
  unique_users: number;
}

// ── Phase 5a: PR Analysis Types ──

export interface PrAnalysis {
  id: string;
  repository_id: string;
  platform: string;
  pr_number: number;
  pr_title: string;
  pr_description?: string;
  pr_author: string;
  source_branch: string;
  target_branch: string;
  commit_sha: string;
  pr_url?: string;
  status: "pending" | "analyzing" | "completed" | "failed" | "stale";
  risk_level?: "High" | "Medium" | "Low";
  changed_node_count?: number;
  blast_radius_total?: number;
  files_changed?: number;
  additions?: number;
  deletions?: number;
  ai_summary?: string;
  ai_summary_tokens?: number;
  analysis_duration_ms?: number;
  created_at: string;
  updated_at: string;
}

export interface PrAnalysisList {
  items: PrAnalysis[];
  total: number;
  limit: number;
  offset: number;
}

export interface PrImpactDetail {
  pr_analysis_id: string;
  total_blast_radius: number;
  by_type: Record<string, number>;
  by_depth: Record<string, number>;
  by_layer: Record<string, number>;
  changed_nodes: Array<{
    fqn: string;
    name: string;
    type: string;
    change_type: string;
  }>;
  downstream_count: number;
  upstream_count: number;
  cross_tech: Array<{
    kind: string;
    name: string;
    detail: string;
  }>;
  transactions_affected: string[];
  new_files: string[];
  non_graph_files: string[];
}

export interface PrDriftDetail {
  pr_analysis_id: string;
  has_drift: boolean;
  potential_new_module_deps: Array<{
    from_module: string;
    to_module: string;
  }>;
  circular_deps_affected: string[][];
  new_files_outside_modules: string[];
}

export interface GitConfig {
  id: string;
  repository_id: string;
  platform: string;
  repo_url: string;
  monitored_branches: string[] | null;
  is_active: boolean;
  post_pr_comments: boolean;
  created_at: string;
  updated_at: string;
}

export interface GitConfigCreateResponse extends GitConfig {
  webhook_url: string;
  webhook_secret: string;
}

export interface WebhookUrlInfo {
  webhook_url: string;
  webhook_secret: string;
}

// ── API Keys (M4 endpoints) ──

export interface ApiKeyResponse {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  is_active: boolean;
}

export interface ApiKeyCreateResponse {
  id: string;
  name: string;
  raw_key: string;
}

// ── AI Usage (M5 endpoints) ──

export interface UsageBySourceItem {
  source: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  count: number;
}

export interface UsageByProjectItem {
  project_id: string;
  project_name: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  count: number;
}

export interface UsageSummaryResponse {
  total_input_tokens: number;
  total_output_tokens: number;
  total_estimated_cost_usd: number;
  by_source: UsageBySourceItem[];
  by_project: UsageByProjectItem[];
}

// ── Phase 4: Saved Views ──

export interface SavedViewState {
  viewType: ViewMode;
  selectedTransaction?: string;
  visibleNodeFqns: string[];
  drilldownPath: string[];
  layout: { name: string; [key: string]: unknown };
  zoom: number;
  pan: { x: number; y: number };
  filters: {
    nodeTypes?: string[];
    languages?: string[];
  };
  highlights?: {
    impact?: { startNode: string; depth: number; direction: string };
    path?: { from: string; to: string };
  };
}

export interface SavedViewResponse {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  author: { id: string; username: string };
  state: SavedViewState;
  created_at: string;
  updated_at: string;
}

export interface SavedViewListItem {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  author: { id: string; username: string };
  created_at: string;
  updated_at: string;
}

// ── License Management ──

export type LicenseState =
  | "UNLICENSED"
  | "LICENSED_HEALTHY"
  | "LICENSED_WARN"
  | "LICENSED_GRACE"
  | "LICENSED_BLOCKED";

export interface LicenseStatusResponse {
  state: LicenseState;
  installation_id: string;
  license_disabled: boolean;
  tier: number | string | null;
  loc_limit: number | null;
  loc_used: number | null;
  loc_breakdown: RepoLocBreakdown[];
  customer_name: string | null;
  customer_email: string | null;
  customer_organization: string | null;
  issued_by: string | null;
  expires_at: number | null;
  issued_at: number | null;
  notes: string | null;
}

export interface InstallationIdResponse {
  installation_id: string;
}

export interface RepoLocBreakdown {
  repository_id: string;
  repo_full_name: string;
  billable_loc: number;
  max_branch: string | null;
  branches: Record<string, number>;
}

// ─── Email config types ─────────────────────────────────────────────────────

export interface EmailConfigResponse {
  enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string; // "***" if stored, "" if not
  smtp_use_tls: boolean;
  from_address: string;
  from_name: string;
  recipients: string[];
  flentas_bcc_enabled: boolean;
  cadence: string; // "off" | "weekly" | "monthly"
  cadence_day: number;
  cadence_hour_utc: number;
}

export interface EmailConfigUpdateRequest {
  enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string;
  smtp_use_tls: boolean;
  from_address: string;
  from_name: string;
  recipients: string[];
  flentas_bcc_enabled: boolean;
  cadence: string;
  cadence_day: number;
  cadence_hour_utc: number;
}

export interface TestSendResponse {
  status: string;
  error: string | null;
}

// ─── System Info types ─────────────────────────────────────────────────────

export interface SystemHealthInfo {
  status: "healthy" | "degraded";
  services: Record<string, "up" | "down">;
}

export interface SystemInstanceInfo {
  installation_id: string | null;
  auth_disabled: boolean;
  license_disabled: boolean;
  python_version: string;
  os: string;
  cpu_count: number | null;
}

export interface SystemAnalysisConfig {
  total_timeout_seconds: number;
  scip_timeout_seconds: number;
  git_clone_timeout_seconds: number;
  max_traversal_depth: number;
  treesitter_workers: number;
  repo_storage_path: string;
}

export interface SystemAiConfig {
  pr_analysis_model: string;
  chat_model: string;
  chat_timeout_seconds: number;
  chat_max_response_tokens: number;
  mcp_port: number;
}

export interface SystemConnectionsInfo {
  neo4j_uri: string;
  redis_url: string;
  minio_endpoint: string;
  database_host: string;
}

export interface SystemInfoResponse {
  health: SystemHealthInfo;
  instance: SystemInstanceInfo;
  analysis: SystemAnalysisConfig;
  ai: SystemAiConfig;
  connections: SystemConnectionsInfo;
}

// ─── AI Configuration types ──────────────────────────────────────────────────

export interface AiConfigResponse {
  provider: "bedrock" | "openai";
  // Bedrock
  aws_region: string;
  bedrock_use_iam_role: boolean;
  aws_access_key_id: string | null;
  has_aws_secret_key: boolean;
  // OpenAI
  has_openai_api_key: boolean;
  openai_base_url: string | null;
  // Model assignments
  chat_model: string;
  pr_analysis_model: string;
  summary_model: string;
  // Advanced params
  temperature: number;
  top_p: number;
  max_response_tokens: number;
  thinking_budget_tokens: number;
  chat_timeout_seconds: number;
  max_tool_calls: number;
  // Cost
  cost_input_per_mtok: number;
  cost_output_per_mtok: number;
}

export interface AiConfigUpdateRequest {
  provider: string;
  aws_region: string;
  bedrock_use_iam_role: boolean;
  aws_access_key_id: string | null;
  aws_secret_access_key: string | null;
  openai_api_key: string | null;
  openai_base_url: string | null;
  chat_model: string;
  pr_analysis_model: string;
  summary_model: string;
  temperature: number;
  top_p: number;
  max_response_tokens: number;
  thinking_budget_tokens: number;
  chat_timeout_seconds: number;
  max_tool_calls: number;
  cost_input_per_mtok: number;
  cost_output_per_mtok: number;
}

export interface AiModelInfo {
  model_id: string;
  name: string;
  provider_name: string;
  supports_streaming: boolean;
  supports_tool_use: boolean;
}

export interface AiModelsListResponse {
  provider: string;
  models: AiModelInfo[];
}

export interface AiTestConnectionRequest {
  provider: string;
  aws_region: string;
  bedrock_use_iam_role: boolean;
  aws_access_key_id: string | null;
  aws_secret_access_key: string | null;
  openai_api_key: string | null;
  openai_base_url: string | null;
}

export interface AiTestConnectionResponse {
  success: boolean;
  message: string;
}
