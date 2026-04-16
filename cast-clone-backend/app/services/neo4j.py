"""Neo4j async driver wrapper and GraphStore abstraction.

The GraphStore ABC allows swapping Neo4j for Memgraph/AGE in the future.
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from typing import Any

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import Settings
from app.models.graph import GraphEdge, GraphNode

logger = structlog.get_logger(__name__)

# Node labels (Neo4j) with their natural uniqueness key.
#
# Every node written by the pipeline populates ``fqn`` (see
# ``Neo4jGraphStore.write_nodes_batch``) and is scoped to an application via
# ``app_name``. We use a composite (label, fqn, app_name) identity by enforcing
# UNIQUE on ``fqn`` per label. Cross-project collisions are prevented at the
# query level by the ``app_name`` filter — Neo4j Community supports only single
# property UNIQUE constraints, so composite constraints are not used here.
NODE_LABELS_UNIQUE_KEY: dict[str, str] = {
    "Application": "fqn",
    "Module": "fqn",
    "Class": "fqn",
    "Interface": "fqn",
    "Function": "fqn",
    "Field": "fqn",
    "Table": "fqn",
    "Column": "fqn",
    "View": "fqn",
    "StoredProcedure": "fqn",
    "APIEndpoint": "fqn",
    "Route": "fqn",
    "MessageTopic": "fqn",
    "ConfigFile": "fqn",
    "ConfigEntry": "fqn",
    "Layer": "fqn",
    "Component": "fqn",
    "Community": "fqn",
    "Transaction": "fqn",
}


def build_constraint_statements() -> list[str]:
    """Return CREATE CONSTRAINT statements for every node label.

    Each statement uses ``IF NOT EXISTS`` so it is safe to re-run on an
    already-initialized database.
    """
    stmts: list[str] = []
    for label, key in NODE_LABELS_UNIQUE_KEY.items():
        name = f"{label.lower()}_{key}_unique"
        stmts.append(
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
        )
    return stmts


async def ensure_schema_constraints(
    driver: AsyncDriver, database: str = "neo4j"
) -> None:
    """Create UNIQUE constraints for every node label (idempotent).

    Called at FastAPI lifespan startup, after ``init_neo4j``. Ensures that
    MERGE-based writes in the batch writer are backed by an index and that
    duplicate nodes cannot be created by re-runs of the pipeline.
    """
    statements = build_constraint_statements()
    async with driver.session(database=database) as session:
        for stmt in statements:
            await session.run(stmt)
    await logger.ainfo("neo4j.schema_constraints_ensured", count=len(statements))


def _sanitize_props(props: dict[str, Any]) -> dict[str, Any]:
    """Replace NaN/Inf float values with None (Neo4j rejects them).

    Recurses into nested dicts and lists so properties built from enricher
    metrics (averages, ratios) cannot poison a batch write. All other values
    pass through unchanged.
    """

    def _sanitize(value: Any) -> Any:
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
            return value
        if isinstance(value, dict):
            return {k: _sanitize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_sanitize(v) for v in value]
        if isinstance(value, tuple):
            return tuple(_sanitize(v) for v in value)
        return value

    return {k: _sanitize(v) for k, v in props.items()}


_driver: AsyncDriver | None = None


async def init_neo4j(settings: Settings) -> None:
    global _driver
    _driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    await _driver.verify_connectivity()


async def close_neo4j() -> None:
    global _driver
    if _driver:
        await _driver.close()
    _driver = None


def get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j not initialized")
    return _driver


class GraphStore(ABC):
    """Abstract graph database interface."""

    @abstractmethod
    async def write_nodes_batch(self, nodes: list[GraphNode], app_name: str) -> int: ...

    @abstractmethod
    async def write_edges_batch(self, edges: list[GraphEdge], app_name: str) -> int: ...

    @abstractmethod
    async def ensure_indexes(self) -> None: ...

    @abstractmethod
    async def clear_project(self, project_id: str) -> None: ...

    @abstractmethod
    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def query_single(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None: ...


class Neo4jGraphStore(GraphStore):
    """Neo4j implementation of GraphStore."""

    def __init__(self, driver: AsyncDriver, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    async def ensure_indexes(self) -> None:
        """Create indexes and full-text search index."""
        index_statements = [
            "CREATE INDEX IF NOT EXISTS FOR (n:Class) ON (n.fqn)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Function) ON (n.fqn)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Interface) ON (n.fqn)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Module) ON (n.fqn)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Table) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:APIEndpoint) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Column) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Transaction) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Class) ON (n.language)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Function) ON (n.language)",
            # Phase 5a: path indexes for diff-to-graph mapping
            "CREATE INDEX IF NOT EXISTS FOR (n:Class) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Function) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Interface) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Field) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:APIEndpoint) ON (n.path)",
        ]
        async with self._driver.session(database=self._database) as session:
            for stmt in index_statements:
                await session.run(stmt)

    async def write_nodes_batch(self, nodes: list[GraphNode], app_name: str) -> int:
        """Write nodes in batches of 5000 using UNWIND + MERGE.

        Nodes are MERGEd on ``(label {fqn})`` to guarantee idempotency: re-running
        the pipeline for the same project does not duplicate nodes. All property
        dicts are sanitized for NaN/Inf before being sent to Neo4j.
        """
        batch_size = 5000
        total = 0
        # Group by label — one MERGE statement per label keeps Cypher simple and
        # lets Neo4j use the UNIQUE constraint index on each label.
        nodes_by_label: dict[str, list[GraphNode]] = {}
        for node in nodes:
            nodes_by_label.setdefault(node.label, []).append(node)

        for label, label_nodes in nodes_by_label.items():
            for i in range(0, len(label_nodes), batch_size):
                batch = label_nodes[i : i + batch_size]
                records = []
                for node in batch:
                    # Neo4j properties must be primitives or arrays of primitives.
                    # Serialize dicts and lists-of-dicts as JSON strings so data
                    # (e.g. parameters, annotation_args) is preserved.
                    serializable_props: dict[str, Any] = {}
                    for k, v in node.properties.items():
                        if isinstance(v, dict):
                            serializable_props[k] = json.dumps(v)
                        elif isinstance(v, list) and v and isinstance(v[0], dict):
                            serializable_props[k] = json.dumps(v)
                        else:
                            serializable_props[k] = v
                    props: dict[str, Any] = {
                        "fqn": node.fqn,
                        "name": node.name,
                        "kind": node.kind.value,
                        "app_name": app_name,
                        **serializable_props,
                    }
                    for key, val in [
                        ("language", node.language),
                        ("path", node.path),
                        ("line", node.line),
                        ("end_line", node.end_line),
                        ("loc", node.loc),
                        ("complexity", node.complexity),
                        ("visibility", node.visibility),
                    ]:
                        if val is not None:
                            props[key] = val
                    records.append({"fqn": node.fqn, "props": _sanitize_props(props)})
                # Label is validated against the internal mapping: it is not user
                # input, so interpolating into Cypher is safe.
                cypher = (
                    "UNWIND $batch AS n "
                    f"MERGE (x:`{label}` {{fqn: n.fqn}}) "
                    "SET x += n.props "
                    "RETURN count(x) AS cnt"
                )
                async with self._driver.session(database=self._database) as session:
                    result = await session.run(cypher, {"batch": records})
                    record = await result.single()
                    total += record["cnt"] if record else 0
        return total

    async def write_edges_batch(self, edges: list[GraphEdge], app_name: str) -> int:
        """Write edges in batches of 5000 using UNWIND.

        Source and target nodes must already exist (stub nodes are pre-created
        by _create_stub_hierarchy in writer.py). Edges whose source or target
        node is missing are silently skipped by the MATCH clauses.

        Both endpoints are scoped to ``app_name`` to prevent cross-project
        edge creation when multiple projects share the same FQNs.
        """
        batch_size = 5000
        total = 0
        for i in range(0, len(edges), batch_size):
            batch = edges[i : i + batch_size]
            records = []
            for edge in batch:
                props = {
                    "confidence": edge.confidence.name,
                    "evidence": edge.evidence,
                    **edge.properties,
                }
                records.append(
                    {
                        "from_fqn": edge.source_fqn,
                        "to_fqn": edge.target_fqn,
                        "type": edge.kind.value,
                        "properties": _sanitize_props(props),
                    }
                )
            # apoc.merge.relationship with empty identifier props merges on
            # (from, type, to) — idempotent for the (src, kind, dst) triple.
            cypher = """
            UNWIND $batch AS e
            MATCH (from {fqn: e.from_fqn, app_name: $app_name})
            MATCH (to {fqn: e.to_fqn, app_name: $app_name})
            CALL apoc.merge.relationship(from, e.type, {}, e.properties, to) YIELD rel
            RETURN count(rel) AS cnt
            """
            async with self._driver.session(database=self._database) as session:
                result = await session.run(
                    cypher, {"batch": records, "app_name": app_name}
                )
                record = await result.single()
                total += record["cnt"] if record else 0
        return total

    async def clear_project(self, project_id: str) -> None:
        cypher = """
        MATCH (n {app_name: $app_name})
        DETACH DELETE n
        """
        async with self._driver.session(database=self._database) as session:
            await session.run(cypher, {"app_name": project_id})

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, params or {})
            return [dict(record) async for record in result]

    async def query_single(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, params or {})
            record = await result.single()
            return dict(record) if record else None
