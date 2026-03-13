"""Tests for Django Settings plugin — config extraction."""

from pathlib import Path

import pytest

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.models.manifest import DetectedFramework, ProjectManifest
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
    graph.add_edge(
        GraphEdge(
            source_fqn=parent_fqn,
            target_fqn=fqn,
            kind=EdgeKind.CONTAINS,
        )
    )
    return node


def _make_settings_module(graph: SymbolGraph) -> None:
    """Create a typical Django settings module with common settings."""
    _add_module(graph, "myproject.settings", "settings")
    _add_field(
        graph,
        "myproject.settings",
        "INSTALLED_APPS",
        value=(
            '["django.contrib.admin", "django.contrib.auth",'
            ' "myapp", "rest_framework"]'
        ),
    )
    _add_field(
        graph,
        "myproject.settings",
        "ROOT_URLCONF",
        value='"myproject.urls"',
    )
    _add_field(
        graph,
        "myproject.settings",
        "DATABASES",
        value=(
            '{"default": {"ENGINE": '
            '"django.db.backends.postgresql", "NAME": "mydb"}}'
        ),
    )
    _add_field(
        graph,
        "myproject.settings",
        "MIDDLEWARE",
        value=(
            '["django.middleware.security.SecurityMiddleware",'
            ' "django.contrib.sessions.middleware.SessionMiddleware"]'
        ),
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
        assert (
            len(contains_edges) >= 4
        )  # INSTALLED_APPS, ROOT_URLCONF, DATABASES, MIDDLEWARE


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
