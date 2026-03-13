# Transaction Depth: JPA Stubs + Table Nodes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make transaction call chains traverse from Controller → Service → Repository → Table by (A) adding stub FUNCTION nodes for inherited JPA methods and (B) including TABLE nodes in transaction flows.

**Architecture:** Three targeted backend changes — the Spring Data plugin gets stub FUNCTION nodes for JpaRepository inherited methods so BFS can traverse them; the transactions stage collects TABLE nodes reachable via WRITES/READS from visited functions; the transaction detail API endpoint returns WRITES/READS edges alongside CALLS edges. No frontend changes needed.

**Tech Stack:** Python 3.12, FastAPI, Neo4j Cypher, tree-sitter (not touched), Spring Data plugin

---

## Chunk 1: Spring Data plugin — JPA stub nodes

### Task 1: Add stub FUNCTION nodes for inherited JPA methods

**Files:**
- Modify: `app/stages/plugins/spring/data.py`
- Test: `tests/unit/plugins/test_spring_data.py`

**Context:** When the Spring Data plugin detects a repo interface extending `JpaRepository`/`CrudRepository`, it currently only adds `MANAGES` and `READS`/`WRITES` edges. The transaction BFS follows CALLS edges to FUNCTION nodes. The Java extractor already generates CALLS edges from service methods to e.g. `com.example.repo.AccountRepository.save` — but that FQN has no corresponding FUNCTION node, so BFS drops it. Fix: add stub FUNCTION nodes for the 10 standard JPA inherited methods on every detected repo interface.

**What to add in `spring/data.py`:**

At module level, add constants:

```python
# Standard JPA inherited CRUD methods — not declared in source, but called via service layer
_JPA_INHERITED_METHODS: list[str] = [
    "save", "saveAll",
    "findById", "findAll", "findAllById",
    "deleteById", "delete", "deleteAll",
    "count", "existsById",
]

_JPA_WRITE_METHODS: frozenset[str] = frozenset({
    "save", "saveAll", "deleteById", "delete", "deleteAll",
})

_JPA_READ_METHODS: frozenset[str] = frozenset({
    "findById", "findAll", "findAllById", "count", "existsById",
})
```

In `extract()`, change `nodes: list[GraphNode] = []` to collect stub nodes. After the `# Find repository interfaces` loop, for each detected repo, **before** the `if not table_fqn: continue` guard, add the stub nodes. Then if `table_fqn` exists, also add READS/WRITES edges for the stubs.

Also fix `detect()` to add annotation-based fallback (same fix as spring-web):

```python
def detect(self, context: AnalysisContext) -> PluginDetectionResult:
    if context.manifest:
        for fw in context.manifest.detected_frameworks:
            if "spring" in fw.name.lower():
                return PluginDetectionResult(
                    confidence=Confidence.HIGH,
                    reason=f"Framework '{fw.name}' detected in manifest",
                )
    # Fallback: look for JPA repository interfaces in graph
    for node in context.graph.nodes.values():
        implements = set(node.properties.get("implements", []))
        if implements & _REPO_BASE_INTERFACES:
            return PluginDetectionResult(
                confidence=Confidence.MEDIUM,
                reason="Spring Data repository interfaces found in graph",
            )
    return PluginDetectionResult.not_detected()
```

Full restructured inner loop for `extract()` (replace the repo processing block):

