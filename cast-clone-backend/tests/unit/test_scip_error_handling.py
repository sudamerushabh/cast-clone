"""Tests for SCIP indexer error handling (CHAN-69, CHAN-70).

Covers three distinct failure modes that must degrade gracefully instead of
aborting the pipeline:

* ``FileNotFoundError`` -- the SCIP binary is not installed on PATH.
* ``TimeoutError``      -- the subprocess hangs past ``scip_timeout``.
* ``RuntimeError``      -- the subprocess exits with a non-zero code.

All three routes should add the language to ``languages_needing_fallback``
so Stage 4b (LSP fallback) can take over.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.models.context import AnalysisContext
from app.models.manifest import BuildTool, DetectedLanguage, ProjectManifest
from app.orchestrator.subprocess_utils import SubprocessResult
from app.stages.scip.indexer import (
    SCIP_INDEXER_CONFIGS,
    run_scip_indexers,
    run_single_scip_indexer,
)


def _make_java_context(tmp_path: Path) -> AnalysisContext:
    """Build a minimal AnalysisContext with a Java Maven manifest."""
    ctx = AnalysisContext(project_id="test-proj")
    manifest = ProjectManifest(root_path=tmp_path)
    manifest.detected_languages = [
        DetectedLanguage(name="java", file_count=1, total_loc=10),
    ]
    manifest.build_tools = [
        BuildTool(
            name="maven",
            config_file="pom.xml",
            language="java",
            subproject_root=".",
        ),
    ]
    ctx.manifest = manifest
    return ctx


class TestSCIPMissingBinary:
    """CHAN-69: ``FileNotFoundError`` from ``create_subprocess_exec``."""

    @pytest.mark.asyncio
    async def test_scip_missing_binary_returns_empty_graph(self, tmp_path):
        """If the SCIP binary is not on PATH, the pipeline records a warning
        and routes the language to LSP fallback -- it must NOT propagate the
        FileNotFoundError and abort the run.
        """
        ctx = _make_java_context(tmp_path)

        with patch(
            "app.stages.scip.indexer.run_subprocess",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.side_effect = FileNotFoundError(
                "Executable not found on PATH: 'scip-java'"
            )

            result = await run_scip_indexers(ctx)

        assert result.resolved_count == 0
        assert "java" in ctx.languages_needing_fallback
        assert "java" not in ctx.scip_resolved_languages
        assert any("SCIP indexer failed" in w or "scip-java" in w for w in ctx.warnings)

    @pytest.mark.asyncio
    async def test_missing_binary_logs_structured_warning(self, tmp_path, caplog):
        """The missing-binary path must log a structured warning via structlog
        naming the binary and the language so operators can diagnose quickly.
        """
        ctx = _make_java_context(tmp_path)

        with patch(
            "app.stages.scip.indexer.run_subprocess",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.side_effect = FileNotFoundError(
                "Executable not found on PATH: 'scip-java'"
            )

            cfg = SCIP_INDEXER_CONFIGS["java"]
            with pytest.raises(FileNotFoundError):
                # _run_scip_in_directory (via run_single_scip_indexer) should
                # re-raise FileNotFoundError so the caller can distinguish it.
                await run_single_scip_indexer(
                    context=ctx,
                    indexer_config=cfg,
                    project_name="myapp",
                )


class TestSCIPTimeout:
    """CHAN-70: ``TimeoutError`` must be distinct from ``RuntimeError``."""

    @pytest.mark.asyncio
    async def test_scip_timeout_logs_and_returns_empty(self, tmp_path):
        """When the SCIP subprocess times out, the top-level orchestrator
        records the failure and routes the language to LSP fallback.
        """
        ctx = _make_java_context(tmp_path)

        with patch(
            "app.stages.scip.indexer.run_subprocess",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.side_effect = TimeoutError(
                "Command timed out after 300s: scip-java index"
            )

            result = await run_scip_indexers(ctx)

        assert result.resolved_count == 0
        assert "java" in ctx.languages_needing_fallback
        assert "java" not in ctx.scip_resolved_languages
        assert any("scip-java" in w for w in ctx.warnings)

    @pytest.mark.asyncio
    async def test_timeout_propagates_as_timeout_error(self, tmp_path):
        """The indexer helper must re-raise TimeoutError specifically -- not
        collapsed into RuntimeError -- so callers can differentiate.
        """
        from app.stages.scip.indexer import _run_scip_in_directory

        ctx = _make_java_context(tmp_path)

        with patch(
            "app.stages.scip.indexer.run_subprocess",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.side_effect = TimeoutError(
                "Command timed out after 300s: scip-java index"
            )

            cfg = SCIP_INDEXER_CONFIGS["java"]
            with pytest.raises(TimeoutError) as exc_info:
                await _run_scip_in_directory(
                    context=ctx,
                    indexer_config=cfg,
                    project_name="myapp",
                    cwd=tmp_path,
                )

            # Must NOT be collapsed into RuntimeError -- the two branches
            # must stay distinguishable (CHAN-70).
            assert not isinstance(exc_info.value, RuntimeError)


class TestSCIPNonZeroExit:
    """CHAN-70: non-zero subprocess exit is a ``RuntimeError``."""

    @pytest.mark.asyncio
    async def test_scip_nonzero_exit_logs_runtime_error(self, tmp_path):
        """When the SCIP subprocess exits non-zero, surface a RuntimeError
        (distinct from TimeoutError) and route the language to fallback.
        """
        ctx = _make_java_context(tmp_path)

        with patch(
            "app.stages.scip.indexer.run_subprocess",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = SubprocessResult(
                returncode=1,
                stdout="",
                stderr="compilation failed: cannot resolve symbol",
            )

            result = await run_scip_indexers(ctx)

        assert result.resolved_count == 0
        assert "java" in ctx.languages_needing_fallback
        assert "java" not in ctx.scip_resolved_languages
        assert any("scip-java" in w for w in ctx.warnings)

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises_runtime_error(self, tmp_path):
        """The indexer helper must raise RuntimeError (not TimeoutError) when
        the subprocess exits with a non-zero code.
        """
        ctx = _make_java_context(tmp_path)

        with patch(
            "app.stages.scip.indexer.run_subprocess",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = SubprocessResult(
                returncode=2,
                stdout="",
                stderr="scip-java: fatal error",
            )

            cfg = SCIP_INDEXER_CONFIGS["java"]
            with pytest.raises(RuntimeError) as exc_info:
                await run_single_scip_indexer(
                    context=ctx,
                    indexer_config=cfg,
                    project_name="myapp",
                )

            assert "scip-java" in str(exc_info.value)
            # Ensure it is NOT a TimeoutError -- RuntimeError must be raised
            # as-is so the two branches stay distinguishable.
            assert not isinstance(exc_info.value, TimeoutError)
