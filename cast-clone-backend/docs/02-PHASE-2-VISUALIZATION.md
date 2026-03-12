# Phase 2 — Rich Visualization & Navigation (Revised)

**Timeline:** Months 3–5
**Goal:** Make the graph explorable and useful for real architecture decisions
**Last Updated:** Simplified based on research — ship fast, iterate later

---

## Overview

Phase 1 proves the analysis works. Phase 2 makes it usable. Users need to navigate from module-level overview down to individual classes, trace transaction flows, and understand dependencies — all without drowning in a 10,000-node hairball.

The guiding principle: **3 views, 3 levels, lazy loading.** No pre-computation, no complex state management, no exotic layouts. Use what Cytoscape.js gives us out of the box.

---

## 1. Technology: Cytoscape.js

### Why Cytoscape.js (Confirmed by Research)

- Purpose-built for graph/network visualization — not a charting library repurposed for graphs
- Handles thousands of nodes with canvas rendering, WebGL extension available for 10K+
- Native support for **compound nodes** (nodes containing other nodes) — essential for drill-down
- MIT license, used in commercial and open-source production systems
- Rich extension ecosystem: expand-collapse, dagre layout, fcose layout, context menus, navigator
- Official React wrapper: `react-cytoscapejs` from Plotly

### Why Not Alternatives

| Library | Why Not |
|---------|---------|
| React Flow | Designed for workflow editors/node-based UIs, not large graph analysis |
| D3.js | Too low-level — thousands of lines to replicate what Cytoscape gives for free |
| Sigma.js | Fast but no compound nodes, less feature-rich |
| KeyLines/yFiles/Ogma | Commercial, expensive, unnecessary for our needs |

### Core Dependencies

```bash
npm install cytoscape react-cytoscapejs
npm install cytoscape-dagre          # hierarchical layout
npm install cytoscape-fcose          # force-directed layout (best CoSE variant)
npm install cytoscape-expand-collapse # compound node expand/collapse
npm install cytoscape-popper         # tooltips on hover
```

### Layout Algorithms (Use Existing, Don't Build Custom)

| View | Layout | Package | Direction |
|------|--------|---------|-----------|
| Architecture view | Dagre (hierarchical) | `cytoscape-dagre` | Top-to-bottom |
| Transaction/flow view | Dagre (hierarchical) | `cytoscape-dagre` | Left-to-right |
| Dependency/module view | fCoSE (force-directed) | `cytoscape-fcose` | Auto |

**fCoSE** is the latest and fastest version of the CoSE compound spring embedder algorithm. It produces the best results for force-directed layouts and works natively with compound nodes. Use it as the default for any non-hierarchical view.

**Dagre** is a traditional hierarchical layout suitable for DAGs and trees. Use it when the graph has clear directional flow (architecture layers top-to-bottom, transaction flows left-to-right).

That's it. Two layout algorithms cover all our Phase 2 needs.

---

## 2. Three Levels of Granularity (Not Five)

Start simple. Three levels covers 90% of what users need:

| Level | Shows | How Loaded |
|-------|-------|------------|
| Level 1 | Modules / Packages | Initial load — one Neo4j query |
| Level 2 | Classes / Interfaces within a module | On drill-down — one Neo4j query |
| Level 3 | Methods / Functions within a class | On drill-down — one Neo4j query |

Levels 4-5 (individual fields, parameters, local variables) can be added later if users ask for them. In practice, most architecture decisions happen at the module and class level.

### Lazy Loading (No Pre-Computation)

Don't pre-compute an aggregation hierarchy during analysis. Instead, compute on-demand:

**Initial load — Level 1 (modules):**
```cypher
MATCH (app:Application {name: $appName})-[:CONTAINS]->(m:Module)
RETURN m.fqn, m.name, m.loc, m.file_count, m.language
```

