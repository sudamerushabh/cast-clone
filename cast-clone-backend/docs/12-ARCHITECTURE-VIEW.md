# True Architecture View — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current "Architecture View" (which is just the Dependency View with a different layout) with a true Application Architecture View that answers: *"What is this application made of?"* — showing technology layers, frameworks, databases, and their interactions, inspired by CAST Imaging's Level 4-5 views.

**What changes:** The Architecture View will show a completely different graph — technology nodes grouped by architectural layer — instead of module nodes with code dependencies. The Dependency View remains unchanged (module-level code coupling analysis).

---

## Context: What Exists Today

### All 14 Registered Plugins (from `plugins/__init__.py`)

| Plugin | Language | Layer Assignments | Key Nodes Produced |
|--------|----------|-------------------|--------------------|
| **SpringDIPlugin** | Java | Controller→Presentation, Service→Business Logic, Repository→Data Access, Configuration→Configuration | INJECTS edges |
| **SpringWebPlugin** | Java | handlers→Presentation | APIEndpoint (framework="spring") |
| **SpringDataPlugin** | Java | — | Edges for Spring Data repos |
| **HibernateJPAPlugin** | Java | — | Table, Column (evidence="hibernate") |
| **FastAPIPlugin** | Python | route handlers→Presentation | APIEndpoint (framework="fastapi") |
| **SQLAlchemyPlugin** | Python | — | Table, Column (evidence="sqlalchemy") |
| **DjangoSettingsPlugin** | Python | — | ConfigFile, ConfigEntry |
| **DjangoURLsPlugin** | Python | handlers→Presentation | APIEndpoint (framework="django") |
| **DjangoORMPlugin** | Python | — | Table, Column (evidence="django-orm") |
| **DjangoDRFPlugin** | Python | handlers→Presentation | APIEndpoint (framework="django-drf") |
| **ASPNetDIPlugin** | C# | Repository→Data Access, DbContext→Data Access, Service→Business Logic | INJECTS edges |
| **ASPNetWebPlugin** | C# | controllers→Presentation | APIEndpoint (framework="aspnet") |
| **ASPNetMiddlewarePlugin** | C# | — | Middleware chain edges |
| **EntityFrameworkPlugin** | C# | DbContext→Data Access | Table, Column (evidence="entity-framework") |

### Data Already in Neo4j After Analysis

- `Layer` nodes: "Presentation", "Business Logic", "Data Access", "Configuration"
- `Layer → CONTAINS → Class` edges
- `Application.frameworks[]`: e.g. `["spring-boot", "hibernate", "react"]`
- `Application.languages[]`: e.g. `["java", "typescript"]`
- `Class.framework` property (set by some plugins)
- `Class.properties["layer"]` — architectural layer from plugin `layer_assignments`
- `APIEndpoint` nodes with `framework` property
- `Table` nodes with evidence of which ORM created them
- `CALLS_API`, `MAPS_TO`, `INJECTS`, `HANDLES`, `EXPOSES` edges
- `Module` nodes with `language` property

### Frontend Infrastructure Already Built

- `graph-styles.ts`: `LAYER_COLORS` (Presentation=blue, Business=green, Data=orange, Utility=gray) + `buildStylesheet("layer")` — **exists but unused**
- `GraphView.tsx`: `colorBy?: "kind" | "layer"` prop — **defaults to "kind"**
- `cytoscape-elements.ts`: `modulesToElements()` — **no architecture-level converter**
- `graph_views.py` API: `/modules`, `/edges/aggregated` — **no architecture endpoint**

---

## Architecture: What We're Building

### The New Architecture View (CAST Imaging-inspired Levels)

**Level 1 — Layers:** Presentation → Business Logic → Data Access  
**Level 2 — Technologies within layers:** [React, JSP, JavaScript] in Presentation, [Spring Services, DTOs] in Business, [Hibernate, MySQL] in Data  
**Level 3 — Drill into a technology:** Double-click "Spring Services" to see individual service classes  

Each **Technology Node** aggregates:
- Name: e.g. "Spring Boot", "React", "MySQL", "FastAPI"
- Category: "web_framework", "orm", "database", "frontend_framework", "di_container", "language_runtime"
- Class count, LOC total, file count
- Language

**Edges** between technology nodes represent:
- CALLS_API: "React" → "Spring Web" (frontend calls backend)
- MAPS_TO: "Hibernate" → "MySQL" (ORM maps to database)
- INJECTS: "Spring DI" → "Spring Services" (DI container wires services)
- DEPENDS_ON: aggregated weight between technology groups

### Technology Classification Map

This is the core mapping that determines how classes are grouped into technology nodes. It must cover ALL languages and ALL plugins.

```python
# framework name (from detection or plugin) → Technology display info
TECHNOLOGY_MAP: dict[str, TechnologyInfo] = {
    # ── Java ──────────────────────────────────────────────
    "spring-boot":       TechnologyInfo(display="Spring Boot",      category="di_container",      language="java",       layer_hint="Business Logic"),
    "spring-web":        TechnologyInfo(display="Spring Web",       category="web_framework",     language="java",       layer_hint="Presentation"),
    "spring-data-jpa":   TechnologyInfo(display="Spring Data",      category="orm",               language="java",       layer_hint="Data Access"),
    "hibernate":         TechnologyInfo(display="Hibernate/JPA",    category="orm",               language="java",       layer_hint="Data Access"),

    # ── Python ────────────────────────────────────────────
    "fastapi":           TechnologyInfo(display="FastAPI",          category="web_framework",     language="python",     layer_hint="Presentation"),
    "django":            TechnologyInfo(display="Django",           category="web_framework",     language="python",     layer_hint="Presentation"),
    "django-drf":        TechnologyInfo(display="Django REST",      category="web_framework",     language="python",     layer_hint="Presentation"),
    "django-orm":        TechnologyInfo(display="Django ORM",       category="orm",               language="python",     layer_hint="Data Access"),
    "sqlalchemy":        TechnologyInfo(display="SQLAlchemy",       category="orm",               language="python",     layer_hint="Data Access"),

    # ── JavaScript/TypeScript ─────────────────────────────
    "react":             TechnologyInfo(display="React",            category="frontend_framework",language="javascript", layer_hint="Presentation"),
    "angular":           TechnologyInfo(display="Angular",          category="frontend_framework",language="typescript", layer_hint="Presentation"),
    "express":           TechnologyInfo(display="Express.js",       category="web_framework",     language="javascript", layer_hint="Presentation"),
    "nestjs":            TechnologyInfo(display="NestJS",           category="web_framework",     language="typescript", layer_hint="Presentation"),

    # ── C# / .NET ─────────────────────────────────────────
    "aspnet":            TechnologyInfo(display="ASP.NET Core",     category="web_framework",     language="csharp",     layer_hint="Presentation"),
    "entity-framework":  TechnologyInfo(display="Entity Framework", category="orm",               language="csharp",     layer_hint="Data Access"),
}
```

