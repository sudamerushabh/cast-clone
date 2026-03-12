# Deep Dive — Analysis Orchestrator (Revised)

**Focus:** How the pipeline stages connect, run, and recover from failures
**Last Updated:** Simplified — focuses on wiring, references other docs for stage details

---

## Overview

The Analysis Orchestrator coordinates the entire analysis pipeline: project discovery → dependency resolution → tree-sitter parsing → SCIP indexing → framework plugins → cross-tech linking → graph enrichment → Neo4j writing → transaction discovery.

**Design principles:**
1. Each stage produces a well-defined output consumed by subsequent stages
2. If any stage fails, the pipeline continues with reduced accuracy
3. Progress is reported via WebSocket in real-time
4. The whole pipeline is a single async function — no Celery needed for Phase 1-3

---

## Why Not Celery (Yet)

In Phase 1-3, analysis is a **single long-running job** triggered by one user at a time. Celery adds:
- A separate worker process + Redis broker configuration
- Complexity passing mutable state between chained tasks
- Event loop issues when running async subprocess code inside sync Celery tasks

**Phase 1-3:** Run the pipeline as a single `async` function inside a FastAPI background task. Use `asyncio.create_subprocess_exec` for SCIP (I/O-bound subprocesses) and `concurrent.futures.ProcessPoolExecutor` for tree-sitter (CPU-bound parsing).

**Phase 4+:** When multiple users trigger concurrent analyses, migrate to Celery with Redis. The refactor is straightforward because each stage is already an independent function.

```python
# Phase 1-3: Simple background task
from fastapi import BackgroundTasks

@app.post("/api/v1/projects/{project_id}/analyze")
async def trigger_analysis(project_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_analysis_pipeline, project_id)
    return {"status": "started"}

# Phase 4+: Upgrade to Celery when needed
@celery.task(bind=True)
def run_analysis_celery(self, project_id: str):
    asyncio.run(run_analysis_pipeline(project_id))
```

---

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    run_analysis_pipeline()                        │
│                                                                   │
│  Input: project_id (source path stored in DB)                    │
│  Output: populated Neo4j graph + analysis report                 │
│                                                                   │
│  Stage 1: discover_project()        → ProjectManifest            │
│       ▼                                                           │
│  Stage 2: resolve_dependencies()    → ResolvedEnvironment        │
│       ▼                                                           │
│  Stage 3: parse_with_treesitter()   → RawSymbolGraph             │
│       ▼                (CPU-bound: ProcessPoolExecutor)           │
│  Stage 4: run_scip_indexers()       → ResolvedSymbolGraph        │
│       ▼                (I/O-bound: asyncio.gather parallel)      │
│  Stage 4b: run_lsp_fallback()       → (only if SCIP missed any) │
│       ▼                                                           │
│  Stage 5: run_framework_plugins()   → EnrichedGraph              │
│       ▼                                                           │
│  Stage 6: run_cross_tech_linker()   → LinkedGraph                │
│       ▼                                                           │
│  Stage 7: enrich_graph()            → FinalGraph                 │
│       ▼                                                           │
│  Stage 8: write_to_neo4j()          → Database populated         │
│       ▼                                                           │
│  Stage 9: discover_transactions()   → Transaction subgraphs      │
└─────────────────────────────────────────────────────────────────┘
```

---

## The Orchestrator Function

This is the actual wiring — the complete pipeline in one async function:

```python
async def run_analysis_pipeline(project_id: str) -> AnalysisReport:
    """Main orchestrator. Runs all stages sequentially, reports progress via WebSocket."""
    
    project = await db.get_project(project_id)
    source_path = Path(project.source_path)
    context = AnalysisContext(project_id=project_id)
    ws = WebSocketProgressReporter(project_id)
    
    try:
        # ── Stage 1: Project Discovery ──────────────────────────────
        await ws.emit("discovery", "running", "Scanning filesystem...")
        context.manifest = discover_project(source_path)
        await ws.emit("discovery", "complete", details={
            "files": context.manifest.total_files,
            "languages": [l.name for l in context.manifest.detected_languages],
            "frameworks": [f.name for f in context.manifest.detected_frameworks],
        })
        
        # ── Stage 2: Dependency Resolution ──────────────────────────
        await ws.emit("dependencies", "running", "Resolving dependencies...")
        context.environment = await resolve_dependencies(context.manifest)
        await ws.emit("dependencies", "complete")
        
        # ── Stage 3: Tree-sitter Parse (CPU-bound, parallel) ───────
        await ws.emit("parsing", "running", "Parsing source files...")
        context.raw_graph = await run_in_process_pool(
            parse_with_treesitter, context.manifest
        )
        await ws.emit("parsing", "complete", details={
            "nodes": len(context.raw_graph.nodes),
            "edges": len(context.raw_graph.edges),
        })
        
        # ── Stage 4: SCIP Indexing (I/O-bound, parallel per language) ─
        await ws.emit("scip", "running", "Running SCIP indexers...")
        scip_result = await run_scip_indexers(context)
        await ws.emit("scip", "complete", details={
            "resolved": scip_result.resolved_count,
            "languages": list(context.scip_resolved_languages),
        })
        
        # ── Stage 4b: LSP Fallback (only if needed) ────────────────
        if context.languages_needing_fallback:
            await ws.emit("lsp_fallback", "running",
                f"LSP fallback for: {context.languages_needing_fallback}")
            await run_lsp_fallback(context)
            await ws.emit("lsp_fallback", "complete")
        else:
            await ws.emit("lsp_fallback", "skipped")
        
        # ── Stage 5: Framework Plugins ──────────────────────────────
        await ws.emit("plugins", "running", "Running framework plugins...")
        await run_framework_plugins(context)
        await ws.emit("plugins", "complete", details={
            "new_nodes": context.plugin_new_nodes,
            "new_edges": context.plugin_new_edges,
        })
        
        # ── Stage 6: Cross-Tech Linker ──────────────────────────────
        await ws.emit("linking", "running", "Linking cross-technology dependencies...")
        await run_cross_tech_linker(context)
        await ws.emit("linking", "complete", details={
            "cross_tech_edges": context.cross_tech_edge_count,
        })
        
        # ── Stage 7: Graph Enrichment ───────────────────────────────
        await ws.emit("enrichment", "running", "Computing metrics and communities...")
        await enrich_graph(context)
        await ws.emit("enrichment", "complete", details={
            "communities": context.community_count,
        })
        
        # ── Stage 8: Write to Neo4j ─────────────────────────────────
        await ws.emit("writing", "running", "Writing to database...")
        await write_to_neo4j(context)
        await ws.emit("writing", "complete")
        
        # ── Stage 9: Transaction Discovery ──────────────────────────
        await ws.emit("transactions", "running", "Discovering transaction flows...")
        await discover_transactions(context)
        await ws.emit("transactions", "complete", details={
            "transactions": context.transaction_count,
        })
        
        # ── Done ────────────────────────────────────────────────────
        report = build_analysis_report(context)
        await ws.emit_complete(report)
        await db.update_project_status(project_id, "analyzed", report)
        return report
    
    except Exception as e:
        await ws.emit_error(str(e))
        await db.update_project_status(project_id, "failed", error=str(e))
        raise
