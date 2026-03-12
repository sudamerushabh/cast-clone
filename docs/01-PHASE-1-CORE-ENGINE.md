# Phase 1 — Foundation & Core Analysis Engine (Revised)

**Timeline:** Months 1–3
**Goal:** Parse code → build graph → store it → display it
**Last Updated:** Based on deep technical research validating and refining our approach

---

## Overview

Phase 1 delivers the foundational infrastructure that everything else builds on. By the end of this phase, a user should be able to point CodeLens at a codebase and see an interactive graph of all code objects and their relationships.

---

## 1. Analysis Engine Architecture

The analysis engine is the core IP of the product. It performs **semantic analysis**, not just syntactic parsing.

### Levels of Analysis

| Level | What It Finds | Difficulty | Tool |
|-------|--------------|------------|------|
| Syntactic | "This file imports that file" | Easy | Tree-sitter |
| Structural | "This class contains these methods, extends that class" | Easy | Tree-sitter |
| Call Graph | "Function A calls function B" (direct calls) | Medium | Tree-sitter + SCIP |
| Semantic | "This @Autowired field resolves to *that specific* implementation" | Hard | SCIP + Framework Plugins |
| Framework-Aware | "This Spring controller exposes this REST endpoint" | Hard | Framework Plugins |
| Cross-Technology | "This React component calls this Spring API which writes to this DB table" | Very Hard | Cross-Tech Linker |

### Parsing Strategy: Hybrid Approach (Tree-sitter + SCIP + Plugins)

The analysis engine uses a **four-layer parsing strategy**:

```
Layer 1: Tree-sitter (structural skeleton — fast, broad)
    +
Layer 2: SCIP Indexers (compiler-accurate resolution — batch, precise)
    +
Layer 3: Framework Plugins (invisible framework connections — custom)
    +
Layer 4: sqlglot (embedded SQL parsing — table/column extraction)
    ↓
Graph Builder → Neo4j
```

**Layer 1 — Tree-sitter (Base Parser)**
- Fast C-based incremental parser with grammars for 100+ languages
- Produces a concrete syntax tree (CST) queryable with S-expressions
- Extracts: classes, functions, methods, fields, imports, annotations/decorators, type annotations, string literals
- Resolves: intra-file relationships, direct calls, import chains
- Achieves ~60-70% of total analysis accuracy alone
- Python bindings via `py-tree-sitter` (pre-compiled wheels, zero dependencies)
- `tree-sitter-languages` package provides pre-compiled grammars for all target languages

**Layer 2 — SCIP Indexers (Compiler-Accurate Resolution) [PRIMARY]**
- SCIP (SCIP Code Intelligence Protocol) is an open-source, language-agnostic protocol for batch code indexing
- Created by Sourcegraph, licensed under Apache 2.0 (fully permissive, commercial use allowed)
- Purpose-built for exactly our use case: batch indexing entire codebases with compiler-level accuracy
- Produces a Protobuf index file containing every symbol definition, reference, and relationship
- Dramatically simpler than LSP: run a single CLI command → parse the output file
- No server lifecycle management, no JSON-RPC, no timeout handling
- Available indexers (all Apache 2.0 licensed):
  - `scip-java` — Java, Scala, Kotlin (hooks into actual compiler via compiler plugin)
  - `scip-typescript` — TypeScript and JavaScript (built on TypeScript typechecker)
  - `scip-python` — Python (fork of Pyright focused on SCIP generation)
  - `scip-dotnet` — C# / .NET
- Performance: SCIP indexes are 4-5x smaller than LSIF equivalents; 10x CI speedup reported vs LSIF

**Layer 2b — LSP Fallback (Only When SCIP Unavailable)**
- If a language lacks a SCIP indexer, fall back to LSP via the `lsp-client` Python library
- `lsp-client` is a production-ready, async-first Python LSP client with full 3.17 spec coverage
- Used only as a fallback — not the primary resolution path

**Layer 3 — Framework Plugins (Domain-Specific Resolution)**
- Custom resolvers for each framework's invisible connections
- Handles: dependency injection wiring, ORM-to-table mapping, route-to-controller mapping, message queue topic matching
- Operates on the enriched AST and SCIP data from layers 1-2
- See `08-FRAMEWORK-PLUGINS.md` for full plugin architecture