### What Happens to Unclassified Classes

Not every class belongs to a detected framework. The fallback grouping:

1. **Has `class.properties["layer"]`?** → Group under that layer's "Other {language} Classes" technology
2. **Has `class.language` but no layer?** → Group under "{Language} Utilities" in a generic "Utility" layer
3. **Classes with no framework and no layer** → "Unclassified" node (gray, shown only if non-empty)

### Database Detection (Cross-Language)

Database technology nodes are inferred from `Table` nodes. The `Table` node doesn't carry a database engine property directly, but we can infer it from:
- `Application.frameworks[]` containing "hibernate" + pom.xml having mysql-connector → MySQL
- `HibernateJPAPlugin` evidence → the database is whatever the JDBC driver points to
- `DjangoSettingsPlugin` → `ConfigEntry` nodes for `DATABASES.default.ENGINE`
- `EntityFrameworkPlugin` → connection string hints in `DbContext`
- **Fallback:** If we can't determine the specific database, create a generic "SQL Database" node

For Phase 1 of this feature, we use a simpler approach: look at `Application.frameworks[]` for known database indicators, and look at detected SQL dialects from the SQL parser plugin. If unresolvable, use "SQL Database".

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── stages/
│   │   └── enricher.py                      # MODIFY — add create_technology_nodes() step
│   ├── api/
│   │   └── graph_views.py                   # MODIFY — add /architecture endpoint
│   └── schemas/
│       └── graph_views.py                   # MODIFY — add ArchitectureResponse schemas

cast-clone-frontend/
├── lib/
│   ├── cytoscape-elements.ts                # MODIFY — add architectureToElements()
│   ├── api.ts                               # MODIFY — add getArchitecture()
│   └── graph-styles.ts                      # MODIFY — add technology category colors
├── hooks/
│   └── useGraph.ts                          # MODIFY — add loadArchitecture()
└── app/
    └── projects/
        └── [id]/
            └── graph/
                └── page.tsx                 # MODIFY — wire architecture view to new data source
```

---

## Task 1: Add Technology Classification to Enricher (Backend)

**File:** `cast-clone-backend/app/stages/enricher.py`
**Tests:** `cast-clone-backend/tests/unit/test_enricher.py`

### Overview

Add a new enrichment step `create_technology_nodes()` that runs AFTER `assign_architectural_layers()`. It reads the manifest's `detected_frameworks[]`, `Application.languages[]`, and class-level `framework`/`layer`/`annotations` properties to create `Technology` (using `Component` NodeKind) nodes grouped under `Layer` nodes.

**Why `Component` NodeKind?** The schema already defines `Component` with `Layer → CONTAINS → Component → CONTAINS → Class` — this is exactly the intermediate level we need. The `NodeKind.COMPONENT` and Neo4j label `Component` already exist in `graph.py`.

- [ ] **Step 1.1: Write the failing tests**

Add to `tests/unit/test_enricher.py`:

```python
# ── Test: Technology Node Creation ────────────────────────