```

That's the entire orchestrator. Each `stage_function(context)` modifies the shared `AnalysisContext` and is detailed in its respective document.

---

## Subprocess Management for SCIP Indexers

SCIP indexers run as external processes. They need timeout handling and parallel execution.

```python
import asyncio

async def run_subprocess(
    command: list[str],
    cwd: Path,
    timeout: int,
    env: dict | None = None,
) -> SubprocessResult:
    """Run an external command with timeout and capture output."""
    
    merged_env = {**os.environ, **(env or {})}
    
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=merged_env,
    )
    
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return SubprocessResult(
            returncode=proc.returncode,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError:
        # Kill the process if it exceeds timeout
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"Command timed out after {timeout}s: {' '.join(command)}")
```

### Parallel SCIP Execution

SCIP indexers for different languages run simultaneously:

```python
async def run_scip_indexers(context: AnalysisContext) -> SCIPResult:
    """Run all applicable SCIP indexers in parallel."""
    
    tasks = []
    for lang in context.manifest.detected_languages:
        indexer = SCIP_INDEXERS.get(lang.language)
        if indexer:
            tasks.append(run_single_scip_indexer(context, lang, indexer))
        else:
            context.languages_needing_fallback.append(lang.language)
    
    # Run all indexers in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results, handle failures
    total_resolved = 0
    for lang, result in zip(context.manifest.detected_languages, results):
        if isinstance(result, Exception):
            context.warnings.append(f"SCIP indexer failed for {lang.name}: {result}")
            context.languages_needing_fallback.append(lang.language)
        else:
            total_resolved += result.resolved_count
            context.scip_resolved_languages.add(lang.language)
    
    return SCIPResult(resolved_count=total_resolved)


