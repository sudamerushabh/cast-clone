"""M3 end-to-end smoke test.

Runs the full Phase 1 pipeline (Stages 1-5 + Stage 8 writer) against a
fixture, then queries Neo4j to verify the new M3 edge types actually
persisted via apoc.merge.relationship's dynamic-edge-type path.

Usage:
    cd cast-clone-backend && uv run python scripts/m3_e2e_smoke.py fastapi-todo
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from neo4j import AsyncGraphDatabase

from app.models.context import AnalysisContext
from app.stages.dependencies import resolve_dependencies
from app.stages.discovery import discover_project
from app.stages.plugins.registry import run_framework_plugins
from app.stages.scip.indexer import run_scip_indexers
from app.stages.treesitter.parser import parse_with_treesitter
from app.stages.writer import write_to_neo4j
from app.services.neo4j import Neo4jGraphStore

NEO4J_URI = "bolt://localhost:17687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "codelens"


async def main(fixture_name: str) -> None:
    fixture_root = Path(__file__).parent.parent / "tests" / "fixtures" / fixture_name
    if not fixture_root.is_dir():
        print(f"❌ fixture not found: {fixture_root}")
        sys.exit(1)

    project_id = f"m3-smoke-{fixture_name}"
    print(f"\n=== M3 E2E smoke test: {fixture_name} ===")
    print(f"project_id: {project_id}")
    print(f"fixture: {fixture_root}\n")

    # Register python tree-sitter extractor (mirrors integration conftest)
    from app.stages.treesitter.extractors import register_extractor
    from app.stages.treesitter.extractors.python import PythonExtractor

    try:
        register_extractor("python", PythonExtractor())
    except Exception:
        pass  # already registered

    manifest = discover_project(fixture_root)
    environment = await resolve_dependencies(manifest)
    graph = await parse_with_treesitter(manifest)
    ctx = AnalysisContext(
        project_id=project_id,
        graph=graph,
        manifest=manifest,
        environment=environment,
    )
    await run_scip_indexers(ctx)
    await run_framework_plugins(ctx)

    print(f"In-memory graph: {ctx.graph.node_count} nodes, {ctx.graph.edge_count} edges")

    # Edge-kind counts in memory before writing
    from collections import Counter

    in_mem_edges = Counter(e.kind.value for e in ctx.graph.edges)
    print("In-memory edge counts (top 10):")
    for k, c in sorted(in_mem_edges.items(), key=lambda x: -x[1])[:10]:
        print(f"  {k}: {c}")

    # Write to Neo4j
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    store = Neo4jGraphStore(driver)

    try:
        await write_to_neo4j(ctx, store)
        print("\n✅ write_to_neo4j succeeded")

        # Query Neo4j for the M3 edge types specifically
        async with driver.session() as session:
            edge_kinds_to_check = [
                "ACCEPTS",
                "RETURNS",
                "MAPS_TO",
                "CONSUMES",
                "PRODUCES",
                "INHERITS",
                "HANDLES",
                "HAS_COLUMN",
                "CONTAINS",
                "CALLS",
            ]
            print("\nNeo4j edge counts (after write):")
            for kind in edge_kinds_to_check:
                rec = await session.run(
                    f"MATCH (a {{app_name: $app}})-[r:{kind}]->(b {{app_name: $app}}) "
                    f"RETURN count(r) AS c",
                    app=project_id,
                )
                row = await rec.single()
                count = row["c"] if row else 0
                marker = "🆕" if kind in {"ACCEPTS", "RETURNS"} else "  "
                print(f"  {marker} {kind}: {count}")

            # Sanity: print one sample of each new edge type
            print("\nSamples of new edge types:")
            for kind in ["ACCEPTS", "RETURNS", "MAPS_TO", "CONSUMES", "PRODUCES"]:
                rec = await session.run(
                    f"MATCH (a {{app_name: $app}})-[r:{kind}]->(b {{app_name: $app}}) "
                    f"RETURN a.fqn AS source, b.fqn AS target, r.evidence AS ev "
                    f"LIMIT 1",
                    app=project_id,
                )
                row = await rec.single()
                if row:
                    print(
                        f"  {kind}: ({row['source']}) -> ({row['target']}) "
                        f"[evidence={row['ev']}]"
                    )
                else:
                    print(f"  {kind}: <no edges>")

    finally:
        await driver.close()


if __name__ == "__main__":
    fixture = sys.argv[1] if len(sys.argv) > 1 else "fastapi-todo"
    asyncio.run(main(fixture))