class TestTechnologyNodes:
    def test_spring_java_app_creates_technology_nodes(self):
        """A Spring Boot app with annotated classes produces technology Component nodes."""
        g = SymbolGraph()

        # Application node with detected frameworks
        app = GraphNode(
            fqn="app:petclinic",
            name="petclinic",
            kind=NodeKind.APPLICATION,
            properties={
                "frameworks": ["spring-boot", "hibernate", "spring-data-jpa"],
                "languages": ["java"],
            },
        )
        g.add_node(app)

        # Classes with layer assignments (as plugins would set them)
        ctrl = _make_class("com.app.UserController")
        ctrl.properties["layer"] = "Presentation"
        ctrl.properties["framework"] = "spring-web"
        ctrl.language = "java"
        ctrl.loc = 100
        g.add_node(ctrl)

        svc = _make_class("com.app.UserService")
        svc.properties["layer"] = "Business Logic"
        svc.properties["framework"] = "spring-boot"
        svc.language = "java"
        svc.loc = 200
        g.add_node(svc)

        repo = _make_class("com.app.UserRepository")
        repo.properties["layer"] = "Data Access"
        repo.properties["framework"] = "spring-data-jpa"
        repo.language = "java"
        repo.loc = 50
        g.add_node(repo)

        # First run layer assignment, then technology nodes
        assign_architectural_layers(g, app_name="petclinic")
        from app.stages.enricher import create_technology_nodes
        tech_count = create_technology_nodes(g, app_name="petclinic")

        # Should create at least technology nodes for each framework group
        tech_nodes = [
            n for n in g.nodes.values() if n.kind == NodeKind.COMPONENT
        ]
        assert len(tech_nodes) >= 2  # At minimum spring-web + spring-boot groups

        # Each tech node should have class_count and loc_total
        for tn in tech_nodes:
            assert "class_count" in tn.properties
            assert "loc_total" in tn.properties
            assert "category" in tn.properties

    def test_python_fastapi_app_creates_technology_nodes(self):
        """A FastAPI + SQLAlchemy app produces correct technology nodes."""
        g = SymbolGraph()

        app = GraphNode(
            fqn="app:myapi",
            name="myapi",
            kind=NodeKind.APPLICATION,
            properties={
                "frameworks": ["fastapi", "sqlalchemy"],
                "languages": ["python"],
            },
        )
        g.add_node(app)

        handler = _make_class("myapi.routes.get_users")
        handler.properties["layer"] = "Presentation"
        handler.properties["framework"] = "fastapi"
        handler.language = "python"
        handler.loc = 30
        g.add_node(handler)

        model = _make_class("myapi.models.User")
        model.properties["layer"] = "Data Access"
        model.properties["framework"] = "sqlalchemy"
        model.language = "python"
        model.loc = 40
        g.add_node(model)

        assign_architectural_layers(g, app_name="myapi")
        from app.stages.enricher import create_technology_nodes
        tech_count = create_technology_nodes(g, app_name="myapi")

        tech_nodes = [
            n for n in g.nodes.values() if n.kind == NodeKind.COMPONENT
        ]
        tech_names = {n.name for n in tech_nodes}
        # Should have FastAPI and SQLAlchemy technology nodes
        assert any("FastAPI" in name or "fastapi" in name.lower() for name in tech_names)
        assert any("SQLAlchemy" in name or "sqlalchemy" in name.lower() for name in tech_names)

    def test_dotnet_app_creates_technology_nodes(self):
        """An ASP.NET + EF Core app produces correct technology nodes."""
        g = SymbolGraph()

        app = GraphNode(
            fqn="app:webapp",
            name="webapp",
            kind=NodeKind.APPLICATION,
            properties={
                "frameworks": ["aspnet", "entity-framework"],
                "languages": ["csharp"],
            },
        )
        g.add_node(app)

        ctrl = _make_class("WebApp.Controllers.UsersController")
        ctrl.properties["layer"] = "Presentation"
        ctrl.properties["framework"] = "aspnet"
        ctrl.language = "csharp"
        ctrl.loc = 80
        g.add_node(ctrl)

        ctx = _make_class("WebApp.Data.AppDbContext")
        ctx.properties["layer"] = "Data Access"
        ctx.properties["framework"] = "entity-framework"
        ctx.language = "csharp"
        ctx.loc = 60
        g.add_node(ctx)

        assign_architectural_layers(g, app_name="webapp")
        from app.stages.enricher import create_technology_nodes
        tech_count = create_technology_nodes(g, app_name="webapp")

        tech_nodes = [
            n for n in g.nodes.values() if n.kind == NodeKind.COMPONENT
        ]
        assert len(tech_nodes) >= 2

    def test_multi_language_app(self):
        """A React + Spring Boot fullstack app groups technologies by layer correctly."""
        g = SymbolGraph()

        app = GraphNode(
            fqn="app:fullstack",
            name="fullstack",
            kind=NodeKind.APPLICATION,
            properties={
                "frameworks": ["spring-boot", "hibernate", "react"],
                "languages": ["java", "javascript"],
            },
        )
        g.add_node(app)

        # React component (frontend)
        comp = _make_class("src.components.UserList")
        comp.properties["layer"] = "Presentation"
        comp.properties["framework"] = "react"
        comp.language = "javascript"
        comp.loc = 60
        g.add_node(comp)

        # Spring controller (backend presentation)
        ctrl = _make_class("com.app.UserController")
        ctrl.properties["layer"] = "Presentation"
        ctrl.properties["framework"] = "spring-web"
        ctrl.language = "java"
        ctrl.loc = 90
        g.add_node(ctrl)

        # Service (business)
        svc = _make_class("com.app.UserService")
        svc.properties["layer"] = "Business Logic"
        svc.language = "java"
        svc.loc = 150
        g.add_node(svc)

        assign_architectural_layers(g, app_name="fullstack")
        from app.stages.enricher import create_technology_nodes
        tech_count = create_technology_nodes(g, app_name="fullstack")

        tech_nodes = [
            n for n in g.nodes.values() if n.kind == NodeKind.COMPONENT
        ]
        # Should have React and Spring Web as separate tech nodes in Presentation
        tech_names = {n.name for n in tech_nodes}
        assert len(tech_nodes) >= 3  # React + Spring Web + at least one more

    def test_unclassified_classes_grouped_by_language(self):
        """Classes without framework property are grouped as '{Language} Classes' under their layer."""
        g = SymbolGraph()

        app = GraphNode(
            fqn="app:simple",
            name="simple",
            kind=NodeKind.APPLICATION,
            properties={"frameworks": ["spring-boot"], "languages": ["java"]},
        )
        g.add_node(app)

        # A utility class with a layer but no framework
        util = _make_class("com.app.StringUtils")
        util.properties["layer"] = "Business Logic"
        util.language = "java"
        util.loc = 20
        g.add_node(util)

        assign_architectural_layers(g, app_name="simple")
        from app.stages.enricher import create_technology_nodes
        create_technology_nodes(g, app_name="simple")

        tech_nodes = [
            n for n in g.nodes.values() if n.kind == NodeKind.COMPONENT
        ]
        # The util class should end up in a "Java Classes" technology node
        assert any("Java" in n.name for n in tech_nodes)

    def test_database_technology_from_tables(self):
        """Table nodes are grouped into a database technology node."""
        g = SymbolGraph()

        app = GraphNode(
            fqn="app:dbapp",
            name="dbapp",
            kind=NodeKind.APPLICATION,
            properties={"frameworks": ["hibernate"], "languages": ["java"]},
        )
        g.add_node(app)

        # Table node (produced by Hibernate or SQL plugin)
        tbl = GraphNode(
            fqn="table:users",
            name="users",
            kind=NodeKind.TABLE,
            properties={"engine": "mysql"},
        )
        g.add_node(tbl)

        tbl2 = GraphNode(
            fqn="table:orders",
            name="orders",
            kind=NodeKind.TABLE,
            properties={},
        )
        g.add_node(tbl2)

        from app.stages.enricher import create_technology_nodes
        create_technology_nodes(g, app_name="dbapp")

        tech_nodes = [
            n for n in g.nodes.values() if n.kind == NodeKind.COMPONENT
        ]
        # Should have a database technology node
        db_nodes = [n for n in tech_nodes if n.properties.get("category") == "database"]
        assert len(db_nodes) >= 1
        # It should contain the table count
        assert db_nodes[0].properties.get("table_count", 0) >= 2