**Layer 4 — sqlglot (Embedded SQL Parsing)**
- `sqlglot` is a zero-dependency Python SQL parser supporting 31+ dialects
- Parses embedded SQL strings detected by tree-sitter (SELECT, INSERT, UPDATE, DELETE)
- Extracts: table references, column references, join relationships, query type (read vs. write)
- Handles dialect-specific syntax (Oracle PL/SQL, SQL Server T-SQL, PostgreSQL, MySQL)
- Also serves as the foundation for Phase 6's Database Migration Advisor

### Why SCIP Over LSP (Key Decision)

| Concern | LSP (Original Plan) | SCIP (Revised Plan) |
|---------|---------------------|---------------------|
| **Design purpose** | Interactive IDE use | Batch code indexing |
| **Operation mode** | Long-running server process | Single CLI command, one-shot output |
| **Integration complexity** | Manage server lifecycle, open/close documents, handle crashes/timeouts | Run subprocess, parse Protobuf file |
| **Protocol** | JSON-RPC (chatty, verbose) | Protobuf (compact, typed, 4-5x smaller) |
| **Accuracy** | Same (compiler-level) | Same (compiler-level) |
| **Performance** | Minutes of back-and-forth requests | Single command, seconds to minutes |
| **Failure handling** | Server crash recovery, restart, resume | Process exit code, retry or fallback |
| **Debugging** | Opaque JSON-RPC traces | Human-readable symbol IDs in Protobuf |
| **License** | Varies per server | Apache 2.0 (all indexers) |

---

## 2. Parser Technology: Tree-sitter

### Why Tree-sitter

- Extremely fast (written in C, processes thousands of files per second)
- Incremental parsing capability (useful for future incremental analysis)
- Grammars available for all target languages
- S-expression queries allow precise pattern matching on syntax trees
- Used by GitHub for code navigation — battle-tested at scale
- Python bindings: `py-tree-sitter` with pre-compiled wheels, zero dependencies

### Installation

```bash
pip install tree-sitter
pip install tree-sitter-java tree-sitter-python tree-sitter-typescript tree-sitter-c-sharp
# OR use the bundled package:
pip install tree-sitter-languages
```

### Basic Usage

```python
import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

JAVA_LANGUAGE = Language(tsjava.language())
parser = Parser(JAVA_LANGUAGE)

source_code = b'public class UserService { public void createUser() {} }'
tree = parser.parse(source_code)
root_node = tree.root_node
```

### S-Expression Queries (Java Examples)

```scheme
;; Find all class declarations
(class_declaration
  name: (identifier) @class_name
  superclass: (superclass (type_identifier) @extends)?
  interfaces: (super_interfaces (type_list (type_identifier) @implements))?
  body: (class_body) @body
) @class

;; Find all method declarations with annotations
(method_declaration
  (modifiers (annotation name: (identifier) @annotation_name)*)
  type: (_) @return_type
  name: (identifier) @method_name
  parameters: (formal_parameters) @params
  body: (block) @body
) @method

;; Find all field declarations
(field_declaration
  (modifiers (annotation name: (identifier) @annotation)*)
  type: (_) @field_type
  declarator: (variable_declarator name: (identifier) @field_name)
) @field

;; Find all method invocations
(method_invocation
  object: (_)? @receiver
  name: (identifier) @method_called
  arguments: (argument_list) @args
) @call

;; Find string literals (for SQL detection, topic names, URLs)
(string_literal) @string

;; Find import declarations
(import_declaration
  (scoped_identifier) @import_path
) @import
```

### File-Level Extraction Process

For each source file, the extractor:

1. **Runs tree-sitter queries** against the parsed AST to find classes, methods, fields, calls, imports, annotations, and string literals
2. **Builds a file symbol table** — maps each declaration to its fully qualified name (FQN), file path, line number, and metadata
3. **Extracts preliminary call edges** — for each method invocation, records the caller, callee name, receiver type, and line number; marks as UNRESOLVED (SCIP will upgrade these)
4. **Extracts imports** — builds a local name → FQN mapping for resolving short names in this file
5. **Extracts annotation arguments** — parses annotation parameters for framework plugins
6. **Tags interesting strings** — identifies string literals that look like SQL queries, URL paths, Kafka topic names, or config keys

### Global Symbol Resolution Pass

After all files are parsed:

1. **Builds FQN index** — indexes every class/interface by fully qualified name for O(1) lookup
2. **Resolves imports** — for each file, maps short names to FQNs using import statements
3. **Upgrades unresolved calls** — uses import resolution + FQN index to partially resolve call edges
4. **Builds inheritance index** — for each interface lists implementors, for each class lists subclasses

### Parallelization

- Files parsed in parallel using ProcessPoolExecutor (one worker per CPU core)
- Each worker parses one file and returns nodes + edges
- Main thread aggregates results
- Typical: 1000 Java files with 8 workers = 5-15 seconds

---

## 3. SCIP Integration (Compiler-Accurate Resolution)

### What SCIP Provides

SCIP is an open-source protocol (Apache 2.0) created by Sourcegraph for batch indexing source code. Each indexer hooks into the actual language compiler to produce a Protobuf index file containing:

- **Symbol definitions** — every class, function, method, field with its exact fully qualified name
- **Symbol references** — every usage of every symbol, linked to its definition with compiler accuracy
- **Hover documentation** — extracted docs/comments for each symbol
- **Implementation relationships** — which classes implement which interfaces
- **Cross-file navigation** — go-to-definition and find-references across the entire project

### Available SCIP Indexers

| Indexer | Languages | Built On | License | Install |
|---------|-----------|----------|---------|---------|
| `scip-java` | Java, Scala, Kotlin | Compiler plugins | Apache 2.0 | Docker image or standalone binary |
| `scip-typescript` | TypeScript, JavaScript | TypeScript typechecker | Apache 2.0 | npm install @sourcegraph/scip-typescript |
| `scip-python` | Python | Pyright fork | Apache 2.0 | npm install @sourcegraph/scip-python |
| `scip-dotnet` | C#, F# | Roslyn compiler | Apache 2.0 | NuGet package |

### SCIP Indexing Process

```
For each detected language with a SCIP indexer:

1. RUN the indexer as a subprocess:
   
   Java (Maven):
     docker run -v $(pwd):/sources sourcegraph/scip-java:latest scip-java index
     # OR: scip-java index (auto-detects Maven/Gradle)
   
   TypeScript/JavaScript:
     npx @sourcegraph/scip-typescript index
   
   Python:
     scip-python index . --project-name=myproject
   
   C#/.NET:
     scip-dotnet index MyProject.sln

2. PARSE the output index.scip file (Protobuf):
   
   For each Document in the SCIP index:
     file_path = document.relative_path
     
     For each Symbol defined in the document:
       fqn = symbol.symbol  (human-readable)
       kind = symbol.kind
       docs = symbol.documentation
       → Create or update GraphNode with exact FQN and metadata
     
     For each Occurrence in the document:
       symbol_fqn = occurrence.symbol
       role = occurrence.symbol_roles  (Definition, Reference, Implementation)
       
       If role is Reference:
         → Create RESOLVED edge (HIGH confidence)
       If role is Implementation:
         → Create IMPLEMENTS edge

3. MERGE with tree-sitter data:
   
   Match SCIP symbols to tree-sitter nodes by file:line
   Upgrade UNRESOLVED edges to RESOLVED (HIGH confidence)
   Add hover documentation from SCIP
   Keep tree-sitter nodes without SCIP match (annotations, strings)
```

### SCIP Symbol Format

SCIP uses human-readable symbol strings:

```
maven . com/app 1.0 UserService#                    → class
maven . com/app 1.0 UserService#createUser().        → method
npm @sourcegraph/scip-typescript 0.2.0 src/index.ts/ → file scope
```

Much easier than LSP's opaque file:line:column — direct FQN mapping without a position index.

### Fallback: LSP via lsp-client

