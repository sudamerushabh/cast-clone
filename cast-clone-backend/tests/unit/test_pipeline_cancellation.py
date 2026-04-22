# tests/unit/test_pipeline_cancellation.py
"""CHAN-73: cancellation tests for subprocess_utils + pipeline.

Covers:
1. ``SubprocessCancelled`` semantics: cancelling ``run_subprocess`` sends
   SIGTERM, raises the custom exception, and exposes any partial overflow
   paths that had been spooled to disk before cancellation.
2. Pipeline cooperative-cancellation: setting ``context.cancelled=True``
   between stages causes the pipeline to exit with status='cancelled'
   without running later stages.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.context import AnalysisContext
from app.orchestrator.subprocess_utils import (
    SubprocessCancelled,
    run_subprocess,
)


class TestSubprocessCancellation:
    """CHAN-73: run_subprocess responds to CancelledError cooperatively."""

    @pytest.mark.asyncio
    async def test_cancel_sends_sigterm_and_raises(self, tmp_path: Path) -> None:
        """Cancel a 30s sleep; assert SubprocessCancelled and child exited."""
        task = asyncio.create_task(
            run_subprocess(
                command=[sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=tmp_path,
                timeout=60,
            )
        )
        await asyncio.sleep(0.3)
        task.cancel()

        with pytest.raises(SubprocessCancelled) as exc_info:
            await task

        assert exc_info.value.command[0] == sys.executable
        # A plain sleep exits cleanly on SIGTERM (default handler), so
        # we should NOT have had to escalate to SIGKILL.
        assert exc_info.value.killed is False

    @pytest.mark.asyncio
    async def test_cancel_escalates_to_sigkill_when_sigterm_ignored(
        self, tmp_path: Path
    ) -> None:
        """If the child ignores SIGTERM, run_subprocess must SIGKILL it."""
        script = (
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "while True:\n"
            "    time.sleep(1)\n"
        )
        task = asyncio.create_task(
            run_subprocess(
                command=[sys.executable, "-c", script],
                cwd=tmp_path,
                timeout=60,
            )
        )
        await asyncio.sleep(0.4)
        task.cancel()

        with pytest.raises(SubprocessCancelled) as exc_info:
            await task

        assert exc_info.value.killed is True

    @pytest.mark.asyncio
    async def test_cancel_preserves_partial_overflow_paths(
        self, tmp_path: Path
    ) -> None:
        """Overflow tempfile paths survive cancellation for post-mortem."""
        script = (
            "import sys, time\n"
            "sys.stdout.buffer.write(b'x' * 11_000_000)\n"
            "sys.stdout.flush()\n"
            "time.sleep(30)\n"
        )
        task = asyncio.create_task(
            run_subprocess(
                command=[sys.executable, "-c", script],
                cwd=tmp_path,
                timeout=60,
            )
        )
        # Wait long enough for 11MB to stream + overflow file to open.
        await asyncio.sleep(1.5)
        task.cancel()

        with pytest.raises(SubprocessCancelled) as exc_info:
            await task

        logs = exc_info.value.overflow_logs
        assert len(logs) >= 1
        stdout_entries = [e for e in logs if e["stream"] == "stdout"]
        assert len(stdout_entries) == 1
        overflow_path = stdout_entries[0]["path"]
        assert os.path.exists(overflow_path)
        try:
            assert os.path.getsize(overflow_path) > 10_000_000
        finally:
            os.unlink(overflow_path)


# -- Pipeline cooperative-cancellation fixtures -------------------------------


class _AsyncCtx:
    """Async-context-manager wrapper around a session mock."""

    def __init__(self, session: AsyncMock) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncMock:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _make_project(project_id: str) -> MagicMock:
    project = MagicMock()
    project.id = project_id
    project.source_path = "/tmp/does-not-exist"
    project.branch = None
    project.repository_id = None
    project.status = "analyzing"
    return project


def _make_run(run_id: str) -> MagicMock:
    run = MagicMock()
    run.id = run_id
    run.status = "running"
    run.stage = None
    run.stage_progress = None
    run.subprocess_logs = None
    return run


class TestPipelineCancellation:
    """CHAN-73: context.cancelled causes the pipeline to exit cleanly."""

    @pytest.mark.asyncio
    async def test_flag_set_mid_pipeline_stops_later_stages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flip cancelled=True inside stage 3 ('parsing'); stages 4+ skip."""
        from app.orchestrator import pipeline as pipeline_mod

        stages_run: list[str] = []

        async def _generic_stage(name: str):
            async def _impl(context: AnalysisContext, services) -> None:
                stages_run.append(name)
                if name == "parsing":
                    context.cancelled = True

            return _impl

        patched = {
            name: await _generic_stage(name) for name in pipeline_mod._STAGE_FUNCS
        }
        monkeypatch.setattr(pipeline_mod, "_STAGE_FUNCS", patched)

        session = _make_session()
        project = _make_project("proj-cancel")
        run = _make_run("run-cancel")

        proj_res = MagicMock()
        proj_res.scalar_one_or_none.return_value = project
        run_res = MagicMock()
        run_res.scalar_one_or_none.return_value = run
        session.execute = AsyncMock(side_effect=[proj_res, run_res])

        def _factory():
            return _AsyncCtx(session)

        monkeypatch.setattr(pipeline_mod, "get_session_factory", lambda: _factory)
        monkeypatch.setattr(pipeline_mod, "log_activity", AsyncMock(return_value=None))

        services = pipeline_mod.PipelineServices(
            graph_store=MagicMock(), source_path=Path("/tmp/x")
        )

        await pipeline_mod.run_analysis_pipeline(
            project_id="proj-cancel", run_id="run-cancel", services=services
        )

        assert "parsing" in stages_run
        assert "scip" not in stages_run, f"scip ran after cancel; order={stages_run}"
        assert "writing" not in stages_run
        assert run.status == "cancelled"
        assert project.status != "analyzing"

    @pytest.mark.asyncio
    async def test_registry_path_flips_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate the DELETE endpoint flipping the flag via the registry."""
        from app.orchestrator import pipeline as pipeline_mod
        from app.orchestrator import progress as progress_mod

        stages_run: list[str] = []

        async def _noop(context: AnalysisContext, services) -> None:
            stages_run.append("noop")

        async def _discovery_triggers_delete(
            context: AnalysisContext, services
        ) -> None:
            stages_run.append("discovery")
            # Simulate the DELETE endpoint flipping the flag via the
            # in-memory registry (same mechanism the real endpoint uses).
            progress_mod.active_contexts[context.project_id].cancelled = True

        patched = dict.fromkeys(pipeline_mod._STAGE_FUNCS, _noop)
        patched["discovery"] = _discovery_triggers_delete
        monkeypatch.setattr(pipeline_mod, "_STAGE_FUNCS", patched)

        session = _make_session()
        project = _make_project("proj-registry")
        run = _make_run("run-registry")
        proj_res = MagicMock()
        proj_res.scalar_one_or_none.return_value = project
        run_res = MagicMock()
        run_res.scalar_one_or_none.return_value = run
        session.execute = AsyncMock(side_effect=[proj_res, run_res])

        def _factory():
            return _AsyncCtx(session)

        monkeypatch.setattr(pipeline_mod, "get_session_factory", lambda: _factory)
        monkeypatch.setattr(pipeline_mod, "log_activity", AsyncMock(return_value=None))

        services = pipeline_mod.PipelineServices(
            graph_store=MagicMock(), source_path=Path("/tmp/x")
        )

        await pipeline_mod.run_analysis_pipeline(
            project_id="proj-registry",
            run_id="run-registry",
            services=services,
        )

        # Only discovery should have run.
        assert stages_run == ["discovery"]
        assert run.status == "cancelled"
        # Registry should be cleaned up after exit.
        assert "proj-registry" not in progress_mod.active_contexts
