import cytoscape from "cytoscape"
import dagre from "cytoscape-dagre"
import fcose from "cytoscape-fcose"
import expandCollapse from "cytoscape-expand-collapse"

let registered = false

export function ensureCytoscapeExtensions(): void {
  if (registered || typeof window === "undefined") return
  cytoscape.use(dagre)
  cytoscape.use(fcose)
  cytoscape.use(expandCollapse)

  // cytoscape-svg accesses `window` at import time — lazy-load it
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const cytoscapeSvg = require("cytoscape-svg")
    cytoscape.use(cytoscapeSvg)
  } catch {
    // SVG export unavailable in SSR
  }

  registered = true
}
