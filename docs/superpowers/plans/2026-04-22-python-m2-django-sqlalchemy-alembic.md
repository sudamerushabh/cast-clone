# Python M2 — Django Settings + Async SQLAlchemy + Alembic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn raw Django settings into structured config entries, verify async SQLAlchemy 2.0 extraction works end-to-end, and introduce an Alembic migration plugin that builds the revision-chain DAG for Python fixtures.

**Architecture:** Additive only, no new NodeKind/EdgeKind values (spec confirms `CONFIG_FILE`, `CONFIG_ENTRY`, `INHERITS`, `MAPS_TO` already exist in `app/models/enums.py`). Extend the existing `DjangoSettingsPlugin` to parse structured values into node properties. Add regression tests confirming `SQLAlchemyPlugin` handles SQLAlchemy 2.0 async style (it already uses `mapped_column` regex — tests pin the contract). Create a new `alembic_plugin/` under `app/stages/plugins/`, modeled structurally on `app/stages/plugins/sql/migration.py`, that parses each file under `migrations/versions/` and emits `CONFIG_FILE` nodes linked by `INHERITS` edges from revision to down_revision.

**Tech Stack:** Python 3.12, tree-sitter (already wired through `PythonExtractor`), stdlib `ast` module for safe literal parsing and migration body analysis, pytest + pytest-asyncio, ruff, mypy. No new runtime dependencies.

**Spec reference:** `docs/superpowers/specs/2026-04-22-python-plugin-complete-design.md` §Milestones / M2.

**Depends on:** Python M1 (`feat/python-m1-scip-foundation`) must be merged to `main` before M2 starts — M2's integration tests reuse the three fixtures authored in M1 (`fastapi-todo`, `django-blog`, `flask-inventory`).

---

## Prerequisites

Verify on PATH:

```bash
uv --version
python3.12 --version
```

Confirm M1 merged:

```bash
cd cast-clone-backend
git log --oneline --grep="docs: M1 Python SCIP foundation complete" | head -1
test -d tests/fixtures/fastapi-todo && test -d tests/fixtures/django-blog && echo "M1 fixtures present"
```

**Branch**: work on a dedicated worktree `python-m2-django-sqlalchemy-alembic` per the `superpowers:using-git-worktrees` skill, branched off current `main`.

---

## File Structure

**Modify:**
- `app/stages/plugins/django/settings.py` — enrich `extract()` to parse structured values for the six recognized Django settings keys.
- `tests/unit/test_django_settings_plugin.py` — add structured-value tests.
- `tests/unit/test_sqlalchemy_plugin.py` — add SQLAlchemy 2.0 async-style tests.
- `app/stages/plugins/registry.py` (or wherever plugin auto-discovery lives) — register new `AlembicPlugin`.
- `cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md` — add Alembic + Django settings M2 notes.
- `CLAUDE.md` (root) Plugin Priority table — M2 completion note.

**Create:**
- `app/stages/plugins/alembic_plugin/__init__.py`
- `app/stages/plugins/alembic_plugin/migrations.py` — the plugin class + migration-file parser.
- `tests/unit/test_alembic_plugin.py` — unit tests for the new plugin.
- `tests/integration/test_python_m2_plugins.py` — end-to-end against the three M1 fixtures.

**Do NOT touch** (out of scope):
- Anything under `app/stages/scip/` (M1 territory).
- Anything under `app/stages/plugins/spring/`, `hibernate/`, `dotnet/` (non-Python).
- Fixture source files under `tests/fixtures/` — fixtures are parser input, immutable for M2.

---

## Task 1: Inspect current Django settings extraction + print fixture output

**Files:**
- Read: `app/stages/plugins/django/settings.py`
- Read: `tests/unit/test_django_settings_plugin.py`
- Test (temporary, not committed): ad-hoc script

**Context:** The existing `DjangoSettingsPlugin.extract()` already emits `CONFIG_ENTRY` nodes for the six recognized settings keys with `properties["value"] = <raw string>`. M2 needs those raw strings parsed into structured properties (list / dict / single-string depending on the key). Before writing any parser, confirm the actual shape of the `value` property as it arrives from the Python tree-sitter extractor. This reconnaissance prevents wasted effort on the wrong format.

- [ ] **Step 1: Read the current plugin and test file**

```bash
cd cast-clone-backend
wc -l app/stages/plugins/django/settings.py tests/unit/test_django_settings_plugin.py
```

Capture the findings:
- Line count for each file.
- The set of keys in `_DJANGO_SETTINGS_KEYS` (should be `INSTALLED_APPS`, `ROOT_URLCONF`, `DATABASES`, `MIDDLEWARE`, `DEFAULT_AUTO_FIELD`, `AUTH_USER_MODEL`).
- Which tests currently exist in `test_django_settings_plugin.py` (class names + method names).

- [ ] **Step 2: Run the existing plugin tests**

```bash
uv run pytest tests/unit/test_django_settings_plugin.py -v
```

Expected: all existing tests pass on `main`. Record the pass count.

- [ ] **Step 3: Print raw `value` shape from the real django-blog fixture**

Drop this one-off script at `/tmp/inspect_django_values.py` (NOT committed):

```python
"""One-off: print raw CONFIG_ENTRY values from django-blog fixture."""
import asyncio
from pathlib import Path

from app.models.context import AnalysisContext
from app.models.enums import NodeKind
from app.stages.discovery import discover_project
from app.stages.plugins.django.settings import DjangoSettingsPlugin
from app.stages.treesitter.extractors import register_extractor
from app.stages.treesitter.extractors.python import PythonExtractor
from app.stages.treesitter.parser import parse_with_treesitter


async def main() -> None:
    register_extractor("python", PythonExtractor())
    fixture = Path("tests/fixtures/django-blog")
    manifest = discover_project(fixture)
    graph = await parse_with_treesitter(manifest)
    ctx = AnalysisContext(project_id="m2-recon", graph=graph, manifest=manifest)

    plugin = DjangoSettingsPlugin()
    result = await plugin.extract(ctx)

    for node in result.nodes:
        if node.kind == NodeKind.CONFIG_ENTRY:
            print(f"{node.name}:")
            print(f"  value = {node.properties.get('value', '')!r}")
            print()


asyncio.run(main())
```

Run it:

```bash
uv run python /tmp/inspect_django_values.py
```

Record the actual `value` shape for each of the six keys. Likely the RHS text of the assignment, possibly including outer `[...]` / `{...}` brackets.

- [ ] **Step 4: Remove the temp script**

```bash
rm /tmp/inspect_django_values.py
```

- [ ] **Step 5: Write findings into an inline report (not committed)**

Keep the findings in chat/task report. No commit in this task — it is pure reconnaissance. Tasks 2-5 depend on these findings.

---

## Task 2: Parse INSTALLED_APPS into `properties["apps"]` list

**Files:**
- Modify: `app/stages/plugins/django/settings.py`
- Test: `tests/unit/test_django_settings_plugin.py`

**Context:** `INSTALLED_APPS` is a Python list literal. Parsing it to a `list[str]` is safe via the stdlib `ast.literal_eval` helper — which only accepts literal Python values and refuses arbitrary code. Store the parsed apps on the CONFIG_ENTRY node so downstream consumers (M3+ url routing, DI resolution) don't re-parse.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_django_settings_plugin.py`:

```python
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
```

- [ ] **Step 2: Run — expect FAIL on ImportError**

```bash
uv run pytest tests/unit/test_django_settings_plugin.py::TestInstalledAppsParsing -v
```

Expected: `ImportError: cannot import name 'parse_installed_apps'`.

- [ ] **Step 3: Implement `parse_installed_apps`**

Add to `app/stages/plugins/django/settings.py` (below the existing module constants, above `DjangoSettingsPlugin`):

```python
import ast


def parse_installed_apps(raw_value: str) -> list[str]:
    """Parse an INSTALLED_APPS RHS into a list of app names.

    Uses ast.literal_eval so arbitrary Python in the RHS cannot execute.
    Drops non-string entries (e.g. int, dict) to keep the caller's type sane.
    Returns [] on any parse failure.
    """
    if not raw_value.strip():
        return []
    try:
        parsed = ast.literal_eval(raw_value)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]
```

Also import `ast` at the top of the file (alphabetical among stdlib imports) if not already imported.

