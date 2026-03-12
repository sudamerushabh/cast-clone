# Deep Dive — Neo4j Schema & Query Patterns

## Overview

Neo4j is the graph database backing CodeLens. This document covers the complete schema design, indexing strategy, and the key Cypher query patterns used by the frontend, API, and analysis engine.

---

## Schema Design

### Node Labels

```cypher
// ── Structural Code Nodes ──────────────────────────────
(:Application {
  name: String,
  root_path: String,
  languages: [String],
  frameworks: [String],
  total_loc: Integer,
  total_files: Integer,
  analyzed_at: DateTime
})

(:Module {
  name: String,
  fqn: String,           // e.g., "com.app.user"
  path: String,
  language: String,
  loc: Integer,
  file_count: Integer,
  complexity_avg: Float
})

(:Class {
  name: String,
  fqn: String,           // e.g., "com.app.user.UserService"
  path: String,
  line: Integer,
  end_line: Integer,
  language: String,
  framework: String,      // nullable
  loc: Integer,
  complexity: Integer,
  visibility: String,     // public, private, protected, internal
  annotations: [String],
  is_abstract: Boolean,
  is_interface: Boolean
})

(:Interface {
  name: String,
  fqn: String,
  path: String,
  line: Integer,
  language: String
})

(:Function {
  name: String,
  fqn: String,           // e.g., "com.app.user.UserService.createUser"
  path: String,
  line: Integer,
  end_line: Integer,
  language: String,
  params: [String],       // ["CreateUserRequest req"]
  return_type: String,
  complexity: Integer,
  loc: Integer,
  visibility: String,
  annotations: [String],
  is_static: Boolean,
  is_constructor: Boolean
})

(:Field {
  name: String,
  fqn: String,
  type: String,
  visibility: String,
  is_static: Boolean,
  is_final: Boolean
})

// ── Data Nodes ──────────────────────────────────────────
(:Table {
  name: String,
  schema: String,         // nullable
  database: String,       // nullable
  engine: String,         // nullable (InnoDB, etc.)
  column_count: Integer,
  row_estimate: Integer   // nullable
})

(:Column {
  name: String,
  type: String,           // "VARCHAR(255)", "INTEGER", etc.
  nullable: Boolean,
  is_primary_key: Boolean,
  is_foreign_key: Boolean,
  default_value: String   // nullable
})

(:View {
  name: String,
  schema: String,
  definition_query: String
})

(:StoredProcedure {
  name: String,
  schema: String,
  language: String,
  param_count: Integer,
  loc: Integer
})

// ── API / Interface Nodes ───────────────────────────────
(:APIEndpoint {
  method: String,         // GET, POST, PUT, DELETE, PATCH
  path: String,           // "/api/users/{id}"
  params: [String],
  request_body_type: String,
  response_type: String,
  framework: String       // "spring", "django", "express", etc.
})

(:Route {
  path: String,
  component_name: String,
  is_lazy: Boolean,
  is_exact: Boolean
})

(:MessageTopic {
  name: String,
  broker_type: String,    // "kafka", "rabbitmq", "sqs"
  partitions: Integer     // nullable
})

// ── Configuration Nodes ─────────────────────────────────
(:ConfigFile {
  path: String,
  format: String          // "yaml", "json", "properties", "toml"
})

(:ConfigEntry {
  key: String,
  value: String,
  profile: String         // "default", "dev", "prod"
})

// ── Aggregation Nodes (pre-computed) ────────────────────
(:Layer {
  name: String,           // "Presentation", "Business Logic", etc.
  type: String,           // "architectural_layer"
  app_name: String,
  node_count: Integer,
  edge_count: Integer
})

(:Component {
  name: String,
  type: String,
  layer: String,
  cohesion_score: Float,
  coupling_score: Float,
  node_count: Integer
})

(:Community {
  id: Integer,
  algorithm: String,      // "louvain"
  cohesion: Float,
  coupling: Float,
  node_count: Integer,
  modularity_score: Float
})

// ── Transaction Nodes (pre-computed) ────────────────────
(:Transaction {
  name: String,           // "POST /api/users → UserController.create"
  entry_point_fqn: String,
  end_point_types: [String],  // ["TABLE_WRITE", "MESSAGE_PUBLISH"]
  node_count: Integer,
  depth: Integer,
  http_method: String,    // nullable
  url_path: String        // nullable
})
```

