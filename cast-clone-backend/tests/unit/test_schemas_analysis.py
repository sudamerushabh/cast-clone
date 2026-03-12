# tests/unit/test_schemas_analysis.py
from datetime import datetime

from app.schemas.analysis import (
    AnalysisTriggerResponse,
    AnalysisStatusResponse,
    AnalysisRunResponse,
)


class TestAnalysisTriggerResponse:
    def test_create(self):
        resp = AnalysisTriggerResponse(
            project_id="proj-1",
            run_id="run-1",
            status="analyzing",
            message="Analysis started",
        )
        assert resp.project_id == "proj-1"
        assert resp.status == "analyzing"


class TestAnalysisStatusResponse:
    def test_create(self):
        resp = AnalysisStatusResponse(
            project_id="proj-1",
            status="analyzed",
            current_stage=None,
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        assert resp.status == "analyzed"

    def test_analyzing_with_stage(self):
        resp = AnalysisStatusResponse(
            project_id="proj-1",
            status="analyzing",
            current_stage="parsing",
            started_at=datetime.now(),
        )
        assert resp.current_stage == "parsing"
        assert resp.completed_at is None


class TestAnalysisRunResponse:
    def test_create(self):
        resp = AnalysisRunResponse(
            id="run-1",
            project_id="proj-1",
            status="completed",
            stage=None,
            started_at=datetime.now(),
            completed_at=datetime.now(),
            node_count=100,
            edge_count=200,
            error_message=None,
        )
        assert resp.node_count == 100
