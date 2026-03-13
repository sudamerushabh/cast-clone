import cytoscape from "cytoscape"
import dagre from "cytoscape-dagre"
import fcose from "cytoscape-fcose"
import expandCollapse from "cytoscape-expand-collapse"

let registered = false

export function ensureCytoscapeExtensions(): void {
  if (registered) return
  cytoscape.use(dagre)
  cytoscape.use(fcose)
  cytoscape.use(expandCollapse)
  registered = true
}
