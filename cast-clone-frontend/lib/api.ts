import type {
  AnalysisStatusResponse,
  AnalysisTriggerResponse,
  AggregatedEdgeListResponse,
  ArchitectureResponse,
  BranchListResponse,
  CircularDependenciesResponse,
  ClassListResponse,
  CloneStatusResponse,
  CodeViewerResponse,
  CommunitiesResponse,
  ConnectorListResponse,
  ConnectorResponse,
  ConnectorTestResponse,
  CreateConnectorRequest,
  CreateProjectRequest,
  CreateRepositoryRequest,
  DeadCodeResponse,
  EmailConfigResponse,
  EmailConfigUpdateRequest,
  EvolutionTimelineResponse,
  GitConfig,
  GitConfigCreateResponse,
  GraphEdgeListResponse,
  GraphNodeListResponse,
  GraphSearchResponse,
  ImpactAnalysisResponse,
  MethodListResponse,
  MetricsResponse,
  ModuleListResponse,
  NodeAncestryResponse,
  NodeDetailResponse,
  NodeWithNeighborsResponse,
  PathFinderResponse,
  PrAnalysis,
  PrAnalysisList,
  PrDriftDetail,
  PrImpactDetail,
  ProjectBranchResponse,
  ProjectListResponse,
  ProjectResponse,
  RemoteRepoListResponse,
  RemoteRepoResponse,
  RepositoryListResponse,
  RepositoryResponse,
  TestSendResponse,
  TransactionDetailResponse,
  TransactionListResponse,
  LoginResponse,
  SetupRequest,
  SetupStatusResponse,
  UserCreateRequest,
  UserResponse,
  UserUpdateRequest,
  AnnotationResponse,
  TagResponse,
  SavedViewResponse,
  SavedViewListItem,
  ActivityLogEntry,
  ActivityStatsResponse,
  WebhookUrlInfo,
  ApiKeyResponse,
  ApiKeyCreateResponse,
  UsageSummaryResponse,
  LicenseStatusResponse,
  InstallationIdResponse,
  SystemInfoResponse,
  AiConfigResponse,
  AiConfigUpdateRequest,
  AiModelsListResponse,
  AiTestConnectionRequest,
  AiTestConnectionResponse,
  TraceRouteResponse,
  TraceSummaryResponse,
  TraceChatHistoryResponse,
  TraceChatSendResponse,
} from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  (typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : "http://localhost:8000");

// ─── Error class ────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ─── Auth token helper ───────────────────────────────────────────────────────

function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("auth_token");
}

// ─── Base fetch helper ──────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const { headers: callerHeaders, ...restOptions } = options;
  const needsContentType = options.body !== undefined && options.body !== null && !(options.body instanceof FormData);
  const res = await fetch(url, {
    headers: {
      ...(needsContentType ? { "Content-Type": "application/json" } : {}),
      ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
      ...(callerHeaders as Record<string, string>),
    },
    ...restOptions,
  });

  if (!res.ok) {
    const body = await res.text();
    let message: string;
    try {
      const json = JSON.parse(body);
      message = json.detail ?? json.message ?? body;
    } catch {
      message = body;
    }
    throw new ApiError(res.status, message);
  }

  // 204 No Content
  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

// ─── Project endpoints ──────────────────────────────────────────────────────

