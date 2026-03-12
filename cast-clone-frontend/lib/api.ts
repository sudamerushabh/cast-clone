import type {
  AnalysisStatusResponse,
  AnalysisTriggerResponse,
  AggregatedEdgeListResponse,
  ClassListResponse,
  CodeViewerResponse,
  CreateProjectRequest,
  GraphEdgeListResponse,
  GraphNodeListResponse,
  GraphSearchResponse,
  MethodListResponse,
  ModuleListResponse,
  NodeWithNeighborsResponse,
  ProjectListResponse,
  ProjectResponse,
  TransactionDetailResponse,
  TransactionListResponse,
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

// ─── Base fetch helper ──────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
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
