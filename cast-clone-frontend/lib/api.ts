import type {
  AnalysisStatusResponse,
  AnalysisTriggerResponse,
  AggregatedEdgeListResponse,
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
  EvolutionTimelineResponse,
  GraphEdgeListResponse,
  GraphNodeListResponse,
  GraphSearchResponse,
  ImpactAnalysisResponse,
  MethodListResponse,
  MetricsResponse,
  ModuleListResponse,
  NodeDetailResponse,
  NodeWithNeighborsResponse,
  PathFinderResponse,
  ProjectListResponse,
  ProjectResponse,
  RemoteRepoListResponse,
  RemoteRepoResponse,
  RepositoryListResponse,
  RepositoryResponse,
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
} from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  const needsContentType = options.body !== undefined && options.body !== null;
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