export async function createProject(
  data: CreateProjectRequest,
): Promise<ProjectResponse> {
  return apiFetch<ProjectResponse>("/api/v1/projects", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function listProjects(): Promise<ProjectListResponse> {
  return apiFetch<ProjectListResponse>("/api/v1/projects");
}

export async function getProject(id: string): Promise<ProjectResponse> {
  return apiFetch<ProjectResponse>(`/api/v1/projects/${id}`);
}

export async function deleteProject(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/projects/${id}`, {
    method: "DELETE",
  });
}

// ─── Analysis endpoints ─────────────────────────────────────────────────────

export async function triggerAnalysis(
  projectId: string,
): Promise<AnalysisTriggerResponse> {
  return apiFetch<AnalysisTriggerResponse>(
    `/api/v1/projects/${projectId}/analyze`,
    { method: "POST" },
  );
}

export async function getAnalysisStatus(
  projectId: string,
): Promise<AnalysisStatusResponse> {
  return apiFetch<AnalysisStatusResponse>(
    `/api/v1/projects/${projectId}/status`,
  );
}

// ─── Graph endpoints ────────────────────────────────────────────────────────

export async function getGraphNodes(
  projectId: string,
): Promise<GraphNodeListResponse> {
  return apiFetch<GraphNodeListResponse>(
    `/api/v1/graphs/${projectId}/nodes`,
  );
}

export async function getGraphEdges(
  projectId: string,
): Promise<GraphEdgeListResponse> {
  return apiFetch<GraphEdgeListResponse>(
    `/api/v1/graphs/${projectId}/edges`,
  );
}

export async function getNodeWithNeighbors(
  projectId: string,
  fqn: string,
): Promise<NodeWithNeighborsResponse> {
  return apiFetch<NodeWithNeighborsResponse>(
    `/api/v1/graphs/${projectId}/node/${encodeURIComponent(fqn)}`,
  );
}

export async function searchGraph(
  projectId: string,
  query: string,
): Promise<GraphSearchResponse> {
  return apiFetch<GraphSearchResponse>(
    `/api/v1/graphs/${projectId}/search?q=${encodeURIComponent(query)}`,
  );
}

export async function getNodeAncestry(
  projectId: string,
  fqn: string,
): Promise<NodeAncestryResponse> {
  return apiFetch<NodeAncestryResponse>(
    `/api/v1/graph-views/${projectId}/ancestry/${encodeURIComponent(fqn)}`,
  );
}

// ─── Module / drill-down endpoints (Phase 2 M1) ────────────────────────────

export async function getModules(
  projectId: string,
): Promise<ModuleListResponse> {
  return apiFetch<ModuleListResponse>(
    `/api/v1/graph-views/${projectId}/modules`,
  );
}

export async function getModuleClasses(
  projectId: string,
  moduleFqn: string,
): Promise<ClassListResponse> {
  return apiFetch<ClassListResponse>(
    `/api/v1/graph-views/${projectId}/modules/${encodeURIComponent(moduleFqn)}/classes`,
  );
}

export async function getClassMethods(
  projectId: string,
  classFqn: string,
): Promise<MethodListResponse> {
  return apiFetch<MethodListResponse>(
    `/api/v1/graph-views/${projectId}/classes/${encodeURIComponent(classFqn)}/methods`,
  );
}

export async function getAggregatedEdges(
  projectId: string,
  level: "module" | "class",
  parent?: string,
): Promise<AggregatedEdgeListResponse> {
  const params = new URLSearchParams({ level });
  if (parent) {
    params.set("parent", parent);
  }
  return apiFetch<AggregatedEdgeListResponse>(
    `/api/v1/graph-views/${projectId}/edges/aggregated?${params.toString()}`,
  );
}

// ─── Architecture view endpoint (Phase 2) ───────────────────────────────────

export async function getArchitecture(
  projectId: string,
): Promise<ArchitectureResponse> {
  return apiFetch<ArchitectureResponse>(
    `/api/v1/graph-views/${projectId}/architecture`,
  );
}

// ─── Transaction endpoints (Phase 2 M1) ────────────────────────────────────

export async function getTransactions(
  projectId: string,
): Promise<TransactionListResponse> {
  return apiFetch<TransactionListResponse>(
    `/api/v1/graph-views/${projectId}/transactions`,
  );
}

export async function getTransactionDetail(
  projectId: string,
  fqn: string,
): Promise<TransactionDetailResponse> {
  return apiFetch<TransactionDetailResponse>(
    `/api/v1/graph-views/${projectId}/transactions/${encodeURIComponent(fqn)}`,
  );
}

// ─── Code viewer endpoint (Phase 2) ────────────────────────────────────────

export async function getCodeView(
  projectId: string,
  file: string,
  line?: number,
): Promise<CodeViewerResponse> {
  const params = new URLSearchParams({ file });
  if (line !== undefined) {
    params.set("line", String(line));
  }
  return apiFetch<CodeViewerResponse>(
    `/api/v1/graph-views/${projectId}/code?${params.toString()}`,
  );
}

// ── Phase 3: Analysis APIs ──────────────────────────────

export async function getImpactAnalysis(
  projectId: string,
  nodeFqn: string,
  direction: "downstream" | "upstream" | "both" = "downstream",
  maxDepth: number = 5,
): Promise<ImpactAnalysisResponse> {
  const params = new URLSearchParams({
    direction,
    max_depth: String(maxDepth),
  });
  return apiFetch<ImpactAnalysisResponse>(
    `/api/v1/analysis/${projectId}/impact/${encodeURIComponent(nodeFqn)}?${params}`,
  );
}

export async function getTraceRoute(
  projectId: string,
  nodeFqn: string,
  maxDepth: number = 5,
): Promise<TraceRouteResponse> {
  const params = new URLSearchParams({
    max_depth: String(maxDepth),
  });
  return apiFetch<TraceRouteResponse>(
    `/api/v1/analysis/${projectId}/trace/${encodeURIComponent(nodeFqn)}?${params}`,
  );
}

export async function getTraceSummary(
  projectId: string,
  nodeFqn: string,
  maxDepth: number = 5,
): Promise<TraceSummaryResponse> {
  const params = new URLSearchParams({
    max_depth: String(maxDepth),
  });
  return apiFetch<TraceSummaryResponse>(
    `/api/v1/analysis/${projectId}/trace-summary/${encodeURIComponent(nodeFqn)}?${params}`,
  );
}

export async function getTraceChatHistory(
  projectId: string,
  nodeFqn: string,
): Promise<TraceChatHistoryResponse> {
  return apiFetch<TraceChatHistoryResponse>(
    `/api/v1/analysis/${projectId}/trace-chat/${encodeURIComponent(nodeFqn)}`,
  );
}

export async function sendTraceChatMessage(
  projectId: string,
  nodeFqn: string,
  question: string,
  maxDepth: number = 5,
): Promise<TraceChatSendResponse> {
  return apiFetch<TraceChatSendResponse>(
    `/api/v1/analysis/${projectId}/trace-chat/${encodeURIComponent(nodeFqn)}`,
    {
      method: "POST",
      body: JSON.stringify({ question, max_depth: maxDepth }),
    },
  );
}

export async function clearTraceChatHistory(
  projectId: string,
  nodeFqn: string,
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/analysis/${projectId}/trace-chat/${encodeURIComponent(nodeFqn)}`,
    { method: "DELETE" },
  );
}

export async function getShortestPath(
  projectId: string,
  fromFqn: string,
  toFqn: string,
  maxDepth: number = 10,
): Promise<PathFinderResponse> {
  const params = new URLSearchParams({
    from_fqn: fromFqn,
    to_fqn: toFqn,
    max_depth: String(maxDepth),
  });
  return apiFetch<PathFinderResponse>(
    `/api/v1/analysis/${projectId}/path?${params}`,
  );
}

export async function getCommunities(
  projectId: string,
): Promise<CommunitiesResponse> {
  return apiFetch<CommunitiesResponse>(
    `/api/v1/analysis/${projectId}/communities`,
  );
}

export async function getCircularDependencies(
  projectId: string,
  level: "module" | "class" = "module",
): Promise<CircularDependenciesResponse> {
  return apiFetch<CircularDependenciesResponse>(
    `/api/v1/analysis/${projectId}/circular-dependencies?level=${level}`,
  );
}

export async function getDeadCode(
  projectId: string,
  type: "function" | "class" = "function",
  minLoc: number = 5,
): Promise<DeadCodeResponse> {
  const params = new URLSearchParams({
    type,
    minLoc: String(minLoc),
  });
  return apiFetch<DeadCodeResponse>(
    `/api/v1/analysis/${projectId}/dead-code?${params}`,
  );
}

export async function getMetrics(
  projectId: string,
): Promise<MetricsResponse> {
  return apiFetch<MetricsResponse>(
    `/api/v1/analysis/${projectId}/metrics`,
  );
}

export async function getNodeDetails(
  projectId: string,
  nodeFqn: string,
): Promise<NodeDetailResponse> {
  return apiFetch<NodeDetailResponse>(
    `/api/v1/analysis/${projectId}/node/${encodeURIComponent(nodeFqn)}/details`,
  );
}

// ─── Connector endpoints (Phase 4A) ─────────────────────────────────────────

export async function createConnector(
  data: CreateConnectorRequest,
): Promise<ConnectorResponse> {
  return apiFetch<ConnectorResponse>("/api/v1/connectors", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function listConnectors(): Promise<ConnectorListResponse> {
  return apiFetch<ConnectorListResponse>("/api/v1/connectors");
}

export async function getConnector(id: string): Promise<ConnectorResponse> {
  return apiFetch<ConnectorResponse>(`/api/v1/connectors/${id}`);
}

export async function deleteConnector(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/connectors/${id}`, { method: "DELETE" });
}

export async function testConnector(id: string): Promise<ConnectorTestResponse> {
  return apiFetch<ConnectorTestResponse>(`/api/v1/connectors/${id}/test`, { method: "POST" });
}

export async function listRemoteRepos(
  connectorId: string,
  page: number = 1,
  perPage: number = 30,
  search?: string,
): Promise<RemoteRepoListResponse> {
  const params = new URLSearchParams({ page: String(page), per_page: String(perPage) });
  if (search) params.set("search", search);
  return apiFetch<RemoteRepoListResponse>(`/api/v1/connectors/${connectorId}/repos?${params.toString()}`);
}

export async function getRemoteRepo(
  connectorId: string,
  owner: string,
  repo: string,
): Promise<RemoteRepoResponse> {
  return apiFetch<RemoteRepoResponse>(`/api/v1/connectors/${connectorId}/repos/${owner}/${repo}`);
}

export async function listRemoteBranches(
  connectorId: string,
  owner: string,
  repo: string,
): Promise<BranchListResponse> {
  return apiFetch<BranchListResponse>(`/api/v1/connectors/${connectorId}/repos/${owner}/${repo}/branches`);
}

// ─── Repository endpoints (Phase 4A) ────────────────────────────────────────

export async function createRepository(data: CreateRepositoryRequest): Promise<RepositoryResponse> {
  return apiFetch<RepositoryResponse>("/api/v1/repositories", { method: "POST", body: JSON.stringify(data) });
}

export async function listRepositories(): Promise<RepositoryListResponse> {
  return apiFetch<RepositoryListResponse>("/api/v1/repositories");
}

export async function getRepository(id: string): Promise<RepositoryResponse> {
  return apiFetch<RepositoryResponse>(`/api/v1/repositories/${id}`);
}

export async function addBranch(
  repoId: string,
  branch: string,
): Promise<ProjectBranchResponse> {
  return apiFetch<ProjectBranchResponse>(`/api/v1/repositories/${repoId}/branches`, {
    method: "POST",
    body: JSON.stringify({ branch }),
  });
}

export async function deleteBranchProject(
  repoId: string,
  projectId: string,
): Promise<void> {
  return apiFetch<void>(`/api/v1/repositories/${repoId}/projects/${projectId}`, {
    method: "DELETE",
  });
}

export async function deleteRepository(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/repositories/${id}`, { method: "DELETE" });
}

export async function getCloneStatus(repoId: string): Promise<CloneStatusResponse> {
  return apiFetch<CloneStatusResponse>(`/api/v1/repositories/${repoId}/clone-status`);
}

export async function syncRepository(repoId: string): Promise<CloneStatusResponse> {
  return apiFetch<CloneStatusResponse>(`/api/v1/repositories/${repoId}/sync`, { method: "POST" });
}

export async function getEvolutionTimeline(repoId: string, branch: string): Promise<EvolutionTimelineResponse> {
  return apiFetch<EvolutionTimelineResponse>(`/api/v1/repositories/${repoId}/evolution?branch=${encodeURIComponent(branch)}`);
}

// ── Auth ──

export async function login(
  username: string,
  password: string
): Promise<LoginResponse> {
  const resp = await fetch(`${BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username, password }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body.detail || "Login failed");
  }
  return resp.json();
}

export async function getMe(): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/v1/auth/me");
}

export async function getSetupStatus(): Promise<SetupStatusResponse> {
  return apiFetch<SetupStatusResponse>("/api/v1/auth/setup-status");
}

export async function initialSetup(req: SetupRequest): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/v1/auth/setup", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

// ── User Management (Admin) ──

export async function listUsers(): Promise<UserResponse[]> {
  return apiFetch<UserResponse[]>("/api/v1/users");
}

export async function createUser(req: UserCreateRequest): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/v1/users", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function getUser(userId: string): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/api/v1/users/${userId}`);
}

export async function updateUser(
  userId: string,
  req: UserUpdateRequest
): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/api/v1/users/${userId}`, {
    method: "PUT",
    body: JSON.stringify(req),
  });
}

export async function deactivateUser(userId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/users/${userId}`, { method: "DELETE" });
}

