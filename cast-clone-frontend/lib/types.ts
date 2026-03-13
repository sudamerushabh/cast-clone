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
  status: "pending" | "running" | "completed" | "failed";
  duration_ms?: number;
}

export interface AnalysisStatusResponse {
  project_id: string;
  status: string;
  current_stage: string | null;
  progress?: number;
  stages?: AnalysisStageStatus[];
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
