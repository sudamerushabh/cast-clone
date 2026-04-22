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
            '["django.contrib.admin", "django.contrib.auth", "myapp", "rest_framework"]'
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
            '{"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "mydb"}}'
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


# ---------------------------------------------------------------------------
# INSTALLED_APPS parsing tests
# ---------------------------------------------------------------------------


class TestInstalledAppsParsing:
    def test_simple_list_parsed(self):
        from app.stages.plugins.django.settings import parse_installed_apps

        raw = '["django.contrib.auth", "rest_framework", "posts"]'
        apps = parse_installed_apps(raw)

        assert apps == [
            "django.contrib.auth",
            "rest_framework",
            "posts",
        ]

    def test_multiline_list_parsed(self):
        from app.stages.plugins.django.settings import parse_installed_apps

        raw = (
            "[\n"
            '    "django.contrib.admin",\n'
            '    "django.contrib.auth",\n'
            '    "posts",\n'
            "]"
        )
        apps = parse_installed_apps(raw)

        assert apps == [
            "django.contrib.admin",
            "django.contrib.auth",
            "posts",
        ]

    def test_malformed_returns_empty(self):
        from app.stages.plugins.django.settings import parse_installed_apps

        assert parse_installed_apps("not a list") == []
        assert parse_installed_apps("") == []

    def test_non_string_entries_filtered(self):
        from app.stages.plugins.django.settings import parse_installed_apps

        # We only accept string entries; anything else (ints, dicts) is dropped.
        raw = '["app1", 42, "app2"]'
        assert parse_installed_apps(raw) == ["app1", "app2"]

    def test_tuple_syntax_parsed(self):
        """Django settings commonly use tuple literal for INSTALLED_APPS."""
        from app.stages.plugins.django.settings import parse_installed_apps

        raw = '("django.contrib.admin", "myapp",)'
        assert parse_installed_apps(raw) == ["django.contrib.admin", "myapp"]

    def test_nested_list_filtered(self):
        """Nested list entries are dropped (only strings survive)."""
        from app.stages.plugins.django.settings import parse_installed_apps

        raw = '[["nested"], "app1"]'
        assert parse_installed_apps(raw) == ["app1"]

    @pytest.mark.asyncio
    async def test_extract_emits_apps_property(self, tmp_path):
        """End-to-end: a synthetic graph with an INSTALLED_APPS FIELD
        produces a CONFIG_ENTRY whose properties include the parsed `apps` list."""
        from app.stages.plugins.django.settings import DjangoSettingsPlugin

        graph = SymbolGraph()
        module = GraphNode(
            fqn="myproj.settings",
            name="settings",
            kind=NodeKind.MODULE,
            language="python",
        )
        field = GraphNode(
            fqn="myproj.settings.INSTALLED_APPS",
            name="INSTALLED_APPS",
            kind=NodeKind.FIELD,
            language="python",
            properties={"value": '["django.contrib.auth", "posts"]'},
        )
        graph.add_node(module)
        graph.add_node(field)
        graph.add_edge(
            GraphEdge(
                source_fqn=module.fqn,
                target_fqn=field.fqn,
                kind=EdgeKind.CONTAINS,
                confidence=Confidence.HIGH,
                evidence="test-setup",
            )
        )

        ctx = AnalysisContext(project_id="t", graph=graph)
        result = await DjangoSettingsPlugin().extract(ctx)

        entries = [n for n in result.nodes if n.kind == NodeKind.CONFIG_ENTRY]
        installed = next(e for e in entries if e.name == "INSTALLED_APPS")
        assert installed.properties["apps"] == [
            "django.contrib.auth",
            "posts",
        ]


# ---------------------------------------------------------------------------
# DATABASES parsing tests
# ---------------------------------------------------------------------------