### Relationship Types

```cypher
// ── Code Relationships ──────────────────────────────────
(:Function)-[:CALLS {
  confidence: String,     // "HIGH", "MEDIUM", "LOW"
  is_direct: Boolean,
  line: Integer,
  evidence: String        // "lsp", "tree-sitter", "plugin"
}]->(:Function)

(:Class)-[:INHERITS]->(:Class)
(:Class)-[:IMPLEMENTS]->(:Interface)

(:Class)-[:DEPENDS_ON {
  weight: Integer,        // number of individual edges aggregated
  edge_count: Integer
}]->(:Class)

(:Module)-[:IMPORTS]->(:Module)

// ── Containment Hierarchy ───────────────────────────────
(:Application)-[:CONTAINS]->(:Module)
(:Module)-[:CONTAINS]->(:Class)
(:Module)-[:CONTAINS]->(:Interface)
(:Class)-[:CONTAINS]->(:Function)
(:Class)-[:CONTAINS]->(:Field)

// ── Dependency Injection ────────────────────────────────
(:Class)-[:INJECTS {
  framework: String,      // "spring", "nestjs", "angular"
  qualifier: String,      // nullable
  profile: String,        // nullable
  confidence: String
}]->(:Class)

// ── Data Access ─────────────────────────────────────────
(:Function)-[:READS {
  query_type: String,     // "SELECT", "FIND", "GET"
  table_columns: [String] // nullable
}]->(:Table)

(:Function)-[:WRITES {
  query_type: String,     // "INSERT", "UPDATE", "DELETE", "SAVE"
  table_columns: [String]
}]->(:Table)

(:Class)-[:MAPS_TO {
  orm: String,            // "hibernate", "django_orm", "sqlalchemy", "ef"
  strategy: String        // "single_table", "joined", etc.
}]->(:Table)

(:Table)-[:HAS_COLUMN]->(:Column)

(:Column)-[:REFERENCES {
  constraint_name: String
}]->(:Column)             // Foreign key

// ── API Layer ───────────────────────────────────────────
(:Class)-[:EXPOSES]->(:APIEndpoint)
(:Function)-[:HANDLES]->(:APIEndpoint)

(:Function)-[:CALLS_API {
  url_pattern: String,
  method: String
}]->(:APIEndpoint)

(:Route)-[:RENDERS]->(:Class)

// ── Messaging ───────────────────────────────────────────
(:Function)-[:PRODUCES {
  serializer: String
}]->(:MessageTopic)

(:Function)-[:CONSUMES {
  group_id: String,
  deserializer: String
}]->(:MessageTopic)

// ── Aggregation ─────────────────────────────────────────
(:Layer)-[:CONTAINS]->(:Component)
(:Component)-[:CONTAINS]->(:Class)
(:Community)-[:INCLUDES]->(:Class)

(:Layer)-[:DEPENDS_ON {weight, edge_count}]->(:Layer)
(:Component)-[:DEPENDS_ON {weight, edge_count}]->(:Component)

// ── Transactions ────────────────────────────────────────
(:Transaction)-[:STARTS_AT]->(:Function)
(:Transaction)-[:ENDS_AT]->(:Function)
(:Transaction)-[:INCLUDES {position: Integer}]->(:Function)
```

---

## Indexing Strategy

