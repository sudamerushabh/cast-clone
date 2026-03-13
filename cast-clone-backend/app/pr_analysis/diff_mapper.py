"""Diff-to-Graph Mapper — maps PR file diffs to architecture graph nodes."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from app.pr_analysis.models import ChangedNode, FileDiff, PRDiff
from app.services.neo4j import GraphStore

logger = structlog.get_logger(__name__)


@dataclass
class DiffMapResult:
    """Result of mapping a PR diff to graph nodes."""

    changed_nodes: list[ChangedNode] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    non_graph_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)


class DiffMapper:
    """Maps PR file diffs to architecture graph nodes via Neo4j queries."""

    def __init__(self, store: GraphStore, app_name: str) -> None:
        self._store = store
        self._app_name = app_name

    async def map_diff_to_nodes(self, diff: PRDiff) -> DiffMapResult:
        """Walk every file in the diff and resolve it to graph nodes."""
        result = DiffMapResult()
        for file_diff in diff.files:
            if file_diff.status == "added":
                result.new_files.append(file_diff.path)
                continue
            if file_diff.status == "deleted":
                nodes = await self._query_all_nodes_in_file(file_diff.path)
                if nodes:
                    for n in nodes:
                        n.change_type = "deleted"
                    result.changed_nodes.extend(nodes)
                result.deleted_files.append(file_diff.path)
                continue
            # renamed -> query old_path; modified -> query path
            query_path = (
                file_diff.old_path
                if file_diff.status == "renamed"
                else file_diff.path
            )
            if file_diff.hunks:
                nodes = await self._query_nodes_by_hunks(query_path, file_diff)
            else:
                nodes = await self._query_all_nodes_in_file(query_path)
            if nodes:
                for n in nodes:
                    n.change_type = file_diff.status
                result.changed_nodes.extend(nodes)
            else:
                result.non_graph_files.append(file_diff.path)
        return result

    async def _query_nodes_by_hunks(
        self, path: str, file_diff: FileDiff
    ) -> list[ChangedNode]:
        """Find graph nodes whose line ranges overlap the changed hunks."""
        hunk_params = [
            {"new_start": h.new_start, "new_end": h.new_end}
            for h in file_diff.hunks
        ]
        cypher = (
            "UNWIND $hunks AS hunk "
            "MATCH (n) "
            "WHERE n.app_name = $appName "
            "  AND n.path = $path "
            "  AND n.line IS NOT NULL "
            "  AND n.end_line IS NOT NULL "
            "  AND n.line <= hunk.new_end "
            "  AND n.end_line >= hunk.new_start "
            "  AND labels(n)[0] IN "
            "['Class', 'Function', 'Interface', 'Field', 'APIEndpoint'] "
            "RETURN DISTINCT n.fqn AS fqn, n.name AS name, "
            "  labels(n)[0] AS type, n.path AS path, "
            "  n.line AS line, n.end_line AS end_line, "
            "  n.language AS language"
        )
        records = await self._store.query(
            cypher,
            {"appName": self._app_name, "path": path, "hunks": hunk_params},
        )
        return [
            ChangedNode(
                fqn=r["fqn"],
                name=r["name"],
                type=r["type"],
                path=r["path"],
                line=r["line"],
                end_line=r["end_line"],
                language=r.get("language", ""),
                change_type=file_diff.status,
            )
            for r in records
        ]

    async def _query_all_nodes_in_file(
        self, path: str
    ) -> list[ChangedNode]:
        """Return every graph node defined in the given file."""
        cypher = (
            "MATCH (n) "
            "WHERE n.app_name = $appName AND n.path = $path "
            "  AND labels(n)[0] IN "
            "['Class', 'Function', 'Interface', 'Field', 'APIEndpoint'] "
            "RETURN n.fqn AS fqn, n.name AS name, labels(n)[0] AS type, "
            "  n.path AS path, n.line AS line, n.end_line AS end_line, "
            "  n.language AS language"
        )
        records = await self._store.query(
            cypher, {"appName": self._app_name, "path": path}
        )
        return [
            ChangedNode(
                fqn=r["fqn"],
                name=r["name"],
                type=r["type"],
                path=r["path"],
                line=r.get("line", 0),
                end_line=r.get("end_line", 0),
                language=r.get("language", ""),
                change_type="",
            )
            for r in records
        ]