// ── Annotations ──

export async function createAnnotation(
  projectId: string,
  nodeFqn: string,
  content: string
): Promise<AnnotationResponse> {
  return apiFetch<AnnotationResponse>(
    `/api/v1/projects/${projectId}/annotations`,
    {
      method: "POST",
      body: JSON.stringify({ node_fqn: nodeFqn, content }),
    }
  );
}

export async function listAnnotations(
  projectId: string,
  nodeFqn: string
): Promise<AnnotationResponse[]> {
  return apiFetch<AnnotationResponse[]>(
    `/api/v1/projects/${projectId}/annotations?node_fqn=${encodeURIComponent(nodeFqn)}`
  );
}

export async function updateAnnotation(
  annotationId: string,
  content: string
): Promise<AnnotationResponse> {
  return apiFetch<AnnotationResponse>(`/api/v1/annotations/${annotationId}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export async function deleteAnnotation(annotationId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/annotations/${annotationId}`, {
    method: "DELETE",
  });
}

// ── Tags ──

export async function addTag(
  projectId: string,
  nodeFqn: string,
  tagName: string
): Promise<TagResponse> {
  return apiFetch<TagResponse>(`/api/v1/projects/${projectId}/tags`, {
    method: "POST",
    body: JSON.stringify({ node_fqn: nodeFqn, tag_name: tagName }),
  });
}