```cypher
// Primary lookup indexes
CREATE INDEX idx_class_fqn FOR (n:Class) ON (n.fqn)
CREATE INDEX idx_function_fqn FOR (n:Function) ON (n.fqn)
CREATE INDEX idx_interface_fqn FOR (n:Interface) ON (n.fqn)
CREATE INDEX idx_module_fqn FOR (n:Module) ON (n.fqn)
CREATE INDEX idx_table_name FOR (n:Table) ON (n.name)
CREATE INDEX idx_endpoint_path FOR (n:APIEndpoint) ON (n.path)
CREATE INDEX idx_column_name FOR (n:Column) ON (n.name)
CREATE INDEX idx_config_key FOR (n:ConfigEntry) ON (n.key)
CREATE INDEX idx_transaction_name FOR (n:Transaction) ON (n.name)
CREATE INDEX idx_route_path FOR (n:Route) ON (n.path)
CREATE INDEX idx_topic_name FOR (n:MessageTopic) ON (n.name)

// Composite indexes for filtered queries
CREATE INDEX idx_class_lang FOR (n:Class) ON (n.language)
CREATE INDEX idx_function_lang FOR (n:Function) ON (n.language)
CREATE INDEX idx_endpoint_method FOR (n:APIEndpoint) ON (n.method)

// Full-text search index
CREATE FULLTEXT INDEX idx_node_search
  FOR (n:Class|Function|Interface|Table|APIEndpoint|Module)
  ON EACH [n.name, n.fqn]
```

---

## Key Query Patterns

### Multi-Level Navigation

**Get nodes at a specific level within a parent:**

```cypher
// Level 2: Get all layers for an application
MATCH (app:Application {name: $appName})-[:CONTAINS]->(layer:Layer)
RETURN layer
ORDER BY layer.name

// Level 3: Get all components within a layer
MATCH (layer:Layer {name: $layerName, app_name: $appName})-[:CONTAINS]->(comp:Component)
RETURN comp
ORDER BY comp.name

// Level 4: Get all classes within a component
MATCH (comp:Component {name: $compName})-[:CONTAINS]->(cls:Class)
RETURN cls
ORDER BY cls.name

// Level 5: Get all functions within a class
MATCH (cls:Class {fqn: $classFqn})-[:CONTAINS]->(fn:Function)
RETURN fn
ORDER BY fn.line
```

**Get aggregated edges between nodes at a level:**

```cypher
// Aggregated edges between layers
MATCH (l1:Layer {app_name: $appName})-[:CONTAINS]->(:Component)-[:CONTAINS]->(c1:Class)
      -[:DEPENDS_ON|CALLS|INJECTS]->(c2:Class)<-[:CONTAINS]-(:Component)<-[:CONTAINS]-(l2:Layer {app_name: $appName})
WHERE l1 <> l2
WITH l1, l2, count(*) AS edgeCount
RETURN l1.name AS source, l2.name AS target, edgeCount
ORDER BY edgeCount DESC

// Aggregated edges between components within a layer
MATCH (comp1:Component)-[:CONTAINS]->(c1:Class)-[:DEPENDS_ON|CALLS|INJECTS]->(c2:Class)<-[:CONTAINS]-(comp2:Component)
WHERE comp1 <> comp2
  AND comp1.layer = $layerName AND comp2.layer = $layerName
WITH comp1, comp2, count(*) AS edgeCount
RETURN comp1.name AS source, comp2.name AS target, edgeCount
```

### Transaction Queries

**List all transactions:**

```cypher
MATCH (t:Transaction)
RETURN t.name, t.http_method, t.url_path, t.node_count, t.depth
ORDER BY t.name
```

**Get full transaction call graph:**

```cypher
MATCH (t:Transaction {name: $txnName})-[:INCLUDES]->(fn:Function)
WITH t, fn
ORDER BY fn.fqn
WITH t, collect(fn) AS functions
MATCH (f1:Function)-[r:CALLS]->(f2:Function)
WHERE f1 IN functions AND f2 IN functions
RETURN t, functions, collect({source: f1.fqn, target: f2.fqn, type: type(r)}) AS edges
```

