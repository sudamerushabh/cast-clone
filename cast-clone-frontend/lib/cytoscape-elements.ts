import type cytoscape from "cytoscape"
import type {
  GraphNodeResponse,
  GraphEdgeResponse,
  ModuleResponse,
  AggregatedEdgeResponse,
  TransactionDetailResponse,
} from "@/lib/types"

type ElementDefinition = cytoscape.ElementDefinition

export function modulesToElements(
  modules: ModuleResponse[],
  edges: AggregatedEdgeResponse[]
): ElementDefinition[] {
  const elements: ElementDefinition[] = []

  for (const mod of modules) {
    elements.push({
      group: "nodes",
      data: {
        id: mod.fqn,
        label: mod.name,
        kind: mod.kind,
        language: mod.language ?? undefined,
        loc: mod.loc ?? 0,
        path: undefined,
        line: undefined,
        layer: (mod.properties?.layer as string) ?? undefined,
        drillable: true,
        drillLevel: "module",
      },
    })
  }

  for (const edge of edges) {
    elements.push({
      group: "edges",
      data: {
        id: `edge-${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
        weight: edge.weight,
        kind: "DEPENDS_ON",
        label: edge.weight > 1 ? String(edge.weight) : undefined,
      },
    })
  }

  return elements
}

export function classesToElements(
  classes: GraphNodeResponse[],
  parentFqn: string
): ElementDefinition[] {
  return classes.map((cls) => ({
    group: "nodes" as const,
    data: {
      id: cls.fqn,
      label: cls.name,
      kind: cls.kind,
      parent: parentFqn,
      language: cls.language ?? undefined,
      loc: cls.loc ?? 0,
      complexity: cls.complexity ?? 0,
      path: cls.path ?? undefined,
      line: cls.line ?? undefined,
      layer: (cls.properties?.layer as string) ?? undefined,
      drillable: true,
      drillLevel: "class",
    },
  }))
}

export function methodsToElements(
  methods: GraphNodeResponse[],
  parentFqn: string
): ElementDefinition[] {
  return methods.map((fn) => ({
    group: "nodes" as const,
    data: {
      id: fn.fqn,
      label: fn.name,
      kind: fn.kind,
      parent: parentFqn,
      language: fn.language ?? undefined,
      loc: fn.loc ?? 0,
      complexity: fn.complexity ?? 0,
      path: fn.path ?? undefined,
      line: fn.line ?? undefined,
      drillable: false,
      drillLevel: "method",
    },
  }))
}

export function aggregatedEdgesToClassElements(
  edges: AggregatedEdgeResponse[]
): ElementDefinition[] {
  const elements: ElementDefinition[] = []

  for (const edge of edges) {
    elements.push({
      group: "edges",
      data: {
        id: `edge-${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
        weight: edge.weight,
        kind: "CALLS",
        label: edge.weight > 1 ? String(edge.weight) : undefined,
      },
    })
  }

  return elements
}

export function edgesToElements(
  edges: GraphEdgeResponse[],
  visibleFqns: Set<string>
): ElementDefinition[] {
  const elements: ElementDefinition[] = []

  for (const edge of edges) {
    if (
      !visibleFqns.has(edge.source_fqn) ||
      !visibleFqns.has(edge.target_fqn)
    ) {
      continue
    }

    elements.push({
      group: "edges",
      data: {
        id: `edge-${edge.source_fqn}-${edge.target_fqn}-${edge.kind}`,
        source: edge.source_fqn,
        target: edge.target_fqn,
        kind: edge.kind,
        weight: 1,
        confidence: edge.confidence,
      },
    })
  }

  return elements
}

export function getPerformanceTier(
  nodeCount: number
): "full" | "no-animation" | "simplified" | "force-drilldown" {
  if (nodeCount < 500) return "full"
  if (nodeCount < 2000) return "no-animation"
  if (nodeCount < 5000) return "simplified"
  return "force-drilldown"
}

export function transactionToElements(
  detail: TransactionDetailResponse,
  entryPointFqn: string | null
): ElementDefinition[] {
  const elements: ElementDefinition[] = []

  // Build set of FQNs with outgoing WRITES/READS edges (terminal nodes)
  const terminalFqns = new Set<string>()
  for (const edge of detail.edges) {
    if (edge.kind === "WRITES" || edge.kind === "READS") {
      terminalFqns.add(edge.source_fqn)
    }
  }

  // Find entry point: target of STARTS_AT edge, fallback to provided FQN
  let resolvedEntryFqn: string | null = null
  for (const edge of detail.edges) {
    if (edge.kind === "STARTS_AT") {
      resolvedEntryFqn = edge.target_fqn
      break
    }
  }
  if (!resolvedEntryFqn) {
    resolvedEntryFqn = entryPointFqn
  }

  const nodeFqns = new Set(detail.nodes.map((n) => n.fqn))

  for (const node of detail.nodes) {
    if (node.kind?.toUpperCase() === "TRANSACTION") {
      continue
    }

    const classes: string[] = []
    if (node.fqn === resolvedEntryFqn) {
      classes.push("entry-point")
    }
    if (terminalFqns.has(node.fqn)) {
      classes.push("terminal-node")
    }

    elements.push({
      group: "nodes",
      data: {
        id: node.fqn,
        label: node.name,
        kind: node.kind,
        language: node.language,
        path: node.path,
        line: node.line,
        loc: node.loc,
        complexity: node.complexity,
        ...node.properties,
      },
      classes: classes.length > 0 ? classes.join(" ") : undefined,
    })
  }

  const META_EDGE_KINDS = new Set(["STARTS_AT", "ENDS_AT", "INCLUDES"])

  for (const edge of detail.edges) {
    if (META_EDGE_KINDS.has(edge.kind)) continue
    if (!nodeFqns.has(edge.source_fqn) || !nodeFqns.has(edge.target_fqn)) continue

    elements.push({
      group: "edges",
      data: {
        id: `${edge.source_fqn}->${edge.target_fqn}:${edge.kind}`,
        source: edge.source_fqn,
        target: edge.target_fqn,
        kind: edge.kind,
        confidence: edge.confidence,
        label: edge.kind,
        weight: 1,
      },
      classes: edge.kind === "WRITES" || edge.kind === "READS" ? "data-edge" : "call-edge",
    })
  }

  return elements
}
