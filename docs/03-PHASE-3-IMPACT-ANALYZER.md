# Phase 3 — Impact Analysis & Smart Features (Revised)

**Timeline:** Months 5–7
**Goal:** Go from "I can see" to "I can decide"
**Last Updated:** Simplified — Phase 3 is a set of Cypher queries and one GDS call, not a new engine

---

## Overview

Phase 2 lets users explore and navigate their architecture. Phase 3 adds the analytical layer — answering questions like "what breaks if I change this?", "how is A connected to B?", and "where are the natural module boundaries?"

**Key insight from research:** Phase 3 is not a separate computation system. It's a set of **API endpoints backed by Cypher queries** against the graph already built in Phases 1-2, plus one GDS algorithm call (Louvain for community detection). Everything runs on-demand. No batch pre-computation.

---

## 1. Neo4j Graph Data Science (GDS) Setup

GDS Community Edition includes all algorithms we need — Louvain, PageRank, shortest paths, betweenness centrality, weakly connected components. The Community edition limits concurrency to 4 CPU cores, which is fine for code analysis workloads.

### Installation

GDS ships as a Neo4j plugin JAR. Add to our Docker Compose:

```yaml
neo4j:
  image: neo4j:5.26-community
  environment:
    - NEO4J_PLUGINS=["apoc", "graph-data-science"]
```

### Python Client

```bash
pip install graphdatascience
```

```python
from graphdatascience import GraphDataScience

gds = GraphDataScience("bolt://neo4j:7687", auth=("neo4j", "password"))

# Project an in-memory graph for algorithms
G, stats = gds.graph.project(
    "codeGraph",
    ["Class", "Function", "Module"],
    ["CALLS", "DEPENDS_ON", "CONTAINS"]
)

# Run algorithms
louvain_result = gds.louvain.stream(G)
pagerank_result = gds.pageRank.stream(G)

# Clean up
G.drop()
```

---

## 2. Impact Analysis

**What it answers:** "If I change node X, what else is affected?"

This is a depth-bounded BFS traversal — one Cypher query.

### API Endpoint

```
GET /api/v1/analysis/{project}/impact/{node_fqn}
    ?direction=downstream|upstream|both
    &maxDepth=5
```

### Cypher Query — Downstream Impact

```cypher
// "What does this node affect?"
MATCH path = (start {fqn: $startFqn})-[:CALLS|INJECTS|PRODUCES|WRITES*1..5]->(affected)
WITH affected, min(length(path)) AS depth
RETURN affected.fqn AS fqn,
       affected.name AS name,
       labels(affected)[0] AS type,
       affected.path AS file,
       depth
ORDER BY depth, name
```

### Cypher Query — Upstream Impact

```cypher
// "What depends on this node?"
MATCH path = (dependent)-[:CALLS|INJECTS|CONSUMES|READS*1..5]->(start {fqn: $startFqn})
WITH dependent, min(length(path)) AS depth
RETURN dependent.fqn AS fqn,
       dependent.name AS name,
       labels(dependent)[0] AS type,
       dependent.path AS file,
       depth
ORDER BY depth, name
```

### API Response

```json
{
  "node": "com.app.UserService.createUser",
  "direction": "downstream",
  "maxDepth": 5,
  "summary": {
    "total": 14,
    "byType": {"Function": 8, "Class": 3, "Table": 2, "APIEndpoint": 1},
    "byDepth": {"1": 3, "2": 5, "3": 4, "4": 2}
  },
  "affected": [
    {"fqn": "com.app.UserRepository.save", "name": "save", "type": "Function", "depth": 1},
    {"fqn": "users", "name": "users", "type": "Table", "depth": 2},
    ...
  ]
}
```

### Frontend Visualization

When the user clicks "Show Impact" on a selected node:

1. Call the impact API
2. Highlight affected nodes in the existing Cytoscape graph using color by depth:
   - Depth 1 = red (will definitely break)
   - Depth 2 = orange (likely affected)
   - Depth 3+ = yellow (may be affected)