```python
for node in graph.nodes.values():
    if not node.properties.get("is_interface", False):
        continue
    implements = set(node.properties.get("implements", []))
    if not (implements & _REPO_BASE_INTERFACES):
        continue

    type_args = node.properties.get("type_args", [])
    if not type_args:
        continue

    entity_name = type_args[0]

    # MANAGES edge: repository -> entity
    entity_fqn = self._find_entity_fqn(graph, entity_name)
    if entity_fqn:
        edges.append(GraphEdge(
            source_fqn=node.fqn,
            target_fqn=entity_fqn,
            kind=EdgeKind.MANAGES,
            confidence=Confidence.HIGH,
            evidence="spring-data",
        ))

    # --- NEW: Stub inherited JPA method nodes ---
    for method_name in _JPA_INHERITED_METHODS:
        stub_fqn = f"{node.fqn}.{method_name}"
        if graph.get_node(stub_fqn) is None:
            stub_node = GraphNode(
                fqn=stub_fqn,
                name=method_name,
                kind=NodeKind.FUNCTION,
                language="java",
                properties={"is_jpa_stub": True},
            )
            nodes.append(stub_node)
            edges.append(GraphEdge(
                source_fqn=node.fqn,
                target_fqn=stub_fqn,
                kind=EdgeKind.CONTAINS,
                confidence=Confidence.HIGH,
                evidence="spring-data",
            ))

    # Get the table FQN for this entity (needed for READS/WRITES below)
    table_fqn = entity_to_table.get(entity_name)
    if not table_fqn:
        warnings.append(
            f"No table mapping found for entity '{entity_name}' in repo '{node.fqn}'"
        )
    else:
        # READS/WRITES edges for stub methods
        for method_name in _JPA_INHERITED_METHODS:
            stub_fqn = f"{node.fqn}.{method_name}"
            if method_name in _JPA_WRITE_METHODS:
                edges.append(GraphEdge(
                    source_fqn=stub_fqn,
                    target_fqn=table_fqn,
                    kind=EdgeKind.WRITES,
                    confidence=Confidence.HIGH,
                    evidence="spring-data",
                ))
            elif method_name in _JPA_READ_METHODS:
                edges.append(GraphEdge(
                    source_fqn=stub_fqn,
                    target_fqn=table_fqn,
                    kind=EdgeKind.READS,
                    confidence=Confidence.HIGH,
                    evidence="spring-data",
                ))

    # Process explicitly declared methods (unchanged from original)
    for containment_edge in graph.get_edges_from(node.fqn):
        if containment_edge.kind != EdgeKind.CONTAINS:
            continue
        method = graph.get_node(containment_edge.target_fqn)
        if method is None or method.kind != NodeKind.FUNCTION:
            continue
        # ... (rest of method processing unchanged)
```

Also change `PluginResult` to return `nodes=nodes`:
```python
return PluginResult(
    nodes=nodes,   # was []
    edges=edges,
    layer_assignments={},
    entry_points=[],
    warnings=warnings,
)
```