export async function listTags(
  projectId: string,
  params: { node_fqn?: string; tag_name?: string }
): Promise<TagResponse[]> {
  const searchParams = new URLSearchParams();
  if (params.node_fqn) searchParams.set("node_fqn", params.node_fqn);
  if (params.tag_name) searchParams.set("tag_name", params.tag_name);
  return apiFetch<TagResponse[]>(
    `/api/v1/projects/${projectId}/tags?${searchParams}`
  );
}

export async function deleteTag(tagId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/tags/${tagId}`, { method: "DELETE" });
}

// ── Saved Views ──

export async function saveView(
  projectId: string,
  name: string,
  state: Record<string, unknown>,
  description?: string
): Promise<SavedViewResponse> {
  return apiFetch<SavedViewResponse>(
    `/api/v1/projects/${projectId}/views`,
    {
      method: "POST",
      body: JSON.stringify({ name, description, state }),
    }
  );
}

export async function listViews(
  projectId: string
): Promise<SavedViewListItem[]> {
  return apiFetch<SavedViewListItem[]>(
    `/api/v1/projects/${projectId}/views`
  );
}

export async function getView(viewId: string): Promise<SavedViewResponse> {
  return apiFetch<SavedViewResponse>(`/api/v1/views/${viewId}`);
}

export async function updateView(
  viewId: string,
  data: { name?: string; description?: string; state?: Record<string, unknown> }
): Promise<SavedViewResponse> {
  return apiFetch<SavedViewResponse>(`/api/v1/views/${viewId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteView(viewId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/views/${viewId}`, { method: "DELETE" });
}

// ── Export ──

export function getExportUrl(
  projectId: string,
  type: "nodes.csv" | "edges.csv" | "graph.json" | "impact.csv",
  params?: Record<string, string>
): string {
  const searchParams = new URLSearchParams(params);
  const token = getAuthToken();
  if (token) searchParams.set("token", token);
  return `${BASE_URL}/api/v1/export/${projectId}/${type}?${searchParams}`;
}

export function downloadExport(
  projectId: string,
  type: "nodes.csv" | "edges.csv" | "graph.json" | "impact.csv",
  params?: Record<string, string>
) {
  const url = getExportUrl(projectId, type, params);
  // Use fetch with auth header for download
  const token = getAuthToken();
  fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
    .then((resp) => resp.blob())
    .then((blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${projectId}_${type}`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
}

// ── Activity Feed ──

export async function getActivityFeed(params?: {
  limit?: number;
  user_id?: string;
  action?: string;
  category?: string;
  days?: number;
}): Promise<ActivityLogEntry[]> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.user_id) searchParams.set("user_id", params.user_id);
  if (params?.action) searchParams.set("action", params.action);
  if (params?.category) searchParams.set("category", params.category);
  if (params?.days) searchParams.set("days", String(params.days));
  return apiFetch<ActivityLogEntry[]>(`/api/v1/activity?${searchParams}`);
}

