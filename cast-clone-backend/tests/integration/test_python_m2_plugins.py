"""M2 acceptance tests: Django settings structured parsing, SQLAlchemy 2.0
async recognition, Alembic migration chain — against M1 fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.context import AnalysisContext
from app.models.enums import EdgeKind, NodeKind
from app.stages.discovery import discover_project
from app.stages.plugins.django.settings import DjangoSettingsPlugin
from app.stages.treesitter.parser import parse_with_treesitter

FIXTURES = Path(__file__).parent.parent / "fixtures"
DJANGO_BLOG = FIXTURES / "django-blog"
FASTAPI_TODO = FIXTURES / "fastapi-todo"


@pytest.mark.integration
class TestDjangoSettingsM2:
    @pytest.mark.asyncio
    async def test_django_blog_settings_structured(self):
        manifest = discover_project(DJANGO_BLOG)
        graph = await parse_with_treesitter(manifest)
        ctx = AnalysisContext(
            project_id="m2-django",
            graph=graph,
            manifest=manifest,
        )

        result = await DjangoSettingsPlugin().extract(ctx)

        entries = {n.name: n for n in result.nodes if n.kind == NodeKind.CONFIG_ENTRY}

        # INSTALLED_APPS: structured list contains both django apps and local apps.
        apps = entries["INSTALLED_APPS"].properties.get("apps", [])
        assert "rest_framework" in apps, apps
        assert "posts" in apps, apps

        # DATABASES: engine pinned to postgres; name/host/port preserved.
        db_props = entries["DATABASES"].properties
        assert db_props.get("default_engine") == "django.db.backends.postgresql"
        assert db_props.get("default_name") == "blog"
        assert db_props.get("default_host") == "localhost"
        assert db_props.get("default_port") == "5432"

        # MIDDLEWARE: contains the security middleware at position 0.
        middleware = entries["MIDDLEWARE"].properties.get("middleware", [])
        assert middleware, "MIDDLEWARE list is empty"
        assert middleware[0] == "django.middleware.security.SecurityMiddleware", (
            middleware
        )

        # Single-string normalizations
        assert entries["AUTH_USER_MODEL"].properties.get("model") == "auth.User"
        assert entries["ROOT_URLCONF"].properties.get("urlconf") == "blog_project.urls"
        assert (
            entries["DEFAULT_AUTO_FIELD"].properties.get("field_class")
            == "django.db.models.BigAutoField"
        )

        # The CONFIG_FILE parent exists and CONTAINS all six entries.
        config_files = [n for n in result.nodes if n.kind == NodeKind.CONFIG_FILE]
        assert len(config_files) == 1
        cf_fqn = config_files[0].fqn
        contained = {
            e.target_fqn
            for e in result.edges
            if e.kind == EdgeKind.CONTAINS and e.source_fqn == cf_fqn
        }
        assert len(contained) == 6, contained


@pytest.mark.integration
class TestSQLAlchemy20AsyncM2:
    @pytest.mark.asyncio
    async def test_fastapi_todo_tables_and_columns_extracted(self):
        from app.stages.plugins.sqlalchemy_plugin.models import SQLAlchemyPlugin

        manifest = discover_project(FASTAPI_TODO)
        graph = await parse_with_treesitter(manifest)
        ctx = AnalysisContext(
            project_id="m2-sqla",
            graph=graph,
            manifest=manifest,
        )

        result = await SQLAlchemyPlugin().extract(ctx)

        tables = {n.name for n in result.nodes if n.kind == NodeKind.TABLE}
        assert "users" in tables, tables
        assert "todos" in tables, tables

        columns = {
            (n.properties.get("table"), n.name)
            for n in result.nodes
            if n.kind == NodeKind.COLUMN
        }
        for expected in [
            ("users", "id"),
            ("users", "email"),
            ("todos", "id"),
            ("todos", "owner_id"),
        ]:
            assert expected in columns, f"missing {expected}; got {columns}"

        refs = {
            (e.source_fqn, e.target_fqn)
            for e in result.edges
            if e.kind == EdgeKind.REFERENCES
        }
        assert ("table:todos.owner_id", "table:users.id") in refs, refs


@pytest.mark.integration
class TestAlembicMigrationsM2:
    @pytest.mark.asyncio
    async def test_fastapi_todo_migrations_form_chain(self):
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        manifest = discover_project(FASTAPI_TODO)
        graph = await parse_with_treesitter(manifest)
        ctx = AnalysisContext(
            project_id="m2-alembic",
            graph=graph,
            manifest=manifest,
        )

        result = await AlembicPlugin().extract(ctx)

        config_files = {
            n.name: n for n in result.nodes if n.kind == NodeKind.CONFIG_FILE
        }
        assert set(config_files.keys()) == {"001_initial", "002_add_todo_completed"}

        # 002 points back at 001 via INHERITS.
        inherits_edges = [
            (e.source_fqn, e.target_fqn)
            for e in result.edges
            if e.kind == EdgeKind.INHERITS
        ]
        assert inherits_edges == [
            ("alembic:002_add_todo_completed", "alembic:001_initial"),
        ]

        # 001 creates users + todos; 002 adds completed column.
        ops_001 = config_files["001_initial"].properties["upgrade_ops"]
        created_tables = sorted(
            op["target"] for op in ops_001 if op["op"] == "create_table"
        )
        assert created_tables == ["todos", "users"]

        ops_002 = config_files["002_add_todo_completed"].properties["upgrade_ops"]
        assert ops_002 == [
            {"op": "add_column", "target": "todos", "column": "completed"},
        ]