```

- [ ] **Step 1.2: Implement `create_technology_nodes()` function**

Add to `app/stages/enricher.py` after `assign_architectural_layers()`:

```python
from dataclasses import dataclass

@dataclass
class _TechnologyInfo:
    """Metadata for a detected technology."""
    display: str
    category: str  # web_framework, orm, database, frontend_framework, di_container, language_runtime
    language: str
    layer_hint: str  # default layer if not otherwise assigned


# Covers ALL registered plugins across ALL languages
_TECHNOLOGY_MAP: dict[str, _TechnologyInfo] = {
    # ── Java ──────────────────────────────────────────────
    "spring-boot":       _TechnologyInfo("Spring Boot",      "di_container",       "java",       "Business Logic"),
    "spring-web":        _TechnologyInfo("Spring Web",       "web_framework",      "java",       "Presentation"),
    "spring-data-jpa":   _TechnologyInfo("Spring Data",      "orm",                "java",       "Data Access"),
    "hibernate":         _TechnologyInfo("Hibernate/JPA",    "orm",                "java",       "Data Access"),
    # ── Python ────────────────────────────────────────────
    "fastapi":           _TechnologyInfo("FastAPI",          "web_framework",      "python",     "Presentation"),
    "django":            _TechnologyInfo("Django",           "web_framework",      "python",     "Presentation"),
    "django-drf":        _TechnologyInfo("Django REST",      "web_framework",      "python",     "Presentation"),
    "django-orm":        _TechnologyInfo("Django ORM",       "orm",                "python",     "Data Access"),
    "django-settings":   _TechnologyInfo("Django Config",    "configuration",      "python",     "Configuration"),
    "sqlalchemy":        _TechnologyInfo("SQLAlchemy",       "orm",                "python",     "Data Access"),
    # ── JavaScript/TypeScript ─────────────────────────────
    "react":             _TechnologyInfo("React",            "frontend_framework", "javascript", "Presentation"),
    "angular":           _TechnologyInfo("Angular",          "frontend_framework", "typescript", "Presentation"),
    "express":           _TechnologyInfo("Express.js",       "web_framework",      "javascript", "Presentation"),
    "nestjs":            _TechnologyInfo("NestJS",           "web_framework",      "typescript", "Presentation"),
    # ── C# / .NET ─────────────────────────────────────────
    "aspnet":            _TechnologyInfo("ASP.NET Core",     "web_framework",      "csharp",     "Presentation"),
    "entity-framework":  _TechnologyInfo("Entity Framework", "orm",                "csharp",     "Data Access"),
}

_LANGUAGE_DISPLAY: dict[str, str] = {
    "java": "Java",
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "csharp": "C#",
    "sql": "SQL",
}


