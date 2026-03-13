"""Aggregate per-node impact across all changed nodes in a PR."""
from __future__ import annotations

from collections import Counter

import structlog

from app.pr_analysis.models import (
    AffectedNode,
    AggregatedImpact,
    ChangedNode,
    CrossTechImpact,
)
from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)

_MAX_DEPTH = 5


class ImpactAggregator:
    def __init__(self, store: GraphStore, app_name: str) -> None:
        self._store = store
        self._app_name = app_name

    async def compute_aggregated_impact(self, changed_nodes: list[ChangedNode]) -> AggregatedImpact:
        if not changed_nodes:
            return AggregatedImpact(
                changed_nodes=[], downstream_affected=[], upstream_dependents=[],
                total_blast_radius=0, by_type={}, by_depth={}, by_layer={}, by_module={},
                cross_tech_impacts=[], transactions_affected=[])

        all_downstream: dict[str, AffectedNode] = {}
        all_upstream: dict[str, AffectedNode] = {}
        all_cross_tech: list[CrossTechImpact] = []
        all_transactions: set[str] = set()
        changed_fqns = {n.fqn for n in changed_nodes}

        for node in changed_nodes:
            await self._enrich_node(node)

            downstream = await self._query_downstream(node.fqn)
            for d in downstream:
                if d.fqn not in changed_fqns:
                    if d.fqn not in all_downstream or d.depth < all_downstream[d.fqn].depth:
                        all_downstream[d.fqn] = d

            upstream = await self._query_upstream(node.fqn)
            for u in upstream:
                if u.fqn not in changed_fqns:
                    if u.fqn not in all_upstream or u.depth < all_upstream[u.fqn].depth:
                        all_upstream[u.fqn] = u

            cross_tech = await self._query_cross_tech(node.fqn)
            all_cross_tech.extend(cross_tech)

            txns = await self._query_transactions(node.fqn)
            all_transactions.update(txns)

        # Dedup cross-tech
        seen_ct: set[tuple[str, str]] = set()
        deduped_ct: list[CrossTechImpact] = []
        for ct in all_cross_tech:
            key = (ct.kind, ct.name)
            if key not in seen_ct:
                seen_ct.add(key)
                deduped_ct.append(ct)

        # Aggregate stats
        all_unique: dict[str, AffectedNode] = {}
        for fqn, n in all_downstream.items():
            all_unique[fqn] = n
        for fqn, n in all_upstream.items():
            if fqn not in all_unique:
                all_unique[fqn] = n

        by_type = dict(Counter(a.type for a in all_unique.values()))
        by_depth = dict(Counter(a.depth for a in all_unique.values()))

        return AggregatedImpact(
            changed_nodes=changed_nodes,
            downstream_affected=sorted(all_downstream.values(), key=lambda a: (a.depth, a.name)),
            upstream_dependents=sorted(all_upstream.values(), key=lambda a: (a.depth, a.name)),
            total_blast_radius=len(all_unique),
            by_type=by_type, by_depth=by_depth, by_layer={}, by_module={},
            cross_tech_impacts=deduped_ct,
            transactions_affected=sorted(all_transactions))

    async def _enrich_node(self, node: ChangedNode) -> None:
        records = await self._store.query(
            "MATCH (n {fqn: $fqn, app_name: $appName}) "
            "OPTIONAL MATCH (caller)-[:CALLS]->(n) "
            "WITH n, count(DISTINCT caller) AS fan_in "
            "RETURN n.fqn AS fqn, fan_in, COALESCE(n.pagerank, 0.0) AS pagerank",
            {"fqn": node.fqn, "appName": self._app_name})
        if records:
            node.fan_in = records[0].get("fan_in", 0)
            node.is_hub = records[0].get("pagerank", 0) > 0.05

    async def _query_downstream(self, fqn: str) -> list[AffectedNode]:
        records = await self._store.query(
            f"MATCH path = (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CALLS|INJECTS|IMPLEMENTS|PRODUCES|WRITES|READS|CONTAINS|DEPENDS_ON*1..{_MAX_DEPTH}]->(affected) "
            "WHERE affected.app_name = $appName AND affected.fqn <> $fqn "
            "WITH affected, min(length(path)) AS depth "
            "RETURN affected.fqn AS fqn, affected.name AS name, "
            "  labels(affected)[0] AS type, affected.path AS file, depth "
            "ORDER BY depth, name",
            {"fqn": fqn, "appName": self._app_name})
        return [AffectedNode(**r) for r in records]

    async def _query_upstream(self, fqn: str) -> list[AffectedNode]:
        records = await self._store.query(
            "MATCH (start {fqn: $fqn, app_name: $appName})-[:CONTAINS*0..10]->(seed) "
            "WITH collect(DISTINCT seed.fqn) AS seed_fqns "
            f"MATCH (dep {{app_name: $appName}})"
            f"-[:CALLS|IMPLEMENTS|DEPENDS_ON|INHERITS|INJECTS|CONSUMES|READS|INCLUDES*1..{_MAX_DEPTH}]->(target) "
            "WHERE target.fqn IN seed_fqns AND dep.fqn <> $fqn "
            "AND NOT dep.fqn STARTS WITH $fqnPrefix "
            "WITH DISTINCT dep, 1 AS depth "
            "RETURN dep.fqn AS fqn, dep.name AS name, "
            "  labels(dep)[0] AS type, dep.path AS file, depth "
            "ORDER BY name",
            {"fqn": fqn, "appName": self._app_name, "fqnPrefix": fqn + "."})
        return [AffectedNode(**r) for r in records]

    async def _query_cross_tech(self, fqn: str) -> list[CrossTechImpact]:
        impacts: list[CrossTechImpact] = []

        # API endpoints
        eps = await self._store.query(
            f"MATCH (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CALLS|INJECTS*0..{_MAX_DEPTH}]->(fn:Function)-[:HANDLES]->(ep:APIEndpoint) "
            "RETURN ep.method AS method, ep.path AS path, fn.fqn AS handler_fqn",
            {"fqn": fqn, "appName": self._app_name})
        for ep in eps:
            impacts.append(CrossTechImpact(kind="api_endpoint", name=f"{ep['method']} {ep['path']}", detail=f"via {ep['handler_fqn']}"))

        # Message topics
        mts = await self._store.query(
            f"MATCH path = (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CALLS*0..{_MAX_DEPTH}]->(fn:Function)-[:PRODUCES|CONSUMES]->(mt:MessageTopic) "
            "RETURN mt.name AS topic, type(last(relationships(path))) AS direction",
            {"fqn": fqn, "appName": self._app_name})
        for mt in mts:
            impacts.append(CrossTechImpact(kind="message_topic", name=mt["topic"], detail=mt["direction"]))

        # Database tables
        tables = await self._store.query(
            f"MATCH path = (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CALLS*0..{_MAX_DEPTH}]->(fn:Function)-[:READS|WRITES]->(t:Table) "
            "RETURN t.name AS table_name, type(last(relationships(path))) AS access_type",
            {"fqn": fqn, "appName": self._app_name})
        for t in tables:
            impacts.append(CrossTechImpact(kind="database_table", name=t["table_name"], detail=t["access_type"]))

        return impacts

    async def _query_transactions(self, fqn: str) -> list[str]:
        records = await self._store.query(
            "MATCH (t:Transaction {app_name: $appName})-[:INCLUDES]->(fn {fqn: $fqn}) "
            "RETURN DISTINCT t.name AS transaction_name",
            {"fqn": fqn, "appName": self._app_name})
        return [r["transaction_name"] for r in records]