3. Show a summary panel: "14 nodes affected — 8 functions, 3 classes, 2 tables, 1 endpoint"
4. Dim all unaffected nodes

```javascript
// Color nodes by impact depth
impactResults.affected.forEach(({ fqn, depth }) => {
  const node = cy.getElementById(fqn);
  if (node.length) {
    const colors = { 1: '#ef4444', 2: '#f97316', 3: '#eab308', 4: '#facc15', 5: '#fef08a' };
    node.style('background-color', colors[depth] || '#fef9c3');
    node.style('opacity', 1);
  }
});
// Dim everything else
cy.nodes().not(affectedSelector).style('opacity', 0.2);
```

No separate "impact view." Just overlay impact highlighting on the current graph view.

---

## 3. Path Finder

**What it answers:** "How is node A connected to node B?"

### API Endpoint

```
GET /api/v1/analysis/{project}/path
    ?from={fqn1}&to={fqn2}&maxDepth=10
```

### Cypher Query

```cypher
MATCH path = shortestPath(
  (a {fqn: $fromFqn})-[*..10]-(b {fqn: $toFqn})
)
RETURN [n IN nodes(path) | {fqn: n.fqn, name: n.name, type: labels(n)[0]}] AS nodes,
       [r IN relationships(path) | {type: type(r), source: startNode(r).fqn, target: endNode(r).fqn}] AS edges,
       length(path) AS pathLength
```

Just `shortestPath()`. If users later need multiple paths, add `allShortestPaths()`. Don't build K-shortest-paths unless someone asks for it.

### Frontend Visualization

Highlight the path on the existing graph — color the path nodes and edges, dim everything else. Same overlay pattern as impact analysis.

---

## 4. Community Detection

**What it answers:** "What are the natural module boundaries in this codebase?"

### When It Runs

Run Louvain once during analysis (Stage 7 — Graph Enricher) and write results to Neo4j. Not on-demand — it's a one-time computation that persists.

### Implementation

```python
from graphdatascience import GraphDataScience

async def run_community_detection(gds: GraphDataScience, app_name: str):
    # Project the relevant subgraph
    G, stats = gds.graph.project(
        f"{app_name}_communities",
        {"Class": {"properties": ["fqn"]}},
        {"CALLS": {"orientation": "UNDIRECTED"}, "DEPENDS_ON": {"orientation": "UNDIRECTED"}}
    )
    
    # Run Louvain
    result = gds.louvain.write(G, writeProperty="communityId")
    # result contains: communityCount, modularity, nodePropertiesWritten
    
    G.drop()
    return {
        "communityCount": result["communityCount"],
        "modularity": result["modularity"],
    }
```

### API Endpoint

```
GET /api/v1/analysis/{project}/communities
```

### Cypher Query — List Communities

```cypher
MATCH (c:Class)
WHERE c.communityId IS NOT NULL
WITH c.communityId AS communityId, collect(c.name) AS members, count(*) AS size
RETURN communityId, size, members
ORDER BY size DESC
```

### Frontend Visualization

Color-code nodes by community ID in the dependency view. Cytoscape handles this naturally — just map `communityId` to a color palette:

```javascript
const palette = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6', '#ec4899', ...];
cy.nodes().forEach(node => {
  const communityId = node.data('communityId');
  if (communityId !== undefined) {
    node.style('background-color', palette[communityId % palette.length]);
  }
});
```

Toggle community coloring on/off via a checkbox in the toolbar.

---

## 5. Circular Dependency Detection

**What it answers:** "Where are the architectural anti-patterns?"

### API Endpoint

```
GET /api/v1/analysis/{project}/circular-dependencies
    ?level=module|class
```

### Cypher Query — Module-Level Cycles

