import type cytoscape from "cytoscape"

const KIND_COLORS: Record<string, string> = {
  MODULE: "#3B82F6",
  CLASS: "#22C55E",
  INTERFACE: "#14B8A6",
  FUNCTION: "#EAB308",
  TABLE: "#F97316",
  API_ENDPOINT: "#A855F7",
  ROUTE: "#A855F7",
  TRANSACTION: "#EC4899",
  MESSAGE_TOPIC: "#06B6D4",
  FIELD: "#6B7280",
  CONFIG_FILE: "#6B7280",
}

const LAYER_COLORS: Record<string, string> = {
  presentation: "#3B82F6",
  business: "#22C55E",
  data: "#F97316",
  utility: "#6B7280",
}

const DEFAULT_NODE_COLOR = "#6B7280"

const EDGE_STYLES: Record<string, { lineStyle: string; color: string }> = {
  CALLS: { lineStyle: "solid", color: "#6B7280" },
  DEPENDS_ON: { lineStyle: "dotted", color: "#9CA3AF" },
  READS: { lineStyle: "dashed", color: "#F97316" },
  WRITES: { lineStyle: "dashed", color: "#EF4444" },
  INHERITS: { lineStyle: "solid", color: "#3B82F6" },
  IMPLEMENTS: { lineStyle: "solid", color: "#14B8A6" },
  IMPORTS: { lineStyle: "dotted", color: "#D1D5DB" },
  CONTAINS: { lineStyle: "solid", color: "#E5E7EB" },
  INJECTS: { lineStyle: "solid", color: "#8B5CF6" },
}

export function buildStylesheet(
  colorBy: "kind" | "layer" = "kind"
): cytoscape.StylesheetJsonBlock[] {
  const styles: cytoscape.StylesheetJsonBlock[] = [
    {
      selector: "node",
      style: {
        label: "data(label)",
        "text-valign": "center",
        "text-halign": "center",
        "font-size": "11px",
        "font-family": "Inter, system-ui, sans-serif",
        color: "#1F2937",
        "text-outline-color": "#FFFFFF",
        "text-outline-width": 1.5,
        "background-color": DEFAULT_NODE_COLOR,
        width: "mapData(loc, 0, 5000, 30, 80)",
        height: "mapData(loc, 0, 5000, 30, 80)",
        "border-width": 1,
        "border-color": "#D1D5DB",
        "overlay-padding": "4px",
        "text-wrap": "ellipsis",
        "text-max-width": "80px",
      },
    },
    {
      selector: "node:parent",
      style: {
        "background-opacity": 0.08,
        "background-color": "#3B82F6",
        "border-width": 2,
        "border-color": "#93C5FD",
        "text-valign": "top",
        "text-halign": "center",
        "font-size": "12px",
        padding: "16px",
        shape: "roundrectangle",
        "text-wrap": "ellipsis",
        "text-max-width": "180px",
      },
    },
    {
      selector: "node:selected",
      style: {
        "border-width": 3,
        "border-color": "#2563EB",
        "background-color": "#DBEAFE",
        "overlay-color": "#3B82F6",
        "overlay-opacity": 0.15,
      },
    },
    {
      selector: "edge",
      style: {
        width: "mapData(weight, 1, 50, 1, 6)",
        "line-color": "#9CA3AF",
        "target-arrow-color": "#9CA3AF",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.8,
        "curve-style": "bezier",
        opacity: 0.7,
        label: "data(label)",
        "font-size": "9px",
        "text-rotation": "autorotate",
        color: "#6B7280",
        "text-background-color": "#FFFFFF",
        "text-background-opacity": 0.85,
        "text-background-padding": "2px",
        "text-background-shape": "roundrectangle",
      },
    },
    {
      selector: "edge:selected",
      style: {
        "line-color": "#2563EB",
        "target-arrow-color": "#2563EB",
        width: 3,
        opacity: 1,
      },
    },
    {
      selector: "node:active",
      style: {
        "overlay-color": "#3B82F6",
        "overlay-opacity": 0.2,
      },
    },
  ]

  if (colorBy === "kind") {
    for (const [kind, color] of Object.entries(KIND_COLORS)) {
      styles.push({
        selector: `node[kind = "${kind}"]`,
        style: { "background-color": color, "border-color": color },
      })
    }
  } else {
    for (const [layer, color] of Object.entries(LAYER_COLORS)) {
      styles.push({
        selector: `node[layer = "${layer}"]`,
        style: { "background-color": color, "border-color": color },
      })
    }
  }

  for (const [kind, cfg] of Object.entries(EDGE_STYLES)) {
    styles.push({
      selector: `edge[kind = "${kind}"]`,
      style: {
        "line-style": cfg.lineStyle as cytoscape.Css.LineStyle,
        "line-color": cfg.color,
        "target-arrow-color": cfg.color,
      },
    })
  }

  // Transaction view: entry-point and terminal-node class-based styles
  styles.push(
    {
      selector: ".entry-point",
      style: {
        "border-width": 3,
        "border-color": "#2563EB",
        width: 50,
        height: 50,
        "font-weight": "bold",
      },
    },
    {
      selector: ".terminal-node",
      style: {
        "border-width": 3,
        "border-color": "#F97316",
        "border-style": "double" as cytoscape.Css.LineStyle,
      },
    },
    {
      selector: ".data-edge",
      style: {
        "line-style": "dashed" as cytoscape.Css.LineStyle,
        "line-color": "#F97316",
        "target-arrow-color": "#F97316",
      },
    },
    {
      selector: ".call-edge",
      style: {
        "line-style": "solid" as cytoscape.Css.LineStyle,
        "line-color": "#6B7280",
        "target-arrow-color": "#6B7280",
      },
    }
  )

  // Annotated nodes — blue border indicator
  styles.push({
    selector: "node.has-annotations",
    style: {
      "border-width": 2,
      "border-color": "#3b82f6",
      "border-style": "solid" as cytoscape.Css.LineStyle,
    },
  })

  // Deprecated nodes — faded style
  styles.push({
    selector: "node.tag-deprecated",
    style: {
      opacity: 0.5,
      "border-width": 2,
      "border-color": "#EF4444",
      "border-style": "dashed" as cytoscape.Css.LineStyle,
    },
  })

  // Critical path nodes — emphasized
  styles.push({
    selector: "node.tag-critical-path",
    style: {
      "border-width": 3,
      "border-color": "#7c3aed",
      "border-style": "double" as cytoscape.Css.LineStyle,
    },
  })

  // Security-sensitive nodes
  styles.push({
    selector: "node.tag-security-sensitive",
    style: {
      "border-width": 2,
      "border-color": "#f97316",
      "border-style": "dashed" as cytoscape.Css.LineStyle,
    },
  })

  return styles
}

export const defaultStylesheet = buildStylesheet("kind")
export const layerStylesheet = buildStylesheet("layer")