export async function getActivityStats(days?: number): Promise<ActivityStatsResponse> {
  const params = days ? `?days=${days}` : "";
  return apiFetch<ActivityStatsResponse>(`/api/v1/activity/stats${params}`);
}

// ── Phase 5a: PR Analysis API (repository-level) ──

export async function fetchRepoPrAnalyses(
  repoId: string,
  params?: { status?: string; risk?: string; limit?: number; offset?: number },
): Promise<PrAnalysisList> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.risk) searchParams.set("risk", params.risk);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return apiFetch<PrAnalysisList>(
    `/api/v1/repositories/${repoId}/pull-requests${qs ? `?${qs}` : ""}`,
  );
}

export async function fetchRepoPrAnalysis(
  repoId: string,
  analysisId: string,
): Promise<PrAnalysis> {
  return apiFetch<PrAnalysis>(
    `/api/v1/repositories/${repoId}/pull-requests/${analysisId}`,
  );
}

export async function fetchRepoPrImpact(
  repoId: string,
  analysisId: string,
): Promise<PrImpactDetail> {
  return apiFetch<PrImpactDetail>(
    `/api/v1/repositories/${repoId}/pull-requests/${analysisId}/impact`,
  );
}

export async function fetchRepoPrDrift(
  repoId: string,
  analysisId: string,
): Promise<PrDriftDetail> {
  return apiFetch<PrDriftDetail>(
    `/api/v1/repositories/${repoId}/pull-requests/${analysisId}/drift`,
  );
}

