"""Neo4j async driver wrapper and GraphStore abstraction.

The GraphStore ABC allows swapping Neo4j for Memgraph/AGE in the future.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import Settings
from app.models.graph import GraphEdge, GraphNode

logger = structlog.get_logger(__name__)

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
    assert _driver is not None, "Neo4j not initialized"
    return _driver


class GraphStore(ABC):
    """Abstract graph database interface."""

    @abstractmethod
    async def write_nodes_batch(
        self, nodes: list[GraphNode], app_name: str
    ) -> int: ...

    @abstractmethod
    async def write_edges_batch(
        self, edges: list[GraphEdge]
    ) -> int: ...

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
        ]
        async with self._driver.session(database=self._database) as session:
            for stmt in index_statements:
                await session.run(stmt)

    async def write_nodes_batch(
        self, nodes: list[GraphNode], app_name: str
    ) -> int:
        """Write nodes in batches of 5000 using UNWIND."""
        batch_size = 5000
        total = 0
        for i in range(0, len(nodes), batch_size):
            batch = nodes[i : i + batch_size]
            records = []
            for node in batch:
                props: dict[str, Any] = {
                    "fqn": node.fqn,
                    "name": node.name,
                    "kind": node.kind.value,
                    "app_name": app_name,
                    **node.properties,
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
                records.append({"label": node.label, "properties": props})
            cypher = """
            UNWIND $batch AS n
            CALL apoc.create.node([n.label], n.properties) YIELD node
            RETURN count(node) AS cnt
            """
            async with self._driver.session(database=self._database) as session:
                result = await session.run(cypher, {"batch": records})
                record = await result.single()
                total += record["cnt"] if record else 0
        return total

    async def write_edges_batch(self, edges: list[GraphEdge]) -> int:
        """Write edges in batches of 5000 using UNWIND."""
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
                records.append({
                    "from_fqn": edge.source_fqn,
                    "to_fqn": edge.target_fqn,
                    "type": edge.kind.value,
                    "properties": props,
                })
            cypher = """
            UNWIND $batch AS e
            MATCH (from {fqn: e.from_fqn})
            MATCH (to {fqn: e.to_fqn})
            CALL apoc.create.relationship(from, e.type, e.properties, to) YIELD rel
            RETURN count(rel) AS cnt
            """
            async with self._driver.session(database=self._database) as session:
                result = await session.run(cypher, {"batch": records})
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