class TestDatabasesParsing:
    def test_postgres_default_parsed(self):
        from app.stages.plugins.django.settings import parse_databases

        raw = (
            "{\n"
            '    "default": {\n'
            '        "ENGINE": "django.db.backends.postgresql",\n'
            '        "NAME": "blog",\n'
            '        "USER": "blog",\n'
            '        "PASSWORD": "blog",\n'
            '        "HOST": "localhost",\n'
            '        "PORT": "5432",\n'
            "    }\n"
            "}"
        )
        info = parse_databases(raw)

        assert info == {
            "default_engine": "django.db.backends.postgresql",
            "default_name": "blog",
            "default_host": "localhost",
            "default_port": "5432",
        }

    def test_sqlite_minimal(self):
        from app.stages.plugins.django.settings import parse_databases

        raw = (
            '{"default": {"ENGINE": "django.db.backends.sqlite3", '
            '"NAME": "db.sqlite3"}}'
        )
        info = parse_databases(raw)

        assert info["default_engine"] == "django.db.backends.sqlite3"
        assert info["default_name"] == "db.sqlite3"
        # Absent keys are simply omitted, not set to None
        assert "default_host" not in info
        assert "default_port" not in info

    def test_no_default_key_returns_empty(self):
        from app.stages.plugins.django.settings import parse_databases

        raw = '{"secondary": {"ENGINE": "x"}}'
        assert parse_databases(raw) == {}

    def test_malformed_returns_empty(self):
        from app.stages.plugins.django.settings import parse_databases

        assert parse_databases("not a dict") == {}
        assert parse_databases("") == {}

    def test_integer_port_is_omitted(self):
        """Real Django pattern: `"PORT": 5432` (int) — dropped, not coerced."""
        from app.stages.plugins.django.settings import parse_databases

        raw = '{"default": {"ENGINE": "django.db.backends.postgresql", "PORT": 5432}}'
        info = parse_databases(raw)
        assert "default_port" not in info
        assert info["default_engine"] == "django.db.backends.postgresql"


class TestMiddlewareParsing:
    def test_middleware_list_parsed(self):
        from app.stages.plugins.django.settings import parse_middleware

        raw = (
            "[\n"
            '    "django.middleware.security.SecurityMiddleware",\n'
            '    "django.contrib.sessions.middleware.SessionMiddleware",\n'
            "]"
        )
        mw = parse_middleware(raw)

        assert mw == [
            "django.middleware.security.SecurityMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
        ]

    def test_tuple_syntax_parsed(self):
        """Django settings often use tuple literal for MIDDLEWARE."""
        from app.stages.plugins.django.settings import parse_middleware

        raw = '("django.middleware.security.SecurityMiddleware",)'
        assert parse_middleware(raw) == [
            "django.middleware.security.SecurityMiddleware",
        ]

    def test_malformed_returns_empty(self):
        from app.stages.plugins.django.settings import parse_middleware

        assert parse_middleware("not a list") == []

    @pytest.mark.asyncio
    async def test_extract_emits_middleware_property(self, tmp_path):
        from app.models.context import AnalysisContext
        from app.models.enums import Confidence, EdgeKind, NodeKind
        from app.models.graph import GraphEdge, GraphNode, SymbolGraph
        from app.stages.plugins.django.settings import DjangoSettingsPlugin

        graph = SymbolGraph()
        module = GraphNode(
            fqn="m.settings",
            name="settings",
            kind=NodeKind.MODULE,
            language="python",
        )
        anchor = GraphNode(
            fqn="m.settings.INSTALLED_APPS",
            name="INSTALLED_APPS",
            kind=NodeKind.FIELD,
            language="python",
            properties={"value": "[]"},
        )
        mw_field = GraphNode(
            fqn="m.settings.MIDDLEWARE",
            name="MIDDLEWARE",
            kind=NodeKind.FIELD,
            language="python",
            properties={"value": '["django.middleware.security.SecurityMiddleware"]'},
        )
        graph.add_node(module)
        graph.add_node(anchor)
        graph.add_node(mw_field)
        for child in (anchor, mw_field):
            graph.add_edge(
                GraphEdge(
                    source_fqn=module.fqn,
                    target_fqn=child.fqn,
                    kind=EdgeKind.CONTAINS,
                    confidence=Confidence.HIGH,
                    evidence="test-setup",
                )
            )

        ctx = AnalysisContext(project_id="t", graph=graph)
        result = await DjangoSettingsPlugin().extract(ctx)

        entries = {n.name: n for n in result.nodes if n.kind == NodeKind.CONFIG_ENTRY}
        assert entries["MIDDLEWARE"].properties["middleware"] == [
            "django.middleware.security.SecurityMiddleware",
        ]
