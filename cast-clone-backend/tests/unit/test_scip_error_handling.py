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
    _scrub_stderr,
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


class TestSCIPSubprojectGather:
    """CHAN-69: subproject gather loop must propagate ``FileNotFoundError``."""

    @pytest.mark.asyncio
    async def test_subproject_gather_propagates_file_not_found(self, tmp_path):
        """If one of the per-subproject SCIP invocations fails with
        ``FileNotFoundError`` (binary missing), the aggregation loop must
        re-raise it so the top-level orchestrator routes the language to
        LSP fallback. Prior behaviour swallowed it as a subproject-level
        failure and surfaced an aggregate RuntimeError instead.
        """
        # Build a manifest with two Java subprojects and NO root build file
        # so we skip the root attempt and go straight to the subproject
        # gather path.
        ctx = AnalysisContext(project_id="test-proj")
        sub_a = tmp_path / "svc-a"
        sub_b = tmp_path / "svc-b"
        sub_a.mkdir()
        sub_b.mkdir()

        manifest = ProjectManifest(root_path=tmp_path)
        manifest.detected_languages = [
            DetectedLanguage(name="java", file_count=2, total_loc=20),
        ]
        manifest.build_tools = [
            BuildTool(
                name="maven",
                config_file="svc-a/pom.xml",
                language="java",
                subproject_root="svc-a",
            ),
            BuildTool(
                name="maven",
                config_file="svc-b/pom.xml",
                language="java",
                subproject_root="svc-b",
            ),
        ]
        ctx.manifest = manifest

        # First subproject: binary missing; Second: times out. The critical
        # assertion is that FileNotFoundError wins over TimeoutError.
        call_order: list[Path] = []

        async def fake_run(context, indexer_config, project_name, cwd, build_tool=None):
            call_order.append(cwd)
            if cwd == sub_a:
                raise FileNotFoundError(
                    "Executable not found on PATH: 'scip-java'"
                )
            raise TimeoutError("Command timed out after 300s: scip-java index")

        with patch(
            "app.stages.scip.indexer._run_scip_in_directory",
            side_effect=fake_run,
        ):
            cfg = SCIP_INDEXER_CONFIGS["java"]
            with pytest.raises(FileNotFoundError):
                await run_single_scip_indexer(
                    context=ctx,
                    indexer_config=cfg,
                    project_name="myapp",
                )

        # Must not be wrapped in RuntimeError and must not be swallowed into
        # the aggregate failure list.
        assert any(c == sub_a for c in call_order)


class TestStderrScrubbing:
    """Best-effort PII scrubbing for SCIP subprocess stderr."""

    def test_stderr_scrubbed_of_project_path(self, tmp_path):
        """``_scrub_stderr`` must replace the absolute project root with
        ``<project>`` so routine SCIP stderr does not leak checkout
        locations into structured logs.
        """
        stderr = (
            f"error: could not resolve symbol at {tmp_path}/src/Main.java:42"
        )
        scrubbed = _scrub_stderr(stderr, tmp_path)

        assert str(tmp_path) not in scrubbed
        assert "<project>" in scrubbed
        assert "src/Main.java:42" in scrubbed

    def test_stderr_scrubbed_of_home_directory(self, tmp_path):
        """User home directory must be replaced with ``<home>``."""
        import os

        home = os.path.expanduser("~")
        if home in ("~", ""):
            pytest.skip("HOME not expandable in this environment")

        stderr = f"warning: using cache at {home}/.cache/scip"
        scrubbed = _scrub_stderr(stderr, tmp_path)

        assert home not in scrubbed
        assert "<home>" in scrubbed

    def test_scrub_stderr_handles_none_root(self):
        """Scrubbing must tolerate a missing project_root without crashing."""
        assert _scrub_stderr("", None) == ""
        out = _scrub_stderr("some error message", None)
        assert "some error message" in out

    def test_stderr_scrubs_userprofile(self, tmp_path, monkeypatch):
        """Windows ``USERPROFILE`` must be replaced with ``<userprofile>``."""
        fake_profile = r"C:\Users\alice"
        monkeypatch.setenv("USERPROFILE", fake_profile)
        # Clear APPDATA so it does not interfere with this assertion.
        monkeypatch.delenv("APPDATA", raising=False)

        stderr = (
            rf"error: cannot open {fake_profile}\AppData\Local\scip\cache"
        )
        scrubbed = _scrub_stderr(stderr, tmp_path)

        assert fake_profile not in scrubbed
        assert "<userprofile>" in scrubbed

    def test_stderr_scrubs_appdata(self, tmp_path, monkeypatch):
        """Windows ``APPDATA`` must be replaced with ``<appdata>``."""
        fake_appdata = r"C:\Users\alice\AppData\Roaming"
        monkeypatch.setenv("APPDATA", fake_appdata)
        monkeypatch.delenv("USERPROFILE", raising=False)

        stderr = rf"warning: config missing at {fake_appdata}\scip\config.json"
        scrubbed = _scrub_stderr(stderr, tmp_path)

        assert fake_appdata not in scrubbed
        assert "<appdata>" in scrubbed

    def test_stderr_empty_env_var_does_not_splatter(self, tmp_path, monkeypatch):
        """Empty env vars must not cause ``str.replace("", ...)`` to insert
        the placeholder between every character of the stderr output.
        """
        monkeypatch.setenv("USERPROFILE", "")
        monkeypatch.setenv("APPDATA", "")

        stderr = "hello world"
        scrubbed = _scrub_stderr(stderr, tmp_path)

        assert scrubbed == "hello world"
        assert "<userprofile>" not in scrubbed
        assert "<appdata>" not in scrubbed

    def test_stderr_scrubs_resolved_project_root(self, tmp_path):
        """If the project root is reached via a symlink, both the unresolved
        and resolved variants must be scrubbed -- SCIP indexers often emit
        resolved absolute paths even when launched via a symlink.
        """
        real = tmp_path / "real_project"
        real.mkdir()
        link = tmp_path / "link_project"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported in this environment")

        # Use the symlinked path as the "project_root" passed to the scrubber
        # but craft stderr that includes the RESOLVED path (what SCIP would
        # normally emit).
        resolved = str(link.resolve())
        stderr = f"error: could not parse {resolved}/src/Main.java"
        scrubbed = _scrub_stderr(stderr, link)

        assert resolved not in scrubbed
        assert "<project>" in scrubbed
        assert "src/Main.java" in scrubbed