### Impact Analysis Queries

**Downstream impact (what does this node affect?):**

```cypher
MATCH path = (start {fqn: $startFqn})-[:CALLS|INJECTS|PRODUCES|WRITES*1..$maxDepth]->(affected)
WITH affected, min(length(path)) AS depth
RETURN affected.fqn, affected.name, labels(affected)[0] AS type, depth
ORDER BY depth, affected.name
```

**Upstream impact (what depends on this node?):**

```cypher
MATCH path = (dependent)-[:CALLS|INJECTS|CONSUMES|READS*1..$maxDepth]->(start {fqn: $startFqn})
WITH dependent, min(length(path)) AS depth
RETURN dependent.fqn, dependent.name, labels(dependent)[0] AS type, depth
ORDER BY depth, dependent.name
```

**Impact summary by layer:**

```cypher
MATCH path = (start {fqn: $startFqn})-[:CALLS|INJECTS|WRITES*1..$maxDepth]->(affected)
MATCH (comp:Component)-[:CONTAINS]->(affected)
MATCH (layer:Layer)-[:CONTAINS]->(comp)
WITH layer.name AS layerName, count(DISTINCT affected) AS affectedCount
RETURN layerName, affectedCount
ORDER BY affectedCount DESC
```

### Path Finder Queries

**Shortest path between two nodes:**

```cypher
MATCH path = shortestPath(
  (a {fqn: $fromFqn})-[*..10]-(b {fqn: $toFqn})
)
RETURN [n IN nodes(path) | n.fqn] AS nodePath,
       [r IN relationships(path) | type(r)] AS edgeTypes,
       length(path) AS pathLength
```

**All shortest paths:**

```cypher
MATCH path = allShortestPaths(
  (a {fqn: $fromFqn})-[*..10]-(b {fqn: $toFqn})
)
RETURN [n IN nodes(path) | n.fqn] AS nodePath,
       [r IN relationships(path) | type(r)] AS edgeTypes
```

### Search Queries

**Full-text search:**

```cypher
CALL db.index.fulltext.queryNodes("idx_node_search", $searchQuery)
YIELD node, score
RETURN node.fqn, node.name, labels(node)[0] AS type, score
ORDER BY score DESC
LIMIT $limit
```

**Filtered search (by type and language):**

```cypher
CALL db.index.fulltext.queryNodes("idx_node_search", $searchQuery)
YIELD node, score
WHERE labels(node)[0] IN $nodeTypes
  AND (node.language IS NULL OR node.language IN $languages)
RETURN node.fqn, node.name, labels(node)[0] AS type, node.language, score
ORDER BY score DESC
LIMIT $limit
```

### Data Model Queries

**Get database ER diagram:**

```cypher
// All tables with columns
MATCH (t:Table)-[:HAS_COLUMN]->(c:Column)
WITH t, collect({
  name: c.name, type: c.type, nullable: c.nullable,
  isPK: c.is_primary_key, isFK: c.is_foreign_key
}) AS columns
RETURN t.name, t.schema, columns

// Foreign key relationships
MATCH (c1:Column)-[:REFERENCES]->(c2:Column)
MATCH (t1:Table)-[:HAS_COLUMN]->(c1)
MATCH (t2:Table)-[:HAS_COLUMN]->(c2)
RETURN t1.name AS sourceTable, c1.name AS sourceColumn,
       t2.name AS targetTable, c2.name AS targetColumn
```

**Database access patterns:**

```cypher
// Which functions access which tables
MATCH (fn:Function)-[r:READS|WRITES]->(t:Table)
RETURN fn.fqn, type(r) AS accessType, r.query_type, t.name AS tableName
ORDER BY t.name, fn.fqn
```

### Modularity & Coupling Queries

**Coupling score for a module:**