- [ ] **Step 4: Wire the parsed apps onto the CONFIG_ENTRY for INSTALLED_APPS**

In `DjangoSettingsPlugin.extract()`, inside the `for field_fqn, field_node in self._get_settings_fields(...)` loop, enrich `properties` before constructing the `GraphNode`:

```python
            raw_value = field_node.properties.get("value", "")
            entry_properties: dict[str, object] = {
                "value": raw_value,
                "setting_key": field_node.name,
            }
            if field_node.name == "INSTALLED_APPS":
                entry_properties["apps"] = parse_installed_apps(raw_value)

            entry_fqn = f"config:{module_fqn}.{field_node.name}"
            entry = GraphNode(
                fqn=entry_fqn,
                name=field_node.name,
                kind=NodeKind.CONFIG_ENTRY,
                language="python",
                properties=entry_properties,
            )
```

(Replace the existing `properties={...}` inline dict with `properties=entry_properties`.)

- [ ] **Step 5: Add integration assertion that the emitted node carries `apps`**

Append to `TestInstalledAppsParsing`:

```python
    @pytest.mark.asyncio
    async def test_extract_emits_apps_property(self, tmp_path):
        """End-to-end: a synthetic graph with an INSTALLED_APPS FIELD
        produces a CONFIG_ENTRY whose properties include the parsed `apps` list."""
        from app.models.context import AnalysisContext
        from app.models.enums import Confidence, EdgeKind, NodeKind
        from app.models.graph import GraphEdge, GraphNode, SymbolGraph
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
```

If `SymbolGraph` doesn't expose `add_node` / `add_edge` with those names, use whatever the file's existing tests use — read `tests/unit/test_django_settings_plugin.py` for the established pattern and copy it.

- [ ] **Step 6: Run — expect PASS**

```bash
uv run pytest tests/unit/test_django_settings_plugin.py::TestInstalledAppsParsing -v
```

Expected: 5 passed.

- [ ] **Step 7: Ruff clean check**

```bash
uv run ruff check app/stages/plugins/django/settings.py tests/unit/test_django_settings_plugin.py
```

- [ ] **Step 8: Commit**

```bash
git add app/stages/plugins/django/settings.py tests/unit/test_django_settings_plugin.py
git commit -m "feat(django-settings): parse INSTALLED_APPS into structured list"
```

---

## Task 3: Parse DATABASES into structured engine/name/host properties

**Files:**
- Modify: `app/stages/plugins/django/settings.py`
- Test: `tests/unit/test_django_settings_plugin.py`

**Context:** `DATABASES` is a dict-of-dicts. Downstream consumers (DB migration plugin, impact analysis) only care about the primary connection: engine, database name, host, port. Parsing the full nested dict and then projecting just `default_*` properties keeps the graph node small and queryable.

- [ ] **Step 1: Write the failing test**

Append:

```python
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
```

- [ ] **Step 2: Run — expect FAIL on ImportError**

```bash
uv run pytest tests/unit/test_django_settings_plugin.py::TestDatabasesParsing -v
```

- [ ] **Step 3: Implement `parse_databases`**

Add below `parse_installed_apps`:

```python
def parse_databases(raw_value: str) -> dict[str, str]:
    """Parse a DATABASES RHS, returning structured keys for the default conn.

    Output keys (all optional, present only if the setting supplied them):
    - default_engine
    - default_name
    - default_host
    - default_port

    Returns {} on malformed input or missing "default" key.
    """
    if not raw_value.strip():
        return {}
    try:
        parsed = ast.literal_eval(raw_value)
    except (ValueError, SyntaxError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    default = parsed.get("default")
    if not isinstance(default, dict):
        return {}

    mapping = {
        "ENGINE": "default_engine",
        "NAME": "default_name",
        "HOST": "default_host",
        "PORT": "default_port",
    }
    out: dict[str, str] = {}
    for django_key, out_key in mapping.items():
        value = default.get(django_key)
        if isinstance(value, str):
            out[out_key] = value
    return out
```

- [ ] **Step 4: Wire into `extract()`**

Inside the same loop in `extract()`, extend `entry_properties` when the key is `DATABASES`:

```python
            if field_node.name == "INSTALLED_APPS":
                entry_properties["apps"] = parse_installed_apps(raw_value)
            elif field_node.name == "DATABASES":
                entry_properties.update(parse_databases(raw_value))
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/unit/test_django_settings_plugin.py::TestDatabasesParsing -v
```

- [ ] **Step 6: Ruff check**

```bash
uv run ruff check app/stages/plugins/django/settings.py tests/unit/test_django_settings_plugin.py
```

- [ ] **Step 7: Commit**

```bash
git add app/stages/plugins/django/settings.py tests/unit/test_django_settings_plugin.py
git commit -m "feat(django-settings): parse DATABASES.default into structured properties"
```

---

## Task 4: Parse MIDDLEWARE into `properties["middleware"]` list

**Files:**
- Modify: `app/stages/plugins/django/settings.py`
- Test: `tests/unit/test_django_settings_plugin.py`

**Context:** `MIDDLEWARE` is a Python list literal identical in shape to `INSTALLED_APPS`. Rather than duplicate the parser, reuse `parse_installed_apps` under a more neutral helper name — or keep them distinct for clarity. This plan chooses distinct names (`parse_middleware`) to keep error-logging surfaces clean and make downstream consumers easy to trace, even though the implementation is trivial.

- [ ] **Step 1: Write the failing test**

Append:

```python
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
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/unit/test_django_settings_plugin.py::TestMiddlewareParsing -v
```

- [ ] **Step 3: Implement `parse_middleware`**

Add below `parse_databases`:

```python
def parse_middleware(raw_value: str) -> list[str]:
    """Parse a MIDDLEWARE RHS into a list of middleware class paths.

    Shape-identical to INSTALLED_APPS but exposed under a distinct name so
    downstream log keys and exception context stay accurate. Uses
    ast.literal_eval. Non-string entries are dropped.
    """
    if not raw_value.strip():
        return []
    try:
        parsed = ast.literal_eval(raw_value)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]
```

- [ ] **Step 4: Wire into `extract()`**

Extend the if/elif chain:

```python
            if field_node.name == "INSTALLED_APPS":
                entry_properties["apps"] = parse_installed_apps(raw_value)
            elif field_node.name == "DATABASES":
                entry_properties.update(parse_databases(raw_value))
            elif field_node.name == "MIDDLEWARE":
                entry_properties["middleware"] = parse_middleware(raw_value)
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/unit/test_django_settings_plugin.py::TestMiddlewareParsing -v
```

- [ ] **Step 6: Commit**

```bash
git add app/stages/plugins/django/settings.py tests/unit/test_django_settings_plugin.py
git commit -m "feat(django-settings): parse MIDDLEWARE into structured list"
```

---

## Task 5: Normalize single-string settings (AUTH_USER_MODEL, ROOT_URLCONF, DEFAULT_AUTO_FIELD)

**Files:**
- Modify: `app/stages/plugins/django/settings.py`
- Test: `tests/unit/test_django_settings_plugin.py`

