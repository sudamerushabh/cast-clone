"""Shared mutable state passed through all pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.graph import SymbolGraph
from app.models.manifest import ProjectManifest, ResolvedEnvironment


@dataclass
class EntryPoint:
    """A transaction starting point (e.g., an API endpoint handler)."""

    fqn: str
    kind: str  # "http", "message_consumer", "scheduled", "main"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class AnalysisContext:
    """Mutable state accumulated across all 10 pipeline stages.

    Each stage reads from previous stages' outputs and writes its own.
    This is the single object threaded through the entire pipeline.
    """

    project_id: str

    # Stage 1 output
    manifest: ProjectManifest | None = None

    # Stage 2 output
    environment: ResolvedEnvironment | None = None

    # Stages 3-7 accumulate into this graph
    graph: SymbolGraph = field(default_factory=SymbolGraph)

    # Stage 4 tracking
    scip_resolved_languages: set[str] = field(default_factory=set)
    languages_needing_fallback: list[str] = field(default_factory=list)

    # Stage 5 tracking
    plugin_new_nodes: int = 0
    plugin_new_edges: int = 0
    layer_assignments: dict[str, str] = field(default_factory=dict)  # fqn -> layer

    # Stage 5 DI map: shared between .NET plugins (interface_name -> impl_fqn)
    dotnet_di_map: dict[str, str] = field(default_factory=dict)

    # Stage 6 tracking
    cross_tech_edge_count: int = 0

    # Stage 10 tracking
    community_count: int = 0

    # Stage 9 tracking
    transaction_count: int = 0

    # Entry points collected by plugins for transaction discovery (Stage 9)
    entry_points: list[EntryPoint] = field(default_factory=list)

    # Warnings from non-fatal stage failures
    warnings: list[str] = field(default_factory=list)

    # Progress callback — set by pipeline to persist stage_progress to DB
    report_progress: Any = None  # async (int) -> None