async def run_single_scip_indexer(
    context: AnalysisContext, lang, indexer_config
) -> SCIPMergeStats:
    """Run one SCIP indexer and merge results into context."""
    
    command = build_scip_command(indexer_config, context)
    
    result = await run_subprocess(
        command=command,
        cwd=context.manifest.root_path,
        timeout=indexer_config.timeout_seconds,
        env=context.environment.env_vars,
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"{indexer_config.name} exited with code {result.returncode}: "
                          f"{result.stderr[:500]}")
    
    # Parse SCIP protobuf output
    index_path = context.manifest.root_path / indexer_config.output_file
    scip_index = parse_scip_protobuf(index_path)
    
    # Merge into context (see Phase 1 doc for merge algorithm)
    stats = merge_scip_into_context(context, scip_index, lang.language)
    return stats
```

### Tree-sitter Parallel Parsing (CPU-bound)

Tree-sitter parsing is CPU-bound, so use a process pool instead of asyncio:

```python
from concurrent.futures import ProcessPoolExecutor

async def run_in_process_pool(func, manifest):
    """Run CPU-bound tree-sitter parsing in a process pool."""
    loop = asyncio.get_event_loop()
    
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
        # Split files into chunks, one per worker
        file_chunks = split_files_by_language(manifest)
        
        futures = [
            loop.run_in_executor(pool, parse_file_chunk, chunk)
            for chunk in file_chunks
        ]
        
        results = await asyncio.gather(*futures)
    
    # Merge results from all workers
    return merge_parse_results(results)
```

---

## WebSocket Progress Reporting

```python
from fastapi import WebSocket

# Store active connections per project
active_connections: dict[str, list[WebSocket]] = {}