def create_technology_nodes(graph: SymbolGraph, app_name: str) -> int:
    """Create Technology (Component) nodes by grouping classes by framework.

    For each detected framework in the application:
    1. Find all classes assigned to that framework (via class.properties["framework"])
    2. Create a Component node representing the technology
    3. Link: Layer → CONTAINS → Component, Component → CONTAINS → Class

    Classes without a framework property are grouped as "{Language} Classes"
    under their assigned layer.

    Table nodes are grouped into a database technology Component.
    APIEndpoint nodes are counted against their framework's technology node.

    Returns the number of Component (technology) nodes created.
    """
    # ── Step 1: Find the application node for framework list ──
    app_node = None
    for node in graph.nodes.values():
        if node.kind == NodeKind.APPLICATION:
            app_node = node
            break

    detected_frameworks: list[str] = []
    if app_node:
        detected_frameworks = app_node.properties.get("frameworks", [])

    # ── Step 2: Build class → technology mapping ──
    # Key: (layer_name, tech_key) → list of class FQNs
    tech_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    tech_loc: dict[tuple[str, str], int] = defaultdict(int)

    for fqn, node in graph.nodes.items():
        if node.kind != NodeKind.CLASS:
            continue

        layer = node.properties.get("layer")
        if not layer:
            continue  # No layer = not part of architecture view

        framework = node.properties.get("framework", "")
        lang = node.language or "unknown"

        if framework and framework in _TECHNOLOGY_MAP:
            tech_key = framework
        elif framework:
            # Framework detected but not in our map — use it as-is
            tech_key = f"other:{framework}"
        else:
            # No framework — group by language
            tech_key = f"lang:{lang}"

        tech_groups[(layer, tech_key)].append(fqn)
        tech_loc[(layer, tech_key)] += node.loc or 0

    # ── Step 3: Handle Table nodes → Database technology ──
    table_fqns: list[str] = []
    for fqn, node in graph.nodes.items():
        if node.kind == NodeKind.TABLE:
            table_fqns.append(fqn)

    db_engine = _infer_database_engine(graph, detected_frameworks)

    # ── Step 4: Handle APIEndpoint nodes → count against their framework ──
    endpoint_counts: dict[str, int] = defaultdict(int)
    for node in graph.nodes.values():
        if node.kind == NodeKind.API_ENDPOINT:
            fw = node.properties.get("framework", "unknown")
            endpoint_counts[fw] += 1

    # ── Step 5: Create Component nodes ──
    created = 0

    # Find existing Layer nodes
    layer_fqns: dict[str, str] = {}
    for fqn, node in graph.nodes.items():
        if node.kind == NodeKind.LAYER:
            layer_fqns[node.name] = fqn

    for (layer_name, tech_key), class_fqns in tech_groups.items():
        # Determine display name and category
        if tech_key in _TECHNOLOGY_MAP:
            info = _TECHNOLOGY_MAP[tech_key]
            display_name = info.display
            category = info.category
            tech_language = info.language
        elif tech_key.startswith("other:"):
            raw = tech_key.split(":", 1)[1]
            display_name = raw.title()
            category = "framework"
            tech_language = class_fqns[0] if class_fqns else "unknown"
            # Try to get language from first class
            first_node = graph.get_node(class_fqns[0]) if class_fqns else None
            tech_language = first_node.language if first_node else "unknown"
        else:
            # lang:{language} group
            lang = tech_key.split(":", 1)[1]
            lang_display = _LANGUAGE_DISPLAY.get(lang, lang.title())
            display_name = f"{lang_display} Classes"
            category = "language_runtime"
            tech_language = lang

        comp_fqn = f"tech:{app_name}:{layer_name}:{tech_key}"
        comp_node = GraphNode(
            fqn=comp_fqn,
            name=display_name,
            kind=NodeKind.COMPONENT,
            language=tech_language,
            properties={
                "type": "technology",
                "app_name": app_name,
                "category": category,
                "tech_key": tech_key,
                "layer": layer_name,
                "class_count": len(class_fqns),
                "loc_total": tech_loc.get((layer_name, tech_key), 0),
                "endpoint_count": endpoint_counts.get(tech_key, 0),
            },
        )
        graph.add_node(comp_node)

        # Link Layer → Component
        if layer_name in layer_fqns:
            graph.add_edge(GraphEdge(
                source_fqn=layer_fqns[layer_name],
                target_fqn=comp_fqn,
                kind=EdgeKind.CONTAINS,
            ))

        # Link Component → Class
        for class_fqn in class_fqns:
            graph.add_edge(GraphEdge(
                source_fqn=comp_fqn,
                target_fqn=class_fqn,
                kind=EdgeKind.CONTAINS,
            ))

        created += 1

    # ── Step 6: Create database technology Component if tables exist ──
    if table_fqns:
        db_layer = "Data Access"
        db_fqn = f"tech:{app_name}:{db_layer}:database"
        db_display = db_engine or "SQL Database"

        db_node = GraphNode(
            fqn=db_fqn,
            name=db_display,
            kind=NodeKind.COMPONENT,
            language="sql",
            properties={
                "type": "technology",
                "app_name": app_name,
                "category": "database",
                "tech_key": "database",
                "layer": db_layer,
                "table_count": len(table_fqns),
                "class_count": 0,
                "loc_total": 0,
            },
        )
        graph.add_node(db_node)

        # Link Layer → Database Component
        if db_layer in layer_fqns:
            graph.add_edge(GraphEdge(
                source_fqn=layer_fqns[db_layer],
                target_fqn=db_fqn,
                kind=EdgeKind.CONTAINS,
            ))

        # Link Database Component → Tables
        for tbl_fqn in table_fqns:
            graph.add_edge(GraphEdge(
                source_fqn=db_fqn,
                target_fqn=tbl_fqn,
                kind=EdgeKind.CONTAINS,
            ))

        created += 1

    return created


def _infer_database_engine(graph: SymbolGraph, detected_frameworks: list[str]) -> str | None:
    """Best-effort inference of the database engine from available evidence.

    Checks (in order):
    1. Table nodes with 'engine' property (e.g., set by SQL parser)
    2. Django ConfigEntry for DATABASES.default.ENGINE
    3. Detected frameworks list for known DB indicators
    4. Returns None if unresolvable
    """
    # Check Table.engine property
    for node in graph.nodes.values():
        if node.kind == NodeKind.TABLE:
            engine = node.properties.get("engine")
            if engine:
                return _normalize_db_engine(engine)

    # Check Django config entries
    for node in graph.nodes.values():
        if node.kind == NodeKind.CONFIG_ENTRY:
            key = node.properties.get("key", "")
            if "DATABASE" in key.upper() and "ENGINE" in key.upper():
                value = node.properties.get("value", "")
                return _normalize_db_engine(value)

    # Check Application.frameworks for DB hints
    db_hints = {
        "mysql": "MySQL",
        "postgresql": "PostgreSQL",
        "postgres": "PostgreSQL",
        "sqlserver": "SQL Server",
        "mssql": "SQL Server",
        "oracle": "Oracle",
        "sqlite": "SQLite",
        "mongodb": "MongoDB",
        "redis": "Redis",
    }
    for fw in detected_frameworks:
        fw_lower = fw.lower()
        for hint, name in db_hints.items():
            if hint in fw_lower:
                return name

    return None


def _normalize_db_engine(raw: str) -> str:
    """Convert raw engine strings to display names."""
    raw_lower = raw.lower()
    if "mysql" in raw_lower:
        return "MySQL"
    if "postgres" in raw_lower:
        return "PostgreSQL"
    if "sqlite" in raw_lower:
        return "SQLite"
    if "oracle" in raw_lower:
        return "Oracle"
    if "sqlserver" in raw_lower or "mssql" in raw_lower:
        return "SQL Server"
    if "mongo" in raw_lower:
        return "MongoDB"
    return raw.split(".")[-1] if "." in raw else raw
```

- [ ] **Step 1.3: Wire into `enrich_graph()` pipeline**

Add Step 5 in `enrich_graph()` after the Layer assignment step:

```python
    # Step 5: Technology nodes (must run AFTER layers)
    try:
        tech_count = create_technology_nodes(graph, app_name=app_name)
        logger.info("enricher.technology_nodes.done", techs_created=tech_count)
    except Exception as exc:
        msg = f"Technology node creation failed: {exc}"
        context.warnings.append(msg)
        logger.warning("enricher.technology_nodes.failed", error=str(exc))
```

- [ ] **Step 1.4: Run tests**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_enricher.py -v
```

---

## Task 2: Add Architecture API Endpoint (Backend)

**Files:**
- Modify: `cast-clone-backend/app/schemas/graph_views.py`
- Modify: `cast-clone-backend/app/api/graph_views.py`
- Create: `cast-clone-backend/tests/unit/test_architecture_api.py`

