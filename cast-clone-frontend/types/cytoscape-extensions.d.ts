// Type declarations for Cytoscape extensions that lack @types packages

declare module "react-cytoscapejs" {
  import cytoscape from "cytoscape";
  import { Component } from "react";

  interface CytoscapeComponentProps {
    id?: string;
    cy?: (cy: cytoscape.Core) => void;
    style?: React.CSSProperties;
    elements: cytoscape.ElementDefinition[];
    layout?: cytoscape.LayoutOptions;
    stylesheet?: cytoscape.Stylesheet[];
    className?: string;
    zoom?: number;
    pan?: cytoscape.Position;
    minZoom?: number;
    maxZoom?: number;
    zoomingEnabled?: boolean;
    userZoomingEnabled?: boolean;
    panningEnabled?: boolean;
    userPanningEnabled?: boolean;
    boxSelectionEnabled?: boolean;
    autoungrabify?: boolean;
    autounselectify?: boolean;
    autolock?: boolean;
  }

  export default class CytoscapeComponent extends Component<CytoscapeComponentProps> {
    static normalizeElements(
      elements:
        | cytoscape.ElementDefinition[]
        | { nodes: cytoscape.ElementDefinition[]; edges: cytoscape.ElementDefinition[] }
    ): cytoscape.ElementDefinition[];
  }
}

declare module "cytoscape-dagre" {
  import cytoscape from "cytoscape";
  const register: (cs: typeof cytoscape) => void;
  export default register;
}

declare module "cytoscape-fcose" {
  import cytoscape from "cytoscape";
  const register: (cs: typeof cytoscape) => void;
  export default register;
}

declare module "cytoscape-expand-collapse" {
  import cytoscape from "cytoscape";
  const register: (cs: typeof cytoscape) => void;
  export default register;
}
