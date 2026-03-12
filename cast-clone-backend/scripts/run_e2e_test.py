#!/usr/bin/env python3
"""True end-to-end integration test: run all 9 stages against PetClinic with real Neo4j.

Usage:
    cd cast-clone-backend
    uv run python scripts/run_e2e_test.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neo4j import AsyncGraphDatabase

from app.models.context import AnalysisContext
from app.services.neo4j import Neo4jGraphStore


# ── Config ────────────────────────────────────────────────────────────
NEO4J_URI = "bolt://localhost:17687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "codelens"
PETCLINIC_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "spring-petclinic"
PROJECT_ID = "e2e-petclinic-test"


def banner(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def stage_header(num: str, name: str) -> None:
    print(f"\n--- Stage {num}: {name} ---")


async def main() -> None:
    banner("END-TO-END INTEGRATION TEST: Spring PetClinic")
    print(f"Source:  {PETCLINIC_PATH}")
    print(f"Neo4j:   {NEO4J_URI}")
    print(f"Project: {PROJECT_ID}")

    # Verify fixture exists
    if not PETCLINIC_PATH.exists():
        print(f"ERROR: PetClinic fixture not found at {PETCLINIC_PATH}")
        sys.exit(1)

    # Connect to Neo4j
    print("\nConnecting to Neo4j...")
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        await driver.verify_connectivity()
        print("  Connected!")
    except Exception as e:
        print(f"  ERROR: Cannot connect to Neo4j: {e}")
        sys.exit(1)

    store = Neo4jGraphStore(driver)
    context = AnalysisContext(project_id=PROJECT_ID)
    pipeline_start = time.monotonic()

    # Register tree-sitter extractors (they self-register on import)
    from app.stages.treesitter.extractors.java import JavaExtractor
    from app.stages.treesitter.extractors import register_extractor
    register_extractor("java", JavaExtractor())

    # ── Stage 1: Discovery ────────────────────────────────────────
    stage_header("1", "Project Discovery")
    t = time.monotonic()
    from app.stages.discovery import discover_project
    context.manifest = discover_project(PETCLINIC_PATH)
    elapsed = time.monotonic() - t

    print(f"  Files:       {context.manifest.total_files}")
    print(f"  LOC:         {context.manifest.total_loc}")
    print(f"  Languages:   {context.manifest.language_names}")
    print(f"  Build tools: {[bt.name for bt in context.manifest.build_tools]}")
    print(f"  Frameworks:  {[fw.name for fw in context.manifest.detected_frameworks]}")
    print(f"  Duration:    {elapsed:.2f}s")

    # ── Stage 2: Dependencies ─────────────────────────────────────
    stage_header("2", "Dependency Resolution")
    t = time.monotonic()
    from app.stages.dependencies import resolve_dependencies
    context.environment = await resolve_dependencies(context.manifest)
    elapsed = time.monotonic() - t

    total_deps = sum(len(deps) for deps in context.environment.dependencies.values())
    print(f"  Deps found:  {total_deps}")
    for lang, deps in context.environment.dependencies.items():
        print(f"    [{lang}]:")
        for dep in deps[:5]:
            print(f"      - {dep.name} ({dep.version or 'unknown'})")
        if len(deps) > 5:
            print(f"      ... and {len(deps) - 5} more")
    print(f"  Duration:    {elapsed:.2f}s")

    # ── Stage 3: Tree-sitter Parsing ──────────────────────────────
    stage_header("3", "Tree-sitter Parsing")
    t = time.monotonic()
    from app.stages.treesitter.parser import parse_with_treesitter
    graph = await parse_with_treesitter(context.manifest)
    context.graph.merge(graph)
    elapsed = time.monotonic() - t

    print(f"  Nodes:       {context.graph.node_count}")
    print(f"  Edges:       {context.graph.edge_count}")
    # Show node breakdown by kind
    kind_counts: dict[str, int] = {}
    for node in context.graph.nodes.values():
        k = node.kind.value
        kind_counts[k] = kind_counts.get(k, 0) + 1
    for k, c in sorted(kind_counts.items()):
        print(f"    {k}: {c}")
    print(f"  Duration:    {elapsed:.2f}s")

    # ── Stage 4: SCIP Indexers ────────────────────────────────────
    stage_header("4", "SCIP Indexers")
    t = time.monotonic()
    try:
        from app.stages.scip.indexer import run_scip_indexers
        await run_scip_indexers(context)
        elapsed = time.monotonic() - t
        print(f"  SCIP resolved: {context.scip_resolved_languages}")
        print(f"  Duration:      {elapsed:.2f}s")
    except Exception as e:
        elapsed = time.monotonic() - t
        print(f"  SKIPPED (no SCIP binaries): {e}")
        print(f"  Duration:      {elapsed:.2f}s")
        context.warnings.append(f"Stage 'scip' failed: {e}")

    # ── Stage 4b: LSP Fallback ────────────────────────────────────
    stage_header("4b", "LSP Fallback")
    if context.languages_needing_fallback:
        print(f"  Languages needing fallback: {context.languages_needing_fallback}")
        print("  (Not yet implemented — skipped)")
    else:
        print("  No languages need fallback")

    # ── Stage 5: Framework Plugins ────────────────────────────────
    stage_header("5", "Framework Plugins")
    t = time.monotonic()
    from app.stages.plugins.registry import run_framework_plugins
    await run_framework_plugins(context)
    elapsed = time.monotonic() - t

    print(f"  New nodes:   {context.plugin_new_nodes}")
    print(f"  New edges:   {context.plugin_new_edges}")
    if context.layer_assignments:
        from collections import Counter
        layer_counts = Counter(context.layer_assignments.values())
        print(f"  Layers:      {dict(layer_counts)}")
    else:
        print("  Layers:      (none assigned)")
    print(f"  Entry pts:   {len(context.entry_points)}")
    for ep in context.entry_points[:5]:
        print(f"    - [{ep.kind}] {ep.fqn} {ep.metadata}")
    if len(context.entry_points) > 5:
        print(f"    ... and {len(context.entry_points) - 5} more")
    print(f"  Duration:    {elapsed:.2f}s")

    # ── Stage 6: Cross-Technology Linker ──────────────────────────
    stage_header("6", "Cross-Technology Linker")
    t = time.monotonic()
    from app.stages.linker import run_cross_tech_linker
    await run_cross_tech_linker(context)
    elapsed = time.monotonic() - t

    print(f"  Cross-tech edges: {context.cross_tech_edge_count}")
    print(f"  Duration:         {elapsed:.2f}s")

    # ── Stage 7: Enrichment ───────────────────────────────────────
    stage_header("7", "Graph Enrichment")
    t = time.monotonic()
    from app.stages.enricher import enrich_graph
    await enrich_graph(context)
    elapsed = time.monotonic() - t

    print(f"  Total nodes:  {context.graph.node_count}")
    print(f"  Total edges:  {context.graph.edge_count}")
    print(f"  Communities:  {context.community_count}")
    print(f"  Duration:     {elapsed:.2f}s")

    # ── Stage 8: Neo4j Writer ─────────────────────────────────────
    stage_header("8", "Neo4j Writer (CRITICAL)")
    t = time.monotonic()
    from app.stages.writer import write_to_neo4j
    await write_to_neo4j(context, store)
    elapsed = time.monotonic() - t

    print(f"  Nodes written: {context.graph.node_count}")
    print(f"  Edges written: {context.graph.edge_count}")
    print(f"  Duration:      {elapsed:.2f}s")

    # ── Stage 9: Transaction Discovery ────────────────────────────
    stage_header("9", "Transaction Discovery")
    t = time.monotonic()
    from app.stages.transactions import discover_transactions
    await discover_transactions(context)
    elapsed = time.monotonic() - t

    print(f"  Transactions: {context.transaction_count}")
    print(f"  Entry points: {len(context.entry_points)}")
    print(f"  Duration:     {elapsed:.2f}s")

    # ── Summary ───────────────────────────────────────────────────
    total_elapsed = time.monotonic() - pipeline_start
    banner("PIPELINE COMPLETE")
    print(f"  Total nodes:     {context.graph.node_count}")
    print(f"  Total edges:     {context.graph.edge_count}")
    print(f"  Communities:     {context.community_count}")
    print(f"  Transactions:    {context.transaction_count}")
    print(f"  Total duration:  {total_elapsed:.2f}s")
    if context.warnings:
        print(f"\n  Warnings ({len(context.warnings)}):")
        for w in context.warnings:
            print(f"    - {w}")

    # ── Verify in Neo4j ───────────────────────────────────────────
    banner("NEO4J VERIFICATION QUERIES")

    # Total nodes
    result = await store.query("MATCH (n {app_name: $app}) RETURN count(n) AS cnt", {"app": PROJECT_ID})
    print(f"\n  Total nodes in Neo4j:  {result[0]['cnt']}")

    # Nodes by label
    result = await store.query(
        "MATCH (n {app_name: $app}) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC",
        {"app": PROJECT_ID},
    )
    print("  Nodes by label:")
    for row in result:
        print(f"    {row['label']}: {row['cnt']}")

    # Total relationships
    result = await store.query(
        "MATCH (n {app_name: $app})-[r]->(m) RETURN type(r) AS rel_type, count(r) AS cnt ORDER BY cnt DESC",
        {"app": PROJECT_ID},
    )
    print("  Relationships by type:")
    for row in result:
        print(f"    {row['rel_type']}: {row['cnt']}")

    # OwnerController call chain
    print("\n  OwnerController call chain:")
    result = await store.query(
        """
        MATCH (c {fqn: 'org.springframework.samples.petclinic.owner.OwnerController'})
        OPTIONAL MATCH (c)-[:CONTAINS]->(m)
        RETURN c.name AS class_name, collect(m.name) AS methods
        """,
        {},
    )
    if result:
        print(f"    Class: {result[0]['class_name']}")
        print(f"    Methods: {result[0]['methods']}")

    # Spring DI injection edges
    result = await store.query(
        "MATCH ()-[r:INJECTS]->() RETURN count(r) AS cnt",
        {},
    )
    print(f"\n  Spring DI INJECTS edges: {result[0]['cnt']}")

    # API endpoints
    result = await store.query(
        "MATCH (n:APIEndpoint) RETURN n.name AS name, n.fqn AS fqn LIMIT 10",
        {},
    )
    if result:
        print("  API Endpoints:")
        for row in result:
            print(f"    {row['name']} ({row['fqn']})")
    else:
        print("  API Endpoints: (none found)")

    # Application node
    result = await store.query(
        "MATCH (a:Application {fqn: $pid}) RETURN a.languages AS langs, a.frameworks AS fw, a.total_files AS files",
        {"pid": PROJECT_ID},
    )
    if result:
        print(f"\n  Application node:")
        print(f"    Languages:  {result[0]['langs']}")
        print(f"    Frameworks: {result[0]['fw']}")
        print(f"    Files:      {result[0]['files']}")

    # Clean up
    banner("CLEANUP")
    await store.clear_project(PROJECT_ID)
    print("  Cleared test data from Neo4j")
    await driver.close()
    print("  Closed Neo4j connection")
    print("\n  ALL DONE!")


if __name__ == "__main__":
    asyncio.run(main())