### Overview

New endpoint: `GET /api/v1/graph-views/{project_id}/architecture`

Returns:
- Layer nodes (top-level grouping)
- Technology (Component) nodes (grouped under layers)
- Aggregated inter-technology edges
- Database technology node with table count
- Application metadata (languages, frameworks)

- [ ] **Step 2.1: Add Pydantic schemas**

Add to `app/schemas/graph_views.py`:

```python
class TechnologyNodeResponse(BaseModel):
    """A technology node in the architecture view."""
    fqn: str
    name: str
    category: str  # web_framework, orm, database, frontend_framework, etc.
    language: str | None = None
    layer: str
    class_count: int = 0
    loc_total: int = 0
    endpoint_count: int = 0
    table_count: int = 0
    properties: dict[str, Any] = Field(default_factory=dict)


class ArchitectureLayerResponse(BaseModel):
    """A layer containing technology nodes."""
    fqn: str
    name: str
    technologies: list[TechnologyNodeResponse]
    total_classes: int = 0
    total_loc: int = 0


class ArchitectureLinkResponse(BaseModel):
    """An aggregated edge between two technology nodes."""
    source: str  # source technology FQN
    target: str  # target technology FQN
    weight: int
    kinds: list[str]  # edge kinds: CALLS_API, MAPS_TO, INJECTS, etc.


class ArchitectureResponse(BaseModel):
    """Full architecture view response."""
    app_name: str
    languages: list[str]
    frameworks: list[str]
    layers: list[ArchitectureLayerResponse]
    links: list[ArchitectureLinkResponse]
```

- [ ] **Step 2.2: Add the endpoint**

Add to `app/api/graph_views.py`:

```python
@router.get(
    "/{project_id}/architecture",
    response_model=ArchitectureResponse,
)
async def get_architecture(project_id: str) -> ArchitectureResponse:
    """Return the application architecture: layers, technologies, and their links.

    This powers the Architecture View — a technology-centric visualization
    distinct from the module-level Dependency View.
    """
    store = get_graph_store()

    # 1. Get Application metadata
    app_cypher = (
        "MATCH (a) WHERE a.app_name = $app_name AND a.kind = 'APPLICATION' "
        "RETURN a LIMIT 1"
    )
    app_records = await store.query(app_cypher, {"app_name": project_id})
    languages = []
    frameworks = []
    if app_records:
        app_data = app_records[0]["a"]
        languages = app_data.get("languages", [])
        frameworks = app_data.get("frameworks", [])

    # 2. Get Layer → Technology (Component) hierarchy
    layer_cypher = (
        "MATCH (l) WHERE l.app_name = $app_name AND l.kind = 'LAYER' "
        "OPTIONAL MATCH (l)-[:CONTAINS]->(t) "
        "WHERE t.kind = 'COMPONENT' AND t.app_name = $app_name "
        "RETURN l, collect(t) AS technologies "
        "ORDER BY l.name"
    )
    layer_records = await store.query(layer_cypher, {"app_name": project_id})

    layers = []
    for record in layer_records:
        l = record["l"]
        techs_raw = record.get("technologies", [])

        techs = []
        total_classes = 0
        total_loc = 0
        for t in techs_raw:
            if t is None:
                continue
            cc = t.get("class_count", 0) or 0
            lc = t.get("loc_total", 0) or 0
            total_classes += cc
            total_loc += lc
            techs.append(TechnologyNodeResponse(
                fqn=t.get("fqn", ""),
                name=t.get("name", ""),
                category=t.get("category", ""),
                language=t.get("language"),
                layer=l.get("name", ""),
                class_count=cc,
                loc_total=lc,
                endpoint_count=t.get("endpoint_count", 0) or 0,
                table_count=t.get("table_count", 0) or 0,
            ))

        layers.append(ArchitectureLayerResponse(
            fqn=l.get("fqn", ""),
            name=l.get("name", ""),
            technologies=techs,
            total_classes=total_classes,
            total_loc=total_loc,
        ))

    # 3. Get aggregated inter-technology edges
    # Aggregate class-level edges up to their parent Component (technology) nodes
    link_cypher = (
        "MATCH (t1)<-[:CONTAINS]-(comp1 {kind: 'COMPONENT', app_name: $app_name}) "
        "MATCH (t1)-[r]->(t2) "
        "WHERE type(r) IN ['CALLS', 'DEPENDS_ON', 'CALLS_API', 'MAPS_TO', 'INJECTS', 'READS', 'WRITES'] "
        "MATCH (comp2 {kind: 'COMPONENT', app_name: $app_name})-[:CONTAINS]->(t2) "
        "WHERE comp1 <> comp2 "
        "WITH comp1, comp2, type(r) AS rel_type, count(*) AS cnt "
        "WITH comp1.fqn AS source, comp2.fqn AS target, "
        "     collect(DISTINCT rel_type) AS kinds, sum(cnt) AS weight "
        "RETURN source, target, kinds, weight "
        "ORDER BY weight DESC"
    )
    link_records = await store.query(link_cypher, {"app_name": project_id})

    links = [
        ArchitectureLinkResponse(
            source=r["source"],
            target=r["target"],
            weight=r["weight"],
            kinds=r["kinds"],
        )
        for r in link_records
    ]

    return ArchitectureResponse(
        app_name=project_id,
        languages=languages,
        frameworks=frameworks,
        layers=layers,
        links=links,
    )
```

- [ ] **Step 2.3: Write unit tests**

Create `tests/unit/test_architecture_api.py` with mock graph store, verifying:
- Empty project returns empty layers
- Project with layers+technologies returns structured response
- Links are correctly aggregated across technology boundaries

- [ ] **Step 2.4: Run tests**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_architecture_api.py -v
```

---

## Task 3: Add Architecture Data Fetcher (Frontend)

**File:** `cast-clone-frontend/lib/api.ts`

- [ ] **Step 3.1: Add TypeScript types for architecture response**

Add to `lib/types.ts`:

```typescript
export interface TechnologyNode {
  fqn: string;
  name: string;
  category: string;
  language: string | null;
  layer: string;
  class_count: number;
  loc_total: number;
  endpoint_count: number;
  table_count: number;
  properties: Record<string, unknown>;
}

