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


class TestAlembicExtract:
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

    @pytest.mark.asyncio
    async def test_versions_dir_with_migrations_emits_nodes(
        self, tmp_path: Path
    ):
        from app.models.context import AnalysisContext
        from app.models.enums import NodeKind
        from app.models.graph import SymbolGraph
        from app.models.manifest import ProjectManifest
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        versions = tmp_path / "migrations" / "versions"
        versions.mkdir(parents=True)
        (versions / "001_a.py").write_text(
            'revision = "001_a"\n'
            "down_revision = None\n"
            "def upgrade() -> None: pass\n"
            "def downgrade() -> None: pass\n"
        )
        (versions / "002_b.py").write_text(
            'revision = "002_b"\n'
            'down_revision = "001_a"\n'
            "def upgrade() -> None: pass\n"
            "def downgrade() -> None: pass\n"
        )

        manifest = ProjectManifest(root_path=tmp_path)
        ctx = AnalysisContext(project_id="t", graph=SymbolGraph(), manifest=manifest)

        result = await AlembicPlugin().extract(ctx)

        config_files = [n for n in result.nodes if n.kind == NodeKind.CONFIG_FILE]
        assert {n.name for n in config_files} == {"001_a", "002_b"}

        by_name = {n.name: n for n in config_files}
        assert by_name["001_a"].properties["down_revision"] is None
        assert by_name["002_b"].properties["down_revision"] == "001_a"

    @pytest.mark.asyncio
    async def test_unparseable_migration_is_warned_and_skipped(
        self, tmp_path: Path
    ):
        """A syntax-error file alongside valid migrations produces a warning
        but does not block extraction of the valid ones."""
        from app.models.context import AnalysisContext
        from app.models.enums import NodeKind
        from app.models.graph import SymbolGraph
        from app.models.manifest import ProjectManifest
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        versions = tmp_path / "migrations" / "versions"
        versions.mkdir(parents=True)
        (versions / "001_good.py").write_text(
            'revision = "001_good"\n'
            "down_revision = None\n"
        )
        (versions / "002_broken.py").write_text("def :::\n")

        manifest = ProjectManifest(root_path=tmp_path)
        ctx = AnalysisContext(project_id="t", graph=SymbolGraph(), manifest=manifest)

        result = await AlembicPlugin().extract(ctx)

        config_files = [n for n in result.nodes if n.kind == NodeKind.CONFIG_FILE]
        assert {n.name for n in config_files} == {"001_good"}
        assert any("002_broken.py" in w for w in result.warnings), result.warnings


class TestAlembicRevisionParsing:
    def test_parse_migration_file_metadata(self, tmp_path: Path):
        from app.stages.plugins.alembic_plugin.migrations import (
            parse_migration_file,
        )

        src = (
            '"""initial\n\nRevision ID: 001_initial\nRevises:\n"""\n'
            "from alembic import op\n"
            "import sqlalchemy as sa\n\n"
            'revision = "001_initial"\n'
            "down_revision = None\n"
            "branch_labels = None\n"
            "depends_on = None\n\n"
            "def upgrade() -> None:\n"
            "    pass\n\n"
            "def downgrade() -> None:\n"
            "    pass\n"
        )
        path = tmp_path / "001_initial.py"
        path.write_text(src)

        info = parse_migration_file(path)

        assert info is not None
        assert info.revision_id == "001_initial"
        assert info.down_revision is None
        assert info.file_path == path

    def test_parse_migration_file_with_down_revision(self, tmp_path: Path):
        from app.stages.plugins.alembic_plugin.migrations import (
            parse_migration_file,
        )

        src = (
            "from alembic import op\n"
            "import sqlalchemy as sa\n\n"
            'revision = "002_add_todo_completed"\n'
            'down_revision = "001_initial"\n'
            "branch_labels = None\n"
            "depends_on = None\n\n"
            "def upgrade() -> None:\n"
            "    pass\n"
        )
        path = tmp_path / "002_add_todo_completed.py"
        path.write_text(src)

        info = parse_migration_file(path)

        assert info is not None
        assert info.revision_id == "002_add_todo_completed"
        assert info.down_revision == "001_initial"

    def test_parse_migration_file_missing_revision_returns_none(
        self, tmp_path: Path
    ):
        from app.stages.plugins.alembic_plugin.migrations import (
            parse_migration_file,
        )

        src = "# a file with no revision constant\nx = 1\n"
        path = tmp_path / "junk.py"
        path.write_text(src)

        assert parse_migration_file(path) is None

    def test_parse_migration_file_syntax_error_returns_none(
        self, tmp_path: Path
    ):
        from app.stages.plugins.alembic_plugin.migrations import (
            parse_migration_file,
        )

        path = tmp_path / "broken.py"
        path.write_text("def :::\n")

        assert parse_migration_file(path) is None
