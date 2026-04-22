"""Unit tests for AlembicPlugin."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.context import AnalysisContext
from app.models.enums import Confidence
from app.models.graph import SymbolGraph
from app.models.manifest import ProjectManifest


class TestAlembicDetection:
    def test_detects_via_alembic_ini(self, tmp_path: Path):
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        (tmp_path / "alembic.ini").write_text(
            "[alembic]\nscript_location = migrations\n"
        )

        manifest = ProjectManifest(root_path=tmp_path)
        ctx = AnalysisContext(
            project_id="t",
            graph=SymbolGraph(),
            manifest=manifest,
        )

        result = AlembicPlugin().detect(ctx)

        assert result.confidence == Confidence.HIGH
        assert "alembic.ini" in result.reason

    def test_detects_via_env_py(self, tmp_path: Path):
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "env.py").write_text(
            "from alembic import context\n\n"
            "config = context.config\n"
        )

        manifest = ProjectManifest(root_path=tmp_path)
        ctx = AnalysisContext(
            project_id="t",
            graph=SymbolGraph(),
            manifest=manifest,
        )

        result = AlembicPlugin().detect(ctx)

        assert result.confidence == Confidence.HIGH
        assert "env.py" in result.reason

    def test_detects_via_import_alembic_form(self, tmp_path: Path):
        """Hand-rolled env.py using `import alembic` is still recognized."""
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "env.py").write_text(
            "import alembic\n\n"
            "ctx = alembic.context.config\n"
        )

        manifest = ProjectManifest(root_path=tmp_path)
        ctx = AnalysisContext(
            project_id="t",
            graph=SymbolGraph(),
            manifest=manifest,
        )

        result = AlembicPlugin().detect(ctx)

        assert result.confidence == Confidence.HIGH
        assert "env.py" in result.reason

    def test_no_alembic_artifacts_returns_not_detected(self, tmp_path: Path):
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        manifest = ProjectManifest(root_path=tmp_path)
        ctx = AnalysisContext(
            project_id="t",
            graph=SymbolGraph(),
            manifest=manifest,
        )

        result = AlembicPlugin().detect(ctx)

        assert result.confidence is None


class TestAlembicEmptyExtract:
    @pytest.mark.asyncio
    async def test_empty_project_returns_empty_result(self, tmp_path: Path):
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        manifest = ProjectManifest(root_path=tmp_path)
        ctx = AnalysisContext(
            project_id="t",
            graph=SymbolGraph(),
            manifest=manifest,
        )

        result = await AlembicPlugin().extract(ctx)

        assert result.nodes == []
        assert result.edges == []
        assert result.warnings == []