**Drill into a module — Level 2 (classes):**
```cypher
MATCH (m:Module {fqn: $moduleFqn})-[:CONTAINS]->(c:Class)
RETURN c.fqn, c.name, c.loc, c.complexity, c.language, c.annotations
```

**Drill into a class — Level 3 (methods):**
```cypher
MATCH (c:Class {fqn: $classFqn})-[:CONTAINS]->(f:Function)
RETURN f.fqn, f.name, f.params, f.return_type, f.complexity, f.loc
```

**Aggregated edges between modules (on-demand):**
```cypher
MATCH (m1:Module {fqn: $module1})-[:CONTAINS]->(:Class)-[:CALLS|DEPENDS_ON]->(:Class)<-[:CONTAINS]-(m2:Module)
WHERE m1 <> m2
WITH m1.fqn AS source, m2.fqn AS target, count(*) AS weight
RETURN source, target, weight
```

Each query runs in < 500ms for codebases under 1M LOC. No batch pre-computation needed.

### How Drill-Down Works

Using Cytoscape's compound nodes + the `cytoscape-expand-collapse` extension:

1. **Modules are compound nodes** — they visually contain their classes as children
2. **Initial view** shows modules as collapsed compound nodes with aggregated edges between them
3. **Double-click a module** → expand it to reveal the classes inside
4. **Double-click a class** → fetch its methods from the API and add them as child nodes
5. **Breadcrumb bar** tracks the drill-down path: `Application > com.app.user > UserService`

```javascript
// Register expand-collapse extension
import expandCollapse from 'cytoscape-expand-collapse';
cytoscape.use(expandCollapse);

// Initialize with options
const api = cy.expandCollapse({
  layoutBy: { name: 'dagre', animate: true },
  fisheye: false,
  animate: true,
  animationDuration: 300,
  cueEnabled: true,
  expandCollapseCuePosition: 'top-left',
});

// Programmatic expand on double-click
cy.on('dbltap', 'node.cy-expand-collapse-collapsed-node', (event) => {
  api.expand(event.target);
});
```

### Note on expand-collapse Bugs

Research found some reported edge bugs with the `cytoscape-expand-collapse` extension when dealing with deeply nested collapsed structures. Mitigation:

- Limit nesting to 2 levels of compound nodes in the initial view
- When drilling deeper (Level 3), fetch and render as a separate subgraph rather than nesting further
- Test thoroughly with our real graph data before shipping

---

## 3. Three Core Views

### Architecture View

**Purpose:** See the layered structure of the application.
**Layout:** Dagre, top-to-bottom.
**What it shows:** Modules grouped by layer (Presentation → Business → Data) with dependency edges flowing downward.

```javascript
cy.layout({
  name: 'dagre',
  rankDir: 'TB',        // top to bottom
  nodeSep: 50,
  rankSep: 80,
  animate: true,
}).run();
```

**How layers are shown:**
- Color-code modules by their assigned layer (from Phase 1 framework plugin classification)
- Presentation modules = blue, Business = green, Data = orange, Utility = gray
- Edge thickness = number of calls between modules (weight from aggregated edge query)

**No custom "layer bands" or horizontal grouping in Phase 2.** Just color-coding and the natural dagre layout will group modules by dependency direction. Users can visually see the architecture without us building a custom layout.

### Dependency View

**Purpose:** See how modules/classes relate to each other, spot clusters and coupling.
**Layout:** fCoSE, force-directed.
**What it shows:** Modules or classes as nodes, with dependency edges pulling related nodes together and pushing unrelated ones apart.

```javascript
cy.layout({
  name: 'fcose',
  quality: 'default',
  randomize: true,
  animate: true,
  animationDuration: 500,
  nodeRepulsion: 4500,
  idealEdgeLength: 100,
}).run();
```