- [ ] **Step 1: Write the failing test**

  Create `tests/unit/plugins/test_spring_data.py` (or add to existing if it exists):

  ```python
  import pytest
  from app.models.context import AnalysisContext
  from app.models.enums import EdgeKind, NodeKind
  from app.models.graph import GraphEdge, GraphNode, SymbolGraph
  from app.stages.plugins.spring.data import SpringDataPlugin

  def _make_context_with_repo() -> AnalysisContext:
      """Build a minimal AnalysisContext with a JPA repository interface."""
      graph = SymbolGraph()

      # Entity class with @Entity annotation
      entity = GraphNode(
          fqn="com.example.model.Account",
          name="Account",
          kind=NodeKind.CLASS,
          language="java",
          properties={"annotations": ["Entity"]},
      )
      graph.add_node(entity)

      # Table node (added by Hibernate plugin)
      table = GraphNode(
          fqn="table:accounts",
          name="accounts",
          kind=NodeKind.TABLE,
          properties={},
      )
      graph.add_node(table)

      # MAPS_TO edge from entity to table
      graph.add_edge(GraphEdge(
          source_fqn="com.example.model.Account",
          target_fqn="table:accounts",
          kind=EdgeKind.MAPS_TO,
          evidence="hibernate",
      ))

      # Repository interface extending JpaRepository
      repo = GraphNode(
          fqn="com.example.repository.AccountRepository",
          name="AccountRepository",
          kind=NodeKind.INTERFACE,
          language="java",
          properties={
              "is_interface": True,
              "implements": ["JpaRepository"],
              "type_args": ["Account", "Long"],
          },
      )
      graph.add_node(repo)

      ctx = AnalysisContext(project_id="test")
      ctx.graph = graph
      return ctx

  @pytest.mark.asyncio
  async def test_stub_jpa_methods_created():
      """Spring Data plugin should create FUNCTION nodes for inherited JPA methods."""
      plugin = SpringDataPlugin()
      ctx = _make_context_with_repo()

      result = await plugin.extract(ctx)

      stub_fqns = {n.fqn for n in result.nodes}
      assert "com.example.repository.AccountRepository.save" in stub_fqns
      assert "com.example.repository.AccountRepository.findById" in stub_fqns
      assert "com.example.repository.AccountRepository.deleteById" in stub_fqns
      assert "com.example.repository.AccountRepository.count" in stub_fqns

  @pytest.mark.asyncio
  async def test_stub_nodes_are_functions():
      plugin = SpringDataPlugin()
      ctx = _make_context_with_repo()
      result = await plugin.extract(ctx)

      save_node = next(
          (n for n in result.nodes if n.fqn.endswith(".save")), None
      )
      assert save_node is not None
      assert save_node.kind == NodeKind.FUNCTION
      assert save_node.properties.get("is_jpa_stub") is True

  @pytest.mark.asyncio
  async def test_stub_methods_have_reads_writes_edges():
      """save/delete stubs should have WRITES edges; find stubs should have READS edges."""
      plugin = SpringDataPlugin()
      ctx = _make_context_with_repo()
      result = await plugin.extract(ctx)

      edge_map = {(e.source_fqn, e.kind): e for e in result.edges}

      save_fqn = "com.example.repository.AccountRepository.save"
      find_fqn = "com.example.repository.AccountRepository.findById"

      assert (save_fqn, EdgeKind.WRITES) in edge_map
      assert (find_fqn, EdgeKind.READS) in edge_map

      # They should point to the table
      assert edge_map[(save_fqn, EdgeKind.WRITES)].target_fqn == "table:accounts"
      assert edge_map[(find_fqn, EdgeKind.READS)].target_fqn == "table:accounts"

  @pytest.mark.asyncio
  async def test_no_duplicate_stubs_if_already_in_graph():
      """If a stub node already exists in the graph, don't add it again."""
      plugin = SpringDataPlugin()
      ctx = _make_context_with_repo()

      # Pre-add the save stub
      existing_save = GraphNode(
          fqn="com.example.repository.AccountRepository.save",
          name="save",
          kind=NodeKind.FUNCTION,
          language="java",
          properties={},
      )
      ctx.graph.add_node(existing_save)

      result = await plugin.extract(ctx)

      save_nodes = [n for n in result.nodes if n.fqn.endswith(".save")]
      assert len(save_nodes) == 0  # Not added again since already in graph
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  cd /home/ubuntu/cast-clone/cast-clone-backend
  uv run pytest tests/unit/plugins/test_spring_data.py -v 2>&1 | head -40
  ```
  Expected: 4 test failures (stubs not created yet).

- [ ] **Step 3: Implement the changes in `spring/data.py`**

  Apply all changes described above: add constants, fix `detect()`, restructure repo loop, change `PluginResult(nodes=nodes, ...)`.

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  cd /home/ubuntu/cast-clone/cast-clone-backend
  uv run pytest tests/unit/plugins/test_spring_data.py -v
  ```
  Expected: 4 PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add app/stages/plugins/spring/data.py tests/unit/plugins/test_spring_data.py
  git commit -m "feat(spring-data): add JPA stub FUNCTION nodes for inherited CRUD methods"
  ```

---

## Chunk 2: Transaction discovery — include TABLE nodes

### Task 2: Collect TABLE nodes reachable via WRITES/READS from BFS-visited functions

**Files:**
- Modify: `app/stages/transactions.py` — `discover_transactions()` function only
- Test: `tests/unit/test_transactions.py`

**Context:** Currently, `trace_transaction_flow` returns only FUNCTION FQNs in `visited_fqns`. The `discover_transactions` function adds `INCLUDES` edges only for those functions. TABLE nodes that the repository methods write to/read from are not included. After Task 1, the repo stub FUNCTION nodes will be visited. This task adds one extra step: after BFS, look at all WRITES/READS edges from visited functions, collect the target TABLE node FQNs, and add `INCLUDES` edges for them too. No changes to `trace_transaction_flow` — changes are only in `discover_transactions`.

**What to change in `discover_transactions`:**

After the existing INCLUDES loop (around line 302), add:

```python
# Collect TABLE nodes reachable via WRITES/READS from visited functions
seen_tables: set[str] = set()
for fn_fqn in flow.visited_fqns:
    for edge in graph.get_edges_from(fn_fqn):
        if edge.kind in (EdgeKind.WRITES, EdgeKind.READS):
            table_node = graph.get_node(edge.target_fqn)
            if table_node is not None and edge.target_fqn not in seen_tables:
                seen_tables.add(edge.target_fqn)
                graph.add_edge(
                    GraphEdge(
                        source_fqn=txn_fqn,
                        target_fqn=edge.target_fqn,
                        kind=EdgeKind.INCLUDES,
                        confidence=Confidence.HIGH,
                        evidence="transaction-discovery",
                    )
                )
```

