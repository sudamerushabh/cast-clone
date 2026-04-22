"""M1 acceptance tests: Python pipeline Stages 1-3 against realistic fixtures.

Stage 4 (SCIP) is exercised in `test_python_m1_scip.py` behind the
`scip_python` marker because it requires `scip-python` on PATH.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.stages.treesitter.extractors import register_extractor
from app.stages.treesitter.extractors.python import PythonExtractor

FIXTURES = Path(__file__).parent.parent / "fixtures"
FASTAPI_TODO = FIXTURES / "fastapi-todo"
DJANGO_BLOG = FIXTURES / "django-blog"
FLASK_INVENTORY = FIXTURES / "flask-inventory"


@pytest.fixture(autouse=True)
def _ensure_python_extractor():
    register_extractor("python", PythonExtractor())
    yield


@pytest.mark.integration
class TestFastAPITodoStages1To3:
    def test_discovery_detects_python_and_fastapi(self):
        from app.stages.discovery import discover_project

        manifest = discover_project(FASTAPI_TODO)

        lang_names = [lang.name for lang in manifest.detected_languages]
        assert "python" in lang_names

        fw_names = [fw.name for fw in manifest.detected_frameworks]
        assert "fastapi" in fw_names

    @pytest.mark.asyncio
    async def test_dependencies_parses_pyproject(self):
        from app.stages.dependencies import resolve_dependencies
        from app.stages.discovery import discover_project

        manifest = discover_project(FASTAPI_TODO)
        env = await resolve_dependencies(manifest)

        python_deps = env.dependencies.get("python", [])
        dep_names = [d.name for d in python_deps]
        assert "fastapi" in dep_names
        assert "sqlalchemy" in dep_names
        assert "pydantic" in dep_names

    @pytest.mark.asyncio
    async def test_treesitter_extracts_endpoints_and_models(self):
        from app.stages.discovery import discover_project
        from app.stages.treesitter.parser import parse_with_treesitter

        manifest = discover_project(FASTAPI_TODO)
        graph = await parse_with_treesitter(manifest)

        fqns = list(graph.nodes.keys())

        # Pydantic request models
        assert any(f.endswith("UserCreate") for f in fqns), (
            "UserCreate class not extracted"
        )
        assert any(f.endswith("TodoCreate") for f in fqns), (
            "TodoCreate class not extracted"
        )

        # Route handler function (fastapi-todo lays code under app/routes/users.py
        # so the FQN is app.routes.users.create_user).
        assert any(f.endswith("routes.users.create_user") for f in fqns), (
            "create_user route handler not extracted"
        )


@pytest.mark.integration
class TestDjangoBlogStages1To3:
    def test_discovery_detects_django(self):
        from app.stages.discovery import discover_project

        manifest = discover_project(DJANGO_BLOG)

        fw_names = [fw.name for fw in manifest.detected_frameworks]
        assert "django" in fw_names

    @pytest.mark.asyncio
    async def test_treesitter_extracts_models_and_tasks(self):
        from app.stages.discovery import discover_project
        from app.stages.treesitter.parser import parse_with_treesitter

        manifest = discover_project(DJANGO_BLOG)
        graph = await parse_with_treesitter(manifest)

        fqns = list(graph.nodes.keys())
        assert any(f.endswith("posts.models.Post") for f in fqns), (
            "Post model not extracted"
        )
        assert any(f.endswith("posts.models.Author") for f in fqns), (
            "Author model not extracted"
        )
        assert any(f.endswith("posts.tasks.notify_post_published") for f in fqns), (
            "notify_post_published task not extracted"
        )


@pytest.mark.integration
class TestFlaskInventoryStages1To3:
    def test_discovery_detects_python(self):
        from app.stages.discovery import discover_project

        manifest = discover_project(FLASK_INVENTORY)
        assert "python" in [lang.name for lang in manifest.detected_languages]

    @pytest.mark.asyncio
    async def test_treesitter_extracts_models_and_resources(self):
        from app.stages.discovery import discover_project
        from app.stages.treesitter.parser import parse_with_treesitter

        manifest = discover_project(FLASK_INVENTORY)
        graph = await parse_with_treesitter(manifest)

        fqns = list(graph.nodes.keys())
        # flask-inventory lays code under app/models.py and app/resources.py,
        # so FQNs are app.models.Item, app.resources.ItemResource.
        assert any(f.endswith("app.models.Item") for f in fqns), (
            "Item model not extracted"
        )
        assert any(f.endswith("app.models.Warehouse") for f in fqns), (
            "Warehouse model not extracted"
        )
        assert any(f.endswith("app.resources.ItemResource") for f in fqns), (
            "ItemResource not extracted"
        )