If SCIP indexer unavailable or fails, fall back to LSP using the `lsp-client` Python library. Edges resolved via LSP tagged with `evidence: "lsp"` vs `evidence: "scip"`.

---

## 4. Graph Storage: Neo4j

### Why Neo4j

- Purpose-built for graph traversal (shortest path, transitive closure, neighborhood)
- Cypher query language maps naturally to architecture questions
- Handles millions of nodes and edges efficiently
- APOC + Graph Data Science (GDS) libraries for algorithms
- Validated by similar tools (Potpie uses Neo4j + FastAPI + Celery for same purpose)
- Same choice as CAST Imaging

### Licensing Note

Neo4j Community Edition uses GPLv3 + Commons Clause. Strategy:
- Use Community Edition for Phase 1-3
- Abstract behind a `GraphStore` interface for future swap
- Evaluated alternatives: Memgraph (Cypher compatible, BSL), Apache AGE (PostgreSQL extension), FalkorDB
- Start Neo4j for speed, swap if needed later

### Graph Database Abstraction Layer

```python
class GraphStore(ABC):
    """Abstract interface — swap Neo4j for Memgraph/AGE without changing app code."""
    
    @abstractmethod
    async def write_nodes_batch(self, nodes: list[GraphNode]) -> int: ...
    
    @abstractmethod
    async def write_edges_batch(self, edges: list[GraphEdge]) -> int: ...
    
    @abstractmethod
    async def query_neighbors(self, fqn: str, depth: int, edge_types: list[str]) -> SubGraph: ...
    
    @abstractmethod
    async def query_path(self, from_fqn: str, to_fqn: str, max_depth: int) -> list[Path]: ...
    
    @abstractmethod
    async def search_fulltext(self, query: str, node_types: list[str], limit: int) -> list[SearchResult]: ...
    
    @abstractmethod
    async def clear_application(self, app_name: str) -> None: ...
```

### Core Schema

**Node Labels:**

```cypher
(:Application {name, root_path, languages[], frameworks[], total_loc, analyzed_at})
(:Module {name, fqn, path, language, loc, file_count})
(:Class {name, fqn, path, line, end_line, language, framework, loc, complexity, visibility, annotations[]})
(:Interface {name, fqn, path, line, language})
(:Function {name, fqn, path, line, end_line, language, params[], return_type, complexity, loc, visibility, annotations[]})
(:Field {name, fqn, type, visibility, is_static, is_final})
(:Table {name, schema, database, column_count})
(:Column {name, type, nullable, is_primary_key, is_foreign_key})
(:APIEndpoint {method, path, params[], request_body_type, response_type, framework})
(:Route {path, component_name, is_lazy})
(:MessageTopic {name, broker_type})
(:ConfigFile {path, format})
(:ConfigEntry {key, value, profile})
(:Layer {name, type, app_name, node_count})
(:Component {name, type, layer, cohesion_score, coupling_score})
(:Community {id, algorithm, cohesion, coupling, node_count})
(:Transaction {name, entry_point_fqn, end_point_types[], node_count, depth})
```

**Relationship Types:**

```cypher
(:Function)-[:CALLS {confidence, is_direct, line, evidence}]->(:Function)
(:Class)-[:INHERITS]->(:Class)
(:Class)-[:IMPLEMENTS]->(:Interface)
(:Class)-[:DEPENDS_ON {weight}]->(:Class)
(:Module)-[:IMPORTS]->(:Module)
(:Application)-[:CONTAINS]->(:Module)
(:Module)-[:CONTAINS]->(:Class)
(:Class)-[:CONTAINS]->(:Function)
(:Class)-[:CONTAINS]->(:Field)
(:Class)-[:INJECTS {framework, qualifier, profile, confidence}]->(:Class)
(:Function)-[:READS {query_type}]->(:Table)
(:Function)-[:WRITES {query_type}]->(:Table)
(:Class)-[:MAPS_TO {orm}]->(:Table)
(:Table)-[:HAS_COLUMN]->(:Column)
(:Column)-[:REFERENCES]->(:Column)
(:Class)-[:EXPOSES]->(:APIEndpoint)
(:Function)-[:HANDLES]->(:APIEndpoint)
(:Function)-[:CALLS_API {url_pattern, method}]->(:APIEndpoint)
(:Route)-[:RENDERS]->(:Class)
(:Function)-[:PRODUCES]->(:MessageTopic)
(:Function)-[:CONSUMES]->(:MessageTopic)
(:Transaction)-[:STARTS_AT]->(:Function)
(:Transaction)-[:ENDS_AT]->(:Function)
(:Transaction)-[:INCLUDES {position}]->(:Function)
```