**Context:** These three settings are always a single string assignment. The raw `value` from the extractor is usually the quoted literal itself — `'"auth.User"'` or `"'blog_project.urls'"`. Strip the quotes and store the clean value under a key named after the setting's semantic role. No parse call needed — a tiny dedicated helper.

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestSingleStringSettings:
    def test_strip_string_literal_double_quotes(self):
        from app.stages.plugins.django.settings import strip_string_literal

        assert strip_string_literal('"auth.User"') == "auth.User"

    def test_strip_string_literal_single_quotes(self):
        from app.stages.plugins.django.settings import strip_string_literal

        assert strip_string_literal("'blog_project.urls'") == "blog_project.urls"

    def test_strip_string_literal_unquoted_fallback(self):
        from app.stages.plugins.django.settings import strip_string_literal

        # If the value is already unquoted or the literal isn't well-formed,
        # return the trimmed input rather than raising.
        assert strip_string_literal("not.quoted") == "not.quoted"
        assert strip_string_literal("  leading space  ") == "leading space"
        assert strip_string_literal("") == ""

    @pytest.mark.asyncio
    async def test_extract_emits_model_urlconf_field_properties(self):
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
        graph.add_node(module)
        graph.add_node(anchor)
        graph.add_edge(
            GraphEdge(
                source_fqn=module.fqn,
                target_fqn=anchor.fqn,
                kind=EdgeKind.CONTAINS,
                confidence=Confidence.HIGH,
                evidence="test-setup",
            )
        )

        singles = {
            "AUTH_USER_MODEL": ('"auth.User"', "model", "auth.User"),
            "ROOT_URLCONF": ('"blog_project.urls"', "urlconf", "blog_project.urls"),
            "DEFAULT_AUTO_FIELD": (
                '"django.db.models.BigAutoField"',
                "field_class",
                "django.db.models.BigAutoField",
            ),
        }
        for name, (raw, _prop_key, _expected) in singles.items():
            node = GraphNode(
                fqn=f"m.settings.{name}",
                name=name,
                kind=NodeKind.FIELD,
                language="python",
                properties={"value": raw},
            )
            graph.add_node(node)
            graph.add_edge(
                GraphEdge(
                    source_fqn=module.fqn,
                    target_fqn=node.fqn,
                    kind=EdgeKind.CONTAINS,
                    confidence=Confidence.HIGH,
                    evidence="test-setup",
                )
            )

        ctx = AnalysisContext(project_id="t", graph=graph)
        result = await DjangoSettingsPlugin().extract(ctx)

        entries = {n.name: n for n in result.nodes if n.kind == NodeKind.CONFIG_ENTRY}
        for name, (_raw, prop_key, expected) in singles.items():
            assert entries[name].properties[prop_key] == expected
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/unit/test_django_settings_plugin.py::TestSingleStringSettings -v
```

- [ ] **Step 3: Implement `strip_string_literal`**

Add below `parse_middleware`:

```python
def strip_string_literal(raw_value: str) -> str:
    """Strip surrounding single or double quotes from a string-literal RHS.

    Returns the trimmed input unchanged when it isn't a well-formed literal.
    Never raises.
    """
    trimmed = raw_value.strip()
    if len(trimmed) >= 2:
        if trimmed[0] == trimmed[-1] and trimmed[0] in {'"', "'"}:
            return trimmed[1:-1]
    return trimmed
```

- [ ] **Step 4: Wire into `extract()`**

Extend:

```python
            elif field_node.name == "MIDDLEWARE":
                entry_properties["middleware"] = parse_middleware(raw_value)
            elif field_node.name == "AUTH_USER_MODEL":
                entry_properties["model"] = strip_string_literal(raw_value)
            elif field_node.name == "ROOT_URLCONF":
                entry_properties["urlconf"] = strip_string_literal(raw_value)
            elif field_node.name == "DEFAULT_AUTO_FIELD":
                entry_properties["field_class"] = strip_string_literal(raw_value)
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/unit/test_django_settings_plugin.py::TestSingleStringSettings -v
uv run pytest tests/unit/test_django_settings_plugin.py -v
```

Second command confirms no regression in pre-existing tests.

- [ ] **Step 6: Ruff + mypy**

```bash
uv run ruff check app/stages/plugins/django/settings.py tests/unit/test_django_settings_plugin.py
uv run mypy app/stages/plugins/django/settings.py
```

- [ ] **Step 7: Commit**

```bash
git add app/stages/plugins/django/settings.py tests/unit/test_django_settings_plugin.py
git commit -m "feat(django-settings): normalize AUTH_USER_MODEL, ROOT_URLCONF, DEFAULT_AUTO_FIELD"
```

---

## Task 6: Django settings integration test against the django-blog fixture

**Files:**
- Test: `tests/integration/test_python_m2_plugins.py` (new file)

**Context:** Every structured-value parser has unit tests; this is the end-to-end check that the plugin, driven through the full Stage 1–3 + plugin pipeline, extracts the right values from the real `django-blog` fixture authored in M1.

- [ ] **Step 1: Create the test file with the Django settings class**

Create `tests/integration/test_python_m2_plugins.py`:

```python
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
        assert middleware[0] == "django.middleware.security.SecurityMiddleware", middleware

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
```

- [ ] **Step 2: Run — expect PASS**

```bash
cd cast-clone-backend
uv run pytest tests/integration/test_python_m2_plugins.py::TestDjangoSettingsM2 -v -m integration
```

Expected: 1 passed. If any assertion fails, print the extracted properties (`print(entries)`) temporarily, inspect the actual shape, and decide whether to correct the parser (M1 Task 20 pattern) or the assertion — err on correcting the parser if the value is genuinely off.

- [ ] **Step 3: Ruff**

```bash
uv run ruff check tests/integration/test_python_m2_plugins.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_python_m2_plugins.py
git commit -m "test(integration): django settings M2 structured extraction against django-blog"
```

---

## Task 7: SQLAlchemy 2.0 async-style regression tests on fastapi-todo

**Files:**
- Test: `tests/unit/test_sqlalchemy_plugin.py`
- Test: `tests/integration/test_python_m2_plugins.py`

**Context:** The existing `SQLAlchemyPlugin` already recognizes `mapped_column(...)` via the `_COLUMN_RE` regex (`app/stages/plugins/sqlalchemy_plugin/models.py:34`). M2's "async SQLAlchemy recognition" requirement is therefore a verification task: pin down the contract with tests that use SQLAlchemy 2.0 async-style models. If the existing plugin already produces the expected tables/columns from `fastapi-todo`, these tests pass immediately (outcome-A pattern from M1 Task 11). If gaps surface, fix them targeted and keep scope tight.

- [ ] **Step 1: Add a unit test exercising mapped_column parsing directly**

Append to `tests/unit/test_sqlalchemy_plugin.py`:

```python
class TestSQLAlchemy20AsyncStyle:
    @pytest.mark.asyncio
    async def test_mapped_column_model_extracted(self):
        """A SQLAlchemy 2.0 model (DeclarativeBase + mapped_column) produces
        a Table node and a Column node per field."""
        from app.models.context import AnalysisContext
        from app.models.enums import Confidence, EdgeKind, NodeKind
        from app.models.graph import GraphEdge, GraphNode, SymbolGraph
        from app.stages.plugins.sqlalchemy_plugin.models import SQLAlchemyPlugin

        graph = SymbolGraph()
        klass = GraphNode(
            fqn="myapp.models.User",
            name="User",
            kind=NodeKind.CLASS,
            language="python",
        )
        tablename = GraphNode(
            fqn="myapp.models.User.__tablename__",
            name="__tablename__",
            kind=NodeKind.FIELD,
            language="python",
            properties={"value": '"users"'},
        )
        id_col = GraphNode(
            fqn="myapp.models.User.id",
            name="id",
            kind=NodeKind.FIELD,
            language="python",
            properties={"value": "mapped_column(Integer, primary_key=True)"},
        )
        email_col = GraphNode(
            fqn="myapp.models.User.email",
            name="email",
            kind=NodeKind.FIELD,
            language="python",
            properties={
                "value": "mapped_column(String(255), unique=True, nullable=False)"
            },
        )
        for node in (klass, tablename, id_col, email_col):
            graph.add_node(node)
        for child in (tablename, id_col, email_col):
            graph.add_edge(
                GraphEdge(
                    source_fqn=klass.fqn,
                    target_fqn=child.fqn,
                    kind=EdgeKind.CONTAINS,
                    confidence=Confidence.HIGH,
                    evidence="test-setup",
                )
            )

        ctx = AnalysisContext(project_id="t", graph=graph)
        result = await SQLAlchemyPlugin().extract(ctx)

        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "users"

        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        col_names = {c.name for c in column_nodes}
        assert col_names == {"id", "email"}

        # Primary-key flag is set on `id` from the `primary_key=True` kwarg.
        id_node = next(c for c in column_nodes if c.name == "id")
        assert id_node.properties["is_primary_key"] is True
        email_node = next(c for c in column_nodes if c.name == "email")
        assert email_node.properties["is_primary_key"] is False

    def test_foreign_key_in_mapped_column_captured(self):
        """A mapped_column with ForeignKey still emits a REFERENCES edge."""
        from app.models.context import AnalysisContext
        from app.models.enums import Confidence, EdgeKind, NodeKind
        from app.models.graph import GraphEdge, GraphNode, SymbolGraph
        from app.stages.plugins.sqlalchemy_plugin.models import SQLAlchemyPlugin

        graph = SymbolGraph()
        klass = GraphNode(
            fqn="myapp.models.Todo",
            name="Todo",
            kind=NodeKind.CLASS,
            language="python",
        )
        tablename = GraphNode(
            fqn="myapp.models.Todo.__tablename__",
            name="__tablename__",
            kind=NodeKind.FIELD,
            language="python",
            properties={"value": '"todos"'},
        )
        fk_col = GraphNode(
            fqn="myapp.models.Todo.owner_id",
            name="owner_id",
            kind=NodeKind.FIELD,
            language="python",
            properties={
                "value": (
                    'mapped_column(ForeignKey("users.id", ondelete="CASCADE"), '
                    "nullable=False)"
                )
            },
        )
        for node in (klass, tablename, fk_col):
            graph.add_node(node)
        for child in (tablename, fk_col):
            graph.add_edge(
                GraphEdge(
                    source_fqn=klass.fqn,
                    target_fqn=child.fqn,
                    kind=EdgeKind.CONTAINS,
                    confidence=Confidence.HIGH,
                    evidence="test-setup",
                )
            )

        ctx = AnalysisContext(project_id="t", graph=graph)
        import asyncio

        result = asyncio.run(SQLAlchemyPlugin().extract(ctx))

        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) == 1
        assert ref_edges[0].target_fqn == "table:users.id"
        assert ref_edges[0].source_fqn == "table:todos.owner_id"