**Key insight:** Force-directed layout naturally reveals clusters — tightly connected modules cluster together, loosely connected ones drift apart. This gives users an instant visual read on modularity without any explicit clustering algorithm in the UI. (The Louvain communities from Phase 1 Stage 7 can be used to color-code nodes, but the layout itself reveals structure.)

### Transaction View

**Purpose:** Trace an end-to-end flow from API entry point to database.
**Layout:** Dagre, left-to-right.
**What it shows:** The call chain for a specific transaction, from controller through services to repositories and tables.

```javascript
cy.layout({
  name: 'dagre',
  rankDir: 'LR',        // left to right
  nodeSep: 30,
  rankSep: 60,
  animate: true,
}).run();
```

**Transaction selection:** A dropdown/searchable list of all discovered transactions (from Phase 1 Stage 9). User selects a transaction, we fetch its nodes and edges from Neo4j and render the flow.

```cypher
MATCH (t:Transaction {name: $txnName})-[:INCLUDES]->(f)
WITH t, collect(f) AS functions
MATCH (f1)-[r:CALLS]->(f2)
WHERE f1 IN functions AND f2 IN functions
RETURN f1, f2, r
```

---

## 4. Interaction Patterns (Keep It Simple)

### Navigation
- **Click** a node → select it, show properties panel
- **Double-click** a compound node → expand/drill down
- **Mouse wheel** → zoom in/out
- **Click-drag** on canvas → pan
- **Click-drag** a node → move it

### Properties Panel (Right Sidebar)

When a node is selected, show:
- **Name** and fully qualified name
- **Type** (class, interface, function, table, endpoint)
- **File path** and line number (clickable to open code viewer)
- **Metrics:** LOC, complexity, fan-in, fan-out
- **Connections:** "Called by N functions", "Calls M functions", "Reads K tables"
- **Tags/annotations** (from Phase 4, just show placeholder now)

Keep it as a simple React component reading from the Cytoscape node's `data()` property. No separate API call needed — the data is already in the graph.

### Search

Global search bar (Ctrl+K / Cmd+K):
- Calls the Neo4j full-text index
- Results grouped by type (Classes, Functions, Tables, Endpoints)
- Click a result → center the graph on that node and select it
- If the node isn't visible (it's inside a collapsed compound), expand the parent first

```
GET /api/v1/search/{project_id}?q=UserService&limit=20
```

Returns: `[{fqn, name, type, file, line, score}]`

### Filtering

Simple sidebar checkboxes:
- **By node type:** Classes, Interfaces, Functions, Tables, Endpoints (toggle visibility)
- **By language:** Java, TypeScript, Python, C# (toggle visibility)

Implementation: use Cytoscape's built-in selectors to show/hide nodes:
```javascript
// Hide all function nodes
cy.nodes('[kind = "FUNCTION"]').hide();
// Show them again
cy.nodes('[kind = "FUNCTION"]').show();
```

No complex filter state management needed. Cytoscape handles visibility natively.

---

## 5. Source Code Viewer

When a user clicks a node and then clicks "View Source" in the properties panel, show the code:

- **Monaco Editor** in a bottom or right split panel, read-only mode
- Load the file from the filesystem via API
- Highlight the specific function/class at the relevant line
- Syntax highlighting based on language

```
GET /api/v1/code/{project_id}?file=src/main/java/com/app/UserService.java&line=42&context=30
```

Returns: `{content: "...", language: "java", startLine: 12, highlightLine: 42}`

Keep this simple — just a read-only code viewer. No click-to-navigate-from-code-to-graph in Phase 2. That's a Phase 3+ feature.

---

## 6. Frontend Architecture

### Keep It Simple

