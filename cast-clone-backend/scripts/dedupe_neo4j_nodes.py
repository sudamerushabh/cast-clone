"""One-shot Neo4j duplicate-node cleanup (CHAN-68).

Before commit ``07fda9c`` (CHAN-64/65/66), the writer used
``apoc.create.node`` which created a new node on every pipeline run. Re-running
analysis on the same project therefore produced duplicate ``(label, fqn)``
pairs. After ``07fda9c`` the writer uses ``UNWIND + MERGE`` and is idempotent,
but databases populated by earlier code must be de-duplicated before UNIQUE
constraints (``ensure_schema_constraints``) can be applied — applying a UNIQUE
constraint against data that already violates it will raise.

Usage::

    # Dry run: count duplicates per label, no deletions.
    uv run python scripts/dedupe_neo4j_nodes.py --dry-run

    # Dedupe every label in NODE_LABELS_UNIQUE_KEY.
    uv run python scripts/dedupe_neo4j_nodes.py

    # Dedupe a single label.
    uv run python scripts/dedupe_neo4j_nodes.py --label Class

    # Tune the per-transaction batch size (default 1000).
    uv run python scripts/dedupe_neo4j_nodes.py --batch-size 500

The script walks every label in
:data:`app.services.neo4j.NODE_LABELS_UNIQUE_KEY`, groups nodes by ``fqn``,
keeps ``nodes[0]`` from each duplicate bucket and ``DETACH DELETE`` s the
rest. It is idempotent — a second run reports zero duplicates.

IMPORTANT: run this BEFORE the FastAPI app starts on any Neo4j instance that
was populated before ``07fda9c``. The lifespan's schema-constraint creation
will fail otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog
from neo4j import AsyncDriver

from app.config import Settings
from app.services.neo4j import (
    NODE_LABELS_UNIQUE_KEY,
    close_neo4j,
    get_driver,
    init_neo4j,
)

logger = structlog.get_logger(__name__)


async def count_null_app_name(
    driver: AsyncDriver, label: str, database: str = "neo4j"
) -> int:
    """Return the number of nodes for ``label`` whose ``app_name`` is NULL.

    Null-``app_name`` rows cannot be safely grouped across projects (they would
    collapse into a single cross-tenant bucket), so the dedupe queries skip
    them. This helper surfaces them separately for operator triage.
    """
    cypher = f"MATCH (n:`{label}`) WHERE n.app_name IS NULL RETURN count(n) AS c"
    async with driver.session(database=database) as session:
        result = await session.run(cypher)
        record = await result.single()
        if record is None or record["c"] is None:
            return 0
        return int(record["c"])


async def count_duplicates(
    driver: AsyncDriver, label: str, database: str = "neo4j"
) -> int:
    """Return the number of duplicate nodes for ``label``.

    Legacy pre-MERGE data only has ``fqn`` + ``app_name``; ``_id`` (the
    post-fix composite key) is NULL on those rows. We group on the tuple
    ``(fqn, app_name)`` so the script cleans up legacy duplicates without
    collapsing nodes across projects. Nodes with ``app_name IS NULL`` are
    excluded from the grouping — otherwise null-app_name rows from different
    projects would land in the same bucket and get cross-tenant merged.
    """
    cypher = (
        f"MATCH (n:`{label}`) "
        "WHERE n.app_name IS NOT NULL "
        "WITH n.fqn AS fqn, n.app_name AS app_name, collect(n) AS nodes "
        "WHERE fqn IS NOT NULL AND size(nodes) > 1 "
        "RETURN sum(size(nodes) - 1) AS dup_count"
    )
    async with driver.session(database=database) as session:
        result = await session.run(cypher)
        record = await result.single()
        if record is None or record["dup_count"] is None:
            return 0
        return int(record["dup_count"])


async def delete_duplicates(
    driver: AsyncDriver,
    label: str,
    batch_size: int,
    database: str = "neo4j",
) -> int:
    """DETACH DELETE duplicate nodes for ``label`` in batches.

    Keeps the first node in each ``collect()`` bucket and deletes the rest.
    Uses ``LIMIT`` inside the query to bound the transaction size and loops
    until no more duplicates remain (idempotent fixed-point). Nodes with
    ``app_name IS NULL`` are skipped to avoid cross-tenant merges — those are
    surfaced separately via :func:`count_null_app_name`.
    """
    cypher = (
        f"MATCH (n:`{label}`) "
        "WHERE n.app_name IS NOT NULL "
        "WITH n.fqn AS fqn, n.app_name AS app_name, collect(n) AS nodes "
        "WHERE fqn IS NOT NULL AND size(nodes) > 1 "
        "UNWIND nodes[1..] AS dup "
        "WITH dup LIMIT $batch_size "
        "DETACH DELETE dup "
        "RETURN count(dup) AS deleted"
    )
    total_deleted = 0
    while True:
        async with driver.session(database=database) as session:
            result = await session.run(cypher, {"batch_size": batch_size})
            record = await result.single()
        deleted = int(record["deleted"]) if record and record["deleted"] else 0
        if deleted == 0:
            break
        total_deleted += deleted
        await logger.ainfo(
            "dedupe.batch_deleted",
            label=label,
            deleted=deleted,
            total=total_deleted,
        )
    return total_deleted


async def dedupe_label(
    driver: AsyncDriver,
    label: str,
    *,
    dry_run: bool,
    batch_size: int,
    database: str = "neo4j",
) -> tuple[int, int]:
    """Dedupe a single label. Returns ``(duplicates_found, deleted)``."""
    null_count = await count_null_app_name(driver, label, database=database)
    if null_count > 0:
        await logger.awarning(
            "dedupe.null_app_name_nodes_skipped",
            label=label,
            count=null_count,
        )

    dup_count = await count_duplicates(driver, label, database=database)
    if dup_count == 0:
        await logger.ainfo("dedupe.label_clean", label=label)
        return 0, 0

    if dry_run:
        await logger.ainfo("dedupe.dry_run", label=label, duplicates=dup_count)
        return dup_count, 0

    deleted = await delete_duplicates(
        driver, label, batch_size=batch_size, database=database
    )
    await logger.ainfo(
        "dedupe.label_done", label=label, duplicates=dup_count, deleted=deleted
    )
    return dup_count, deleted


async def run(
    *,
    dry_run: bool,
    label_filter: str | None,
    batch_size: int,
    database: str = "neo4j",
) -> dict[str, tuple[int, int]]:
    """Run the dedupe migration across every labelled node type.

    Returns a mapping of ``label -> (duplicates_found, deleted)``.
    """
    if label_filter is not None and label_filter not in NODE_LABELS_UNIQUE_KEY:
        raise ValueError(
            f"Unknown label {label_filter!r}; must be one of "
            f"{sorted(NODE_LABELS_UNIQUE_KEY)}"
        )

    settings = Settings()
    await init_neo4j(settings)
    try:
        driver = get_driver()
        results: dict[str, tuple[int, int]] = {}
        for label in NODE_LABELS_UNIQUE_KEY:
            if label_filter is not None and label != label_filter:
                continue
            results[label] = await dedupe_label(
                driver,
                label,
                dry_run=dry_run,
                batch_size=batch_size,
                database=database,
            )

        total_dups = sum(dups for dups, _ in results.values())
        total_deleted = sum(deleted for _, deleted in results.values())
        await logger.ainfo(
            "dedupe.complete",
            dry_run=dry_run,
            labels=len(results),
            total_duplicates=total_dups,
            total_deleted=total_deleted,
        )
        return results
    finally:
        await close_neo4j()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot dedupe of Neo4j nodes created before the MERGE-based "
            "writer was introduced (CHAN-68). Safe to re-run."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count duplicates per label; do not delete anything.",
    )
    parser.add_argument(
        "--label",
        default=None,
        help=(
            "Optional single-label filter (e.g. Class). Default: every "
            "label in NODE_LABELS_UNIQUE_KEY."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Max duplicates to DETACH DELETE per transaction (default 1000).",
    )
    parser.add_argument(
        "--database",
        default="neo4j",
        help="Neo4j database name (default 'neo4j').",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.batch_size <= 0:
        print("--batch-size must be positive", file=sys.stderr)
        return 2
    asyncio.run(
        run(
            dry_run=args.dry_run,
            label_filter=args.label,
            batch_size=args.batch_size,
            database=args.database,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
