# tests/unit/test_context.py
from pathlib import Path

from app.models.context import AnalysisContext
from app.models.enums import NodeKind
from app.models.graph import GraphNode
from app.models.manifest import ProjectManifest


class TestAnalysisContext:
    def test_create_with_defaults(self):
        ctx = AnalysisContext(project_id="proj-1")
        assert ctx.project_id == "proj-1"
        assert ctx.manifest is None
        assert ctx.graph.node_count == 0
        assert ctx.warnings == []

    def test_add_warning(self):
        ctx = AnalysisContext(project_id="proj-1")
        ctx.warnings.append("SCIP failed for java")
        assert len(ctx.warnings) == 1

    def test_graph_is_mutable(self):
        ctx = AnalysisContext(project_id="proj-1")
        ctx.graph.add_node(
            GraphNode(fqn="a.B", name="B", kind=NodeKind.CLASS)
        )
        assert ctx.graph.node_count == 1

    def test_manifest_assignable(self):
        ctx = AnalysisContext(project_id="proj-1")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"))
        assert ctx.manifest.root_path == Path("/tmp")

    def test_scip_tracking(self):
        ctx = AnalysisContext(project_id="proj-1")
        ctx.scip_resolved_languages.add("java")
        assert "java" in ctx.scip_resolved_languages
        ctx.languages_needing_fallback.append("python")
        assert "python" in ctx.languages_needing_fallback