**Required Indexes:**

```cypher
CREATE INDEX FOR (n:Class) ON (n.fqn)
CREATE INDEX FOR (n:Function) ON (n.fqn)
CREATE INDEX FOR (n:Interface) ON (n.fqn)
CREATE INDEX FOR (n:Module) ON (n.fqn)
CREATE INDEX FOR (n:Table) ON (n.name)
CREATE INDEX FOR (n:APIEndpoint) ON (n.path)
CREATE FULLTEXT INDEX node_search FOR (n:Class|Function|Interface|Table|APIEndpoint) ON EACH [n.name, n.fqn]
```

### Batch Writing

```cypher
UNWIND $nodes AS n
CALL apoc.create.node([n.label], n.properties) YIELD node
RETURN count(node)

UNWIND $edges AS e
MATCH (from) WHERE from.fqn = e.from_fqn
MATCH (to) WHERE to.fqn = e.to_fqn
CALL apoc.create.relationship(from, e.type, e.properties, to) YIELD rel
RETURN count(rel)
```

---

## 5. Analysis Pipeline (Revised)

```
Stage 1: ProjectDiscovery         → ProjectManifest
Stage 2: DependencyResolver       → ResolvedEnvironment
Stage 3: TreeSitterParser         → RawSymbolGraph
Stage 4: SCIPIndexer (PRIMARY)    → ResolvedSymbolGraph
Stage 4b: LSPFallback (FALLBACK)  → ResolvedSymbolGraph (only if SCIP unavailable)
Stage 5: FrameworkPluginExecutor  → EnrichedGraph
Stage 6: CrossTechLinker          → LinkedGraph
Stage 7: GraphEnricher            → FinalGraph (metrics, communities, layers)
Stage 8: Neo4jWriter              → Database populated
Stage 9: TransactionDiscovery     → Transaction subgraphs
```

See `07-ANALYSIS-ORCHESTRATOR.md` for full stage-by-stage details.

---

## 6. Minimal Web UI (Phase 1)

**Must-have features:**
- Upload a repository (ZIP or local directory path)
- Trigger analysis and see real-time progress (WebSocket)
- Display resulting graph with force-directed layout (Cytoscape.js)
- Click node → properties panel (type, file path, connections)
- Basic zoom, pan, drag
- Search bar to find nodes by name
- Filter by node type

**Tech:** React + TypeScript, Cytoscape.js, Monaco Editor, FastAPI backend, Celery + Redis queue, Nginx proxy

**API Endpoints:**

```
POST   /api/v1/projects                        Create project
POST   /api/v1/projects/{id}/analyze            Trigger analysis
GET    /api/v1/projects/{id}/status             Analysis status
WS     /api/v1/projects/{id}/progress           Live progress

GET    /api/v1/graphs/{project_id}/nodes        Nodes (paginated, filterable)
GET    /api/v1/graphs/{project_id}/edges        Edges (paginated, filterable)
GET    /api/v1/graphs/{project_id}/node/{fqn}   Single node with properties
GET    /api/v1/graphs/{project_id}/neighbors/{fqn}  Node neighbors
GET    /api/v1/search/{project_id}?q=...        Full-text search
```

---

## 7. Error Recovery & Graceful Degradation

| Scenario | Accuracy | What Works | What Doesn't |
|----------|----------|------------|-------------|
| All stages succeed | ~95%+ | Everything | — |
| SCIP fails, tree-sitter + plugins succeed | ~70-80% | Structure, framework analysis | Some call resolution |
| SCIP + some plugins fail | ~50-60% | File-level deps, direct calls | Framework connections |
| Only tree-sitter succeeds | ~30-40% | Basic structure, imports | Semantic resolution |
| Nothing works | 0% | Error page with diagnostics | Guide user to fix environment |