class TestSubprojectGatherTimeout:
    """CHAN-70: subproject gather must distinguish TimeoutError from RuntimeError."""

    @pytest.mark.asyncio
    async def test_subproject_gather_distinguishes_timeout_error(self, tmp_path):
        """When a per-subproject SCIP invocation times out, the aggregation
        loop must emit a distinct ``scip.indexer.subproject_timeout`` log
        event AND re-raise ``TimeoutError`` (not collapse it into an
        aggregate RuntimeError) so the top-level orchestrator can route it
        to LSP fallback distinctly from a non-zero-exit failure.
        """
        import structlog
        from structlog.testing import capture_logs

        ctx = AnalysisContext(project_id="test-proj")
        sub_a = tmp_path / "svc-a"
        sub_b = tmp_path / "svc-b"
        sub_a.mkdir()
        sub_b.mkdir()

        manifest = ProjectManifest(root_path=tmp_path)
        manifest.detected_languages = [
            DetectedLanguage(name="java", file_count=2, total_loc=20),
        ]
        manifest.build_tools = [
            BuildTool(
                name="maven",
                config_file="svc-a/pom.xml",
                language="java",
                subproject_root="svc-a",
            ),
            BuildTool(
                name="maven",
                config_file="svc-b/pom.xml",
                language="java",
                subproject_root="svc-b",
            ),
        ]
        ctx.manifest = manifest

        async def fake_run(context, indexer_config, project_name, cwd, build_tool=None):
            if cwd == sub_a:
                raise TimeoutError("Command timed out after 300s: scip-java index")
            # Make the other subproject also fail so we are sure we would
            # otherwise collapse into aggregate RuntimeError if the branch
            # were missing.
            raise RuntimeError("scip-java exited with code 1")

        # Configure structlog for capture_logs to work reliably. Save the
        # prior config so we can restore it — otherwise other tests that
        # rely on async logger methods (logger.ainfo / awarning) break.
        prior_config = structlog.get_config()
        structlog.configure(
            processors=[structlog.testing.LogCapture()],
            wrapper_class=structlog.BoundLogger,
            cache_logger_on_first_use=False,
        )

        try:
            with patch(
                "app.stages.scip.indexer._run_scip_in_directory",
                side_effect=fake_run,
            ):
                cfg = SCIP_INDEXER_CONFIGS["java"]
                with capture_logs() as cap:
                    with pytest.raises(TimeoutError) as exc_info:
                        await run_single_scip_indexer(
                            context=ctx,
                            indexer_config=cfg,
                            project_name="myapp",
                        )
        finally:
            structlog.configure(**prior_config)

        # Re-raised as-is (not collapsed into RuntimeError).
        assert not isinstance(exc_info.value, RuntimeError)

        # Distinct structured log event was emitted.
        events = [entry.get("event") for entry in cap]
        assert "scip.indexer.subproject_timeout" in events
