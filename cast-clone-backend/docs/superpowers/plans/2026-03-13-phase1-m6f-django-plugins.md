# M6e: Django Plugins Implementation Plan (Settings, URLs, ORM, DRF)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement four Django framework plugins that extract invisible connections — configuration parsing (`INSTALLED_APPS`, `DATABASES`, `MIDDLEWARE`), URL routing resolution (`path()`, `include()`), ORM model-to-table mapping (`ForeignKey`, `ManyToManyField`), and Django REST Framework ViewSet→Model chain resolution. These form a dependency chain: `django-settings` → `django-urls` + `django-orm` → `django-drf`.

**Architecture:** Each plugin extends `FrameworkPlugin` (from M6a). Plugins scan `context.graph` for Python modules/classes/functions with Django-specific patterns (decorators, base classes, field assignments stored in `node.properties` by the Python tree-sitter extractor M4d). Django ORM is the Python equivalent of Hibernate/JPA. Django URLs is the Python equivalent of Spring Web. DRF combines both patterns. The `django-settings` plugin stores extracted config in `context` properties for downstream plugins to consume.

**Tech Stack:** Python 3.12, dataclasses, re, pytest+pytest-asyncio

**Dependencies:** M1 (AnalysisContext, SymbolGraph, GraphNode, GraphEdge, enums), M6a (FrameworkPlugin, PluginResult, PluginDetectionResult, LayerRules, LayerRule), M4d (Python tree-sitter extractor), M6d (SQLAlchemy plugin — shares Table/Column FQN conventions)

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       └── plugins/
│           └── django/
│               ├── __init__.py              # CREATE — re-export plugin classes
│               ├── settings.py              # CREATE — DjangoSettingsPlugin
│               ├── urls.py                  # CREATE — DjangoURLsPlugin
│               ├── orm.py                   # CREATE — DjangoORMPlugin
│               └── drf.py                   # CREATE — DjangoDRFPlugin
├── tests/
│   └── unit/
│       ├── test_django_settings_plugin.py   # CREATE
│       ├── test_django_urls_plugin.py       # CREATE
│       ├── test_django_orm_plugin.py        # CREATE
│       └── test_django_drf_plugin.py        # CREATE
```

---

## Shared Test Helpers — Python Node Conventions for Django

All test files build `AnalysisContext` objects pre-populated with Python nodes. The conventions match the Python tree-sitter extractor (M4d) output:

**Django-specific node patterns:**
- **Settings module**: `MODULE` node at FQN like `myproject.settings`. Contains `FIELD` children for `INSTALLED_APPS`, `DATABASES`, etc. Field values are stored in `properties["value"]` as raw source text.
- **URLs module**: `MODULE` node at FQN like `myapp.urls`. Contains `FIELD` node for `urlpatterns` list assignment. Individual `path()` and `include()` calls appear as `CALLS` edges from the module.
- **Model classes**: `CLASS` nodes with `INHERITS` edge to a `models.Model` parent. `FIELD` children represent model fields with `properties["value"]` containing the call expression (e.g., `models.ForeignKey(User, on_delete=models.CASCADE)`).
- **DRF ViewSets**: `CLASS` nodes with `INHERITS` edge to `ModelViewSet`/`GenericAPIView`. `FIELD` children for `serializer_class`, `queryset`, `permission_classes`.

**Django table naming convention:** `{app_label}_{model_name_lower}`. The app label comes from the module path (e.g., class at `myapp.models.User` → app label `myapp` → table `myapp_user`). Can be overridden by `class Meta: db_table = "custom"`.

---

## Task 1: Django Settings Plugin

**Files:**
- Create: `app/stages/plugins/django/__init__.py`
- Create: `app/stages/plugins/django/settings.py`
- Test: `tests/unit/test_django_settings_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_django_settings_plugin.py
"""Tests for the Django Settings plugin — INSTALLED_APPS, DATABASES, MIDDLEWARE, ROOT_URLCONF."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult, PluginResult
from app.stages.plugins.django.settings import DjangoSettingsPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_django() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="django",
                language="python",
                confidence=Confidence.HIGH,
                evidence=["requirements.txt contains Django"],
            ),
        ],
    )
    return ctx


def _add_module(graph: SymbolGraph, fqn: str, name: str) -> GraphNode:
    node = GraphNode(fqn=fqn, name=name, kind=NodeKind.MODULE, language="python")
    graph.add_node(node)
    return node


def _add_field(
    graph: SymbolGraph,
    parent_fqn: str,
    field_name: str,
    value: str = "",
) -> GraphNode:
    fqn = f"{parent_fqn}.{field_name}"
    node = GraphNode(
        fqn=fqn,
        name=field_name,
        kind=NodeKind.FIELD,
        language="python",
        properties={"value": value},
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=parent_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


def _make_settings_module(graph: SymbolGraph) -> None:
    """Create a typical Django settings module with common settings."""
    _add_module(graph, "myproject.settings", "settings")
    _add_field(
        graph, "myproject.settings", "INSTALLED_APPS",
        value='["django.contrib.admin", "django.contrib.auth", "myapp", "rest_framework"]',
    )
    _add_field(
        graph, "myproject.settings", "ROOT_URLCONF",
        value='"myproject.urls"',
    )
    _add_field(
        graph, "myproject.settings", "DATABASES",
        value='{"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "mydb"}}',
    )
    _add_field(
        graph, "myproject.settings", "MIDDLEWARE",
        value='["django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware"]',
    )


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestDjangoSettingsDetection:
    def test_detect_high_when_django_in_frameworks(self):
        plugin = DjangoSettingsPlugin()
        ctx = _make_context_with_django()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_django(self):
        plugin = DjangoSettingsPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False

    def test_detect_medium_when_installed_apps_found(self):
        """If no django in frameworks but INSTALLED_APPS field exists."""
        plugin = DjangoSettingsPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        _add_module(ctx.graph, "myproject.settings", "settings")
        _add_field(ctx.graph, "myproject.settings", "INSTALLED_APPS", value='["myapp"]')
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM


# ---------------------------------------------------------------------------
# Settings extraction tests
# ---------------------------------------------------------------------------

class TestDjangoSettingsExtraction:
    @pytest.mark.asyncio
    async def test_creates_config_file_node(self):
        """Settings module -> CONFIG_FILE node."""
        plugin = DjangoSettingsPlugin()
        ctx = _make_context_with_django()
        _make_settings_module(ctx.graph)

        result = await plugin.extract(ctx)
        config_files = [n for n in result.nodes if n.kind == NodeKind.CONFIG_FILE]
        assert len(config_files) >= 1
        assert any("settings" in n.name for n in config_files)

    @pytest.mark.asyncio
    async def test_extracts_installed_apps(self):
        """INSTALLED_APPS -> CONFIG_ENTRY nodes for each app."""
        plugin = DjangoSettingsPlugin()
        ctx = _make_context_with_django()
        _make_settings_module(ctx.graph)

        result = await plugin.extract(ctx)
        config_entries = [n for n in result.nodes if n.kind == NodeKind.CONFIG_ENTRY]
        entry_names = {n.name for n in config_entries}
        assert "INSTALLED_APPS" in entry_names

        # The extracted value should contain the app list
        apps_entry = [n for n in config_entries if n.name == "INSTALLED_APPS"][0]
        assert "myapp" in apps_entry.properties.get("value", "")

    @pytest.mark.asyncio
    async def test_extracts_root_urlconf(self):
        """ROOT_URLCONF -> CONFIG_ENTRY with URL module path."""
        plugin = DjangoSettingsPlugin()
        ctx = _make_context_with_django()
        _make_settings_module(ctx.graph)

        result = await plugin.extract(ctx)
        config_entries = [n for n in result.nodes if n.kind == NodeKind.CONFIG_ENTRY]
        urlconf = [n for n in config_entries if n.name == "ROOT_URLCONF"]
        assert len(urlconf) == 1
        assert "myproject.urls" in urlconf[0].properties.get("value", "")

    @pytest.mark.asyncio
    async def test_extracts_databases(self):
        """DATABASES -> CONFIG_ENTRY with database config."""
        plugin = DjangoSettingsPlugin()
        ctx = _make_context_with_django()
        _make_settings_module(ctx.graph)

        result = await plugin.extract(ctx)
        config_entries = [n for n in result.nodes if n.kind == NodeKind.CONFIG_ENTRY]
        db_entry = [n for n in config_entries if n.name == "DATABASES"]
        assert len(db_entry) == 1

    @pytest.mark.asyncio
    async def test_extracts_middleware(self):
        """MIDDLEWARE -> CONFIG_ENTRY with middleware list."""
        plugin = DjangoSettingsPlugin()
        ctx = _make_context_with_django()
        _make_settings_module(ctx.graph)

        result = await plugin.extract(ctx)
        config_entries = [n for n in result.nodes if n.kind == NodeKind.CONFIG_ENTRY]
        mw_entry = [n for n in config_entries if n.name == "MIDDLEWARE"]
        assert len(mw_entry) == 1

    @pytest.mark.asyncio
    async def test_contains_edges_from_file_to_entries(self):
        """CONFIG_FILE -[:CONTAINS]-> CONFIG_ENTRY edges exist."""
        plugin = DjangoSettingsPlugin()
        ctx = _make_context_with_django()
        _make_settings_module(ctx.graph)

        result = await plugin.extract(ctx)
        contains_edges = [e for e in result.edges if e.kind == EdgeKind.CONTAINS]
        assert len(contains_edges) >= 4  # INSTALLED_APPS, ROOT_URLCONF, DATABASES, MIDDLEWARE


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestDjangoSettingsMetadata:
    def test_plugin_name(self):
        assert DjangoSettingsPlugin().name == "django-settings"

    def test_supported_languages(self):
        assert DjangoSettingsPlugin().supported_languages == {"python"}

    def test_depends_on_empty(self):
        assert DjangoSettingsPlugin().depends_on == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_django_settings_plugin.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Create `__init__.py`**

```python
# app/stages/plugins/django/__init__.py
"""Django framework plugins — Settings, URLs, ORM, DRF."""

from app.stages.plugins.django.settings import DjangoSettingsPlugin

# These will be added as each plugin is implemented:
# from app.stages.plugins.django.urls import DjangoURLsPlugin
# from app.stages.plugins.django.orm import DjangoORMPlugin
# from app.stages.plugins.django.drf import DjangoDRFPlugin

__all__ = ["DjangoSettingsPlugin"]
```

- [ ] **Step 4: Implement `django/settings.py`**

```python
# app/stages/plugins/django/settings.py
"""Django Settings plugin.