export interface ArchitectureLayer {
  fqn: string;
  name: string;
  technologies: TechnologyNode[];
  total_classes: number;
  total_loc: number;
}

export interface ArchitectureLink {
  source: string;
  target: string;
  weight: number;
  kinds: string[];
}

export interface ArchitectureResponse {
  app_name: string;
  languages: string[];
  frameworks: string[];
  layers: ArchitectureLayer[];
  links: ArchitectureLink[];
}
```

- [ ] **Step 3.2: Add API function**

Add to `lib/api.ts`:

```typescript
/** Fetch the application architecture view data */
export async function getArchitecture(projectId: string): Promise<ArchitectureResponse> {
  return apiFetch<ArchitectureResponse>(
    `/api/v1/graph-views/${projectId}/architecture`
  );
}
```

---

## Task 4: Add Architecture Elements Converter (Frontend)

**File:** `cast-clone-frontend/lib/cytoscape-elements.ts`

- [ ] **Step 4.1: Add `architectureToElements()` converter**

```typescript
import type { ArchitectureResponse, ArchitectureLayer, TechnologyNode, ArchitectureLink } from "@/lib/types";

/**
 * Convert architecture API response to Cytoscape elements.
 *
 * Structure:
 * - Layer nodes are compound parents (contain technology child nodes)
 * - Technology nodes are children of their layer
 * - Edges represent aggregated cross-technology interactions
 *
 * This produces a DIFFERENT graph from modulesToElements() — it shows
 * the technology stack, not the code dependency structure.
 */
export function architectureToElements(
  data: ArchitectureResponse
): ElementDefinition[] {
  const elements: ElementDefinition[] = [];

  for (const layer of data.layers) {
    // Layer as compound parent node
    elements.push({
      group: "nodes",
      data: {
        id: layer.fqn,
        label: `${layer.name} (${layer.total_classes} classes)`,
        kind: "LAYER",
        layer: layer.name.toLowerCase().replace(/\s+/g, "_"),
        drillable: false,
        drillLevel: "layer",
        isCompound: true,
      },
    });

    // Technology nodes as children
    for (const tech of layer.technologies) {
      const sizeMetric = tech.class_count + (tech.table_count || 0);
      const subtitle = _buildTechSubtitle(tech);

      elements.push({
        group: "nodes",
        data: {
          id: tech.fqn,
          label: tech.name,
          parent: layer.fqn,          // Cytoscape compound node child
          kind: "COMPONENT",
          layer: layer.name.toLowerCase().replace(/\s+/g, "_"),
          category: tech.category,
          language: tech.language ?? undefined,
          class_count: tech.class_count,
          loc_total: tech.loc_total,
          endpoint_count: tech.endpoint_count,
          table_count: tech.table_count,
          subtitle,
          // Size node by class count (min 30, max 100)
          loc: Math.min(Math.max(sizeMetric * 50, 100), 5000),
          drillable: tech.class_count > 0 || tech.table_count > 0,
          drillLevel: "technology",
        },
      });
    }
  }

  // Edges between technologies
  for (const link of data.links) {
    elements.push({
      group: "edges",
      data: {
        id: `arch-edge-${link.source}→${link.target}`,
        source: link.source,
        target: link.target,
        weight: link.weight,
        kind: link.kinds[0] ?? "DEPENDS_ON",
        label: link.weight > 1 ? String(link.weight) : undefined,
        allKinds: link.kinds,
      },
    });
  }

  return elements;
}

function _buildTechSubtitle(tech: TechnologyNode): string {
  const parts: string[] = [];
  if (tech.class_count > 0) parts.push(`${tech.class_count} classes`);
  if (tech.table_count > 0) parts.push(`${tech.table_count} tables`);
  if (tech.endpoint_count > 0) parts.push(`${tech.endpoint_count} endpoints`);
  if (tech.loc_total > 0) parts.push(`${tech.loc_total} LOC`);
  return parts.join(" · ");
}
```

---

## Task 5: Update Graph Styles for Architecture View (Frontend)

**File:** `cast-clone-frontend/lib/graph-styles.ts`

- [ ] **Step 5.1: Add technology category colors**

```typescript
/** Color palette for technology categories (used in architecture view) */
const CATEGORY_COLORS: Record<string, string> = {
  web_framework:      "#3B82F6",  // blue-500
  frontend_framework: "#8B5CF6",  // violet-500
  di_container:       "#22C55E",  // green-500
  orm:                "#F97316",  // orange-500
  database:           "#EF4444",  // red-500
  configuration:      "#6B7280",  // gray-500
  language_runtime:   "#64748B",  // slate-500
  framework:          "#14B8A6",  // teal-500
};
```

- [ ] **Step 5.2: Add `buildArchitectureStylesheet()` function**

```typescript
export function buildArchitectureStylesheet(): cytoscape.Stylesheet[] {
  const styles = buildStylesheet("layer");  // Start with layer-based coloring

  // Override: color technology nodes by category
  for (const [category, color] of Object.entries(CATEGORY_COLORS)) {
    styles.push({
      selector: `node[category = "${category}"]`,
      style: {
        "background-color": color,
        "border-color": color,
      },
    });
  }

  // Technology nodes: show subtitle text
  styles.push({
    selector: "node[subtitle]",
    style: {
      "text-wrap": "wrap" as any,
      "text-max-width": "120px" as any,
    },
  });

  // Database nodes: distinct shape
  styles.push({
    selector: 'node[category = "database"]',
    style: {
      shape: "barrel" as any,
    },
  });

  return styles;
}

