"""CHAN-73 integration test: DELETE /projects/{id}/analyze cancels a live run.

Drives the full HTTP flow (POST /analyze → DELETE /analyze) against a
fake pipeline that sleeps long enough to be cancellable, asserting the
run transitions to ``status='cancelled'`` well under the 10s wall
budget. Uses in-memory mocks for the DB session so the test does not
require Neo4j/Postgres.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.context import AnalysisContext
from app.models.db import Project
from app.orchestrator import progress as progress_mod


@pytest_asyncio.fixture
async def cancel_test_client(monkeypatch: pytest.MonkeyPatch):
    """FastAPI client wired to a mock session + deterministic pipeline.

    The pipeline is swapped for a coroutine that registers itself in
    ``active_contexts`` and polls ``context.cancelled`` every 50ms so
    the DELETE endpoint can flip the flag and the loop exits quickly.
    """
    from app.api.dependencies import require_license_writable
    from app.main import create_app
    from app.services.postgres import get_session

    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("LICENSE_DISABLED", "true")

    # Mock project + run objects that the endpoint handlers read.
    project = MagicMock(spec=Project)
    project.id = "proj-cancel-e2e"
    project.name = "cancel-e2e"
    project.source_path = "/tmp/cancel-e2e"
    project.status = "created"
    project.repository = None

    run = MagicMock()
    run.id = "run-cancel-e2e"
    run.status = "pending"
    run.project_id = project.id
    run.started_at = None

    # DB session mock: scalars return project, then the run for DELETE.
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()

    def _result_for(obj):
        res = MagicMock()
        res.scalar_one_or_none = MagicMock(return_value=obj)
        return res

    # execute() returns whichever fixture row is relevant on that call.
    # Order of calls in this test:
    # 1. POST /analyze: loads Project
    # 2. DELETE /analyze: loads Project (via dependency), then latest AnalysisRun
    session.execute = AsyncMock(
        side_effect=[
            _result_for(project),  # POST: project
            _result_for(project),  # DELETE: project (via get_accessible_project)
            _result_for(run),  # DELETE: latest run lookup
        ]
    )

    # Fake pipeline: registers context and polls the cancel flag.
    # Launched via ``asyncio.create_task`` instead of FastAPI's
    # BackgroundTasks wrapper so the long-running loop does not block
    # the POST response under ``ASGITransport`` (which awaits all
    # background tasks inline before returning from the ASGI call).
    cancel_observed_at: list[float] = []
    flag_set_at: list[float] = []
    spawned_tasks: list[asyncio.Task] = []

    async def _fake_pipeline_body(project_id: str) -> None:
        ctx = AnalysisContext(project_id=project_id)
        progress_mod.active_contexts[project_id] = ctx
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if ctx.cancelled:
                    cancel_observed_at.append(time.monotonic())
                    run.status = "cancelled"
                    return
                await asyncio.sleep(0.05)
        finally:
            progress_mod.active_contexts.pop(project_id, None)

    async def _fake_pipeline(
        project_id: str, run_id: str | None = None, services=None
    ) -> None:
        # Return immediately so BackgroundTasks (which awaits inline in
        # ASGITransport) unblocks the POST response; schedule the real
        # work as a detached task.
        spawned_tasks.append(asyncio.create_task(_fake_pipeline_body(project_id)))

    app = create_app()

    async def override_get_session():
        yield session

    async def override_require_license_writable() -> None:
        return None

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_license_writable] = (
        override_require_license_writable
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "project": project,
            "run": run,
            "session": session,
            "pipeline": _fake_pipeline,
            "cancel_observed_at": cancel_observed_at,
            "flag_set_at": flag_set_at,
        }

    app.dependency_overrides.clear()
    # Safety: pop any leftover registry entry.
    progress_mod.active_contexts.pop("proj-cancel-e2e", None)


class TestAnalysisCancelEndToEnd:
    """POST /analyze → DELETE /analyze flips status within the budget."""

    @pytest.mark.asyncio
    async def test_delete_cancels_running_pipeline(self, cancel_test_client) -> None:
        client = cancel_test_client["client"]
        project = cancel_test_client["project"]
        run = cancel_test_client["run"]
        pipeline_fn = cancel_test_client["pipeline"]
        flag_set_at = cancel_test_client["flag_set_at"]
        cancel_observed_at = cancel_test_client["cancel_observed_at"]

        # Patch the endpoint's reference to the pipeline so POST kicks
        # off our fake long-running coroutine instead of the real
        # 9-stage pipeline.
        # Direct attribute swap — ``patch(..., side_effect=async_fn)``
        # wraps in a MagicMock which FastAPI's BackgroundTasks treats as
        # a sync callable, so the fake coroutine would never await.
        import app.api.analysis as analysis_mod

        original_pipeline = analysis_mod.run_analysis_pipeline
        analysis_mod.run_analysis_pipeline = pipeline_fn  # type: ignore[assignment]
        try:
            with patch("app.api.analysis.get_driver", return_value=MagicMock()):
                # 1. Trigger analysis. BackgroundTask starts after the
                #    response is returned; refresh(run) is mocked so
                #    the response builder gets a stable run_id.

                async def _refresh(obj):
                    obj.id = "run-cancel-e2e"
                    obj.status = "running"

                cancel_test_client["session"].refresh = _refresh

                post_resp = await client.post(f"/api/v1/projects/{project.id}/analyze")
                assert post_resp.status_code == 202, post_resp.text

                # Wait until the background pipeline has registered
                # its context (bounded to 2s).
                for _ in range(40):
                    if project.id in progress_mod.active_contexts:
                        break
                    await asyncio.sleep(0.05)
                assert project.id in progress_mod.active_contexts, (
                    "pipeline never registered its context"
                )

                # 2. Flip run status so DELETE sees it as non-terminal.
                run.status = "running"

                # 3. Fire DELETE.
                flag_set_at.append(time.monotonic())
                delete_resp = await client.delete(
                    f"/api/v1/projects/{project.id}/analyze"
                )
                assert delete_resp.status_code == 204, delete_resp.text

                # 4. Wait for the pipeline to observe the flag.
                for _ in range(60):
                    if cancel_observed_at:
                        break
                    await asyncio.sleep(0.05)

                assert cancel_observed_at, (
                    "pipeline did not observe cancellation flag within budget"
                )
                elapsed = cancel_observed_at[0] - flag_set_at[0]
                assert elapsed < 3.0, (
                    f"pipeline took {elapsed:.2f}s to observe cancel; "
                    f"budget is <3s for this test, <5s per acceptance criteria"
                )
                # Surface the measurement for the CHAN-73 report.
                print(f"\n[CHAN-73] flag_flip -> pipeline_exit: {elapsed * 1000:.1f}ms")

                assert run.status == "cancelled"
        finally:
            analysis_mod.run_analysis_pipeline = original_pipeline  # type: ignore[assignment]

    @pytest.mark.asyncio
    async def test_delete_returns_409_when_run_already_completed(
        self, cancel_test_client
    ) -> None:
        """DELETE against a terminal run must return 409."""
        client = cancel_test_client["client"]
        project = cancel_test_client["project"]
        run = cancel_test_client["run"]

        run.status = "completed"

        # The default side_effect queue consumes
        # [project, project, run] — for this test we only call DELETE
        # once, so the first two "project" entries cover
        # get_accessible_project and the session.execute shouldn't need
        # more. Reset the side_effect for this test.
        session = cancel_test_client["session"]

        def _result_for(obj):
            res = MagicMock()
            res.scalar_one_or_none = MagicMock(return_value=obj)
            return res

        session.execute = AsyncMock(
            side_effect=[_result_for(project), _result_for(run)]
        )

        resp = await client.delete(f"/api/v1/projects/{project.id}/analyze")
        assert resp.status_code == 409, resp.text

    @pytest.mark.asyncio
    async def test_delete_returns_404_when_no_run_exists(
        self, cancel_test_client
    ) -> None:
        """DELETE with no prior run returns 404."""
        client = cancel_test_client["client"]
        project = cancel_test_client["project"]
        session = cancel_test_client["session"]

        def _result_for(obj):
            res = MagicMock()
            res.scalar_one_or_none = MagicMock(return_value=obj)
            return res

        session.execute = AsyncMock(
            side_effect=[_result_for(project), _result_for(None)]
        )

        resp = await client.delete(f"/api/v1/projects/{project.id}/analyze")
        assert resp.status_code == 404, resp.text