```
src/
  components/
    GraphView/
      GraphView.tsx          # Main Cytoscape wrapper
      GraphToolbar.tsx       # View switcher, layout controls, zoom buttons
      NodeProperties.tsx     # Right sidebar panel
      TransactionSelector.tsx # Dropdown for transaction view
    Search/
      SearchBar.tsx          # Cmd+K search
      SearchResults.tsx      # Results dropdown
    CodeViewer/
      CodeViewer.tsx         # Monaco editor wrapper
    Layout/
      AppLayout.tsx          # Main page layout (graph + panels)
      Sidebar.tsx            # Left sidebar with filters
  hooks/
    useGraph.ts              # Fetch graph data from API
    useSearch.ts             # Search API integration
  api/
    graphApi.ts              # API client functions
  types/
    graph.ts                 # TypeScript types for nodes, edges
  App.tsx
  main.tsx
```

### State Management: Just React

Use React's built-in hooks. No Redux, no Zustand, no MobX.

```typescript
// App-level state
const [currentProject, setCurrentProject] = useState<Project | null>(null);
const [currentView, setCurrentView] = useState<'architecture' | 'dependency' | 'transaction'>('architecture');
const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
const [searchQuery, setSearchQuery] = useState('');
const [selectedTransaction, setSelectedTransaction] = useState<string | null>(null);
const [filters, setFilters] = useState<FilterState>(defaultFilters);
const [codeViewerFile, setCodeViewerFile] = useState<string | null>(null);
```

Cytoscape manages its own graph state internally. React just:
1. Fetches data from the API
2. Passes elements to `<CytoscapeComponent>`
3. Listens to Cytoscape events (click, dblclick) and updates React state
4. Renders the properties panel and search results based on React state

That's it. If state management becomes painful later (Phase 4+ with collaboration features), upgrade to Zustand then. Don't preoptimize.

### Data Fetching

Simple pattern: fetch on view change or drill-down, cache in a `Map`.

```typescript
const graphCache = useRef(new Map<string, GraphData>());

async function loadLevel(parentFqn: string, level: number) {
  const cacheKey = `${parentFqn}:${level}`;
  if (graphCache.current.has(cacheKey)) {
    return graphCache.current.get(cacheKey);
  }
  const data = await graphApi.getChildren(projectId, parentFqn, level);
  graphCache.current.set(cacheKey, data);
  return data;
}
```

No SWR, no React Query, no complex caching layer. A `Map` in a `useRef` is enough for Phase 2.

---

## 7. API Endpoints (Phase 2)

```
# Navigation / Drill-down
GET /api/v1/graphs/{project}/modules
    → Returns all modules with aggregated metrics

GET /api/v1/graphs/{project}/modules/{fqn}/classes
    → Returns classes within a module

GET /api/v1/graphs/{project}/classes/{fqn}/methods
    → Returns methods within a class

GET /api/v1/graphs/{project}/edges
    ?level=module                    → Aggregated edges between modules
    ?level=class&parent={moduleFqn}  → Class-level edges within/between modules

# Views
GET /api/v1/graphs/{project}/transactions
    → List all discovered transactions (name, method, path, depth)

GET /api/v1/graphs/{project}/transactions/{id}
    → Full call graph for a specific transaction

# Search
GET /api/v1/search/{project}?q=...&type=class,function&limit=20
    → Full-text search results

# Code
GET /api/v1/code/{project}?file=...&line=...&context=30
    → Source code with context
```

That's 7 endpoints. No need for the 15+ endpoints in the original plan.

---

## 8. Graph Export

Simple exports — don't build a report generator yet (that's Phase 4):

- **PNG:** `cy.png({full: true, scale: 2})` — built into Cytoscape
- **SVG:** `cy.svg({full: true})` — built into Cytoscape (via `cytoscape-svg` extension)
- **JSON:** Dump current elements as JSON — `cy.json().elements`

Three buttons in the toolbar. Each is a one-liner using Cytoscape's built-in methods.

---

## 9. Performance Guidelines

| Node Count | Strategy |
|-----------|----------|
| < 500 | Render everything, full animation |
| 500 – 2,000 | Disable animation during layout, enable after |
| 2,000 – 5,000 | Simplify edge rendering (straight lines, no curves), reduce label rendering |
| 5,000+ | Force user to drill down — don't render this many nodes at once |

