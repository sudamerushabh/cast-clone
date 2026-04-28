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

import re
from dataclasses import dataclass
from typing import Literal

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.scip.protobuf_parser import (
    SCIPIndex,
)

# Kind hint derived from a SCIP symbol's terminal descriptor.  Used by
# ``match_scip_symbol_to_node`` to gate the file:line fallback so a SCIP
# field/parameter definition cannot collide with a tree-sitter CLASS node
# at the same (or off-by-one) line.
SymbolKindHint = Literal[
    "class", "function", "field", "module", "parameter", "local"
]

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

        # Parameter descriptors look like ``method().(param_name)`` (and type
        # parameters like ``method().[T]``).  These are *local* to a function
        # body and have no stable FQN of their own — Pyright/scip-python emits
        # them so that ``match_scip_symbol_to_node`` would otherwise re-bind
        # them to whatever tree-sitter node lives at the same line, mangling
        # FQNs (e.g. ``update_todo().(todo_id)`` rewriting the function FQN).
        # Drop them outright; merge_scip_into_context skips empty FQNs.
        if re.search(r"\(\)\.\(.+\)$", desc) or re.search(r"\(\)\.\[.+\]$", desc):
            return ""

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


def scip_descriptor_kind(scip_symbol: str) -> SymbolKindHint | None:
    """Classify the terminal descriptor of a SCIP symbol.

    Returns a hint indicating what kind of graph node a SCIP symbol *should*
    bind to.  Used by ``match_scip_symbol_to_node`` to prevent file:line
    fallback from cross-binding a field/parameter SCIP symbol to a CLASS
    or FUNCTION tree-sitter node living at a nearby line (the off-by-one
    that arises because tree-sitter records 1-indexed lines while
    scip-python emits 0-indexed lines).

    Returns ``None`` for empty / malformed / external-package symbols
    (callers should treat as "no kind hint" and use the legacy match).
    """
    if not scip_symbol:
        return None
    if scip_symbol.startswith("local "):
        return "local"

    parts = scip_symbol.split(" ")
    if len(parts) < 4:
        return None
    descriptors = " ".join(parts[4:]) if len(parts) >= 5 else (
        parts[3] if len(parts) > 3 else ""
    )
    if not descriptors:
        return None

    # Parameter descriptor: ``foo().(param)`` or ``foo().[T]``.
    if re.search(r"\(\)\.\(.+\)$", descriptors) or re.search(
        r"\(\)\.\[.+\]$", descriptors
    ):
        return "parameter"
    if descriptors.endswith("().") or descriptors.endswith("()"):
        return "function"
    if descriptors.endswith("#"):
        return "class"
    if descriptors.endswith(":"):
        return "module"
    if descriptors.endswith("."):
        # Field/property — a non-callable member ending in a single dot,
        # e.g. ``Foo#bar.`` or ``module/CONST.``.
        return "field"
    return None


# Mapping from SCIP descriptor hint -> set of NodeKinds the file:line
# fallback is allowed to match.  Anything outside these sets is rejected
# even if the path and line agree, which is critical for Python where
# scip-python emits the field at the line *immediately after* the class
# keyword (its 0-indexed line equals tree-sitter's 1-indexed class line).
_HINT_TO_NODE_KINDS: dict[SymbolKindHint, frozenset[NodeKind]] = {
    "class": frozenset({NodeKind.CLASS, NodeKind.INTERFACE}),
    "function": frozenset({NodeKind.FUNCTION}),
    "field": frozenset({NodeKind.FIELD}),
    "module": frozenset({NodeKind.MODULE}),
    # parameter / local hints intentionally omitted — callers must skip.
}


# -- Node Matching -----------------------------------------------------------