Scans for Django settings modules (files containing INSTALLED_APPS,
DATABASES, MIDDLEWARE, ROOT_URLCONF) and extracts configuration entries
as CONFIG_FILE and CONFIG_ENTRY nodes. Downstream plugins (django-urls,
django-orm, django-drf) read these entries to resolve app labels,
URL root, and database configuration.

Produces:
- CONFIG_FILE nodes: one per settings module
- CONFIG_ENTRY nodes: one per key setting (INSTALLED_APPS, ROOT_URLCONF, etc.)
- CONTAINS edges: (:CONFIG_FILE)-[:CONTAINS]->(:CONFIG_ENTRY)
"""

from __future__ import annotations

import structlog

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.context import AnalysisContext
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()

# Settings keys we care about
_DJANGO_SETTINGS_KEYS = frozenset({
    "INSTALLED_APPS", "ROOT_URLCONF", "DATABASES", "MIDDLEWARE",
    "DEFAULT_AUTO_FIELD", "AUTH_USER_MODEL",
})


class DjangoSettingsPlugin(FrameworkPlugin):
    name = "django-settings"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest:
            for fw in context.manifest.detected_frameworks:
                if "django" in fw.name.lower() and "rest" not in fw.name.lower():
                    return PluginDetectionResult(
                        confidence=Confidence.HIGH,
                        reason=f"Framework '{fw.name}' detected in manifest",
                    )

        # Fallback: look for INSTALLED_APPS field in graph
        for node in context.graph.nodes.values():
            if (
                node.kind == NodeKind.FIELD
                and node.language == "python"
                and node.name == "INSTALLED_APPS"
            ):
                return PluginDetectionResult(
                    confidence=Confidence.MEDIUM,
                    reason="INSTALLED_APPS field found in graph",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("django_settings_extract_start")

        graph = context.graph
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []

        # Find settings modules: modules containing INSTALLED_APPS field
        settings_modules = self._find_settings_modules(graph)
        log.info("django_settings_modules_found", count=len(settings_modules))

        for module_fqn in settings_modules:
            # Create CONFIG_FILE node
            config_file_fqn = f"config:{module_fqn}"
            config_file = GraphNode(
                fqn=config_file_fqn,
                name=module_fqn.split(".")[-1],
                kind=NodeKind.CONFIG_FILE,
                language="python",
                properties={"module_fqn": module_fqn},
            )
            nodes.append(config_file)

            # Extract settings entries
            for field_fqn, field_node in self._get_settings_fields(graph, module_fqn):
                entry_fqn = f"config:{module_fqn}.{field_node.name}"
                entry = GraphNode(
                    fqn=entry_fqn,
                    name=field_node.name,
                    kind=NodeKind.CONFIG_ENTRY,
                    language="python",
                    properties={
                        "value": field_node.properties.get("value", ""),
                        "setting_key": field_node.name,
                    },
                )
                nodes.append(entry)
                edges.append(GraphEdge(
                    source_fqn=config_file_fqn,
                    target_fqn=entry_fqn,
                    kind=EdgeKind.CONTAINS,
                    confidence=Confidence.HIGH,
                    evidence="django-settings",
                ))

        log.info("django_settings_extract_complete", entries=len(nodes) - len(settings_modules))

        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_settings_modules(self, graph: SymbolGraph) -> list[str]:
        """Find module FQNs that contain INSTALLED_APPS."""
        modules: set[str] = set()
        for node in graph.nodes.values():
            if node.kind != NodeKind.FIELD or node.name != "INSTALLED_APPS":
                continue
            # Find parent module via CONTAINS edge
            for edge in graph.edges:
                if edge.target_fqn == node.fqn and edge.kind == EdgeKind.CONTAINS:
                    parent = graph.nodes.get(edge.source_fqn)
                    if parent and parent.kind == NodeKind.MODULE:
                        modules.add(edge.source_fqn)
                    break
        return sorted(modules)

    def _get_settings_fields(
        self, graph: SymbolGraph, module_fqn: str
    ) -> list[tuple[str, GraphNode]]:
        """Get Django settings fields from a module."""
        fields: list[tuple[str, GraphNode]] = []
        for edge in graph.edges:
            if edge.source_fqn != module_fqn or edge.kind != EdgeKind.CONTAINS:
                continue
            field_node = graph.nodes.get(edge.target_fqn)
            if (
                field_node
                and field_node.kind == NodeKind.FIELD
                and field_node.name in _DJANGO_SETTINGS_KEYS
            ):
                fields.append((edge.target_fqn, field_node))
        return fields
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_django_settings_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/django/ tests/unit/test_django_settings_plugin.py && git commit -m "feat(plugins): add Django Settings plugin — config extraction for INSTALLED_APPS, ROOT_URLCONF, DATABASES, MIDDLEWARE"
```

---

## Task 2: Django URLs Plugin

**Files:**
- Create: `app/stages/plugins/django/urls.py`
- Test: `tests/unit/test_django_urls_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_django_urls_plugin.py
"""Tests for the Django URLs plugin — path(), re_path(), include() resolution."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext, EntryPoint
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult, PluginResult
from app.stages.plugins.django.urls import DjangoURLsPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_django() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(
                name="django",
                language="python",
                confidence=Confidence.HIGH,
                evidence=["requirements.txt contains Django"],
            ),
        ],
    )
    return ctx


