"""Tests for SCIP indexer runner.

All subprocess calls are mocked -- no actual SCIP indexers needed.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.stages.scip.indexer import (
    SCIP_INDEXER_CONFIGS,
    build_scip_command,
    detect_available_indexers,
    run_scip_indexers,
    run_single_scip_indexer,
)


class TestSCIPIndexerConfig:
    def test_java_config_exists(self):
        assert "java" in SCIP_INDEXER_CONFIGS
        cfg = SCIP_INDEXER_CONFIGS["java"]
        assert cfg.language == "java"
        assert cfg.timeout_seconds > 0
        assert cfg.output_file == "index.scip"

    def test_typescript_config_exists(self):
        assert "typescript" in SCIP_INDEXER_CONFIGS
        cfg = SCIP_INDEXER_CONFIGS["typescript"]
        assert cfg.language == "typescript"

    def test_python_config_exists(self):
        assert "python" in SCIP_INDEXER_CONFIGS
        cfg = SCIP_INDEXER_CONFIGS["python"]
        assert cfg.language == "python"

    def test_csharp_config_exists(self):
        assert "csharp" in SCIP_INDEXER_CONFIGS
        cfg = SCIP_INDEXER_CONFIGS["csharp"]
        assert cfg.language == "csharp"


class TestBuildSCIPCommand:
    def test_java_command(self):
        cfg = SCIP_INDEXER_CONFIGS["java"]
        cmd = build_scip_command(cfg, project_name="myapp", root_path=Path("/code"))
        assert cmd[0] == "scip-java"
        assert "index" in cmd

    def test_typescript_command(self):
        cfg = SCIP_INDEXER_CONFIGS["typescript"]
        cmd = build_scip_command(cfg, project_name="myapp", root_path=Path("/code"))
        assert "scip-typescript" in " ".join(cmd)
        assert "index" in cmd

    def test_python_command_includes_project_name(self):
        cfg = SCIP_INDEXER_CONFIGS["python"]
        cmd = build_scip_command(cfg, project_name="myapp", root_path=Path("/code"))
        assert "scip-python" in " ".join(cmd)
        assert any("myapp" in arg for arg in cmd)

    def test_csharp_command(self):
        cfg = SCIP_INDEXER_CONFIGS["csharp"]
        cmd = build_scip_command(cfg, project_name="myapp", root_path=Path("/code"))
        assert "scip-dotnet" in " ".join(cmd)


class TestDetectAvailableIndexers:
    def test_returns_configs_for_detected_languages(self):
        """Only returns configs for languages that have SCIP indexers."""
        detected_languages = ["java", "typescript", "sql", "xml"]
        configs = detect_available_indexers(detected_languages)
        assert len(configs) == 2  # java, typescript (no SCIP for sql/xml)
        lang_names = [c.language for c in configs]
        assert "java" in lang_names
        assert "typescript" in lang_names

    def test_returns_empty_for_unsupported_languages(self):
        configs = detect_available_indexers(["cobol", "fortran"])
        assert len(configs) == 0

    def test_javascript_maps_to_typescript_indexer(self):
        """JavaScript uses the same scip-typescript indexer."""
        configs = detect_available_indexers(["javascript"])
        assert len(configs) == 1
        assert configs[0].language == "typescript"


class TestRunSingleSCIPIndexer:
    @pytest.mark.asyncio
    async def test_successful_indexer_run(self, tmp_path):
        """Mock a successful SCIP indexer run and verify merge is called."""
        from app.orchestrator.subprocess_utils import SubprocessResult
        from app.stages.scip.protobuf_parser import SCIPIndex, write_test_scip_index

        # Create a mock SCIP index file
        scip_file = tmp_path / "index.scip"
        write_test_scip_index(
            scip_file,
            documents=[
                {
                    "relative_path": "src/App.java",
                    "occurrences": [
                        {
                            "range": [5, 10, 20],
                            "symbol": "test . App#",
                            "symbol_roles": 1,
                        },
                    ],
                    "symbols": [
                        {
                            "symbol": "test . App#",
                            "documentation": ["App class"],
                            "relationships": [],
                        },
                    ],
                },
            ],
        )

        mock_subprocess_result = SubprocessResult(returncode=0, stdout="OK", stderr="")

        with patch(
            "app.stages.scip.indexer.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_subprocess_result

            with patch("app.stages.scip.indexer.parse_scip_index") as mock_parse:
                mock_parse.return_value = SCIPIndex(
                    documents=[],
                    metadata_tool_name="test",
                    metadata_tool_version="1.0",
                )

                with patch(
                    "app.stages.scip.indexer.merge_scip_into_context"
                ) as mock_merge:
                    from app.stages.scip.merger import MergeStats

                    mock_merge.return_value = MergeStats(
                        resolved_count=10,
                        new_nodes=2,
                        upgraded_edges=8,
                        new_implements_edges=1,
                    )

                    from app.models.manifest import BuildTool

                    cfg = SCIP_INDEXER_CONFIGS["java"]
                    mock_manifest = MagicMock(root_path=tmp_path)
                    mock_manifest.build_tools = [
                        BuildTool(name="maven", config_file="pom.xml", language="java", subproject_root="."),
                    ]
                    stats = await run_single_scip_indexer(
                        context=MagicMock(
                            manifest=mock_manifest,
                            project_id="test-proj",
                        ),
                        indexer_config=cfg,
                        project_name="myapp",
                    )

                    mock_run.assert_called_once()
                    mock_parse.assert_called_once()
                    mock_merge.assert_called_once()
                    assert stats.resolved_count == 10

    @pytest.mark.asyncio
    async def test_failed_indexer_raises(self, tmp_path):
        """When subprocess returns non-zero, raise RuntimeError."""
        from app.orchestrator.subprocess_utils import SubprocessResult

        mock_result = SubprocessResult(
            returncode=1, stdout="", stderr="compilation failed"
        )

        with patch(
            "app.stages.scip.indexer.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = mock_result

            from app.models.manifest import BuildTool

            cfg = SCIP_INDEXER_CONFIGS["java"]
            mock_manifest = MagicMock(root_path=tmp_path)
            mock_manifest.build_tools = [
                BuildTool(name="maven", config_file="pom.xml", language="java", subproject_root="."),
            ]
            with pytest.raises(RuntimeError, match="failed at root and no subprojects"):
                await run_single_scip_indexer(
                    context=MagicMock(
                        manifest=mock_manifest,
                        project_id="test-proj",
                    ),
                    indexer_config=cfg,
                    project_name="myapp",
                )


class TestRunSCIPIndexers:
    @pytest.mark.asyncio
    async def test_successful_parallel_run(self):
        """All indexers succeed -- languages added to scip_resolved_languages."""
        from app.models.context import AnalysisContext
        from app.models.manifest import DetectedLanguage, ProjectManifest
        from app.stages.scip.merger import MergeStats

        ctx = AnalysisContext(project_id="test-proj")
        ctx.manifest = ProjectManifest(root_path=Path("/code"))
        ctx.manifest.detected_languages = [
            DetectedLanguage(name="java", file_count=10, total_loc=1000),
        ]

        mock_stats = MergeStats(
            resolved_count=50,
            new_nodes=5,
            upgraded_edges=40,
            new_implements_edges=3,
        )

        with patch(
            "app.stages.scip.indexer.run_single_scip_indexer",
            new_callable=AsyncMock,
        ) as mock_single:
            mock_single.return_value = mock_stats

            result = await run_scip_indexers(ctx)

            assert result.resolved_count == 50
            assert "java" in ctx.scip_resolved_languages
            assert len(ctx.languages_needing_fallback) == 0

    @pytest.mark.asyncio
    async def test_failed_indexer_adds_to_fallback(self):
        """When an indexer fails, language goes to fallback list."""
        from app.models.context import AnalysisContext
        from app.models.manifest import DetectedLanguage, ProjectManifest

        ctx = AnalysisContext(project_id="test-proj")
        ctx.manifest = ProjectManifest(root_path=Path("/code"))
        ctx.manifest.detected_languages = [
            DetectedLanguage(name="java", file_count=10, total_loc=1000),
        ]

        with patch(
            "app.stages.scip.indexer.run_single_scip_indexer",
            new_callable=AsyncMock,
        ) as mock_single:
            mock_single.side_effect = RuntimeError("scip-java failed")

            result = await run_scip_indexers(ctx)

            assert result.resolved_count == 0
            assert "java" in ctx.languages_needing_fallback
            assert "java" not in ctx.scip_resolved_languages
            assert len(ctx.warnings) >= 1

    @pytest.mark.asyncio
    async def test_unsupported_language_goes_to_fallback(self):
        """Languages without SCIP indexers go to fallback."""
        from app.models.context import AnalysisContext
        from app.models.manifest import DetectedLanguage, ProjectManifest

        ctx = AnalysisContext(project_id="test-proj")
        ctx.manifest = ProjectManifest(root_path=Path("/code"))
        ctx.manifest.detected_languages = [
            DetectedLanguage(name="ruby", file_count=5, total_loc=500),
        ]

        result = await run_scip_indexers(ctx)

        assert result.resolved_count == 0
        assert "ruby" in ctx.languages_needing_fallback

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self):
        """One indexer succeeds, one fails."""
        from app.models.context import AnalysisContext
        from app.models.manifest import DetectedLanguage, ProjectManifest
        from app.stages.scip.merger import MergeStats

        ctx = AnalysisContext(project_id="test-proj")
        ctx.manifest = ProjectManifest(root_path=Path("/code"))
        ctx.manifest.detected_languages = [
            DetectedLanguage(name="java", file_count=10, total_loc=1000),
            DetectedLanguage(name="typescript", file_count=5, total_loc=500),
        ]

        async def mock_run(context, indexer_config, project_name):
            if indexer_config.language == "java":
                return MergeStats(
                    resolved_count=50,
                    new_nodes=5,
                    upgraded_edges=40,
                    new_implements_edges=3,
                )
            else:
                raise RuntimeError("scip-typescript failed")

        with patch(
            "app.stages.scip.indexer.run_single_scip_indexer",
            new_callable=AsyncMock,
        ) as mock_single:
            mock_single.side_effect = mock_run

            result = await run_scip_indexers(ctx)

            assert result.resolved_count == 50
            assert "java" in ctx.scip_resolved_languages
            assert "typescript" in ctx.languages_needing_fallback

    @pytest.mark.asyncio
    async def test_no_manifest_returns_empty(self):
        """If manifest is None, return empty result."""
        from app.models.context import AnalysisContext

        ctx = AnalysisContext(project_id="test-proj")
        result = await run_scip_indexers(ctx)
        assert result.resolved_count == 0