```cypher
MATCH path = (m:Module)-[:IMPORTS*2..6]->(m)
WITH [n IN nodes(path) | n.name] AS cycle, length(path) AS cycleLength
RETURN DISTINCT cycle, cycleLength
ORDER BY cycleLength
LIMIT 50
```

### Cypher Query — Class-Level Cycles

```cypher
MATCH path = (c:Class)-[:DEPENDS_ON*2..4]->(c)
WITH [n IN nodes(path) | n.fqn] AS cycle, length(path) AS cycleLength
RETURN DISTINCT cycle, cycleLength
ORDER BY cycleLength
LIMIT 50
```

### Frontend

Show circular dependencies as a list in a panel. Click a cycle → highlight those nodes and edges in the graph, color them red. Shorter cycles = higher severity.

---

## 6. Dead Code Candidates

**What it answers:** "What code is never called?"

### API Endpoint

```
GET /api/v1/analysis/{project}/dead-code
    ?type=function|class
    &minLoc=5
```

### Cypher Query

```cypher
// Functions with no callers (excluding known entry points)
MATCH (f:Function)
WHERE NOT (f)<-[:CALLS]-()
  AND NOT (f)<-[:HANDLES]-(:APIEndpoint)
  AND NOT (f)<-[:CONSUMES]-(:MessageTopic)
  AND NOT f.is_constructor
  AND NOT any(ann IN f.annotations WHERE ann IN ['PostConstruct', 'EventListener', 'Scheduled', 'Bean', 'Test'])
  AND f.loc >= $minLoc
RETURN f.fqn, f.name, f.path, f.line, f.loc
ORDER BY f.loc DESC
LIMIT 100
```

### Frontend

Show as a sortable table: name, file, LOC, type. Click a row → navigate to the node in the graph + open code viewer.

**Important:** Label clearly as "candidates" — static analysis can't detect reflection-based calls, serialization callbacks, or framework lifecycle methods with 100% accuracy.

---

## 7. Metrics Dashboard

**What it answers:** "What's the overall health of this codebase?"

### API Endpoint

```
GET /api/v1/analysis/{project}/metrics
```

### Cypher Queries

```cypher
// Overview stats
MATCH (app:Application {name: $appName})
OPTIONAL MATCH (app)-[:CONTAINS]->(m:Module)
OPTIONAL MATCH (m)-[:CONTAINS]->(c:Class)
OPTIONAL MATCH (c)-[:CONTAINS]->(f:Function)
RETURN count(DISTINCT m) AS modules,
       count(DISTINCT c) AS classes,
       count(DISTINCT f) AS functions,
       sum(c.loc) AS totalLoc

// Most complex classes (top 10)
MATCH (c:Class)
WHERE c.complexity IS NOT NULL
RETURN c.fqn, c.name, c.complexity, c.loc
ORDER BY c.complexity DESC
LIMIT 10

// Highest fan-in (most depended upon)
MATCH (caller)-[:CALLS]->(target:Function)
WITH target, count(DISTINCT caller) AS fanIn
RETURN target.fqn, target.name, fanIn
ORDER BY fanIn DESC
LIMIT 10

// Highest fan-out (depends on most things)
MATCH (source:Function)-[:CALLS]->(callee)
WITH source, count(DISTINCT callee) AS fanOut
RETURN source.fqn, source.name, fanOut
ORDER BY fanOut DESC
LIMIT 10
```

### Frontend

A simple dashboard page with:
- **Summary cards:** Total modules, classes, functions, LOC
- **Top 10 most complex classes** (sortable table)
- **Top 10 highest fan-in nodes** (sortable table)
- **Top 10 highest fan-out nodes** (sortable table)
- **Community count + modularity score**
- **Circular dependency count**
- **Dead code candidate count**

Click any row → navigate to that node in the graph. No charts or visualizations needed yet — tables are sufficient for Phase 3.

---

## 8. Source Code Viewer (Enhanced)

Phase 2 added a basic code viewer. Phase 3 enhances it:

