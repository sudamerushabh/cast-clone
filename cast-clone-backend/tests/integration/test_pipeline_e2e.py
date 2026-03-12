"""End-to-end pipeline test: run stages 1-3 against Spring PetClinic fixture.

Stages 4-9 require external tooling (SCIP, Neo4j) and are tested separately.
This test verifies the in-memory pipeline from discovery through tree-sitter parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.context import AnalysisContext
from app.models.enums import EdgeKind, NodeKind
from app.stages.treesitter.extractors import register_extractor
from app.stages.treesitter.extractors.java import JavaExtractor

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
PETCLINIC_DIR = FIXTURE_DIR / "spring-petclinic"


@pytest.fixture(autouse=True)
def _ensure_java_extractor():
    """Re-register Java extractor (may be cleared by other test modules)."""
    register_extractor("java", JavaExtractor())
    yield


@pytest.mark.integration
class TestPipelineStages1Through3:
    """Run stages 1-3 sequentially against PetClinic fixture."""

    @pytest.mark.asyncio
    async def test_discovery_finds_java_files(self):
        """Stage 1: Discovery should find all .java files."""
        from app.stages.discovery import discover_project

        manifest = discover_project(PETCLINIC_DIR)

        assert "java" in [lang.name for lang in manifest.detected_languages]
        assert manifest.total_files > 0
        # Should find at least Owner.java, OwnerController.java, etc.
        java_files = [f for f in manifest.source_files if f.path.endswith(".java")]
        assert len(java_files) >= 8

    @pytest.mark.asyncio
    async def test_discovery_detects_spring(self):
        """Stage 1: Discovery should detect Spring Boot framework."""
        from app.stages.discovery import discover_project

        manifest = discover_project(PETCLINIC_DIR)

        framework_names = [f.name for f in manifest.detected_frameworks]
        assert "spring-boot" in framework_names

    @pytest.mark.asyncio
    async def test_discovery_detects_maven(self):
        """Stage 1: Discovery should detect Maven build tool."""
        from app.stages.discovery import discover_project

        manifest = discover_project(PETCLINIC_DIR)

        build_tool_names = [bt.name for bt in manifest.build_tools]
        assert "maven" in build_tool_names

    @pytest.mark.asyncio
    async def test_treesitter_parses_java(self):
        """Stage 3: Tree-sitter should extract classes and methods from Java files."""
        from app.stages.discovery import discover_project
        from app.stages.treesitter.parser import parse_with_treesitter

        manifest = discover_project(PETCLINIC_DIR)
        graph = await parse_with_treesitter(manifest)

        # Should find Owner, OwnerController, Vet, VetController, Pet, PetType, etc.
        class_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.CLASS]
        assert len(class_nodes) >= 5

        # Should find methods
        function_nodes = [
            n for n in graph.nodes.values() if n.kind == NodeKind.FUNCTION
        ]
        assert len(function_nodes) >= 5

    @pytest.mark.asyncio
    async def test_treesitter_extracts_relationships(self):
        """Stage 3: Tree-sitter should extract CONTAINS edges."""
        from app.stages.discovery import discover_project
        from app.stages.treesitter.parser import parse_with_treesitter

        manifest = discover_project(PETCLINIC_DIR)
        graph = await parse_with_treesitter(manifest)

        # CONTAINS edges: class contains methods
        contains_edges = [e for e in graph.edges if e.kind == EdgeKind.CONTAINS]
        assert len(contains_edges) > 0

    @pytest.mark.asyncio
    async def test_stages_1_through_3_sequential(self):
        """Run stages 1-3 in sequence, verify cumulative result."""
        from app.stages.dependencies import resolve_dependencies
        from app.stages.discovery import discover_project
        from app.stages.treesitter.parser import parse_with_treesitter

        # Stage 1: Discovery
        manifest = discover_project(PETCLINIC_DIR)
        assert manifest is not None

        # Stage 2: Dependencies
        environment = await resolve_dependencies(manifest)
        assert environment is not None

        # Stage 3: Tree-sitter parsing
        graph = await parse_with_treesitter(manifest)
        assert graph.node_count > 0
        assert graph.edge_count > 0

        # Compose into context
        context = AnalysisContext(project_id="test-e2e")
        context.manifest = manifest
        context.environment = environment
        context.graph = graph

        # Verify context state
        assert context.graph.node_count > 10
        assert len(context.warnings) == 0

    @pytest.mark.asyncio
    async def test_sql_migration_detected(self):
        """Stage 1: SQL migration files should be discovered."""
        from app.stages.discovery import discover_project

        manifest = discover_project(PETCLINIC_DIR)

        # Should find V1__init.sql
        sql_files = [f for f in manifest.source_files if f.path.endswith(".sql")]
        assert len(sql_files) >= 1