export const architectureStylesheet = buildArchitectureStylesheet();
```

---

## Task 6: Wire Architecture View in useGraph Hook (Frontend)

**File:** `cast-clone-frontend/hooks/useGraph.ts`

- [ ] **Step 6.1: Add `loadArchitecture()` function**

```typescript
import { getArchitecture } from "@/lib/api";
import { architectureToElements } from "@/lib/cytoscape-elements";

// Inside useGraph hook, add:
const loadArchitecture = useCallback(async (projectId: string) => {
  const cacheKey = `architecture:${projectId}`;

  setIsLoading(true);
  setError(null);
  setDrilldownPath([]);

  try {
    if (cache.current.has(cacheKey)) {
      const cached = cache.current.get(cacheKey)!;
      setElements(cached);
      return;
    }

    const archData = await getArchitecture(projectId);
    const els = architectureToElements(archData);

    cache.current.set(cacheKey, els);
    setElements(els);
  } catch (err) {
    setError(
      err instanceof Error ? err.message : "Failed to load architecture"
    );
  } finally {
    setIsLoading(false);
  }
}, []);
```

Return `loadArchitecture` from the hook alongside `loadModules`.

---

## Task 7: Wire Architecture View in Graph Page (Frontend)

**File:** `cast-clone-frontend/app/projects/[id]/graph/page.tsx`

- [ ] **Step 7.1: Load different data based on view mode**

```typescript
// When viewMode changes:
useEffect(() => {
  if (!projectId) return;

  if (viewMode === "architecture") {
    loadArchitecture(projectId);
  } else if (viewMode === "transaction") {
    // existing transaction logic
  } else {
    // dependency view — existing loadModules logic
    loadModules(projectId);
  }
}, [viewMode, projectId]);
```

- [ ] **Step 7.2: Pass correct colorBy and stylesheet for architecture view**

```tsx
<GraphView
  elements={elements}
  viewMode={viewMode}
  performanceTier={performanceTier}
  colorBy={viewMode === "architecture" ? "layer" : "kind"}
  stylesheet={viewMode === "architecture" ? architectureStylesheet : undefined}
  onNodeSelect={handleNodeSelect}
  onNodeDrillDown={handleNodeDrillDown}
/>
```

- [ ] **Step 7.3: Handle drill-down into technology nodes**

When a user double-clicks a technology node in architecture view, load the classes within that technology:

```typescript
const handleArchitectureDrillDown = useCallback(
  async (fqn: string, name: string, level: string) => {
    if (level === "technology") {
      // Fetch classes belonging to this technology Component
      // Use existing classes endpoint filtered by parent Component FQN
      await drillIntoModule(projectId, fqn, name);
    }
  },
  [projectId]
);
```

---

## Task 8: Verify TypeScript Compilation and Lint

- [ ] **Step 8.1: Run TypeScript check**

```bash
cd cast-clone-frontend && npx tsc --noEmit
```

- [ ] **Step 8.2: Run lint**

```bash
cd cast-clone-frontend && npm run lint
```

- [ ] **Step 8.3: Run backend tests**

```bash
cd cast-clone-backend && uv run pytest tests/unit/test_enricher.py -v
```

---

## Summary of Changes

| # | File | Change | Purpose |
|---|------|--------|---------|
| 1 | `app/stages/enricher.py` | ADD `create_technology_nodes()` + `_TECHNOLOGY_MAP` + `_infer_database_engine()` | Create technology Component nodes from detected frameworks across all languages |
| 2 | `app/api/graph_views.py` | ADD `GET /{project_id}/architecture` | Return layers, technologies, and aggregated inter-technology edges |
| 3 | `app/schemas/graph_views.py` | ADD `TechnologyNodeResponse`, `ArchitectureLayerResponse`, `ArchitectureLinkResponse`, `ArchitectureResponse` | Pydantic schemas for architecture API |
| 4 | `lib/types.ts` | ADD `TechnologyNode`, `ArchitectureLayer`, `ArchitectureLink`, `ArchitectureResponse` | TypeScript types matching backend schemas |
| 5 | `lib/api.ts` | ADD `getArchitecture()` | Fetch architecture data from new endpoint |
| 6 | `lib/cytoscape-elements.ts` | ADD `architectureToElements()` | Convert architecture response to Cytoscape compound node structure |
| 7 | `lib/graph-styles.ts` | ADD `CATEGORY_COLORS`, `buildArchitectureStylesheet()` | Technology-category-based coloring + database barrel shape |
| 8 | `hooks/useGraph.ts` | ADD `loadArchitecture()` | Data loading for architecture view with caching |
| 9 | `app/projects/[id]/graph/page.tsx` | MODIFY view switching logic | Route architecture view to new data source, pass `colorBy="layer"` |
| 10 | `tests/unit/test_enricher.py` | ADD `TestTechnologyNodes` class | Test technology node creation for Java, Python, C#, multi-lang apps |
| 11 | `tests/unit/test_architecture_api.py` | CREATE | Test architecture API endpoint |

---

## Design Decisions & Rationale

### Why Component (not a new NodeKind)?
The Neo4j schema already defines `Component` with `Layer → CONTAINS → Component → CONTAINS → Class`. This is exactly the intermediate "technology" level. No schema changes needed.

### Why a separate API endpoint (not reusing /modules)?
The architecture view shows fundamentally different data — technology groupings, not code modules. Reusing the modules endpoint would require complex client-side transformation and wouldn't have access to the aggregated technology metadata.

### Why `_TECHNOLOGY_MAP` is exhaustive across all plugins?
Each entry in the map corresponds to a framework that one of our 14 registered plugins detects and processes. If a new plugin is added in the future, it only needs one new entry in this map to appear in the architecture view.

### Why fallback grouping by language?
Real applications have utility classes, DTOs, and other code that no framework plugin claims. Grouping these as "Java Classes" or "Python Classes" under their layer ensures the architecture view accounts for 100% of the codebase, not just framework-managed classes.

### Why infer database engine instead of requiring explicit config?
Most users analyze codebases they don't own (legacy modernization). They can't always provide config. The inference chain (Table.engine → Django config → framework hints → fallback) covers the common cases without requiring user input.