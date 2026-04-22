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
from app.stages.treesitter.extractors import register_extractor
from app.stages.treesitter.extractors.python import PythonExtractor
from app.stages.treesitter.parser import parse_with_treesitter

FIXTURES = Path(__file__).parent.parent / "fixtures"
DJANGO_BLOG = FIXTURES / "django-blog"
FASTAPI_TODO = FIXTURES / "fastapi-todo"


@pytest.fixture(autouse=True)
def _ensure_python_extractor():
    register_extractor("python", PythonExtractor())
    yield


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
        assert (
            middleware[0] == "django.middleware.security.SecurityMiddleware"
        ), middleware

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
            e.target_fqn for e in result.edges
            if e.kind == EdgeKind.CONTAINS and e.source_fqn == cf_fqn
        }
        assert len(contained) == 6, contained