- **Click-to-navigate from code to graph:** When viewing source code, clicking a function call or class reference navigates to that node in the graph
- **Highlight callers/callees:** When viewing a function, show inline markers for which lines call other functions (with links)

Implementation: Monaco Editor supports custom decorations and click handlers. When we load a file, we overlay the tree-sitter AST data (which has line numbers for every call site) to make references clickable.

This is the only non-trivial frontend feature in Phase 3. Everything else is API endpoints + simple UI.

---

## 9. API Endpoints (Phase 3)

Seven new endpoints. All backed by Cypher queries. No complex backend logic.

```
GET /api/v1/analysis/{project}/impact/{node_fqn}
    ?direction=downstream|upstream|both&maxDepth=5
    → Blast radius for a node

GET /api/v1/analysis/{project}/path
    ?from={fqn1}&to={fqn2}&maxDepth=10
    → Shortest path between two nodes

GET /api/v1/analysis/{project}/communities
    → List all detected communities with member counts

GET /api/v1/analysis/{project}/circular-dependencies
    ?level=module|class
    → All circular dependency cycles

GET /api/v1/analysis/{project}/dead-code
    ?type=function|class&minLoc=5
    → Dead code candidates

GET /api/v1/analysis/{project}/metrics
    → Overview dashboard data (stats, top-10 lists)

GET /api/v1/analysis/{project}/node/{fqn}/details
    → Enhanced node details (fan-in, fan-out, community, callers, callees)
```

---

## 10. What's Explicitly Deferred

| Feature | Deferred To | Why |
|---------|------------|-----|
| Microservice extraction scoring | Phase 6 | Enterprise feature, needs advisors framework |
| Formal coupling/cohesion score formula | Phase 6 | Fan-in/fan-out + communities is enough for now |
| Impact report PDF/Markdown generation | Phase 4 | Phase 4 handles exports |
| K-shortest paths | Later if requested | shortestPath() covers 95% of use cases |
| Custom graph algorithms | Never | GDS provides everything we need |
| Separate impact analysis engine | Never | It's just a Cypher query |
| Change-over-time tracking | Phase 6 (CI/CD) | Requires multiple analysis snapshots |

---

## 11. Deliverables Checklist

### Backend (API + Cypher)
- [ ] Neo4j GDS plugin installed in Docker Compose
- [ ] `graphdatascience` Python client integration
- [ ] Louvain community detection run during Stage 7 (write results to Neo4j)
- [ ] Impact analysis endpoint (downstream + upstream BFS query)
- [ ] Path finder endpoint (shortestPath query)
- [ ] Communities listing endpoint
- [ ] Circular dependency detection endpoint
- [ ] Dead code candidates endpoint
- [ ] Metrics dashboard endpoint (overview stats + top-10 lists)
- [ ] Enhanced node details endpoint (fan-in, fan-out, community, callers, callees)

### Frontend
- [ ] Impact analysis overlay on graph (color by depth, dim unaffected, summary panel)
- [ ] "Show Impact" button in node properties panel
- [ ] Path finder UI (select two nodes → highlight path)
- [ ] Community coloring toggle in toolbar
- [ ] Circular dependency panel (list of cycles, click to highlight)
- [ ] Dead code candidates panel (sortable table, click to navigate)
- [ ] Metrics dashboard page (summary cards + top-10 tables)
- [ ] Enhanced code viewer (clickable references → navigate to graph node)

---

## 12. Success Criteria

Phase 3 is complete when:

1. Impact analysis returns blast radius for any node within 2 seconds
2. Path finder returns shortest path between any two nodes within 1 second
3. Community detection produces meaningful clusters visible in the dependency view
4. Circular dependencies are detected and highlighted at module and class level
5. Dead code candidates list is populated with reasonable results (manual spot-check for accuracy)
6. Metrics dashboard shows correct stats that match the graph data
7. All features are overlays on the existing Phase 2 graph views — no separate pages needed (except metrics dashboard)