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

export interface AnalysisStatusResponse {
  project_id: string;
  status: string;
  current_stage: string | null;
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
