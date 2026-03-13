import type cytoscape from "cytoscape"
import type {
  ArchitectureResponse,
  GraphNodeResponse,
  GraphEdgeResponse,
  ModuleResponse,
  AggregatedEdgeResponse,
  TransactionDetailResponse,
} from "@/lib/types"

type ElementDefinition = cytoscape.ElementDefinition

/** Return the last dot-separated segment of a name for compact display.
 *  e.g. "org.training.user.service.implementation" → "implementation"
 *       "FundTransferController"                   → "FundTransferController"
 */
function shortLabel(name: string): string {
  if (!name) return name
  const parts = name.split(".")
  return parts[parts.length - 1]
}

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
        label: shortLabel(mod.name),
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
    const kind = edge.kind ?? "DEPENDS_ON"
    elements.push({
      group: "edges",
      data: {
        id: `edge-${edge.source}-${edge.target}-${kind}`,
        source: edge.source,
        target: edge.target,
        weight: edge.weight,
        kind,
        label: edge.weight > 1 ? `${kind} (${edge.weight})` : kind,
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
    const kind = edge.kind ?? "CALLS"
    elements.push({
      group: "edges",
      data: {
        id: `edge-${edge.source}-${edge.target}-${kind}`,
        source: edge.source,
        target: edge.target,
        weight: edge.weight,
        kind,
        label: edge.weight > 1 ? `${kind} (${edge.weight})` : kind,
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

function _buildTechSubtitle(
  classCount: number,
  endpointCount: number,
  locTotal: number,
  tableCount: number
): string {
  const parts: string[] = []
  if (classCount > 0) parts.push(`${classCount} classes`)
  if (endpointCount > 0) parts.push(`${endpointCount} endpoints`)
  if (tableCount > 0) parts.push(`${tableCount} tables`)
  if (locTotal > 0) parts.push(`${locTotal} LOC`)
  return parts.join(" · ")
}

export function architectureToElements(
  data: ArchitectureResponse
): ElementDefinition[] {
  const elements: ElementDefinition[] = []

  for (const layer of data.layers) {
    // Layer node (compound parent)
    elements.push({
      group: "nodes",
      data: {
        id: layer.fqn,
        label: layer.name,
        kind: "LAYER",
        drillable: false,
        drillLevel: undefined,
      },
    })

    // Technology nodes (children of layer)
    for (const tech of layer.technologies) {
      elements.push({
        group: "nodes",
        data: {
          id: tech.fqn,
          label: tech.name,
          kind: "COMPONENT",
          parent: layer.fqn,
          category: tech.category,
          language: tech.language ?? undefined,
          layer: layer.name,
          loc: tech.loc_total,
          subtitle: _buildTechSubtitle(
            tech.class_count,
            tech.endpoint_count,
            tech.loc_total,
            tech.table_count
          ),
          classCount: tech.class_count,
          endpointCount: tech.endpoint_count,
          tableCount: tech.table_count,
          drillable: tech.class_count > 0,
          drillLevel: "module",
        },
      })
    }
  }

  // Links between technology nodes
  for (const link of data.links) {
    const kindLabel = link.kinds.join(", ")
    elements.push({
      group: "edges",
      data: {
        id: `arch-edge-${link.source}-${link.target}`,
        source: link.source,
        target: link.target,
        weight: link.weight,
        kind: link.kinds[0] ?? "DEPENDS_ON",
        label: link.weight > 1 ? `${kindLabel} (${link.weight})` : kindLabel,
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
      classes:
        edge.kind === "WRITES" || edge.kind === "READS"
          ? "data-edge"
          : edge.kind === "IMPLEMENTS"
            ? "impl-edge"
            : "call-edge",
    })
  }

  return elements
}