def match_scip_symbol_to_node(
    graph: SymbolGraph,
    fqn: str,
    file_path: str,
    line: int,
    kind_hint: SymbolKindHint | None = None,
) -> GraphNode | None:
    """Find the GraphNode matching a SCIP symbol.

    Strategy:
    1. Direct FQN lookup (fast path)
    2. File:line scan (fallback for short/mismatched FQNs).  If
       ``kind_hint`` is provided, the fallback only matches nodes whose
       kind is compatible with the hint.  This prevents a SCIP field
       definition (whose 0-indexed line lands on the tree-sitter
       1-indexed class line) from re-binding the CLASS node.

    Args:
        graph: The current symbol graph.
        fqn: SCIP-derived FQN for the symbol.
        file_path: Relative path from the SCIP document.
        line: Line number of the occurrence (0-indexed in SCIP).
        kind_hint: Optional hint about the kind of node to match.

    Returns:
        Matching GraphNode or None.
    """
    # Strategy 1: direct FQN lookup
    node = graph.get_node(fqn)
    if node is not None:
        return node

    allowed_kinds = (
        _HINT_TO_NODE_KINDS.get(kind_hint) if kind_hint is not None else None
    )

    # Strategy 2: file:line scan.  Tree-sitter records 1-indexed lines while
    # scip-python emits 0-indexed lines (semanticdb/maven appears 1-indexed
    # in fixtures).  When a kind hint is supplied we also accept a
    # ``candidate.line == line + 1`` match to absorb the Python off-by-one;
    # the kind gate prevents the broader window from cross-binding to the
    # wrong tree-sitter node.  Without a hint we keep the legacy strict match.
    for candidate in graph.nodes.values():
        if candidate.path is None or candidate.line is None:
            continue
        # Normalize paths for comparison (remove leading ./ or src/ differences)
        cand_path = candidate.path.lstrip("./")
        scip_path = file_path.lstrip("./")
        if cand_path != scip_path:
            continue
        if allowed_kinds is None:
            line_match = candidate.line == line
        else:
            line_match = candidate.line == line or candidate.line == line + 1
        if not line_match:
            continue
        if allowed_kinds is not None and candidate.kind not in allowed_kinds:
            continue
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

    for node in graph.nodes.values():
        if node.kind not in (NodeKind.FUNCTION,):
            continue
        if node.path is None or node.line is None:
            continue

        cand_path = node.path.lstrip("./")
        scip_path = file_path.lstrip("./")
        if cand_path != scip_path:
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
                # Skip local symbols, parameters, and malformed entries.
                # Parameters in particular MUST be skipped: their containing
                # function lives at the same or adjacent line, and binding
                # them would rewrite the function FQN to e.g.
                # ``update_todo().(todo_id)``, breaking M3 plugins that key
                # off ``rsplit('.', 1)`` of the function FQN.
                continue

            scip_fqn_map[occ.symbol] = scip_fqn
            kind_hint = scip_descriptor_kind(occ.symbol)

            matched_node = match_scip_symbol_to_node(
                graph,
                scip_fqn,
                doc.relative_path,
                occ.start_line,
                kind_hint=kind_hint,
            )

            if matched_node is None:
                continue

            stats.resolved_count += 1

            # Defence-in-depth: even if the FQN-direct match returns a node
            # of the wrong kind (e.g. a stale rename collision), refuse to
            # rewrite it as a CLASS->field cross-bind.  This keeps INHERITS
            # edge sources rooted at the real CLASS node.
            if (
                kind_hint is not None
                and matched_node.fqn != scip_fqn
                and matched_node.kind not in _HINT_TO_NODE_KINDS.get(
                    kind_hint, frozenset()
                )
            ):
                continue

            # Upgrade FQN if SCIP has a more precise one
            if matched_node.fqn != scip_fqn and len(scip_fqn) > len(matched_node.fqn):
                old_fqn = matched_node.fqn
                # Remove old entry, update FQN, re-add
                del graph.nodes[old_fqn]
                matched_node.fqn = scip_fqn
                graph.add_node(matched_node)

                # Update edges that reference the old FQN
                for edge in graph.edges:
                    if edge.source_fqn == old_fqn:
                        edge.source_fqn = scip_fqn
                    if edge.target_fqn == old_fqn:
                        edge.target_fqn = scip_fqn
                graph._index_dirty = True

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