```cypher
// External edges from module
MATCH (internal:Class {module: $moduleName})-[:DEPENDS_ON]->(external:Class)
WHERE external.module <> $moduleName
WITH count(*) AS externalEdges

// Total edges from module
MATCH (a:Class {module: $moduleName})-[:DEPENDS_ON]->(b:Class)
WITH externalEdges, count(*) AS totalEdges

RETURN toFloat(externalEdges) / CASE WHEN totalEdges = 0 THEN 1 ELSE totalEdges END AS couplingScore
```

**Circular dependency detection:**

```cypher
// At module level
MATCH path = (m:Module)-[:IMPORTS*2..6]->(m)
RETURN [n IN nodes(path) | n.name] AS cycle, length(path) AS cycleLength
ORDER BY cycleLength

// At class level (more granular)
MATCH path = (c:Class)-[:DEPENDS_ON*2..4]->(c)
RETURN [n IN nodes(path) | n.fqn] AS cycle, length(path) AS cycleLength
ORDER BY cycleLength
LIMIT 50
```

### Statistics & Metrics Queries

**Application overview:**

```cypher
MATCH (app:Application {name: $appName})
OPTIONAL MATCH (app)-[:CONTAINS]->(m:Module)
OPTIONAL MATCH (m)-[:CONTAINS]->(c:Class)
OPTIONAL MATCH (c)-[:CONTAINS]->(f:Function)
RETURN app.name,
       count(DISTINCT m) AS moduleCount,
       count(DISTINCT c) AS classCount,
       count(DISTINCT f) AS functionCount,
       sum(c.loc) AS totalLoc
```

**Technology distribution:**

```cypher
MATCH (c:Class)
WITH c.language AS language, count(*) AS classCount, sum(c.loc) AS loc
RETURN language, classCount, loc
ORDER BY loc DESC
```

**Most complex classes:**

```cypher
MATCH (c:Class)
WHERE c.complexity IS NOT NULL
RETURN c.fqn, c.name, c.complexity, c.loc, c.language
ORDER BY c.complexity DESC
LIMIT 20
```

**Highest fan-in nodes (most depended upon):**

```cypher
MATCH (dependent)-[:CALLS|INJECTS]->(target:Function)
WITH target, count(DISTINCT dependent) AS fanIn
RETURN target.fqn, target.name, fanIn
ORDER BY fanIn DESC
LIMIT 20
```

---

## Batch Write Patterns

### Creating Nodes in Bulk

```cypher
// Process nodes in batches of 5000
UNWIND $batch AS n
CALL apoc.create.node([n.label], {
  fqn: n.fqn,
  name: n.name,
  path: n.path,
  line: n.line,
  language: n.language,
  loc: n.loc,
  complexity: n.complexity
}) YIELD node
RETURN count(node)
```

### Creating Edges in Bulk

```cypher
UNWIND $batch AS e
MATCH (from {fqn: e.from_fqn})
MATCH (to {fqn: e.to_fqn})
CALL apoc.create.relationship(from, e.type, {
  confidence: e.confidence,
  is_direct: e.is_direct,
  line: e.line
}, to) YIELD rel
RETURN count(rel)
```

### Full Database Reset for Re-Analysis

```cypher
// Delete everything in the database (use before re-importing)
CALL apoc.periodic.iterate(
  "MATCH (n) RETURN n",
  "DETACH DELETE n",
  {batchSize: 10000}
)
```

---

## Performance Considerations

1. **Always use indexes** for MATCH clauses on `fqn`, `name`, `path`
2. **Batch writes** with UNWIND in groups of 5000 — individual CREATE statements are 100x slower
3. **Limit traversal depth** — open-ended `*` patterns without depth limits can explode on large graphs
4. **Use DISTINCT** when aggregating paths — Neo4j may return duplicate paths
5. **Profile queries** with `PROFILE` or `EXPLAIN` before deploying — check for full graph scans
6. **Memory configuration** — Neo4j heap should be at least 4GB for large codebases, page cache 2GB+