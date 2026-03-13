"""Verify pipeline stage functions are wired to real implementations."""

from __future__ import annotations

import inspect

from app.orchestrator.pipeline import _STAGE_FUNCS


class TestPipelineWiring:
    """Ensure every stage function calls real code, not a pass statement."""

    def test_discovery_is_wired(self):
        """Stage 1 should call discover_project from stages.discovery."""
        func = _STAGE_FUNCS["discovery"]
        source = inspect.getsource(func)
        assert "discover_project" in source

    def test_dependencies_is_wired(self):
        """Stage 2 should call resolve_dependencies from stages.dependencies."""
        func = _STAGE_FUNCS["dependencies"]
        source = inspect.getsource(func)
        assert "resolve_dependencies" in source

    def test_parsing_is_wired(self):
        """Stage 3 should call parse_with_treesitter from stages.treesitter."""
        func = _STAGE_FUNCS["parsing"]
        source = inspect.getsource(func)
        assert "parse_with_treesitter" in source

    def test_scip_is_wired(self):
        """Stage 4 should call run_scip_indexers from stages.scip."""
        func = _STAGE_FUNCS["scip"]
        source = inspect.getsource(func)
        assert "run_scip_indexers" in source

    def test_plugins_is_wired(self):
        """Stage 5 should call run_framework_plugins from stages.plugins."""
        func = _STAGE_FUNCS["plugins"]
        source = inspect.getsource(func)
        assert "run_framework_plugins" in source

    def test_linking_is_wired(self):
        """Stage 6 should call run_cross_tech_linker from stages.linker."""
        func = _STAGE_FUNCS["linking"]
        source = inspect.getsource(func)
        assert "run_cross_tech_linker" in source

    def test_enrichment_is_wired(self):
        """Stage 7 should call enrich_graph from stages.enricher."""
        func = _STAGE_FUNCS["enrichment"]
        source = inspect.getsource(func)
        assert "enrich_graph" in source

    def test_writing_is_wired(self):
        """Stage 8 should call write_to_neo4j from stages.writer."""
        func = _STAGE_FUNCS["writing"]
        source = inspect.getsource(func)
        assert "write_to_neo4j" in source

    def test_transactions_is_wired(self):
        """Stage 9 should call discover_transactions from stages.transactions."""
        func = _STAGE_FUNCS["transactions"]
        source = inspect.getsource(func)
        assert "discover_transactions" in source

    def test_gds_enrichment_is_wired(self):
        """Stage 10 should call run_gds_community_detection from stages.gds_enricher."""
        func = _STAGE_FUNCS["gds_enrichment"]
        source = inspect.getsource(func)
        assert "run_gds_community_detection" in source

    def test_all_stages_present(self):
        """All 11 stage names should be in _STAGE_FUNCS."""
        expected = {
            "discovery",
            "dependencies",
            "parsing",
            "scip",
            "lsp_fallback",
            "plugins",
            "linking",
            "enrichment",
            "writing",
            "transactions",
            "gds_enrichment",
        }
        assert set(_STAGE_FUNCS.keys()) == expected