export async function reanalyzeRepoPr(
  repoId: string,
  analysisId: string,
): Promise<void> {
  return apiFetch<void>(
    `/api/v1/repositories/${repoId}/pull-requests/${analysisId}/reanalyze`,
    { method: "POST" },
  );
}

export async function deleteRepoPrAnalysis(
  repoId: string,
  analysisId: string,
): Promise<void> {
  return apiFetch<void>(
    `/api/v1/repositories/${repoId}/pull-requests/${analysisId}`,
    { method: "DELETE" },
  );
}

// ── Git Config (repository-level) ──

export async function fetchGitConfig(
  repoId: string,
): Promise<GitConfig | null> {
  try {
    return await apiFetch<GitConfig>(
      `/api/v1/repositories/${repoId}/git-config`,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function createGitConfig(
  repoId: string,
  body: {
    platform: string;
    repo_url: string;
    api_token: string;
    monitored_branches?: string[];
  },
): Promise<GitConfigCreateResponse> {
  return apiFetch<GitConfigCreateResponse>(
    `/api/v1/repositories/${repoId}/git-config`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function deleteGitConfig(repoId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/repositories/${repoId}/git-config`, {
    method: "DELETE",
  });
}

export async function fetchWebhookUrl(
  repoId: string,
): Promise<WebhookUrlInfo> {
  return apiFetch<WebhookUrlInfo>(
    `/api/v1/repositories/${repoId}/git-config/webhook-url`,
  );
}

export async function testGitConnectivity(
  repoId: string,
): Promise<{ status: string; username?: string; message?: string }> {
  return apiFetch<{ status: string; username?: string; message?: string }>(
    `/api/v1/repositories/${repoId}/git-config/test`,
    { method: "POST" },
  );
}

export interface EnableWebhooksResponse {
  webhook_url: string;
  webhook_secret: string;
  platform: string;
  monitored_branches: string[] | null;
  is_active: boolean;
  post_pr_comments: boolean;
  auto_registered: boolean;
  auto_register_error: string | null;
}

export async function enableWebhooks(
  repoId: string,
  opts: {
    monitorAll?: boolean;
    monitoredBranches?: string[];
    autoRegister?: boolean;
    postPrComments?: boolean;
  } = {},
): Promise<EnableWebhooksResponse> {
  return apiFetch<EnableWebhooksResponse>(
    `/api/v1/repositories/${repoId}/git-config/enable-webhooks`,
    {
      method: "POST",
      body: JSON.stringify({
        monitor_all_branches: opts.monitorAll ?? true,
        monitored_branches: opts.monitoredBranches ?? null,
        auto_register: opts.autoRegister ?? false,
        post_pr_comments: opts.postPrComments ?? false,
      }),
    },
  );
}

export async function updateGitConfig(
  repoId: string,
  updates: { post_pr_comments?: boolean },
): Promise<GitConfig> {
  return apiFetch<GitConfig>(
    `/api/v1/repositories/${repoId}/git-config`,
    {
      method: "PUT",
      body: JSON.stringify(updates),
    },
  );
}

export async function autoRegisterWebhook(
  repoId: string,
): Promise<{ success: boolean; error: string | null }> {
  return apiFetch<{ success: boolean; error: string | null }>(
    `/api/v1/repositories/${repoId}/git-config/auto-register-webhook`,
    { method: "POST" },
  );
}

export async function disableWebhooks(repoId: string): Promise<void> {
  return deleteGitConfig(repoId);
}

// ── API Keys (M4 endpoints, consumed by M5 UI) ──

export async function listApiKeys(): Promise<ApiKeyResponse[]> {
  return apiFetch<ApiKeyResponse[]>("/api/v1/api-keys");
}

export async function createApiKey(name: string): Promise<ApiKeyCreateResponse> {
  return apiFetch<ApiKeyCreateResponse>("/api/v1/api-keys", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function revokeApiKey(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/api-keys/${id}`, { method: "DELETE" });
}

// ── AI Usage (M5 endpoints) ──

export async function getAiUsageSummary(
  days: number = 30,
): Promise<UsageSummaryResponse> {
  return apiFetch<UsageSummaryResponse>(
    `/api/v1/admin/ai-usage?days=${days}`,
  );
}

// ── License Management ──

export async function getLicenseStatus(): Promise<LicenseStatusResponse> {
  return apiFetch<LicenseStatusResponse>("/api/v1/license/status");
}

export async function getInstallationId(): Promise<InstallationIdResponse> {
  return apiFetch<InstallationIdResponse>("/api/v1/license/installation-id");
}

export async function uploadLicense(file: File): Promise<LicenseStatusResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<LicenseStatusResponse>("/api/v1/license/upload", {
    method: "POST",
    body: formData,
  });
}

// ── System Info ──

export async function getSystemInfo(): Promise<SystemInfoResponse> {
  return apiFetch<SystemInfoResponse>("/api/v1/system/info");
}

// ── Email Config ──

export async function getEmailConfig(): Promise<EmailConfigResponse> {
  return apiFetch<EmailConfigResponse>("/api/v1/email/config");
}

export async function updateEmailConfig(data: EmailConfigUpdateRequest): Promise<EmailConfigResponse> {
  return apiFetch<EmailConfigResponse>("/api/v1/email/config", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function testSendEmail(to: string): Promise<TestSendResponse> {
  return apiFetch<TestSendResponse>("/api/v1/email/test-send", {
    method: "POST",
    body: JSON.stringify({ to }),
  });
}

// ── AI Config ──

export async function getAiConfig(): Promise<AiConfigResponse> {
  return apiFetch<AiConfigResponse>("/api/v1/ai/config");
}

export async function updateAiConfig(data: AiConfigUpdateRequest): Promise<AiConfigResponse> {
  return apiFetch<AiConfigResponse>("/api/v1/ai/config", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function getAiModels(): Promise<AiModelsListResponse> {
  return apiFetch<AiModelsListResponse>("/api/v1/ai/models");
}

export async function testAiConnection(data: AiTestConnectionRequest): Promise<AiTestConnectionResponse> {
  return apiFetch<AiTestConnectionResponse>("/api/v1/ai/test-connection", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ── Health Check ──

export interface HealthResponse {
  status: "healthy" | "unhealthy";
  services: Record<string, "up" | "down">;
}

export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}