- [ ] **Step 1: Write the failing test**

  Add to `tests/unit/test_transactions.py` (create if doesn't exist):

  ```python
  import pytest
  from app.models.context import AnalysisContext, EntryPoint
  from app.models.enums import Confidence, EdgeKind, NodeKind
  from app.models.graph import GraphEdge, GraphNode, SymbolGraph
  from app.stages.transactions import discover_transactions


  def _build_controller_service_repo_graph() -> tuple[SymbolGraph, list[EntryPoint]]:
      """
      Controller.addAccount
        -[:CALLS]-> Service.createAccount
          -[:CALLS]-> AccountRepository.save   (stub JPA node)
            -[:WRITES]-> table:accounts
      """
      graph = SymbolGraph()

      for fqn, name, kind in [
          ("com.example.AccountController.addAccount", "addAccount", NodeKind.FUNCTION),
          ("com.example.AccountService.createAccount", "createAccount", NodeKind.FUNCTION),
          ("com.example.AccountRepository.save", "save", NodeKind.FUNCTION),
      ]:
          graph.add_node(GraphNode(fqn=fqn, name=name, kind=kind, language="java"))

      table = GraphNode(
          fqn="table:accounts", name="accounts", kind=NodeKind.TABLE, properties={}
      )
      graph.add_node(table)

      graph.add_edge(GraphEdge(
          source_fqn="com.example.AccountController.addAccount",
          target_fqn="com.example.AccountService.createAccount",
          kind=EdgeKind.CALLS, confidence=Confidence.HIGH, evidence="tree-sitter",
      ))
      graph.add_edge(GraphEdge(
          source_fqn="com.example.AccountService.createAccount",
          target_fqn="com.example.AccountRepository.save",
          kind=EdgeKind.CALLS, confidence=Confidence.MEDIUM, evidence="tree-sitter",
      ))
      graph.add_edge(GraphEdge(
          source_fqn="com.example.AccountRepository.save",
          target_fqn="table:accounts",
          kind=EdgeKind.WRITES, confidence=Confidence.HIGH, evidence="spring-data",
      ))

      entry_points = [
          EntryPoint(
              fqn="com.example.AccountController.addAccount",
              kind="http_endpoint",
              metadata={"method": "POST", "path": "/accounts"},
          )
      ]
      return graph, entry_points


  @pytest.mark.asyncio
  async def test_transaction_includes_table_nodes():
      """Transaction INCLUDES edges should also point to TABLE nodes."""
      graph, entry_points = _build_controller_service_repo_graph()
      ctx = AnalysisContext(project_id="test")
      ctx.graph = graph
      ctx.entry_points = entry_points

      await discover_transactions(ctx)

      # Find the transaction node
      txn_nodes = [
          n for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION
      ]
      assert len(txn_nodes) == 1
      txn_fqn = txn_nodes[0].fqn

      # Collect all INCLUDES targets
      includes_targets = {
          e.target_fqn
          for e in ctx.graph.edges
          if e.kind == EdgeKind.INCLUDES and e.source_fqn == txn_fqn
      }

      # Should include all 3 functions + the table
      assert "com.example.AccountController.addAccount" in includes_targets
      assert "com.example.AccountService.createAccount" in includes_targets
      assert "com.example.AccountRepository.save" in includes_targets
      assert "table:accounts" in includes_targets


  @pytest.mark.asyncio
  async def test_transaction_no_duplicate_table_includes():
      """If two functions WRITE to the same table, only one INCLUDES edge to that table."""
      graph, entry_points = _build_controller_service_repo_graph()

      # Add a second service method that also writes to accounts
      graph.add_node(GraphNode(
          fqn="com.example.AccountRepository.deleteById",
          name="deleteById",
          kind=NodeKind.FUNCTION,
          language="java",
      ))
      graph.add_edge(GraphEdge(
          source_fqn="com.example.AccountService.createAccount",
          target_fqn="com.example.AccountRepository.deleteById",
          kind=EdgeKind.CALLS, confidence=Confidence.MEDIUM, evidence="tree-sitter",
      ))
      graph.add_edge(GraphEdge(
          source_fqn="com.example.AccountRepository.deleteById",
          target_fqn="table:accounts",
          kind=EdgeKind.WRITES, confidence=Confidence.HIGH, evidence="spring-data",
      ))

      ctx = AnalysisContext(project_id="test")
      ctx.graph = graph
      ctx.entry_points = entry_points

      await discover_transactions(ctx)

      txn_fqn = next(
          n.fqn for n in ctx.graph.nodes.values() if n.kind == NodeKind.TRANSACTION
      )
      table_includes = [
          e for e in ctx.graph.edges
          if e.kind == EdgeKind.INCLUDES
          and e.source_fqn == txn_fqn
          and e.target_fqn == "table:accounts"
      ]
      assert len(table_includes) == 1  # No duplicates
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  cd /home/ubuntu/cast-clone/cast-clone-backend
  uv run pytest tests/unit/test_transactions.py::test_transaction_includes_table_nodes tests/unit/test_transactions.py::test_transaction_no_duplicate_table_includes -v
  ```
  Expected: 2 failures.

- [ ] **Step 3: Implement the change in `transactions.py`**

  After the existing INCLUDES loop in `discover_transactions` (after position ~302), insert the `seen_tables` block shown above.

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  cd /home/ubuntu/cast-clone/cast-clone-backend
  uv run pytest tests/unit/test_transactions.py -v
  ```
  Expected: all PASS (including any pre-existing tests).

- [ ] **Step 5: Commit**

  ```bash
  git add app/stages/transactions.py tests/unit/test_transactions.py
  git commit -m "feat(transactions): include TABLE nodes in transaction flow via WRITES/READS edges"
  ```

---

## Chunk 3: Transaction API — return WRITES/READS edges

### Task 3: Include WRITES and READS edges in transaction detail response

**Files:**
- Modify: `app/api/graph_views.py` — `get_transaction()` endpoint only (lines ~390–406)
- Test: integration test (manual curl verification — unit test for this endpoint requires Neo4j testcontainer which is out of scope)

**Context:** `get_transaction()` currently only returns `CALLS` edges between included nodes. The frontend's `transactionToElements` function already handles WRITES/READS edges — it uses them to mark terminal nodes with an "entry-point" class and sets `classes: "data-edge"`. So the only backend change needed is to also return WRITES/READS edges from the Cypher query. Neo4j Cypher supports `[r:CALLS|WRITES|READS]` relationship type union syntax.

**What to change in `get_transaction()`:**

Replace the edge query (the second `store.query` call):

```python
# Before:
edge_records = await store.query(
    "MATCH (t {fqn: $fqn, app_name: $app_name})-[:INCLUDES]->(f1) "
    "MATCH (f1)-[r:CALLS]->(f2) "
    "WHERE (t)-[:INCLUDES]->(f2) "
    "RETURN f1.fqn AS source_fqn, f2.fqn AS target_fqn, "
    "type(r) AS kind, r.confidence AS confidence, r.evidence AS evidence",
    {"fqn": fqn, "app_name": project_id},
)

# After:
edge_records = await store.query(
    "MATCH (t {fqn: $fqn, app_name: $app_name})-[:INCLUDES]->(f1) "
    "MATCH (f1)-[r:CALLS|WRITES|READS]->(f2) "
    "WHERE (t)-[:INCLUDES]->(f2) "
    "RETURN f1.fqn AS source_fqn, f2.fqn AS target_fqn, "
    "type(r) AS kind, r.confidence AS confidence, r.evidence AS evidence",
    {"fqn": fqn, "app_name": project_id},
)
```

- [ ] **Step 1: Apply the one-line change to `graph_views.py`**

  Change `[r:CALLS]` to `[r:CALLS|WRITES|READS]` in the edge query inside `get_transaction()`.

- [ ] **Step 2: Verify with curl after re-analysis**

  After the backend is restarted and analysis re-run:
  ```bash
  # Get a transaction FQN first
  curl -s "http://localhost:8000/api/v1/graph-views/{project_id}/transactions" | python3 -m json.tool | head -20

  # Then fetch detail — edges should now include WRITES/READS
  curl -s "http://localhost:8000/api/v1/graph-views/{project_id}/transactions/{encoded_fqn}" | python3 -m json.tool | python3 -c "
  import sys, json
  d = json.load(sys.stdin)
  kinds = set(e['kind'] for e in d.get('edges', []))
  print('Edge kinds:', kinds)
  print('Node count:', len(d.get('nodes', [])))
  "
  ```
  Expected: `Edge kinds: {'CALLS', 'WRITES'}` or `{'CALLS', 'READS'}` depending on the transaction, and `Node count: 3` or `4`.

- [ ] **Step 3: Commit**

  ```bash
  git add app/api/graph_views.py
  git commit -m "feat(api): include WRITES/READS edges in transaction detail response"
  ```

---

## Chunk 4: Re-analysis + end-to-end verification

### Task 4: Re-run analysis and verify transaction depth in UI

**Context:** The code changes affect the analysis pipeline (Stage 5 — Spring Data plugin) and Stage 9 (transaction discovery). Existing Neo4j data is stale. Must re-run analysis to populate the new stub nodes and table INCLUDES edges.

- [ ] **Step 1: Restart the backend to pick up code changes**

  ```bash
  pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
  cd /home/ubuntu/cast-clone/cast-clone-backend
  nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/uvicorn.log 2>&1 &
  sleep 2 && curl -s http://localhost:8000/health | python3 -m json.tool
  ```

- [ ] **Step 2: Trigger a fresh analysis run**

  ```bash
  # Get the project ID
  PROJECT_ID=$(curl -s http://localhost:8000/api/v1/projects/ | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
  echo "Project ID: $PROJECT_ID"

  # Trigger analysis
  curl -s -X POST "http://localhost:8000/api/v1/analysis/$PROJECT_ID/analyze" | python3 -m json.tool
  ```

- [ ] **Step 3: Monitor analysis logs for Spring Data and transaction stages**

  ```bash
  tail -f /tmp/uvicorn.log | grep -E "(spring_data|transaction_discovery)" | head -20
  ```
  Expected logs:
  - `spring_data_extract_done` with `edges=N` (N should be larger than before due to stub nodes + their READS/WRITES)
  - `transaction_discovery.complete` with `transactions=23`

- [ ] **Step 4: Verify transaction nodes include TABLE nodes via Neo4j**

  ```bash
  # Check that a transaction INCLUDES a table node
  curl -s "http://localhost:8000/api/v1/graph-views/$PROJECT_ID/transactions" | \
    python3 -c "
  import sys, json
  txns = json.load(sys.stdin)['transactions']
  print(f'Total transactions: {len(txns)}')
  print('First 3:', [t['name'] for t in txns[:3]])
  "
  ```

- [ ] **Step 5: Fetch a transaction detail and verify depth**

  ```bash
  # Pick the first transaction FQN (URL-encode the colon)
  TXN_FQN=$(curl -s "http://localhost:8000/api/v1/graph-views/$PROJECT_ID/transactions" | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['transactions'][0]['fqn'])")

  TXN_ENCODED=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote('$TXN_FQN', safe=''))")

  curl -s "http://localhost:8000/api/v1/graph-views/$PROJECT_ID/transactions/$TXN_ENCODED" | \
    python3 -c "
  import sys, json
  d = json.load(sys.stdin)
  print('Transaction:', d['name'])
  print('Node count:', len(d['nodes']))
  print('Node kinds:', [n['kind'] for n in d['nodes']])
  print('Edge kinds:', list(set(e['kind'] for e in d['edges'])))
  "
  ```
  Expected: `Node count: 3` or `4`, `Node kinds` includes `TABLE`, `Edge kinds` includes `WRITES` or `READS`.

- [ ] **Step 6: Check in browser**

  Open `http://localhost:3000/projects/{project_id}/graph`, switch to Transaction view, select a transaction. The graph should now show 3–4 nodes: controller method → service method → repository stub → table node (with dashed edge from repo to table).

- [ ] **Step 7: Run full unit test suite to make sure nothing regressed**

  ```bash
  cd /home/ubuntu/cast-clone/cast-clone-backend
  uv run pytest tests/unit/ -v --tb=short 2>&1 | tail -30
  ```
  Expected: all PASS.