**Principle:** Always produce a result. Partial graph with warnings > blank error screen.

---

## 8. Key Dependencies

| Package | Purpose | License |
|---------|---------|---------|
| `tree-sitter` + language grammars | AST parsing | MIT |
| `scip-java` | Java/Scala/Kotlin indexer | Apache 2.0 |
| `@sourcegraph/scip-typescript` | TypeScript/JS indexer | Apache 2.0 |
| `@sourcegraph/scip-python` | Python indexer | Apache 2.0 |
| `scip-dotnet` | C#/.NET indexer | Apache 2.0 |
| `protobuf` | Parse SCIP index files | BSD |
| `sqlglot` | SQL parsing (31+ dialects) | MIT |
| `lsp-client` | LSP fallback | MIT |
| `fastapi` | Backend API | MIT |
| `celery` | Async job queue | BSD |
| `neo4j` (driver) | Graph DB client | Apache 2.0 |
| `neo4j` (server) | Graph DB server | GPLv3 + Commons Clause |
| `cytoscape.js` | Graph visualization | MIT |
| `monaco-editor` | Code viewer | MIT |

---

## 9. Deliverables Checklist

### Tree-sitter Layer
- [ ] Grammar loader for Java, Python, TypeScript, C#, SQL
- [ ] Language-specific extractors with S-expression queries
- [ ] Global symbol table builder with FQN resolution
- [ ] Import resolution engine
- [ ] Preliminary call graph construction (UNRESOLVED edges)
- [ ] Annotation argument extraction
- [ ] String tagging (SQL, URLs, topics, config keys)
- [ ] Parallel file parsing with ProcessPoolExecutor

### SCIP Layer
- [ ] SCIP Protobuf parser (read index.scip files)
- [ ] SCIP indexer orchestration (subprocess management for all 4 indexers)
- [ ] SCIP-to-graph mapper (symbols/occurrences → GraphNode/GraphEdge)
- [ ] SCIP + tree-sitter merger (reconcile both data sources)
- [ ] Edge confidence upgrade (UNRESOLVED → RESOLVED via SCIP)

### LSP Fallback
- [ ] Integration with lsp-client library
- [ ] Activation logic (only when SCIP unavailable)

### Framework Plugins
- [ ] Plugin base class + auto-discovery loader
- [ ] Plugin dependency resolver (topological sort)
- [ ] Spring DI plugin
- [ ] Hibernate/JPA plugin
- [ ] SQL parser plugin (sqlglot)
- [ ] HTTP endpoint matcher (cross-tech)

### Graph Database
- [ ] GraphStore abstraction interface
- [ ] Neo4jGraphStore implementation
- [ ] Schema creation (indexes, constraints)
- [ ] Batch write operations
- [ ] Community detection (GDS Louvain)
- [ ] Aggregation hierarchy builder (5 levels)
- [ ] Transaction discovery

### Infrastructure
- [ ] Docker Compose stack
- [ ] FastAPI scaffold with project CRUD
- [ ] Celery worker configuration
- [ ] WebSocket progress reporting
- [ ] Pipeline orchestrator with error recovery

### Frontend
- [ ] React app scaffold
- [ ] Project creation / upload page
- [ ] Analysis progress page (WebSocket)
- [ ] Basic graph view (Cytoscape.js)
- [ ] Node properties panel
- [ ] Search bar + node type filters

---

## 10. Success Criteria

Phase 1 is complete when:

1. A user can upload a Spring Boot + React project
2. Analysis completes within 10 minutes for 100K LOC
3. Graph correctly shows: class hierarchies, SCIP-resolved call chains, Spring DI wiring, REST endpoints, Hibernate→table mapping, React component tree, cross-tech linking
4. Resolution accuracy ≥ 90% for call edges (sampled)
5. UI displays graph with basic exploration
6. Runs on-premise via `docker-compose up`
7. Graceful degradation when SCIP or plugins partially fail