**Practical approach:** Most module-level views will have 10-100 nodes. Class-level views within a module will have 10-200 nodes. Transaction views will have 5-50 nodes. We're unlikely to hit performance problems in Phase 2.

If a module has 500+ classes, paginate the results and show a "this module has 500 classes — showing top 50 by complexity" message with a "show all" option.

Don't build WebGL rendering, node virtualization, or level-of-detail systems in Phase 2. Build them when (if) you actually hit performance problems.

---

## 10. Deliverables Checklist

### Graph Visualization
- [ ] Cytoscape.js integration with `react-cytoscapejs`
- [ ] Dagre layout (hierarchical, top-to-bottom and left-to-right)
- [ ] fCoSE layout (force-directed)
- [ ] Compound nodes with expand-collapse extension
- [ ] Node styling (color by type/layer, size by LOC/complexity)
- [ ] Edge styling (thickness by weight, dashed for READS, solid for CALLS)
- [ ] Zoom, pan, node drag

### Views
- [ ] Architecture view (dagre TB, modules color-coded by layer)
- [ ] Dependency view (fcose, modules/classes with dependency edges)
- [ ] Transaction view (dagre LR, call chain for selected transaction)
- [ ] View switcher in toolbar

### Navigation & Interaction
- [ ] Double-click to drill down (expand compound node or fetch children)
- [ ] Click to select → show properties panel
- [ ] Breadcrumb bar for drill-down path
- [ ] Back button to drill up

### Panels
- [ ] Node properties panel (right sidebar)
- [ ] Source code viewer panel (Monaco Editor, bottom split)
- [ ] Transaction selector dropdown

### Search & Filter
- [ ] Global search bar (Cmd+K) with full-text results
- [ ] Click search result → navigate to node
- [ ] Filter checkboxes (by node type, by language)

### Export
- [ ] Export as PNG
- [ ] Export as SVG
- [ ] Export as JSON

### API
- [ ] Module listing endpoint
- [ ] Class listing (per module) endpoint
- [ ] Method listing (per class) endpoint
- [ ] Aggregated edges endpoint (module-level, class-level)
- [ ] Transaction list and detail endpoints
- [ ] Search endpoint
- [ ] Code viewer endpoint

---

## 11. What's Explicitly Deferred to Later Phases

| Feature | Deferred To | Why |
|---------|------------|-----|
| Levels 4-5 (fields, variables) | Phase 3+ | Rarely needed for architecture decisions |
| Pre-computed aggregation hierarchy | Never (lazy loading is sufficient) | Unnecessary complexity |
| Minimap | Phase 3 | Nice-to-have, not essential |
| Right-click context menus | Phase 3 | Click + properties panel is enough |
| Multi-select, lasso select | Phase 3 | Single selection covers initial needs |
| Data model ER diagram view | Phase 3 | Filter main graph to table nodes instead |
| Database access bipartite view | Phase 3 | Use existing views with filters |
| Custom aggregation modes | Phase 4 | CAST Taxonomy equivalent, enterprise feature |
| State management library (Zustand/Redux) | Phase 4 (if needed) | React hooks are sufficient |
| WebGL rendering | When performance requires it | Canvas is fast enough for Phase 2 node counts |

---

## 12. Success Criteria

Phase 2 is complete when:

1. Users can see a module-level overview of their application on first load
2. Users can drill into a module to see its classes, and into a class to see its methods
3. Architecture view shows clear layered structure with dependency direction
4. Transaction view correctly displays end-to-end call flows for selected transactions
5. Search finds nodes within 200ms and navigates to them
6. Source code viewer shows the correct file and highlights the relevant function
7. UI stays responsive (< 300ms interaction response) for graphs up to 2,000 visible nodes
8. PNG/SVG export produces clean, readable output