def _add_module(graph: SymbolGraph, fqn: str, name: str) -> GraphNode:
    node = GraphNode(fqn=fqn, name=name, kind=NodeKind.MODULE, language="python")
    graph.add_node(node)
    return node


def _add_class(
    graph: SymbolGraph, fqn: str, name: str, bases: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn, name=name, kind=NodeKind.CLASS, language="python",
        properties={"annotations": []},
    )
    graph.add_node(node)
    for base in (bases or []):
        graph.add_edge(GraphEdge(
            source_fqn=fqn, target_fqn=base, kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW, evidence="tree-sitter",
        ))
    return node


def _add_function(
    graph: SymbolGraph, parent_fqn: str, name: str,
    annotations: list[str] | None = None,
) -> GraphNode:
    fqn = f"{parent_fqn}.{name}"
    node = GraphNode(
        fqn=fqn, name=name, kind=NodeKind.FUNCTION, language="python",
        properties={"annotations": annotations or []},
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=parent_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


def _add_field(
    graph: SymbolGraph, parent_fqn: str, name: str, value: str = "",
) -> GraphNode:
    fqn = f"{parent_fqn}.{name}"
    node = GraphNode(
        fqn=fqn, name=name, kind=NodeKind.FIELD, language="python",
        properties={"value": value},
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=parent_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestDjangoURLsDetection:
    def test_detect_high_when_django_present(self):
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_django(self):
        plugin = DjangoURLsPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# URL extraction tests
# ---------------------------------------------------------------------------

class TestDjangoURLExtraction:
    @pytest.mark.asyncio
    async def test_simple_path_creates_endpoint(self):
        """path("users/", views.user_list) -> APIEndpoint node."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph, "myapp.urls", "urlpatterns",
            value='[path("users/", views.user_list, name="user-list")]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_list")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert endpoint_nodes[0].properties["path"] == "/users/"

    @pytest.mark.asyncio
    async def test_path_with_parameter(self):
        """path("users/<int:pk>/", ...) -> endpoint with parameter in path."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph, "myapp.urls", "urlpatterns",
            value='[path("users/<int:pk>/", views.user_detail)]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_detail")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1
        assert "<int:pk>" in endpoint_nodes[0].properties["path"]

    @pytest.mark.asyncio
    async def test_handles_edge_to_view(self):
        """View function referenced in path() -> HANDLES edge."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph, "myapp.urls", "urlpatterns",
            value='[path("users/", views.user_list)]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_list")

        result = await plugin.extract(ctx)
        handles_edges = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        assert len(handles_edges) == 1

    @pytest.mark.asyncio
    async def test_class_based_view(self):
        """path("users/", UserListView.as_view()) -> endpoint + HANDLES to class."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph, "myapp.urls", "urlpatterns",
            value='[path("users/", UserListView.as_view())]',
        )
        _add_class(ctx.graph, "myapp.views.UserListView", "UserListView")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) == 1

    @pytest.mark.asyncio
    async def test_include_resolves_prefix(self):
        """path("api/", include("myapp.urls")) -> prefixed endpoints."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()

        # Root urls with include
        _add_module(ctx.graph, "myproject.urls", "urls")
        _add_field(
            ctx.graph, "myproject.urls", "urlpatterns",
            value='[path("api/", include("myapp.urls"))]',
        )

        # App urls
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph, "myapp.urls", "urlpatterns",
            value='[path("users/", views.user_list)]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_list")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoint_nodes) >= 1
        # The full path should combine the prefix
        paths = [n.properties["path"] for n in endpoint_nodes]
        assert any("/api/users/" in p for p in paths)

    @pytest.mark.asyncio
    async def test_entry_points_created(self):
        """Each URL endpoint should produce an entry point."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph, "myapp.urls", "urlpatterns",
            value='[path("users/", views.user_list)]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_list")

        result = await plugin.extract(ctx)
        assert len(result.entry_points) >= 1
        assert result.entry_points[0].kind == "http_endpoint"

    @pytest.mark.asyncio
    async def test_view_layer_assignment(self):
        """View functions/classes -> Presentation layer."""
        plugin = DjangoURLsPlugin()
        ctx = _make_context_with_django()
        _add_module(ctx.graph, "myapp.urls", "urls")
        _add_field(
            ctx.graph, "myapp.urls", "urlpatterns",
            value='[path("users/", views.user_list)]',
        )
        _add_module(ctx.graph, "myapp.views", "views")
        _add_function(ctx.graph, "myapp.views", "user_list")

        result = await plugin.extract(ctx)
        # The view function should be classified as Presentation
        assert "Presentation" in result.layer_assignments.values()


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestDjangoURLsMetadata:
    def test_plugin_name(self):
        assert DjangoURLsPlugin().name == "django-urls"

    def test_depends_on(self):
        assert DjangoURLsPlugin().depends_on == ["django-settings"]

    def test_supported_languages(self):
        assert DjangoURLsPlugin().supported_languages == {"python"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_django_urls_plugin.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `django/urls.py`**

The implementation should:
1. Find modules containing `urlpatterns` field assignments
2. Parse the `urlpatterns` value string to extract `path()` and `include()` calls using regex
3. For `path()` calls: extract the URL pattern and view reference, create `APIEndpoint` node + `HANDLES` edge
4. For `include()` calls: find the referenced module, extract its urlpatterns, prepend the prefix
5. Resolve view references to existing graph nodes (function views and class-based views via `.as_view()`)
6. Create entry points for each endpoint
7. Assign Presentation layer to view functions/classes

Key regex patterns:
```python
_PATH_RE = re.compile(r'path\(\s*["\']([^"\']*)["\'],\s*([^,\)]+)')
_INCLUDE_RE = re.compile(r'include\(\s*["\']([^"\']+)["\']')
_AS_VIEW_RE = re.compile(r'(\w+)\.as_view\(\)')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_django_urls_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Update `__init__.py` and commit**

```python
# Update app/stages/plugins/django/__init__.py to add:
from app.stages.plugins.django.urls import DjangoURLsPlugin
```

```bash
cd cast-clone-backend && git add app/stages/plugins/django/ tests/unit/test_django_urls_plugin.py && git commit -m "feat(plugins): add Django URLs plugin — path/include resolution, view layer classification"
```

---

## Task 3: Django ORM Plugin

**Files:**
- Create: `app/stages/plugins/django/orm.py`
- Test: `tests/unit/test_django_orm_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_django_orm_plugin.py
"""Tests for the Django ORM plugin — Model-to-table, ForeignKey, ManyToManyField."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult, PluginResult
from app.stages.plugins.django.orm import DjangoORMPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_django() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(name="django", language="python",
                              confidence=Confidence.HIGH, evidence=["Django detected"]),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph, fqn: str, name: str, bases: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn, name=name, kind=NodeKind.CLASS, language="python",
        properties={"annotations": []},
    )
    graph.add_node(node)
    for base in (bases or []):
        graph.add_edge(GraphEdge(
            source_fqn=fqn, target_fqn=base, kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW, evidence="tree-sitter",
        ))
    return node


def _add_field(
    graph: SymbolGraph, class_fqn: str, name: str, value: str = "",
) -> GraphNode:
    fqn = f"{class_fqn}.{name}"
    node = GraphNode(
        fqn=fqn, name=name, kind=NodeKind.FIELD, language="python",
        properties={"value": value},
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


def _add_django_model(
    graph: SymbolGraph, fqn: str, name: str, fields: dict[str, str],
    db_table: str | None = None,
) -> GraphNode:
    """Convenience: add a Django model class with fields."""
    node = _add_class(graph, fqn, name, bases=["django.db.models.Model"])
    for field_name, field_value in fields.items():
        _add_field(graph, fqn, field_name, value=field_value)
    if db_table:
        # Simulate class Meta: db_table = "custom"
        _add_field(graph, fqn, "_meta_db_table", value=f'"{db_table}"')
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestDjangoORMDetection:
    def test_detect_high_when_django_present(self):
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_medium_when_models_found(self):
        plugin = DjangoORMPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        _add_class(ctx.graph, "myapp.models.User", "User",
                   bases=["django.db.models.Model"])
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM

    def test_detect_none_without_django(self):
        plugin = DjangoORMPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False


# ---------------------------------------------------------------------------
# Model-to-table mapping tests
# ---------------------------------------------------------------------------

class TestDjangoORMEntityMapping:
    @pytest.mark.asyncio
    async def test_model_creates_table_node(self):
        """Django model -> Table node with conventional name (app_model)."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(ctx.graph, "myapp.models.User", "User", {
            "id": "models.AutoField(primary_key=True)",
            "name": "models.CharField(max_length=100)",
            "email": "models.EmailField(unique=True)",
        })

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "myapp_user"

        maps_to = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
        assert len(maps_to) == 1
        assert maps_to[0].properties.get("orm") == "django"

    @pytest.mark.asyncio
    async def test_custom_db_table_override(self):
        """Model with Meta.db_table override uses custom table name."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(
            ctx.graph, "myapp.models.User", "User",
            {"id": "models.AutoField(primary_key=True)"},
            db_table="custom_users",
        )

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "custom_users"

    @pytest.mark.asyncio
    async def test_columns_from_model_fields(self):
        """Model fields -> Column nodes + HAS_COLUMN edges."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(ctx.graph, "myapp.models.User", "User", {
            "id": "models.AutoField(primary_key=True)",
            "name": "models.CharField(max_length=100)",
        })

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        names = {n.name for n in column_nodes}
        assert "id" in names
        assert "name" in names

    @pytest.mark.asyncio
    async def test_primary_key_detected(self):
        """primary_key=True -> Column with is_primary_key property."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(ctx.graph, "myapp.models.User", "User", {
            "id": "models.AutoField(primary_key=True)",
        })

        result = await plugin.extract(ctx)
        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        pk_cols = [n for n in column_nodes if n.properties.get("is_primary_key")]
        assert len(pk_cols) == 1
        assert pk_cols[0].name == "id"


# ---------------------------------------------------------------------------
# Relationship tests
# ---------------------------------------------------------------------------

class TestDjangoORMRelationships:
    @pytest.mark.asyncio
    async def test_foreign_key_creates_references_edge(self):
        """ForeignKey(User) -> REFERENCES edge + implicit _id column."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(ctx.graph, "myapp.models.User", "User", {
            "id": "models.AutoField(primary_key=True)",
        })
        _add_django_model(ctx.graph, "myapp.models.Post", "Post", {
            "id": "models.AutoField(primary_key=True)",
            "author": "models.ForeignKey(User, on_delete=models.CASCADE)",
        })

        result = await plugin.extract(ctx)
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1
        # Django adds _id suffix: author -> author_id column
        assert "author_id" in ref_edges[0].source_fqn

    @pytest.mark.asyncio
    async def test_many_to_many_creates_junction_table(self):
        """ManyToManyField -> junction table with FK edges."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(ctx.graph, "myapp.models.Tag", "Tag", {
            "id": "models.AutoField(primary_key=True)",
            "name": "models.CharField(max_length=50)",
        })
        _add_django_model(ctx.graph, "myapp.models.Post", "Post", {
            "id": "models.AutoField(primary_key=True)",
            "tags": "models.ManyToManyField(Tag)",
        })

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        table_names = {n.name for n in table_nodes}
        # Should have the junction table
        assert any("post" in t and "tag" in t for t in table_names)

    @pytest.mark.asyncio
    async def test_one_to_one_creates_references_edge(self):
        """OneToOneField(User) -> REFERENCES edge (like FK but unique)."""
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(ctx.graph, "myapp.models.User", "User", {
            "id": "models.AutoField(primary_key=True)",
        })
        _add_django_model(ctx.graph, "myapp.models.Profile", "Profile", {
            "id": "models.AutoField(primary_key=True)",
            "user": "models.OneToOneField(User, on_delete=models.CASCADE)",
        })

        result = await plugin.extract(ctx)
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1


# ---------------------------------------------------------------------------
# Layer classification tests
# ---------------------------------------------------------------------------

class TestDjangoORMLayerClassification:
    @pytest.mark.asyncio
    async def test_model_is_data_access(self):
        plugin = DjangoORMPlugin()
        ctx = _make_context_with_django()
        _add_django_model(ctx.graph, "myapp.models.User", "User", {
            "id": "models.AutoField(primary_key=True)",
        })

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("myapp.models.User") == "Data Access"


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestDjangoORMMetadata:
    def test_plugin_name(self):
        assert DjangoORMPlugin().name == "django-orm"

    def test_depends_on(self):
        assert DjangoORMPlugin().depends_on == ["django-settings"]

    def test_supported_languages(self):
        assert DjangoORMPlugin().supported_languages == {"python"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_django_orm_plugin.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `django/orm.py`**

The implementation should:
1. Find classes inheriting from `models.Model` (via `INHERITS` edges)
2. Derive table name: custom `_meta_db_table` field or convention `{app_label}_{model_lower}`
3. Extract fields: scan `FIELD` children for `models.CharField(...)`, `models.ForeignKey(...)`, etc.
4. For `ForeignKey(TargetModel)`: create `{field_name}_id` column (Django convention) + `REFERENCES` edge to target table PK
5. For `ManyToManyField(TargetModel)`: create junction table `{app}_{model}_{field}` with two FK columns
6. For `OneToOneField(TargetModel)`: same as ForeignKey but with unique constraint metadata

Key regex patterns:
```python
_MODEL_FIELD_RE = re.compile(r'^models\.(\w+)\(')
_FK_TARGET_RE = re.compile(r'^models\.(?:ForeignKey|OneToOneField)\(\s*(\w+)')
_M2M_TARGET_RE = re.compile(r'^models\.ManyToManyField\(\s*(\w+)')
_PK_RE = re.compile(r'primary_key\s*=\s*True')
```

App label extraction: from model FQN, e.g., `myapp.models.User` → app_label = `myapp`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_django_orm_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Update `__init__.py` and commit**

```python
# Update app/stages/plugins/django/__init__.py to add:
from app.stages.plugins.django.orm import DjangoORMPlugin
```

```bash
cd cast-clone-backend && git add app/stages/plugins/django/ tests/unit/test_django_orm_plugin.py && git commit -m "feat(plugins): add Django ORM plugin — model-to-table mapping, ForeignKey/M2M/O2O resolution"
```

---

## Task 4: Django DRF Plugin

**Files:**
- Create: `app/stages/plugins/django/drf.py`
- Test: `tests/unit/test_django_drf_plugin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_django_drf_plugin.py
"""Tests for the Django REST Framework plugin — ViewSet->Serializer->Model chain."""

import pytest
from pathlib import Path

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from app.stages.plugins.base import PluginDetectionResult, PluginResult
from app.stages.plugins.django.drf import DjangoDRFPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context_with_drf() -> AnalysisContext:
    ctx = AnalysisContext(project_id="test")
    ctx.manifest = ProjectManifest(
        root_path=Path("/tmp/test-project"),
        detected_frameworks=[
            DetectedFramework(name="django", language="python",
                              confidence=Confidence.HIGH, evidence=["Django detected"]),
            DetectedFramework(name="djangorestframework", language="python",
                              confidence=Confidence.HIGH, evidence=["DRF detected"]),
        ],
    )
    return ctx


def _add_class(
    graph: SymbolGraph, fqn: str, name: str,
    bases: list[str] | None = None,
) -> GraphNode:
    node = GraphNode(
        fqn=fqn, name=name, kind=NodeKind.CLASS, language="python",
        properties={"annotations": []},
    )
    graph.add_node(node)
    for base in (bases or []):
        graph.add_edge(GraphEdge(
            source_fqn=fqn, target_fqn=base, kind=EdgeKind.INHERITS,
            confidence=Confidence.LOW, evidence="tree-sitter",
        ))
    return node


def _add_field(
    graph: SymbolGraph, class_fqn: str, name: str, value: str = "",
) -> GraphNode:
    fqn = f"{class_fqn}.{name}"
    node = GraphNode(
        fqn=fqn, name=name, kind=NodeKind.FIELD, language="python",
        properties={"value": value},
    )
    graph.add_node(node)
    graph.add_edge(GraphEdge(
        source_fqn=class_fqn, target_fqn=fqn, kind=EdgeKind.CONTAINS,
    ))
    return node


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestDjangoDRFDetection:
    def test_detect_high_when_drf_in_frameworks(self):
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.HIGH

    def test_detect_none_without_drf(self):
        plugin = DjangoDRFPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        result = plugin.detect(ctx)
        assert result.is_active is False

    def test_detect_medium_when_viewset_found(self):
        """If no DRF in frameworks but ModelViewSet subclass exists."""
        plugin = DjangoDRFPlugin()
        ctx = AnalysisContext(project_id="test")
        ctx.manifest = ProjectManifest(root_path=Path("/tmp"), detected_frameworks=[])
        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        result = plugin.detect(ctx)
        assert result.confidence == Confidence.MEDIUM


# ---------------------------------------------------------------------------
# ViewSet chain resolution tests
# ---------------------------------------------------------------------------

class TestDRFViewSetChain:
    @pytest.mark.asyncio
    async def test_viewset_manages_model(self):
        """ViewSet with queryset = User.objects.all() -> MANAGES edge to User."""
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()

        # Model
        _add_class(ctx.graph, "myapp.models.User", "User",
                   bases=["django.db.models.Model"])

        # ViewSet
        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        _add_field(ctx.graph, "myapp.views.UserViewSet", "queryset",
                   value="User.objects.all()")
        _add_field(ctx.graph, "myapp.views.UserViewSet", "serializer_class",
                   value="UserSerializer")

        result = await plugin.extract(ctx)
        manages_edges = [e for e in result.edges if e.kind == EdgeKind.MANAGES]
        assert len(manages_edges) == 1
        assert manages_edges[0].source_fqn == "myapp.views.UserViewSet"

    @pytest.mark.asyncio
    async def test_viewset_reads_writes_table(self):
        """ViewSet -> READS/WRITES edges to associated table (if ORM plugin ran first)."""
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()

        # Simulate ORM plugin output: model + table
        _add_class(ctx.graph, "myapp.models.User", "User",
                   bases=["django.db.models.Model"])
        table_node = GraphNode(
            fqn="table:myapp_user", name="myapp_user", kind=NodeKind.TABLE,
        )
        ctx.graph.add_node(table_node)
        ctx.graph.add_edge(GraphEdge(
            source_fqn="myapp.models.User", target_fqn="table:myapp_user",
            kind=EdgeKind.MAPS_TO, confidence=Confidence.HIGH, evidence="django-orm",
        ))

        # ViewSet
        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        _add_field(ctx.graph, "myapp.views.UserViewSet", "queryset",
                   value="User.objects.all()")

        result = await plugin.extract(ctx)
        rw_edges = [e for e in result.edges
                    if e.kind in (EdgeKind.READS, EdgeKind.WRITES)]
        assert len(rw_edges) >= 1

    @pytest.mark.asyncio
    async def test_viewset_creates_crud_endpoints(self):
        """ModelViewSet generates standard CRUD endpoints."""
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()

        _add_class(ctx.graph, "myapp.models.User", "User",
                   bases=["django.db.models.Model"])
        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        _add_field(ctx.graph, "myapp.views.UserViewSet", "queryset",
                   value="User.objects.all()")

        result = await plugin.extract(ctx)
        endpoint_nodes = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        # ModelViewSet generates list, create, retrieve, update, destroy
        assert len(endpoint_nodes) >= 2  # At minimum list + detail

    @pytest.mark.asyncio
    async def test_viewset_layer_assignment(self):
        """ViewSet -> Presentation layer."""
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()

        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        _add_field(ctx.graph, "myapp.views.UserViewSet", "queryset",
                   value="User.objects.all()")

        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("myapp.views.UserViewSet") == "Presentation"


# ---------------------------------------------------------------------------
# Serializer chain tests
# ---------------------------------------------------------------------------

class TestDRFSerializerChain:
    @pytest.mark.asyncio
    async def test_serializer_with_meta_model(self):
        """ModelSerializer with Meta.model = User -> link to model."""
        plugin = DjangoDRFPlugin()
        ctx = _make_context_with_drf()

        _add_class(ctx.graph, "myapp.models.User", "User",
                   bases=["django.db.models.Model"])
        _add_class(ctx.graph, "myapp.serializers.UserSerializer", "UserSerializer",
                   bases=["rest_framework.serializers.ModelSerializer"])
        _add_field(ctx.graph, "myapp.serializers.UserSerializer", "_meta_model",
                   value="User")

        _add_class(ctx.graph, "myapp.views.UserViewSet", "UserViewSet",
                   bases=["rest_framework.viewsets.ModelViewSet"])
        _add_field(ctx.graph, "myapp.views.UserViewSet", "serializer_class",
                   value="UserSerializer")
        _add_field(ctx.graph, "myapp.views.UserViewSet", "queryset",
                   value="User.objects.all()")

        result = await plugin.extract(ctx)
        manages_edges = [e for e in result.edges if e.kind == EdgeKind.MANAGES]
        assert len(manages_edges) >= 1


# ---------------------------------------------------------------------------
# Plugin metadata tests
# ---------------------------------------------------------------------------

class TestDjangoDRFMetadata:
    def test_plugin_name(self):
        assert DjangoDRFPlugin().name == "django-drf"

    def test_depends_on(self):
        assert DjangoDRFPlugin().depends_on == ["django-orm", "django-urls"]

    def test_supported_languages(self):
        assert DjangoDRFPlugin().supported_languages == {"python"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_django_drf_plugin.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `django/drf.py`**

The implementation should:
1. Find classes inheriting from `ModelViewSet`, `GenericAPIView`, `APIView`, etc.
2. Extract `queryset` field to resolve the model reference (e.g., `User.objects.all()` → `User`)
3. Extract `serializer_class` field to find the serializer class
4. For `ModelViewSet`: generate CRUD endpoint nodes (list, create, retrieve, update, destroy)
5. Create `MANAGES` edges (ViewSet → Model)
6. If ORM plugin has already run: find `MAPS_TO` edges from model to table, create `READS`/`WRITES` edges from ViewSet to table
7. Assign Presentation layer to ViewSets and Serializers

Key regex patterns:
```python
_QUERYSET_MODEL_RE = re.compile(r'^(\w+)\.objects')
_SERIALIZER_REF_RE = re.compile(r'^(\w+)$')
```

DRF ViewSet → CRUD endpoint mapping:
```python
_VIEWSET_ACTIONS = {
    "ModelViewSet": ["list", "create", "retrieve", "update", "partial_update", "destroy"],
    "ReadOnlyModelViewSet": ["list", "retrieve"],
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_django_drf_plugin.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Update `__init__.py` and commit**

```python
# Final app/stages/plugins/django/__init__.py:
"""Django framework plugins — Settings, URLs, ORM, DRF."""

from app.stages.plugins.django.settings import DjangoSettingsPlugin
from app.stages.plugins.django.urls import DjangoURLsPlugin
from app.stages.plugins.django.orm import DjangoORMPlugin
from app.stages.plugins.django.drf import DjangoDRFPlugin

__all__ = ["DjangoSettingsPlugin", "DjangoURLsPlugin", "DjangoORMPlugin", "DjangoDRFPlugin"]
```

```bash
cd cast-clone-backend && git add app/stages/plugins/django/ tests/unit/test_django_drf_plugin.py && git commit -m "feat(plugins): add Django DRF plugin — ViewSet->Serializer->Model chain resolution"
```

---

## Task 5: Register All Django Plugins in Global Registry

**Files:**
- Modify: `app/stages/plugins/__init__.py`

- [ ] **Step 1: Add imports and registrations**

Add after existing registrations:

```python
from app.stages.plugins.django.settings import DjangoSettingsPlugin
from app.stages.plugins.django.urls import DjangoURLsPlugin
from app.stages.plugins.django.orm import DjangoORMPlugin
from app.stages.plugins.django.drf import DjangoDRFPlugin

global_registry.register(DjangoSettingsPlugin)
global_registry.register(DjangoURLsPlugin)
global_registry.register(DjangoORMPlugin)
global_registry.register(DjangoDRFPlugin)
```

- [ ] **Step 2: Run the full Django test suite**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_django_settings_plugin.py tests/unit/test_django_urls_plugin.py tests/unit/test_django_orm_plugin.py tests/unit/test_django_drf_plugin.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add app/stages/plugins/__init__.py app/stages/plugins/django/__init__.py && git commit -m "feat(plugins): register all Django plugins (settings, urls, orm, drf) in global registry"
```

---

## Task 6: Lint and Type-Check

- [ ] **Step 1: Run ruff check**

Run: `cd cast-clone-backend && uv run ruff check app/stages/plugins/django/ tests/unit/test_django_*.py`

- [ ] **Step 2: Run ruff format**

Run: `cd cast-clone-backend && uv run ruff format app/stages/plugins/django/ tests/unit/test_django_*.py`

- [ ] **Step 3: Commit any formatting fixes**

```bash
cd cast-clone-backend && git add -u && git commit -m "style(plugins): apply ruff formatting to Django plugins"
```

---

## Summary of Produced Graph Artifacts

| Plugin | Nodes Created | Edges Created |
|--------|--------------|---------------|
| `django-settings` | `CONFIG_FILE`, `CONFIG_ENTRY` | `CONTAINS` (File->Entry) |
| `django-urls` | `API_ENDPOINT` | `HANDLES` (View->Endpoint), `EXPOSES` (Module->Endpoint) |
| `django-orm` | `TABLE`, `COLUMN` | `MAPS_TO` (Class->Table), `HAS_COLUMN` (Table->Column), `REFERENCES` (Column->Column) |
| `django-drf` | `API_ENDPOINT` (CRUD) | `MANAGES` (ViewSet->Model), `READS`/`WRITES` (ViewSet->Table), `HANDLES` (ViewSet->Endpoint) |

## Dependency Chain

```
django-settings (no deps)
    ├── django-urls (depends on django-settings)
    └── django-orm (depends on django-settings)
            └── django-drf (depends on django-orm, django-urls)
```

The registry topologically sorts these: `django-settings` runs first, then `django-urls` and `django-orm` can run concurrently, then `django-drf` runs last.

---

## Implementation Notes

### Django Table Naming Convention

Django derives table names as `{app_label}_{model_name_lower}`:
- `myapp.models.User` → app_label = `myapp`, model = `user` → table = `myapp_user`
- `blog.models.BlogPost` → table = `blog_blogpost`

Override via `class Meta: db_table = "custom"`. In the graph, this is represented as a `_meta_db_table` field on the class.

### Django ForeignKey Column Naming

Django automatically appends `_id` to ForeignKey field names:
- `author = models.ForeignKey(User)` → column `author_id` in the database
- The plugin creates a Column node named `author_id` and a REFERENCES edge to the target table's PK

### DRF ViewSet CRUD Endpoints

`ModelViewSet` auto-generates these endpoints:
- `list` → GET `/{resource}/`
- `create` → POST `/{resource}/`
- `retrieve` → GET `/{resource}/{pk}/`
- `update` → PUT `/{resource}/{pk}/`
- `partial_update` → PATCH `/{resource}/{pk}/`
- `destroy` → DELETE `/{resource}/{pk}/`

The resource name is derived from the model name (lowered, pluralized).

### FQN Conventions

- **Table FQN:** `table:{table_name}` (matches Hibernate and SQLAlchemy conventions)
- **Column FQN:** `table:{table_name}.{column_name}`
- **Config FQN:** `config:{module_fqn}.{setting_key}`
- **Endpoint FQN:** `{METHOD}:{path}` (matches FastAPI convention)

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] `uv run pytest tests/unit/test_django_settings_plugin.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/test_django_urls_plugin.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/test_django_orm_plugin.py -v` — all tests pass
- [ ] `uv run pytest tests/unit/test_django_drf_plugin.py -v` — all tests pass
- [ ] `uv run ruff check app/stages/plugins/django/` — no lint errors
- [ ] `app/stages/plugins/django/__init__.py` exports all four plugin classes
- [ ] `django-settings` produces `CONFIG_FILE` + `CONFIG_ENTRY` nodes
- [ ] `django-urls` resolves `include()` prefix composition
- [ ] `django-orm` uses `{app_label}_{model_lower}` table naming convention
- [ ] `django-orm` appends `_id` to ForeignKey column names
- [ ] `django-orm` creates junction tables for ManyToManyField
- [ ] `django-drf` generates CRUD endpoint nodes for ModelViewSet
- [ ] `django-drf` creates `MANAGES` edges from ViewSet to Model
- [ ] All four plugins are registered in `global_registry`
- [ ] Dependency chain is respected: settings → urls + orm → drf