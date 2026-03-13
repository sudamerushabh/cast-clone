"""Architecture drift detection for PR analysis."""

from __future__ import annotations

import structlog

from app.pr_analysis.models import ChangedNode, DriftReport, ModuleDependency
from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)


class DriftDetector:
    """Detects architecture drift by comparing PR changes against the existing graph."""

    def __init__(self, store: GraphStore, app_name: str) -> None:
        self._store = store
        self._app_name = app_name

    async def detect_drift(
        self,
        changed_nodes: list[ChangedNode],
        new_files: list[str] | None = None,
    ) -> DriftReport:
        """Analyse changed nodes for module-level drift.

        Checks for:
        1. New cross-module dependencies not previously recorded.
        2. Circular dependencies involving changed modules.
        3. New files that fall outside any known module boundary.
        """
        new_module_deps: list[ModuleDependency] = []
        circular_deps: list[list[str]] = []
        new_files_outside = list(new_files) if new_files else []

        if not changed_nodes:
            return DriftReport(
                potential_new_module_deps=new_module_deps,
                circular_deps_affected=circular_deps,
                new_files_outside_modules=new_files_outside,
            )

        changed_fqns = [n.fqn for n in changed_nodes]

        # 1. Find modules of changed nodes
        module_records = await self._store.query(
            "UNWIND $changedFqns AS fqn "
            "MATCH (m:Module)-[:CONTAINS*1..3]->(n {fqn: fqn, app_name: $appName}) "
            "RETURN DISTINCT m.fqn AS module_fqn, m.name AS module_name, "
            "collect(fqn) AS changed_nodes_in_module",
            {"changedFqns": changed_fqns, "appName": self._app_name},
        )

        if not module_records:
            return DriftReport(
                potential_new_module_deps=new_module_deps,
                circular_deps_affected=circular_deps,
                new_files_outside_modules=new_files_outside,
            )

        changed_module_fqns = [r["module_fqn"] for r in module_records]

        # 2. New cross-module deps
        dep_records = await self._store.query(
            "UNWIND $changedFqns AS fqn "
            "MATCH (n {fqn: fqn, app_name: $appName}) "
            "MATCH (srcMod:Module)-[:CONTAINS*1..3]->(n) "
            "MATCH (n)-[:CALLS|DEPENDS_ON|INJECTS]->(target) "
            "MATCH (tgtMod:Module)-[:CONTAINS*1..3]->(target) "
            "WHERE srcMod.fqn <> tgtMod.fqn AND NOT (srcMod)-[:IMPORTS]->(tgtMod) "
            "RETURN DISTINCT srcMod.name AS from_module, tgtMod.name AS to_module",
            {"changedFqns": changed_fqns, "appName": self._app_name},
        )
        for r in dep_records:
            new_module_deps.append(
                ModuleDependency(from_module=r["from_module"], to_module=r["to_module"])
            )

        # 3. Circular deps
        cycle_records = await self._store.query(
            "UNWIND $moduleFqns AS mFqn "
            "MATCH (m {fqn: mFqn, app_name: $appName}) "
            "MATCH cyclePath = (m)-[:IMPORTS|DEPENDS_ON*2..6]->(m) "
            "RETURN DISTINCT [node IN nodes(cyclePath) | node.name] AS cycle",
            {"moduleFqns": changed_module_fqns, "appName": self._app_name},
        )
        for r in cycle_records:
            circular_deps.append(r["cycle"])

        return DriftReport(
            potential_new_module_deps=new_module_deps,
            circular_deps_affected=circular_deps,
            new_files_outside_modules=new_files_outside,
        )
