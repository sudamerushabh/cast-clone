"""Merge SCIP index data into the SymbolGraph built by tree-sitter.

The merge algorithm:
1. For each SCIP symbol definition: find matching GraphNode by file:line or FQN
2. Update the node's FQN if SCIP provides a more precise one
3. Add hover documentation from SCIP
4. For each SCIP reference occurrence:
   - Find the containing function (caller) by file:line
   - Find or resolve the target symbol (callee) by FQN
   - Upgrade existing CALLS edge confidence from LOW -> HIGH
5. For SCIP implementation relationships:
   - Add/update IMPLEMENTS edges with HIGH confidence
6. Return stats: resolved_count, new_nodes, upgraded_edges, new_implements_edges
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.scip.protobuf_parser import (
    SCIPIndex,
)

logger = structlog.get_logger(__name__)


# -- Result Type -------------------------------------------------------------


@dataclass
class MergeStats:
    """Statistics from merging SCIP data into the graph."""

    resolved_count: int = 0
    new_nodes: int = 0
    upgraded_edges: int = 0
    new_call_edges: int = 0
    new_implements_edges: int = 0


# -- Path & Index Helpers ---------------------------------------------------


def _normalize_path(path: str) -> str:
    """Normalize a filesystem path for stable cross-platform comparison.

    Uses :meth:`pathlib.Path.resolve` which handles:
    - symlink resolution (macOS ``/var`` -> ``/private/var``)
    - case-folding on case-insensitive filesystems (when strict)
    - forward/backward slash normalization on Windows
    - redundant separators and ``.``/``..`` segments

    ``resolve(strict=False)`` still raises ``OSError`` on some platforms
    for pathological inputs and can be slow for synthetic paths used in
    tests. When that happens (or the path does not exist on disk) we
    fall back to :func:`os.path.normpath` and a forward-slash form via
    :meth:`PurePath.as_posix` so that tests operating on purely
    hypothetical paths still produce a deterministic key.
    """
    try:
        return Path(path).resolve(strict=False).as_posix()
    except (OSError, RuntimeError, ValueError):
        # Fallback: normpath + posix form so synthetic/invalid paths
        # still hash consistently across platforms.
        return Path(os.path.normpath(path)).as_posix()


def _reindex_edge_for_fqn_change(
    graph: SymbolGraph,
    edge: GraphEdge,
    old_source: str | None,
    old_target: str | None,
) -> None:
    """Incrementally patch the reverse indexes for a single edge.

    Called after an edge's ``source_fqn`` or ``target_fqn`` has been
    mutated in place. Removes the edge from its old bucket(s) and
    appends it to the new one(s). This keeps FQN-upgrade cost at
    ``O(1)`` amortized per edge rather than ``O(E)`` per upgrade,
    which matters because SCIP may upgrade many FQNs in a single pass.

    If the indexes are already marked dirty we skip the patch; the
    next read will rebuild from scratch anyway.
    """
    if graph._index_dirty:
        return
    if old_source is not None and old_source != edge.source_fqn:
        bucket = graph._edges_from.get(old_source)
        if bucket is not None:
            try:
                bucket.remove(edge)
            except ValueError:
                pass
            if not bucket:
                graph._edges_from.pop(old_source, None)
        graph._edges_from.setdefault(edge.source_fqn, []).append(edge)
    if old_target is not None and old_target != edge.target_fqn:
        bucket = graph._edges_to.get(old_target)
        if bucket is not None:
            try:
                bucket.remove(edge)
            except ValueError:
                pass
            if not bucket:
                graph._edges_to.pop(old_target, None)
        graph._edges_to.setdefault(edge.target_fqn, []).append(edge)


def _upgrade_node_fqn(
    graph: SymbolGraph,
    node: GraphNode,
    new_fqn: str,
) -> None:
    """Upgrade a node's FQN and keep all graph indexes consistent.

    1. Move the node from ``graph.nodes[old_fqn]`` to
       ``graph.nodes[new_fqn]``.
    2. Walk every edge once, rewriting ``source_fqn``/``target_fqn``
       references to the old FQN and incrementally patching the
       reverse indexes so ``get_edges_from(new_fqn)`` /
       ``get_edges_to(new_fqn)`` are correct on the next read and
       ``get_edges_from(old_fqn)`` / ``get_edges_to(old_fqn)`` no
       longer return stale edges.

    Incremental patching is preferred over a full
    :meth:`SymbolGraph._rebuild_index` call because the merger may
    upgrade hundreds of FQNs in a single pass; a full rebuild each
    time would be quadratic in edge count.
    """
    old_fqn = node.fqn
    if old_fqn == new_fqn:
        return

    if old_fqn in graph.nodes:
        del graph.nodes[old_fqn]
    node.fqn = new_fqn
    graph.nodes[new_fqn] = node

    index_ready = not graph._index_dirty
    for edge in graph.edges:
        old_source = edge.source_fqn
        old_target = edge.target_fqn
        touched = False
        if old_source == old_fqn:
            edge.source_fqn = new_fqn
            touched = True
        if old_target == old_fqn:
            edge.target_fqn = new_fqn
            touched = True
        if touched and index_ready:
            _reindex_edge_for_fqn_change(graph, edge, old_source, old_target)


# -- SCIP Symbol -> FQN Conversion ------------------------------------------


def scip_symbol_to_fqn(scip_symbol: str) -> str:
    """Convert a SCIP symbol string to our internal FQN format.

    SCIP symbol format: ``<scheme> <manager> <package> <version> <descriptors>``

    For Java (semanticdb/maven), the descriptors already contain the full
    Java package path, so the SCIP "package" field (Maven artifact coords)
    must be ignored.  For other schemes (npm, pip) the package field
    contributes to the FQN.

    Examples::

        semanticdb maven maven/org.example/myapp 1.0 com/example/UserService#
          -> com.example.UserService

        semanticdb maven maven/org.example/myapp 1.0 com/example/UserService#createUser().
          -> com.example.UserService.createUser

        npm @sourcegraph/scip-typescript 0.2.0 src/index.ts/App#
          -> sourcegraph.scip-typescript.src.index.ts.App

        local 42
          -> (empty)

    Conversion rules:
    - ``/`` -> ``.``
    - Class suffix ``#`` -> removed
    - Method suffix ``().`` -> removed
    - Field suffix ``.`` (trailing) -> removed
    - Back-ticked names like ```<init>``` -> stripped of back-ticks

    Args:
        scip_symbol: Raw SCIP symbol string.

    Returns:
        Converted FQN string, or empty string for local/invalid symbols.
    """
    if not scip_symbol:
        return ""

    # Local symbols have no stable FQN
    if scip_symbol.startswith("local "):
        return ""

    # SCIP symbol format: <scheme> <manager> <package> <version> <descriptors>
    parts = scip_symbol.split(" ")
    if len(parts) < 4:
        return ""

    # Standard form (5+ parts): scheme manager package version descriptor...
    if len(parts) >= 5:
        scheme = parts[0]
        manager = parts[1]
        package = parts[2]
        descriptors = " ".join(parts[4:])
    else:
        scheme = parts[0]
        manager = ""
        package = parts[1]
        descriptors = parts[3] if len(parts) > 3 else ""

    # For Java/Scala (semanticdb maven), the descriptors already contain the
    # full package path (e.g. org/springframework/.../ClassName#).  The SCIP
    # "package" field holds Maven coordinates (maven/groupId/artifactId) which
    # should NOT be included in the FQN.
    is_java_maven = (
        manager == "maven"
        or scheme == "semanticdb"
        or package.startswith("maven/")
    )

    if is_java_maven:
        # Use only the descriptors for the FQN
        fqn_base = ""
    else:
        # For npm/pip/etc., the package contributes to the FQN
        fqn_base = package.lstrip("@").replace("/", ".")

    if descriptors:
        desc = descriptors
        # Remove back-ticks around special names like `<init>`
        desc = desc.replace("`", "")
        # Remove trailing method marker: ().
        desc = re.sub(r"\(\)\.$", "", desc)
        # Remove trailing class marker: #
        desc = desc.rstrip("#")
        # Remove trailing field marker (single .)
        desc = desc.rstrip(".")
        # Convert remaining # to . (nested class/member separator)
        desc = desc.replace("#", ".")
        # Convert / to . (path separators)
        desc = desc.replace("/", ".")

        if desc:
            fqn_base = f"{fqn_base}.{desc}" if fqn_base else desc

    # Clean up any double dots
    fqn_base = re.sub(r"\.{2,}", ".", fqn_base)
    # Remove leading/trailing dots
    fqn_base = fqn_base.strip(".")

    return fqn_base


# -- Node Matching -----------------------------------------------------------


def match_scip_symbol_to_node(
    graph: SymbolGraph,
    fqn: str,
    file_path: str,
    line: int,
) -> GraphNode | None:
    """Find the GraphNode matching a SCIP symbol.

    Strategy:
    1. Direct FQN lookup (fast path)
    2. File:line scan (fallback for short/mismatched FQNs)

    Args:
        graph: The current symbol graph.
        fqn: SCIP-derived FQN for the symbol.
        file_path: Relative path from the SCIP document.
        line: Line number of the occurrence (0-indexed in SCIP).

    Returns:
        Matching GraphNode or None.
    """
    # Strategy 1: direct FQN lookup
    node = graph.get_node(fqn)
    if node is not None:
        return node

    # Strategy 2: file:line scan (use pathlib.Path.resolve() for a
    # cross-platform-stable key — handles symlinks, case differences,
    # and ``./`` vs absolute forms; falls back to normpath for
    # synthetic paths that don't exist on disk).
    scip_key = _normalize_path(file_path)
    for candidate in graph.nodes.values():
        if candidate.path and candidate.line is not None:
            if (
                _normalize_path(candidate.path) == scip_key
                and candidate.line == line
            ):
                return candidate

    return None


# -- Edge Upgrade ------------------------------------------------------------


def _find_containing_function(
    graph: SymbolGraph,
    file_path: str,
    line: int,
) -> GraphNode | None:
    """Find the function/method that contains a given line in a file.

    Used to determine the caller for a SCIP reference occurrence.
    """
    best: GraphNode | None = None
    best_distance = float("inf")
    scip_key = _normalize_path(file_path)

    for node in graph.nodes.values():
        if node.kind not in (NodeKind.FUNCTION,):
            continue
        if node.path is None or node.line is None:
            continue

        if _normalize_path(node.path) != scip_key:
            continue

        end_line = node.end_line or (node.line + 100)
        if node.line <= line <= end_line:
            distance = line - node.line
            if distance < best_distance:
                best = node
                best_distance = distance

    return best


def _upgrade_edge(
    graph: SymbolGraph,
    caller_fqn: str,
    callee_fqn: str,
) -> bool:
    """Upgrade confidence of a CALLS edge from caller to callee.

    Returns True if an edge was upgraded.
    """
    for edge in graph.get_edges_from(caller_fqn):
        if edge.kind == EdgeKind.CALLS and edge.target_fqn == callee_fqn:
            edge.confidence = Confidence.HIGH
            edge.evidence = "scip"
            return True
    return False


# -- Main Merge Function -----------------------------------------------------


def merge_scip_into_context(
    context: AnalysisContext,
    scip_index: SCIPIndex,
    language: str,
) -> MergeStats:
    """Merge SCIP index data into the context's SymbolGraph.

    This is the core merge algorithm:
    1. Process definitions: match to nodes, upgrade FQNs, add docs
    2. Process references: upgrade call edge confidence
    3. Process relationships: add IMPLEMENTS edges

    Args:
        context: Pipeline analysis context (graph is modified in place).
        scip_index: Parsed SCIP index from protobuf_parser.
        language: Language identifier for logging.

    Returns:
        MergeStats with counts of changes made.
    """
    stats = MergeStats()
    graph = context.graph

    # Build a symbol -> documentation lookup from SymbolInformation
    symbol_docs: dict[str, list[str]] = {}
    symbol_rels: dict[str, list] = {}
    for doc in scip_index.documents:
        for sym_info in doc.symbols:
            if sym_info.documentation:
                symbol_docs[sym_info.symbol] = sym_info.documentation
            if sym_info.relationships:
                symbol_rels[sym_info.symbol] = sym_info.relationships

    # Build a FQN -> SCIP symbol mapping for reference resolution
    scip_fqn_map: dict[str, str] = {}  # scip_symbol -> our_fqn

    # -- Pass 1: Process definitions -----------------------------------------
    for doc in scip_index.documents:
        for occ in doc.occurrences:
            if not occ.is_definition:
                continue

            scip_fqn = scip_symbol_to_fqn(occ.symbol)
            if not scip_fqn:
                continue  # skip local symbols

            scip_fqn_map[occ.symbol] = scip_fqn

            matched_node = match_scip_symbol_to_node(
                graph, scip_fqn, doc.relative_path, occ.start_line
            )

            if matched_node is None:
                continue

            stats.resolved_count += 1

            # Upgrade FQN if SCIP has a more precise one. ``_upgrade_node_fqn``
            # rewrites the node dict, updates every edge's source/target FQN,
            # and *incrementally patches* the ``_edges_from``/``_edges_to``
            # reverse indexes before returning — so subsequent reads under
            # the new FQN are consistent and reads under the old FQN no
            # longer return stale edges.
            if matched_node.fqn != scip_fqn and len(scip_fqn) > len(
                matched_node.fqn
            ):
                _upgrade_node_fqn(graph, matched_node, scip_fqn)

            # Add documentation
            if occ.symbol in symbol_docs:
                matched_node.properties["documentation"] = "\n".join(
                    symbol_docs[occ.symbol]
                )

    # -- Pass 2: Process references (upgrade call edges or create new ones) --
    for doc in scip_index.documents:
        for occ in doc.occurrences:
            if occ.is_definition:
                continue

            callee_fqn = scip_fqn_map.get(occ.symbol)
            if not callee_fqn:
                callee_fqn = scip_symbol_to_fqn(occ.symbol)
            if not callee_fqn:
                continue

            # Find the containing function (caller)
            caller_node = _find_containing_function(
                graph, doc.relative_path, occ.start_line
            )
            if caller_node is None:
                continue

            # Try to upgrade an existing edge
            if _upgrade_edge(graph, caller_node.fqn, callee_fqn):
                stats.upgraded_edges += 1
            else:
                # SCIP found a cross-file reference that tree-sitter missed.
                # Create a new HIGH-confidence CALLS edge if the callee exists
                # in the graph (i.e., it's not an external library symbol).
                callee_node = graph.get_node(callee_fqn)
                if callee_node is not None and callee_node.kind == NodeKind.FUNCTION:
                    graph.add_edge(
                        GraphEdge(
                            source_fqn=caller_node.fqn,
                            target_fqn=callee_fqn,
                            kind=EdgeKind.CALLS,
                            confidence=Confidence.HIGH,
                            evidence="scip",
                        )
                    )
                    stats.new_call_edges += 1

    # -- Pass 3: Process implementation relationships ------------------------
    for scip_symbol, relationships in symbol_rels.items():
        impl_fqn = scip_fqn_map.get(scip_symbol)
        if not impl_fqn:
            impl_fqn = scip_symbol_to_fqn(scip_symbol)
        if not impl_fqn:
            continue

        for rel in relationships:
            if not rel.is_implementation:
                continue

            iface_fqn = scip_symbol_to_fqn(rel.symbol)
            if not iface_fqn:
                continue

            # Check both nodes exist
            impl_node = graph.get_node(impl_fqn)
            iface_node = graph.get_node(iface_fqn)
            if impl_node is None or iface_node is None:
                continue

            # Check if edge already exists
            existing = False
            for edge in graph.get_edges_from(impl_fqn):
                if edge.kind == EdgeKind.IMPLEMENTS and edge.target_fqn == iface_fqn:
                    edge.confidence = Confidence.HIGH
                    edge.evidence = "scip"
                    existing = True
                    break

            if not existing:
                graph.add_edge(
                    GraphEdge(
                        source_fqn=impl_fqn,
                        target_fqn=iface_fqn,
                        kind=EdgeKind.IMPLEMENTS,
                        confidence=Confidence.HIGH,
                        evidence="scip",
                    )
                )
                stats.new_implements_edges += 1

    logger.info(
        "scip.merge.complete",
        language=language,
        resolved=stats.resolved_count,
        upgraded_edges=stats.upgraded_edges,
        new_call_edges=stats.new_call_edges,
        new_implements=stats.new_implements_edges,
        project_id=context.project_id,
    )

    return stats