```

- [ ] **Step 2: Run — expect PASS if the plugin already handles SQLAlchemy 2.0, FAIL otherwise**

```bash
uv run pytest tests/unit/test_sqlalchemy_plugin.py::TestSQLAlchemy20AsyncStyle -v
```

Two outcomes:

**(A) All 2 tests PASS immediately.** The plugin already works for SQLAlchemy 2.0. Proceed to Step 4 (integration test). No plugin changes.

**(B) One or both tests FAIL.** Inspect the failure. Most likely the `_COLUMN_RE` regex or `_extract_columns` logic needs a small tweak. Make the minimum change to `app/stages/plugins/sqlalchemy_plugin/models.py` that lets the tests pass. DO NOT restructure the plugin.

- [ ] **Step 3 (only if B): Targeted plugin fix**

If Step 2 failed, the most likely culprit is the `_COLUMN_RE`, `_FK_RE`, or `_PK_RE` regex. For each failing test, add a print statement, run the test once to confirm the shape of the `value`, delete the print, then adjust the regex. Commit only the narrowest possible change.

- [ ] **Step 4: Add integration test for the fastapi-todo fixture**

Append to `tests/integration/test_python_m2_plugins.py`:

```python
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
        # A handful of the expected (table, column) pairs — tight enough to
        # catch regressions, loose enough to tolerate benign future additions.
        for expected in [
            ("users", "id"),
            ("users", "email"),
            ("todos", "id"),
            ("todos", "owner_id"),
        ]:
            assert expected in columns, f"missing {expected}; got {columns}"

        # Foreign key todos.owner_id -> users.id must be captured.
        refs = {
            (e.source_fqn, e.target_fqn)
            for e in result.edges
            if e.kind == EdgeKind.REFERENCES
        }
        assert ("table:todos.owner_id", "table:users.id") in refs, refs
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/integration/test_python_m2_plugins.py::TestSQLAlchemy20AsyncM2 -v -m integration
```

- [ ] **Step 6: Ruff**

```bash
uv run ruff check tests/unit/test_sqlalchemy_plugin.py tests/integration/test_python_m2_plugins.py app/stages/plugins/sqlalchemy_plugin/models.py
```

- [ ] **Step 7: Commit**

If outcome A (no plugin change):

```bash
git add tests/unit/test_sqlalchemy_plugin.py tests/integration/test_python_m2_plugins.py
git commit -m "test(sqlalchemy): pin SQLAlchemy 2.0 async-style extraction contract"
```

If outcome B (plugin changed):

```bash
git add app/stages/plugins/sqlalchemy_plugin/models.py tests/unit/test_sqlalchemy_plugin.py tests/integration/test_python_m2_plugins.py
git commit -m "feat(sqlalchemy): recognize SQLAlchemy 2.0 async-style <what>"
```

…with `<what>` specifying the exact narrow change (e.g. `mapped_column with ForeignKey kwarg`).

---

## Task 8: Alembic plugin — skeleton (class, detection, empty extract)

**Files:**
- Create: `app/stages/plugins/alembic_plugin/__init__.py`
- Create: `app/stages/plugins/alembic_plugin/migrations.py`
- Test: `tests/unit/test_alembic_plugin.py`

**Context:** Plugin precedent is `app/stages/plugins/sql/migration.py` (744 lines) — read it to confirm the shape of `detect()` + `extract()` but do NOT inherit from it. Alembic and Flyway/Liquibase diverge enough that independent modules are clearer.

Detection anchors (any one of these suffices):
- A file named `alembic.ini` in the project root.
- A file under `migrations/env.py` with `from alembic import context`.

The skeleton returns an empty `PluginResult` when detected. Downstream tasks (9-11) add the actual parser.

- [ ] **Step 1: Write the failing detection test**

Create `tests/unit/test_alembic_plugin.py`:

```python
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

        (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = migrations\n")

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
```

- [ ] **Step 2: Run — expect FAIL on ModuleNotFoundError**

```bash
uv run pytest tests/unit/test_alembic_plugin.py -v
```

- [ ] **Step 3: Create the plugin skeleton**

Create `app/stages/plugins/alembic_plugin/__init__.py` — empty file.

Create `app/stages/plugins/alembic_plugin/migrations.py`:

```python
"""Alembic migration plugin.

Parses files under `migrations/versions/*.py` to reconstruct the revision
chain as a DAG:

- Each migration file becomes a CONFIG_FILE node with `revision_id`,
  `down_revision`, and `upgrade_ops` / `downgrade_ops` properties.
- An INHERITS edge from revision -> down_revision encodes the chain.

The parser uses the stdlib `ast` module (not regex) so nested keyword args
inside `op.*` calls don't break extraction.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from app.models.context import AnalysisContext
from app.models.enums import Confidence
from app.models.graph import GraphEdge, GraphNode
from app.stages.plugins.base import (
    FrameworkPlugin,
    PluginDetectionResult,
    PluginResult,
)

logger = structlog.get_logger()


class AlembicPlugin(FrameworkPlugin):
    name = "alembic"
    version = "1.0.0"
    supported_languages = {"python"}
    depends_on: list[str] = []

    def detect(self, context: AnalysisContext) -> PluginDetectionResult:
        if context.manifest is None:
            return PluginDetectionResult.not_detected()

        root = context.manifest.root_path
        ini = root / "alembic.ini"
        if ini.is_file():
            return PluginDetectionResult(
                confidence=Confidence.HIGH,
                reason="alembic.ini present at project root",
            )

        env_py = root / "migrations" / "env.py"
        if env_py.is_file():
            try:
                text = env_py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return PluginDetectionResult.not_detected()
            if "from alembic import" in text:
                return PluginDetectionResult(
                    confidence=Confidence.HIGH,
                    reason="migrations/env.py imports alembic",
                )

        return PluginDetectionResult.not_detected()

    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("alembic_extract_start")

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []

        # Task 9 populates nodes; Task 10 populates per-revision op lists;
        # Task 11 adds INHERITS edges.

        log.info(
            "alembic_extract_complete",
            nodes=len(nodes),
            edges=len(edges),
        )
        return PluginResult(
            nodes=nodes,
            edges=edges,
            layer_assignments={},
            entry_points=[],
            warnings=warnings,
        )
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/unit/test_alembic_plugin.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Ruff + mypy**

```bash
uv run ruff check app/stages/plugins/alembic_plugin/ tests/unit/test_alembic_plugin.py
uv run mypy app/stages/plugins/alembic_plugin/migrations.py
```

- [ ] **Step 6: Commit**

```bash
git add app/stages/plugins/alembic_plugin/ tests/unit/test_alembic_plugin.py
git commit -m "feat(alembic): plugin skeleton with detection via ini/env.py"
```

---

## Task 9: Alembic plugin — parse revision metadata into CONFIG_FILE nodes

**Files:**
- Modify: `app/stages/plugins/alembic_plugin/migrations.py`
- Test: `tests/unit/test_alembic_plugin.py`

**Context:** Each `migrations/versions/NNN_*.py` file contains module-level string assignments: `revision = "..."`, `down_revision = "..." | None`, `branch_labels = ...`, `depends_on = ...`. The parser walks the AST module-level assignments and extracts `revision` and `down_revision`. Each migration becomes a `CONFIG_FILE` node keyed by its revision id.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_alembic_plugin.py`:

```python
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
```

- [ ] **Step 2: Run — expect FAIL on ImportError**

```bash
uv run pytest tests/unit/test_alembic_plugin.py::TestAlembicRevisionParsing -v
```

- [ ] **Step 3: Implement `parse_migration_file` + `MigrationInfo`**

Add to `app/stages/plugins/alembic_plugin/migrations.py` above `AlembicPlugin`:

```python
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class MigrationInfo:
    """Static metadata extracted from a single Alembic migration file."""

    file_path: Path
    revision_id: str
    down_revision: str | None


def parse_migration_file(path: Path) -> MigrationInfo | None:
    """Parse an Alembic migration file's module-level metadata.

    Returns None if:
    - The file cannot be read.
    - The file has a Python syntax error.
    - The file has no `revision = "..."` module-level assignment.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    revision: str | None = None
    down_revision: str | None = None

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        target_name = node.targets[0].id
        if target_name == "revision":
            revision = _literal_string_or_none(node.value)
        elif target_name == "down_revision":
            down_revision = _literal_string_or_none(node.value)

    if revision is None:
        return None

    return MigrationInfo(
        file_path=path,
        revision_id=revision,
        down_revision=down_revision,
    )


def _literal_string_or_none(value: ast.expr) -> str | None:
    """Return the string literal value, or None for `None`/non-literal exprs."""
    if isinstance(value, ast.Constant):
        if isinstance(value.value, str):
            return value.value
        if value.value is None:
            return None
    return None
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/unit/test_alembic_plugin.py::TestAlembicRevisionParsing -v
```

Expected: 4 passed.

- [ ] **Step 5: Hook parsing into `extract()` — emit CONFIG_FILE nodes**

Replace the body of `AlembicPlugin.extract()` with:

```python
    async def extract(self, context: AnalysisContext) -> PluginResult:
        log = logger.bind(plugin=self.name)
        log.info("alembic_extract_start")

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        warnings: list[str] = []

        if context.manifest is None:
            log.warning("alembic_extract_no_manifest")
            return PluginResult(
                nodes=nodes, edges=edges, layer_assignments={},
                entry_points=[], warnings=warnings,
            )

        versions_dir = self._find_versions_dir(context.manifest.root_path)
        if versions_dir is None:
            log.info("alembic_no_versions_dir")
            return PluginResult(
                nodes=nodes, edges=edges, layer_assignments={},
                entry_points=[], warnings=warnings,
            )

        migrations: list[MigrationInfo] = []
        for py_file in sorted(versions_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            info = parse_migration_file(py_file)
            if info is None:
                warnings.append(f"Skipped unparseable migration file: {py_file.name}")
                continue
            migrations.append(info)

        for info in migrations:
            node = GraphNode(
                fqn=f"alembic:{info.revision_id}",
                name=info.revision_id,
                kind=NodeKind.CONFIG_FILE,
                language="python",
                properties={
                    "revision_id": info.revision_id,
                    "down_revision": info.down_revision,
                    "file_path": str(info.file_path),
                },
            )
            nodes.append(node)

        log.info(
            "alembic_extract_complete",
            migrations=len(migrations),
            warnings=len(warnings),
        )
        return PluginResult(
            nodes=nodes, edges=edges, layer_assignments={},
            entry_points=[], warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_versions_dir(self, root: Path) -> Path | None:
        """Find the Alembic versions directory relative to project root.

        Alembic defaults put it under `migrations/versions/`; the plan assumes
        that convention. If `alembic.ini` specifies a different `script_location`,
        honor it when possible (the ini file is small enough to scan cheaply).
        """
        # Default first.
        default = root / "migrations" / "versions"
        if default.is_dir():
            return default

        ini = root / "alembic.ini"
        if ini.is_file():
            try:
                text = ini.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("script_location"):
                    _, _, value = stripped.partition("=")
                    script_location = value.strip()
                    if script_location:
                        candidate = root / script_location / "versions"
                        if candidate.is_dir():
                            return candidate
        return None
```

Add the required import at the top of the file:

```python
from app.models.enums import NodeKind
```

(`Confidence` is already imported for `detect()`.)

- [ ] **Step 6: Extend the `TestAlembicEmptyExtract` class with a populated-extract test**

Append to the existing `TestAlembicEmptyExtract` class (or a new class — either works):

```python
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
```

- [ ] **Step 7: Run — expect PASS**

```bash
uv run pytest tests/unit/test_alembic_plugin.py -v
```

Expected: 8 passed (4 prior + 4 new — 3 revision tests + 1 extract test).

- [ ] **Step 8: Ruff + mypy**

```bash
uv run ruff check app/stages/plugins/alembic_plugin/ tests/unit/test_alembic_plugin.py
uv run mypy app/stages/plugins/alembic_plugin/migrations.py
```

- [ ] **Step 9: Commit**

```bash
git add app/stages/plugins/alembic_plugin/migrations.py tests/unit/test_alembic_plugin.py
git commit -m "feat(alembic): parse revision metadata and emit CONFIG_FILE nodes"
```

---

## Task 10: Alembic plugin — extract `op.*` calls inside upgrade/downgrade

**Files:**
- Modify: `app/stages/plugins/alembic_plugin/migrations.py`
- Test: `tests/unit/test_alembic_plugin.py`

**Context:** Per the spec, the plugin "parses `upgrade()`/`downgrade()` + `op.*` calls" — capturing the table/column that each migration touches is what makes the graph useful for impact analysis (e.g. "which migration added column X?"). Store the captured op summaries on the CONFIG_FILE node's properties as `upgrade_ops` and `downgrade_ops`.

Each op summary is a plain dict like `{"op": "create_table", "target": "users"}`. We capture only the common ops: `create_table`, `drop_table`, `add_column`, `drop_column`, `rename_table`, `alter_column`. Other op calls are logged and skipped so the plugin stays deterministic and small.

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestAlembicOpExtraction:
    def test_upgrade_create_table_captured(self, tmp_path: Path):
        from app.stages.plugins.alembic_plugin.migrations import (
            extract_ops_from_function,
            parse_migration_file,
        )

        src = (
            "from alembic import op\n"
            "import sqlalchemy as sa\n\n"
            'revision = "001"\n'
            "down_revision = None\n\n"
            "def upgrade() -> None:\n"
            '    op.create_table("users", sa.Column("id", sa.Integer, primary_key=True))\n\n'
            "def downgrade() -> None:\n"
            '    op.drop_table("users")\n"'
            "\n"
        )
        path = tmp_path / "001.py"
        path.write_text(src)

        import ast

        tree = ast.parse(path.read_text())
        funcs = {
            fn.name: fn for fn in tree.body if isinstance(fn, ast.FunctionDef)
        }

        upgrade_ops = extract_ops_from_function(funcs["upgrade"])
        downgrade_ops = extract_ops_from_function(funcs["downgrade"])

        assert upgrade_ops == [{"op": "create_table", "target": "users"}]
        assert downgrade_ops == [{"op": "drop_table", "target": "users"}]

    def test_add_drop_column_captured(self, tmp_path: Path):
        from app.stages.plugins.alembic_plugin.migrations import (
            extract_ops_from_function,
        )

        import ast

        src = (
            "def upgrade():\n"
            '    op.add_column("todos", sa.Column("completed", sa.Boolean, nullable=False))\n'
            "\n"
            "def downgrade():\n"
            '    op.drop_column("todos", "completed")\n'
        )
        tree = ast.parse(src)
        funcs = {fn.name: fn for fn in tree.body if isinstance(fn, ast.FunctionDef)}

        assert extract_ops_from_function(funcs["upgrade"]) == [
            {"op": "add_column", "target": "todos", "column": "completed"},
        ]
        assert extract_ops_from_function(funcs["downgrade"]) == [
            {"op": "drop_column", "target": "todos", "column": "completed"},
        ]

    def test_unknown_op_ignored(self):
        from app.stages.plugins.alembic_plugin.migrations import (
            extract_ops_from_function,
        )

        import ast

        src = (
            "def upgrade():\n"
            '    op.execute("UPDATE users SET deleted = 0")\n'
            '    op.create_table("x")\n'
        )
        tree = ast.parse(src)
        funcs = {fn.name: fn for fn in tree.body if isinstance(fn, ast.FunctionDef)}

        # `op.execute` is not in the captured-ops whitelist.
        ops = extract_ops_from_function(funcs["upgrade"])
        assert ops == [{"op": "create_table", "target": "x"}]

    @pytest.mark.asyncio
    async def test_extract_populates_ops_on_config_file_node(
        self, tmp_path: Path
    ):
        from app.models.context import AnalysisContext
        from app.models.enums import NodeKind
        from app.models.graph import SymbolGraph
        from app.models.manifest import ProjectManifest
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        versions = tmp_path / "migrations" / "versions"
        versions.mkdir(parents=True)
        (versions / "001.py").write_text(
            "from alembic import op\n"
            "import sqlalchemy as sa\n\n"
            'revision = "001"\n'
            "down_revision = None\n\n"
            "def upgrade() -> None:\n"
            '    op.create_table("users", sa.Column("id", sa.Integer, primary_key=True))\n\n'
            "def downgrade() -> None:\n"
            '    op.drop_table("users")\n'
        )

        manifest = ProjectManifest(root_path=tmp_path)
        ctx = AnalysisContext(project_id="t", graph=SymbolGraph(), manifest=manifest)

        result = await AlembicPlugin().extract(ctx)

        cfn = next(n for n in result.nodes if n.kind == NodeKind.CONFIG_FILE)
        assert cfn.properties["upgrade_ops"] == [
            {"op": "create_table", "target": "users"},
        ]
        assert cfn.properties["downgrade_ops"] == [
            {"op": "drop_table", "target": "users"},
        ]
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/unit/test_alembic_plugin.py::TestAlembicOpExtraction -v
```

- [ ] **Step 3: Implement `extract_ops_from_function`**

Add to `migrations.py` below `_literal_string_or_none`:

```python
_SINGLE_TARGET_OPS = frozenset({"create_table", "drop_table"})
_TABLE_COLUMN_OPS = frozenset({"add_column", "drop_column"})
# alter_column / rename_table captured with target only — full modeling is M3+.
_OTHER_TABLE_OPS = frozenset({"alter_column", "rename_table"})


def extract_ops_from_function(func: ast.FunctionDef) -> list[dict[str, str]]:
    """Scan a function body for `op.<known_name>(...)` calls.

    Returns a list of summary dicts — one per recognized op call — preserving
    source order. Unknown ops (e.g. `op.execute`, `op.bulk_insert`) are
    silently skipped rather than raised, so an unfamiliar Alembic pattern in
    one file doesn't hide the rest of the migration.
    """
    ops: list[dict[str, str]] = []
    for stmt in ast.walk(func):
        if not isinstance(stmt, ast.Call):
            continue
        func_expr = stmt.func
        if not (
            isinstance(func_expr, ast.Attribute)
            and isinstance(func_expr.value, ast.Name)
            and func_expr.value.id == "op"
        ):
            continue
        op_name = func_expr.attr
        if op_name in _SINGLE_TARGET_OPS:
            target = _first_string_arg(stmt.args)
            if target is not None:
                ops.append({"op": op_name, "target": target})
        elif op_name in _TABLE_COLUMN_OPS:
            table = _first_string_arg(stmt.args)
            if table is None:
                continue
            # Alembic: add_column(table, sa.Column("name", ...))
            #          drop_column(table, "name")
            column = _second_string_arg(stmt.args)
            if column is None:
                column = _column_name_from_sa_column(stmt.args)
            if column is not None:
                ops.append({"op": op_name, "target": table, "column": column})
        elif op_name in _OTHER_TABLE_OPS:
            target = _first_string_arg(stmt.args)
            if target is not None:
                ops.append({"op": op_name, "target": target})
    return ops


def _first_string_arg(args: list[ast.expr]) -> str | None:
    if not args:
        return None
    first = args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _second_string_arg(args: list[ast.expr]) -> str | None:
    if len(args) < 2:
        return None
    second = args[1]
    if isinstance(second, ast.Constant) and isinstance(second.value, str):
        return second.value
    return None


def _column_name_from_sa_column(args: list[ast.expr]) -> str | None:
    """Extract the column name from a `sa.Column("name", ...)` arg."""
    if len(args) < 2:
        return None
    second = args[1]
    if not isinstance(second, ast.Call):
        return None
    func_expr = second.func
    # Accept both `sa.Column(...)` and `Column(...)`.
    is_sa_column = (
        isinstance(func_expr, ast.Attribute)
        and func_expr.attr == "Column"
    )
    is_bare_column = isinstance(func_expr, ast.Name) and func_expr.id == "Column"
    if not (is_sa_column or is_bare_column):
        return None
    return _first_string_arg(second.args)
```

- [ ] **Step 4: Wire ops into `extract()`**

Extend `MigrationInfo` to carry parsed op lists:

```python
@dataclass(frozen=True)
class MigrationInfo:
    file_path: Path
    revision_id: str
    down_revision: str | None
    upgrade_ops: list[dict[str, str]]
    downgrade_ops: list[dict[str, str]]
```

Update `parse_migration_file` to fill those fields:

```python
def parse_migration_file(path: Path) -> MigrationInfo | None:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    revision: str | None = None
    down_revision: str | None = None
    upgrade_ops: list[dict[str, str]] = []
    downgrade_ops: list[dict[str, str]] = []

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            target_name = node.targets[0].id
            if target_name == "revision":
                revision = _literal_string_or_none(node.value)
            elif target_name == "down_revision":
                down_revision = _literal_string_or_none(node.value)
        elif isinstance(node, ast.FunctionDef):
            if node.name == "upgrade":
                upgrade_ops = extract_ops_from_function(node)
            elif node.name == "downgrade":
                downgrade_ops = extract_ops_from_function(node)

    if revision is None:
        return None

    return MigrationInfo(
        file_path=path,
        revision_id=revision,
        down_revision=down_revision,
        upgrade_ops=upgrade_ops,
        downgrade_ops=downgrade_ops,
    )
```

Update `extract()` to copy ops into node properties:

```python
        for info in migrations:
            node = GraphNode(
                fqn=f"alembic:{info.revision_id}",
                name=info.revision_id,
                kind=NodeKind.CONFIG_FILE,
                language="python",
                properties={
                    "revision_id": info.revision_id,
                    "down_revision": info.down_revision,
                    "file_path": str(info.file_path),
                    "upgrade_ops": info.upgrade_ops,
                    "downgrade_ops": info.downgrade_ops,
                },
            )
            nodes.append(node)
```

- [ ] **Step 5: Update prior revision-parsing tests that assumed the old MigrationInfo shape**

The tests in `TestAlembicRevisionParsing` (Task 9) will now fail if they compare a full `MigrationInfo` dataclass instance. They shouldn't — they access individual fields — but if any does, update to pass explicit default lists:

```python
# Example if needed:
# info.upgrade_ops == []
# info.downgrade_ops == []
```

- [ ] **Step 6: Run — expect PASS**

```bash
uv run pytest tests/unit/test_alembic_plugin.py -v
```

Expected: 12 passed (8 prior + 4 new TestAlembicOpExtraction).

- [ ] **Step 7: Ruff + mypy**

```bash
uv run ruff check app/stages/plugins/alembic_plugin/ tests/unit/test_alembic_plugin.py
uv run mypy app/stages/plugins/alembic_plugin/migrations.py
```

- [ ] **Step 8: Commit**

```bash
git add app/stages/plugins/alembic_plugin/migrations.py tests/unit/test_alembic_plugin.py
git commit -m "feat(alembic): capture op.create_table/drop_table/add_column/drop_column calls"
```

---

## Task 11: Alembic plugin — INHERITS edges for revision chain

**Files:**
- Modify: `app/stages/plugins/alembic_plugin/migrations.py`
- Test: `tests/unit/test_alembic_plugin.py`

**Context:** The spec asks for "INHERITS edge between revision -> down_revision". This builds the DAG that answers "which migrations lead up to revision X?". Each CONFIG_FILE node gets one outgoing INHERITS edge to its parent (the one whose revision matches this node's `down_revision`). Root migrations (`down_revision = None`) have no outgoing INHERITS.

If `down_revision` points to a revision that doesn't exist in the versions dir, emit a warning and skip the edge rather than creating a dangling one.

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestAlembicRevisionChain:
    @pytest.mark.asyncio
    async def test_linear_chain_emits_inherits_edges(self, tmp_path: Path):
        from app.models.context import AnalysisContext
        from app.models.enums import EdgeKind
        from app.models.graph import SymbolGraph
        from app.models.manifest import ProjectManifest
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        versions = tmp_path / "migrations" / "versions"
        versions.mkdir(parents=True)
        (versions / "001_a.py").write_text(
            'revision = "001_a"\ndown_revision = None\n'
            "def upgrade(): pass\ndef downgrade(): pass\n"
        )
        (versions / "002_b.py").write_text(
            'revision = "002_b"\ndown_revision = "001_a"\n'
            "def upgrade(): pass\ndef downgrade(): pass\n"
        )
        (versions / "003_c.py").write_text(
            'revision = "003_c"\ndown_revision = "002_b"\n'
            "def upgrade(): pass\ndef downgrade(): pass\n"
        )

        manifest = ProjectManifest(root_path=tmp_path)
        ctx = AnalysisContext(project_id="t", graph=SymbolGraph(), manifest=manifest)
        result = await AlembicPlugin().extract(ctx)

        inherits = {
            (e.source_fqn, e.target_fqn)
            for e in result.edges
            if e.kind == EdgeKind.INHERITS
        }
        assert inherits == {
            ("alembic:002_b", "alembic:001_a"),
            ("alembic:003_c", "alembic:002_b"),
        }
        # Root migration has no outgoing INHERITS.
        assert ("alembic:001_a", "alembic:001_a") not in inherits

    @pytest.mark.asyncio
    async def test_dangling_down_revision_emits_warning_not_edge(
        self, tmp_path: Path
    ):
        from app.models.context import AnalysisContext
        from app.models.enums import EdgeKind
        from app.models.graph import SymbolGraph
        from app.models.manifest import ProjectManifest
        from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin

        versions = tmp_path / "migrations" / "versions"
        versions.mkdir(parents=True)
        (versions / "007.py").write_text(
            'revision = "007"\ndown_revision = "missing_parent"\n'
            "def upgrade(): pass\ndef downgrade(): pass\n"
        )

        manifest = ProjectManifest(root_path=tmp_path)
        ctx = AnalysisContext(project_id="t", graph=SymbolGraph(), manifest=manifest)
        result = await AlembicPlugin().extract(ctx)

        inherits = [e for e in result.edges if e.kind == EdgeKind.INHERITS]
        assert inherits == []
        assert any("missing_parent" in w for w in result.warnings), result.warnings
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/unit/test_alembic_plugin.py::TestAlembicRevisionChain -v
```

- [ ] **Step 3: Emit INHERITS edges in `extract()`**

Inside `extract()`, after the `for info in migrations:` loop, add:

```python
        known_revisions = {info.revision_id for info in migrations}
        for info in migrations:
            if info.down_revision is None:
                continue
            if info.down_revision not in known_revisions:
                warnings.append(
                    f"Migration {info.revision_id} references unknown parent "
                    f"{info.down_revision}; skipping INHERITS edge"
                )
                continue
            edges.append(
                GraphEdge(
                    source_fqn=f"alembic:{info.revision_id}",
                    target_fqn=f"alembic:{info.down_revision}",
                    kind=EdgeKind.INHERITS,
                    confidence=Confidence.HIGH,
                    evidence="alembic-revision-chain",
                )
            )
```

Add `EdgeKind` to the imports at the top of the file (it's already imported if you added it in Task 9 — verify; add if missing).

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/unit/test_alembic_plugin.py -v
```

Expected: 14 passed (12 prior + 2 new TestAlembicRevisionChain).

- [ ] **Step 5: Ruff + mypy**

```bash
uv run ruff check app/stages/plugins/alembic_plugin/ tests/unit/test_alembic_plugin.py
uv run mypy app/stages/plugins/alembic_plugin/migrations.py
```

- [ ] **Step 6: Commit**

```bash
git add app/stages/plugins/alembic_plugin/migrations.py tests/unit/test_alembic_plugin.py
git commit -m "feat(alembic): INHERITS edges form the revision chain DAG"
```

---

## Task 12: Register AlembicPlugin in the plugin registry

**Files:**
- Modify: `app/stages/plugins/registry.py` (or the plugin auto-discovery module)

**Context:** Plugin auto-discovery lives in `app/stages/plugins/registry.py`. Confirm by reading the existing file (it may auto-import everything under `app/stages/plugins/`, in which case adding the `alembic_plugin/` package already works — no registry change needed). If it uses an explicit list of plugins, add `AlembicPlugin` to that list.

- [ ] **Step 1: Inspect the registry**

```bash
cd cast-clone-backend
wc -l app/stages/plugins/registry.py
grep -n "SQLAlchemyPlugin\|DjangoSettingsPlugin\|FastAPIPlugin\|import " app/stages/plugins/registry.py | head -30
```

Check:
- Does it explicitly import `SQLAlchemyPlugin` and instantiate it, or does it auto-scan subdirs?
- If explicit: note the pattern (`from app.stages.plugins.django.settings import DjangoSettingsPlugin`) and follow it.

- [ ] **Step 2: Two paths**

**(A) If auto-discovery:** run the smoke test below; if AlembicPlugin is already picked up, commit an empty change (or just move to Task 13 — document the finding in your task report). No registry code change needed.

**(B) If explicit:** Add to the registry:

```python
from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin
```

And register it in whatever list/dict the existing plugins are registered in. Follow the existing pattern — do not restructure.

- [ ] **Step 3: Smoke test — confirm AlembicPlugin participates in plugin execution**

Add to `tests/unit/test_plugin_registry.py` (file already exists per CLAUDE.md — read it first to follow its style):

```python
class TestAlembicRegistration:
    def test_alembic_plugin_discovered(self):
        from app.stages.plugins.registry import get_all_plugins

        plugins = get_all_plugins()
        names = [p.name for p in plugins]
        assert "alembic" in names
```

Replace `get_all_plugins()` with the registry's actual accessor function — grep for it in `test_plugin_registry.py`.

- [ ] **Step 4: Run**

```bash
uv run pytest tests/unit/test_plugin_registry.py::TestAlembicRegistration -v
```

- [ ] **Step 5: Ruff**

```bash
uv run ruff check app/stages/plugins/registry.py tests/unit/test_plugin_registry.py
```

- [ ] **Step 6: Commit**

```bash
git add app/stages/plugins/registry.py tests/unit/test_plugin_registry.py
git commit -m "feat(plugins): register AlembicPlugin in plugin registry"
```

If path (A) left no code changes, the commit contains only the test file:

```bash
git add tests/unit/test_plugin_registry.py
git commit -m "test(plugins): confirm AlembicPlugin is auto-discovered"
```

---

## Task 13: Alembic integration test against fastapi-todo migrations

**Files:**
- Modify: `tests/integration/test_python_m2_plugins.py`

**Context:** Pin down the end-to-end contract against the `fastapi-todo` fixture authored in M1, which has two migrations (`001_initial.py` adds users + todos tables; `002_add_todo_completed.py` adds the `completed` column). This test is the acceptance gate for M2's third work item.

- [ ] **Step 1: Append to `tests/integration/test_python_m2_plugins.py`**

```python
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
```

- [ ] **Step 2: Run — expect PASS**

```bash
uv run pytest tests/integration/test_python_m2_plugins.py::TestAlembicMigrationsM2 -v -m integration
```

- [ ] **Step 3: Also run the full M2 integration file**

```bash
uv run pytest tests/integration/test_python_m2_plugins.py -v -m integration
```

Expected: 3 tests pass (Django settings from Task 6, SQLAlchemy from Task 7, Alembic from this task).

- [ ] **Step 4: Ruff**

```bash
uv run ruff check tests/integration/test_python_m2_plugins.py
```

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_python_m2_plugins.py
git commit -m "test(integration): alembic migration chain against fastapi-todo"
```

---

## Task 14: Full regression sweep

- [ ] **Step 1: Unit tests**

```bash
cd cast-clone-backend
uv run pytest tests/unit/ -v 2>&1 | tail -20
```

Flag any NEW failures vs the known pre-existing baseline documented in M1's Task 23 (list of pre-existing failures in the Python M1 plan, unchanged here).

- [ ] **Step 2: Integration tests (excluding scip_python)**

```bash
uv run pytest tests/integration/ -v -m "integration and not scip_python" 2>&1 | tail -20
```

Expected: M1's 7 tests + M2's 3 tests all pass; unchanged integration tests still pass.

- [ ] **Step 3: Ruff check**

```bash
uv run ruff check app/ tests/
```

Expected: no new violations. Count stays within the pre-existing baseline.

- [ ] **Step 4: Ruff format check on M2-touched files only**

```bash
uv run ruff format --check \
  app/stages/plugins/django/settings.py \
  app/stages/plugins/alembic_plugin/migrations.py \
  app/stages/plugins/alembic_plugin/__init__.py \
  app/stages/plugins/registry.py \
  tests/unit/test_django_settings_plugin.py \
  tests/unit/test_sqlalchemy_plugin.py \
  tests/unit/test_alembic_plugin.py \
  tests/unit/test_plugin_registry.py \
  tests/integration/test_python_m2_plugins.py
```

If any need formatting:

```bash
uv run ruff format \
  app/stages/plugins/django/settings.py \
  app/stages/plugins/alembic_plugin/migrations.py \
  app/stages/plugins/alembic_plugin/__init__.py \
  app/stages/plugins/registry.py \
  tests/unit/test_django_settings_plugin.py \
  tests/unit/test_sqlalchemy_plugin.py \
  tests/unit/test_alembic_plugin.py \
  tests/unit/test_plugin_registry.py \
  tests/integration/test_python_m2_plugins.py

git add -u
git commit -m "chore(format): ruff format after M2 changes" || echo "nothing to commit"
```

- [ ] **Step 5: Mypy on M2-touched app files**

```bash
uv run mypy \
  app/stages/plugins/django/settings.py \
  app/stages/plugins/alembic_plugin/migrations.py \
  app/stages/plugins/registry.py
```

Expected: no new mypy errors on these three files.

- [ ] **Step 6: Write a sweep report inline**

Report:
- Unit test pass/fail counts + any new failures.
- Integration test pass/fail counts.
- Ruff violation count (pre-existing baseline vs new).
- Mypy status on the 3 files.
- Verdict: GREEN / YELLOW / RED.

Do not create a separate doc file. No commit beyond the optional format commit.

---

## Task 15: Update docs and close out M2

**Files:**
- Modify: `cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md`
- Modify: `CLAUDE.md` (root — M1 added its note there; keep M2 consistent).

- [ ] **Step 1: Add M2 section to `08-FRAMEWORK-PLUGINS.md`**

Under the existing Python section (added in M1 at Task 24), append:

```markdown
### Python — Django settings + async SQLAlchemy + Alembic (M2 complete)

As of 2026-04-22, building on M1:
- **Django settings plugin** (`app/stages/plugins/django/settings.py`) parses structured values for INSTALLED_APPS, DATABASES (default engine/name/host/port), MIDDLEWARE, AUTH_USER_MODEL, ROOT_URLCONF, and DEFAULT_AUTO_FIELD. Downstream plugins can consume these as typed properties without re-parsing.
- **SQLAlchemy plugin** regression-pinned on SQLAlchemy 2.0 async-style models (`DeclarativeBase` + `Mapped[T]` + `mapped_column(...)`). ForeignKey REFERENCES edges work for both `Column(ForeignKey(...))` and `mapped_column(ForeignKey(...))`.
- **Alembic plugin** (`app/stages/plugins/alembic_plugin/`) — new. Detects via `alembic.ini` or `migrations/env.py`. Parses each `migrations/versions/*.py`, emits one CONFIG_FILE per revision with `upgrade_ops` / `downgrade_ops` capturing the common `op.*` calls (`create_table`, `drop_table`, `add_column`, `drop_column`, `alter_column`, `rename_table`). Emits INHERITS edges to form the revision chain DAG; dangling parents become warnings, not dangling edges.

Subsequent milestones (M3-M4) add Pydantic deep extraction, Celery, Flask, and integration polish.
```

- [ ] **Step 2: Update Plugin Priority note in the root `CLAUDE.md`**

Append a one-liner below the Python M1 note added in M1 Task 24:

```markdown
> **Python status (M2 complete, 2026-04-22):** Django settings enriched (structured INSTALLED_APPS/DATABASES/MIDDLEWARE/*); SQLAlchemy 2.0 async style pinned with tests; Alembic plugin landed with revision-chain DAG. M3 scheduled: Pydantic deep + Celery.
```

- [ ] **Step 3: Commit**

```bash
git add cast-clone-backend/docs/08-FRAMEWORK-PLUGINS.md CLAUDE.md
git commit -m "docs: M2 Django settings + SQLAlchemy 2.0 + Alembic complete"
```

- [ ] **Step 4: Do NOT push, do NOT open PR**

The user controls branch publication.

- [ ] **Step 5: Final branch summary**

```bash
git log --oneline main..HEAD
git log --oneline main..HEAD | wc -l
```

Report the commit count and full oneline log back to the reviewer.

---

## Summary

M2 delivers three spec work items with an additive, low-risk approach:

- **WI-1 (Django settings):** Tasks 1–6. Five targeted `parse_*` helpers + wiring + one integration test.
- **WI-2 (SQLAlchemy 2.0 async):** Task 7. Pin-down tests; targeted fix only if a regex gap surfaces.
- **WI-3 (Alembic plugin):** Tasks 8–13. Plugin skeleton -> revision metadata -> op capture -> INHERITS chain -> registry -> integration test.

Plus the usual close-out: Task 14 regression sweep, Task 15 docs.

---

## Test plan

- [ ] Unit tests: `uv run pytest tests/unit/ -v` — all green (pre-existing baseline unchanged).
- [ ] Integration tests: `uv run pytest tests/integration/test_python_m2_plugins.py -v -m integration` — 3 tests green.
- [ ] Alembic plugin units: `uv run pytest tests/unit/test_alembic_plugin.py -v` — 14 tests green.
- [ ] Ruff clean: `uv run ruff check app/ tests/`.
- [ ] Mypy clean on M2-touched files.

---

## Self-Review Notes

1. **Spec coverage** — M2 work items 1-3 map to:
   - Finish `DjangoSettingsPlugin.extract()` -> Tasks 2-6.
   - Async SQLAlchemy recognition -> Task 7.
   - Alembic plugin -> Tasks 8-13.
   - Acceptance criteria "Django fixture emits settings graph" -> Task 6 integration test.
   - Acceptance criteria "fastapi-todo Alembic migrations form a chained DAG" -> Task 13 integration test.
   - Acceptance criteria "async SQLAlchemy models recognized" -> Task 7 unit + integration tests.

2. **Type consistency** — `MigrationInfo` defined in Task 9, extended in Task 10 with `upgrade_ops`/`downgrade_ops` fields. Task 9's tests access only `revision_id`/`down_revision`/`file_path`, so the Task 10 extension does not break them. Plugin class name `AlembicPlugin` used consistently across Tasks 8-13. Config entry property names — `apps`, `default_engine`, `default_name`, `default_host`, `default_port`, `middleware`, `model`, `urlconf`, `field_class` — all defined once each and asserted in both unit and integration tests.

3. **No placeholders** — every task contains runnable code. No "add handling", no "similar to Task N", no bare TODOs.

4. **DRY** — `parse_installed_apps` and `parse_middleware` are structurally identical but named for their semantic role to keep log keys and error context accurate (documented in Task 4 context). Rest of the parsers are unique to their setting key's shape.

5. **Risks flagged in-plan**:
   - Task 1's reconnaissance may reveal `value` shape assumptions are wrong; each parser task has fallback guidance (adapt parser, not assertion).
   - Task 7 has explicit outcome-A vs outcome-B branches (regression tests vs targeted fix).
   - Task 12 has explicit (A) auto-discovery vs (B) explicit-registry branches.
