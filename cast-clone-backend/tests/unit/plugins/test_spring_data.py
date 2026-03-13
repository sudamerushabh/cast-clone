"""Tests for Spring Data plugin — JPA stub FUNCTION nodes for inherited CRUD methods."""

import pytest
from pathlib import Path

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.spring.data import SpringDataPlugin


def _make_context_with_repo() -> AnalysisContext:
    """Build a minimal AnalysisContext with a JPA repository interface."""
    graph = SymbolGraph()

    entity = GraphNode(
        fqn="com.example.model.Account",
        name="Account",
        kind=NodeKind.CLASS,
        language="java",
        properties={"annotations": ["Entity"]},
    )
    graph.add_node(entity)

    table = GraphNode(
        fqn="table:accounts",
        name="accounts",
        kind=NodeKind.TABLE,
        properties={},
    )
    graph.add_node(table)

    graph.add_edge(GraphEdge(
        source_fqn="com.example.model.Account",
        target_fqn="table:accounts",
        kind=EdgeKind.MAPS_TO,
        evidence="hibernate",
    ))

    repo = GraphNode(
        fqn="com.example.repository.AccountRepository",
        name="AccountRepository",
        kind=NodeKind.INTERFACE,
        language="java",
        properties={
            "is_interface": True,
            "implements": ["JpaRepository"],
            "type_args": ["Account", "Long"],
        },
    )
    graph.add_node(repo)

    ctx = AnalysisContext(project_id="test")
    ctx.graph = graph
    return ctx


@pytest.mark.asyncio
async def test_stub_jpa_methods_created():
    plugin = SpringDataPlugin()
    ctx = _make_context_with_repo()

    result = await plugin.extract(ctx)

    stub_fqns = {n.fqn for n in result.nodes}
    assert "com.example.repository.AccountRepository.save" in stub_fqns
    assert "com.example.repository.AccountRepository.findById" in stub_fqns
    assert "com.example.repository.AccountRepository.deleteById" in stub_fqns
    assert "com.example.repository.AccountRepository.count" in stub_fqns


@pytest.mark.asyncio
async def test_stub_nodes_are_functions():
    plugin = SpringDataPlugin()
    ctx = _make_context_with_repo()
    result = await plugin.extract(ctx)

    save_node = next(
        (n for n in result.nodes if n.fqn.endswith(".save")), None
    )
    assert save_node is not None
    assert save_node.kind == NodeKind.FUNCTION
    assert save_node.properties.get("is_jpa_stub") is True


@pytest.mark.asyncio
async def test_stub_methods_have_reads_writes_edges():
    plugin = SpringDataPlugin()
    ctx = _make_context_with_repo()
    result = await plugin.extract(ctx)

    edge_map = {(e.source_fqn, e.kind): e for e in result.edges}

    save_fqn = "com.example.repository.AccountRepository.save"
    find_fqn = "com.example.repository.AccountRepository.findById"

    assert (save_fqn, EdgeKind.WRITES) in edge_map
    assert (find_fqn, EdgeKind.READS) in edge_map
    assert edge_map[(save_fqn, EdgeKind.WRITES)].target_fqn == "table:accounts"
    assert edge_map[(find_fqn, EdgeKind.READS)].target_fqn == "table:accounts"


@pytest.mark.asyncio
async def test_no_duplicate_stubs_if_already_in_graph():
    plugin = SpringDataPlugin()
    ctx = _make_context_with_repo()

    existing_save = GraphNode(
        fqn="com.example.repository.AccountRepository.save",
        name="save",
        kind=NodeKind.FUNCTION,
        language="java",
        properties={},
    )
    ctx.graph.add_node(existing_save)

    result = await plugin.extract(ctx)

    save_nodes = [n for n in result.nodes if n.fqn.endswith(".save")]
    assert len(save_nodes) == 0  # Not added again since already in graph


@pytest.mark.asyncio
async def test_detect_fallback_finds_repo_in_graph():
    """detect() should return MEDIUM confidence when no manifest but repo interfaces exist."""
    plugin = SpringDataPlugin()
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])

    repo = GraphNode(
        fqn="com.example.repository.AccountRepository",
        name="AccountRepository",
        kind=NodeKind.INTERFACE,
        language="java",
        properties={
            "is_interface": True,
            "implements": ["JpaRepository"],
            "type_args": ["Account", "Long"],
        },
    )
    ctx.graph.add_node(repo)

    result = plugin.detect(ctx)
    assert result.confidence == Confidence.MEDIUM


@pytest.mark.asyncio
async def test_stubs_created_even_without_table_mapping():
    """Stub FUNCTION nodes should be created even if no table mapping exists."""
    plugin = SpringDataPlugin()
    graph = SymbolGraph()

    entity = GraphNode(
        fqn="com.example.model.Account",
        name="Account",
        kind=NodeKind.CLASS,
        language="java",
        properties={"annotations": ["Entity"]},
    )
    graph.add_node(entity)

    # No table node or MAPS_TO edge

    repo = GraphNode(
        fqn="com.example.repository.AccountRepository",
        name="AccountRepository",
        kind=NodeKind.INTERFACE,
        language="java",
        properties={
            "is_interface": True,
            "implements": ["JpaRepository"],
            "type_args": ["Account", "Long"],
        },
    )
    graph.add_node(repo)

    ctx = AnalysisContext(project_id="test")
    ctx.graph = graph

    result = await plugin.extract(ctx)

    stub_fqns = {n.fqn for n in result.nodes}
    assert "com.example.repository.AccountRepository.save" in stub_fqns
    assert "com.example.repository.AccountRepository.findById" in stub_fqns
    # But no READS/WRITES edges since no table
    rw_edges = [e for e in result.edges if e.kind in (EdgeKind.READS, EdgeKind.WRITES)]
    assert len(rw_edges) == 0


@pytest.mark.asyncio
async def test_all_ten_jpa_methods_stubbed():
    """All 10 standard JPA methods should get stub nodes."""
    plugin = SpringDataPlugin()
    ctx = _make_context_with_repo()
    result = await plugin.extract(ctx)

    stub_names = {n.name for n in result.nodes}
    expected = {
        "save", "saveAll", "findById", "findAll", "findAllById",
        "deleteById", "delete", "deleteAll", "count", "existsById",
    }
    assert expected == stub_names


@pytest.mark.asyncio
async def test_contains_edges_for_stubs():
    """Each stub should have a CONTAINS edge from the repository."""
    plugin = SpringDataPlugin()
    ctx = _make_context_with_repo()
    result = await plugin.extract(ctx)

    contains_edges = [
        e for e in result.edges
        if e.kind == EdgeKind.CONTAINS
        and e.source_fqn == "com.example.repository.AccountRepository"
    ]
    assert len(contains_edges) == 10