class WebSocketProgressReporter:
    def __init__(self, project_id: str):
        self.project_id = project_id
    
    async def emit(self, stage: str, status: str, message: str = "", details: dict = None):
        event = {
            "stage": stage,
            "status": status,
            "message": message,
            "details": details or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        for ws in active_connections.get(self.project_id, []):
            try:
                await ws.send_json(event)
            except:
                pass  # connection may have closed
    
    async def emit_complete(self, report: AnalysisReport):
        await self.emit("complete", "complete", details=report.to_dict())
    
    async def emit_error(self, error: str):
        await self.emit("error", "failed", message=error)


# WebSocket endpoint
@app.websocket("/api/v1/projects/{project_id}/progress")
async def analysis_progress(websocket: WebSocket, project_id: str):
    await websocket.accept()
    active_connections.setdefault(project_id, []).append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep connection alive
    except:
        active_connections[project_id].remove(websocket)
```

### Progress Event Stream

```json
{"stage": "discovery", "status": "complete", "details": {"files": 1342, "languages": ["java", "typescript"]}}
{"stage": "dependencies", "status": "complete"}
{"stage": "parsing", "status": "complete", "details": {"nodes": 12450, "edges": 34200}}
{"stage": "scip", "status": "running", "message": "Running scip-java indexer..."}
{"stage": "scip", "status": "complete", "details": {"resolved": 11800, "languages": ["java", "typescript"]}}
{"stage": "lsp_fallback", "status": "skipped"}
{"stage": "plugins", "status": "complete", "details": {"new_nodes": 340, "new_edges": 890}}
{"stage": "linking", "status": "complete", "details": {"cross_tech_edges": 45}}
{"stage": "enrichment", "status": "complete", "details": {"communities": 12}}
{"stage": "writing", "status": "complete"}
{"stage": "transactions", "status": "complete", "details": {"transactions": 89}}
{"stage": "complete", "status": "complete", "details": {"total_nodes": 13200, "total_edges": 36400, "duration_seconds": 185}}
```

---

## Error Recovery

### Per-Stage Error Handling

Every stage is wrapped in try/except inside the orchestrator. A stage failure doesn't crash the pipeline — it logs a warning and continues:

```python
# Pattern used for every non-critical stage:
try:
    await run_framework_plugins(context)
except Exception as e:
    context.warnings.append(f"Framework plugins failed: {e}")
    # Pipeline continues without plugin-enriched edges
```

### Critical vs. Non-Critical Stages

| Stage | On Failure | Impact | Critical? |
|-------|-----------|--------|-----------|
| 1. Discovery | **Abort** — can't proceed without manifest | Fatal | Yes |
| 2. Dependencies | Warn, continue | SCIP accuracy reduced | No |
| 3. Tree-sitter | Warn for failed files, continue with rest | Missing nodes for failed files | No |
| 4. SCIP | Queue language for LSP fallback | Falls to Stage 4b | No |
| 4b. LSP fallback | Warn, continue | Some edges stay UNRESOLVED | No |
| 5. Plugins | Skip failed plugin + dependents | Missing framework connections | No |
| 6. Cross-tech linker | Warn, continue | Missing cross-language edges | No |
| 7. Enrichment | Warn, continue | Missing metrics/communities | No |
| 8. Neo4j writer | **Abort** — can't save results | Fatal | Yes |
| 9. Transactions | Warn, continue | Missing transaction views | No |

Only Stage 1 (discovery) and Stage 8 (writing) are fatal. Everything else degrades gracefully.

### Accuracy Degradation

| What Succeeds | Accuracy | User Gets |
|---------------|----------|-----------|
| Everything | ~95% | Full architecture intelligence |
| SCIP fails → LSP fallback works | ~90% | Same quality, slower |
| SCIP + LSP both fail, plugins work | ~70% | Structure + framework info, some calls unresolved |
| Only tree-sitter succeeds | ~35% | Basic file/class/import structure |

---

## Stage Reference

Each stage's implementation details are in the corresponding doc:

| Stage | Implementation Details In |
|-------|--------------------------|
| Stage 1: Project Discovery | `01-PHASE-1-CORE-ENGINE.md` §5 |
| Stage 2: Dependency Resolution | `01-PHASE-1-CORE-ENGINE.md` §5 |
| Stage 3: Tree-sitter Parse | `01-PHASE-1-CORE-ENGINE.md` §2 |
| Stage 4: SCIP Indexing | `01-PHASE-1-CORE-ENGINE.md` §3 |
| Stage 4b: LSP Fallback | `01-PHASE-1-CORE-ENGINE.md` §3 |
| Stage 5: Framework Plugins | `08-FRAMEWORK-PLUGINS.md` |
| Stage 6: Cross-Tech Linker | `08-FRAMEWORK-PLUGINS.md` (Cross-Technology Linkers section) |
| Stage 7: Graph Enrichment | `03-PHASE-3-IMPACT-ANALYSIS.md` §4 (community detection) |
| Stage 8: Neo4j Writer | `09-NEO4J-SCHEMA.md` (batch write patterns) |
| Stage 9: Transaction Discovery | `01-PHASE-1-CORE-ENGINE.md` §5 |

---

## Configuration

The orchestrator accepts optional configuration overrides:

```python
@dataclass
class AnalysisConfig:
    # Plugin toggles
    enabled_plugins: list[str] | None = None    # None = auto-detect all
    disabled_plugins: list[str] = field(default_factory=list)
    
    # Timeouts
    dependency_timeout: int = 600        # 10 min for dependency resolution
    scip_timeout: int = 600              # 10 min per SCIP indexer
    lsp_timeout: int = 600               # 10 min for LSP fallback
    total_timeout: int = 3600            # 1 hour total pipeline limit
    
    # SCIP
    skip_scip: bool = False              # Force LSP-only mode
    skip_lsp_fallback: bool = False      # Skip LSP even if SCIP fails
    
    # Graph
    max_traversal_depth: int = 15        # For transaction discovery
    community_detection: bool = True     # Run Louvain
    
    # Dependency resolution
    skip_dependencies: bool = False      # Skip dep resolution (faster, less accurate)
    dependency_cache_dir: Path = Path("/data/cache/deps")
```

Stored per-project in PostgreSQL. Editable via the project settings UI (Phase 4).

---

## File Structure

```
src/
  orchestrator/
    pipeline.py              # run_analysis_pipeline() — the main function above
    subprocess_utils.py      # run_subprocess(), run_in_process_pool()
    progress.py              # WebSocketProgressReporter
    config.py                # AnalysisConfig
  stages/
    discovery.py             # Stage 1: discover_project()
    dependencies.py          # Stage 2: resolve_dependencies()
    treesitter/
      parser.py              # Stage 3: parse_with_treesitter()
      extractors/
        java.py
        python.py
        typescript.py
        csharp.py
    scip/
      indexer.py             # Stage 4: run_scip_indexers()
      protobuf_parser.py     # parse_scip_protobuf()
      merger.py              # merge_scip_into_context()
    lsp/
      fallback.py            # Stage 4b: run_lsp_fallback()
    plugins/
      executor.py            # Stage 5: run_framework_plugins()
      loader.py              # Plugin auto-discovery
    linker.py                # Stage 6: run_cross_tech_linker()
    enricher.py              # Stage 7: enrich_graph()
    writer.py                # Stage 8: write_to_neo4j()
    transactions.py          # Stage 9: discover_transactions()
  models/
    context.py               # AnalysisContext
    graph.py                 # GraphNode, GraphEdge
    manifest.py              # ProjectManifest
```

---

## Summary

The orchestrator is one async function that calls nine stage functions in sequence, emits progress via WebSocket, and handles errors gracefully. SCIP indexers run as parallel subprocesses via `asyncio.gather`. Tree-sitter parsing runs in a process pool. Everything else is sequential Python.

No Celery. No task chains. No message queues. No distributed computing framework. Just an async function with subprocess calls and error handling. Upgrade to Celery in Phase 4 when concurrent multi-user analysis is needed.