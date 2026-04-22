# Deep Dive — Framework Plugin Architecture (Revised)

**Focus:** How plugins extract invisible framework connections from source code
**Last Updated:** Revised with tree-sitter query patterns, accuracy expectations, and practical implementation details

---

## Overview

Every framework creates **invisible connections** not visible in raw code:
- Spring's `@Autowired` wires interfaces to implementations at runtime
- Django's `ForeignKey("User")` creates a database relationship
- React's `<Header />` in JSX creates a component tree
- Hibernate's `@OneToMany` maps objects to database tables
- Raw SQL strings inside code create table dependencies

The plugin system's job: make the invisible visible by turning framework conventions into explicit graph edges.

**Core technique:** Every plugin is fundamentally a set of **tree-sitter S-expression queries** plus post-processing logic. Tree-sitter gives us the AST nodes; the plugin interprets them in the context of its framework.

---

## Plugin Contract

```python
class FrameworkPlugin(ABC):
    name: str
    version: str
    supported_languages: set[Language]
    depends_on: list[str] = []

    @abstractmethod
    def detect(self, ctx: AnalysisContext) -> Confidence:
        """Is this plugin relevant? Returns: HIGH, MEDIUM, LOW, NONE"""
        ...

    @abstractmethod
    def extract(self, ctx: AnalysisContext) -> PluginResult:
        """Find hidden connections, produce new nodes/edges."""
        ...

    def get_layer_classification(self) -> LayerRules:
        """Optional: How to classify nodes into architectural layers."""
        return LayerRules.empty()

    def get_entry_points(self, ctx: AnalysisContext) -> list[EntryPoint]:
        """Optional: Transaction starting points (e.g., HTTP endpoints)."""
        return []
```

```python
@dataclass
class PluginResult:
    nodes: list[GraphNode]             # New nodes discovered
    edges: list[GraphEdge]             # New connections found
    layer_assignments: dict[str, str]  # node_fqn -> layer_name
    entry_points: list[EntryPoint]     # Transaction start points
    warnings: list[str]                # Issues encountered
```

---

## Plugin Lifecycle

```
1. DISCOVERY   -- Load plugin classes from /plugins directory
2. DETECTION   -- Call plugin.detect(ctx); rank by confidence
3. ACTIVATION  -- HIGH auto-activates, MEDIUM activates with warning
4. ORDERING    -- Topological sort on depends_on
5. EXECUTION   -- Run each plugin in order; merge results into context
```

Independent chains run in parallel. If plugin X depends on Y, Y runs first. If A and B are independent, they run concurrently.

---

## The Core Technique: Tree-sitter Queries

Every plugin uses the same pattern:

```python
def extract_annotations(tree, language, query_string):
    """Run a tree-sitter query and yield matches."""
    query = language.query(query_string)
    return query.matches(tree.root_node)
```

Tree-sitter queries use S-expressions to pattern-match AST nodes. This is the fundamental building block -- the query runs in microseconds per file, making it feasible to scan thousands of files.

### Example: Extracting Spring @GetMapping annotations

```scheme
; Tree-sitter query for Spring endpoint annotations
(method_declaration
  (modifiers
    (annotation
      name: (identifier) @annotation-name
      (annotation_argument_list
        (string_literal) @endpoint-path)?
      (annotation_argument_list
        (element_value_pair
          (identifier) @param-name
          value: (string_literal) @endpoint-path))?))
  name: (identifier) @method-name)
```

This query captures the annotation name (e.g., "GetMapping"), the endpoint path (e.g., "/users"), and the handler method name. The plugin then:
1. Filters matches where `@annotation-name` is in the set of HTTP method annotations
2. Combines class-level `@RequestMapping` prefix with method-level path
3. Creates an `APIEndpoint` node and `HANDLES` edge

### Example: Extracting Django model ForeignKey fields

```scheme
; Tree-sitter query for Django model field assignments
(class_definition
  name: (identifier) @class-name
  superclasses: (argument_list
    (attribute (identifier) @module) (identifier) @base-class)
  body: (block
    (expression_statement
      (assignment
        left: (identifier) @field-name
        right: (call
          function: (attribute
            object: (identifier) @field-module
            attribute: (identifier) @field-type)
          arguments: (argument_list) @field-args)))))
```

The plugin filters for classes where `@base-class` is "Model" and `@field-type` is "ForeignKey", "ManyToManyField", "OneToOneField". It then parses `@field-args` to extract the target model name.

---

## Plugin Specifications

### Tier 1: Spring Ecosystem (Build First)

Spring is the most complex framework to analyze statically. If the plugin system handles Spring's DI, everything else is simpler.

#### Spring DI Plugin (`spring-di`)

**Depends on:** none
**Detection:** pom.xml/build.gradle with spring-boot -> HIGH; `@Component` annotations -> MEDIUM

**What it extracts:**

**Component scanning** -- Finds all stereotype-annotated classes:
- `@Component`, `@Service`, `@Repository`, `@Controller`, `@RestController`, `@Configuration`
- Tree-sitter query matches `(annotation name: (identifier) @ann)` then filters by known stereotype names

**Bean definitions** -- `@Bean` methods in `@Configuration` classes:
- Method return type becomes the bean type
- Method name becomes the bean name (or `@Bean(name="...")`)

**Injection resolution** -- For each `@Autowired` field or constructor param:
1. Get the declared type
2. If concrete class -> direct match -> HIGH confidence edge
3. If interface -> find all implementors annotated with stereotypes
4. If exactly one implementor -> resolved -> HIGH confidence
5. If multiple -> check `@Primary` annotation -> resolved if found
6. If still ambiguous -> check `@Qualifier` matching -> resolved if found
7. If still ambiguous -> create edges to ALL candidates -> LOW confidence
8. Constructor injection (preferred in modern Spring) -> same resolution logic

**Accuracy expectation: ~85-90%.** Research (Jasmine, ASE '22) shows static Spring DI analysis achieves good but imperfect results. Main blind spots: runtime profiles, conditional beans based on property values, factory method patterns, Spring AOP proxies. These require runtime information we don't have.

**What we intentionally skip (too hard for static analysis):**
- `@ConditionalOnProperty` -- depends on runtime config values
- Spring AOP proxy interception chains
- `@Bean` methods that return different types based on conditions
- XML-based bean definitions (legacy, decreasing usage)

**Output edges:** `(:Class)-[:INJECTS {qualifier, confidence}]->(:Class)`

**Layer classification:**
- `@Controller/@RestController` -> Presentation
- `@Service` -> Business Logic
- `@Repository` -> Data Access
- `@Configuration` -> Configuration

---

#### Spring Web Plugin (`spring-web`)

**Depends on:** `spring-di`

**What it extracts:**

**Endpoint mappings** -- `@RequestMapping`, `@GetMapping`, `@PostMapping`, `@PutMapping`, `@DeleteMapping`, `@PatchMapping`

**Path resolution** -- Combines class-level prefix with method-level path:
```java
@RestController
@RequestMapping("/api/v1")      // class-level prefix
public class UserController {
    @GetMapping("/users/{id}")   // full path: /api/v1/users/{id}
    public User getUser(@PathVariable Long id) { ... }
}
```

The tree-sitter query (as shown in the technique section) captures annotation name and path string. The plugin:
1. Normalizes path parameters (`{id}` -> `:id`)
2. Extracts HTTP method from annotation name
3. Resolves request/response body types from method signatures

**Output:**
- Nodes: `(:APIEndpoint {method: "GET", path: "/api/v1/users/:id", request_type, response_type})`
- Edges: `(:Function)-[:HANDLES]->(:APIEndpoint)`, `(:Class)-[:EXPOSES]->(:APIEndpoint)`

---

#### Hibernate / JPA Plugin (`hibernate`)

**Depends on:** `spring-di`

**What it extracts:**

**Entity-to-table mapping** -- `@Entity` + `@Table(name="users")` or convention (class name -> table name)

**Column mapping** -- `@Column(name="email")` or field name convention

**Relationship annotations** -- This is the most important extraction:
- `@OneToMany(mappedBy="cart")` -- Find the `cart` field in the target entity, resolve the inverse
- `@ManyToOne` + `@JoinColumn(name="cart_id")` -- FK edge with join column name
- `@ManyToMany` + `@JoinTable` -- junction table node with both FK edges
- `@OneToOne` -- Unique FK edge

**Key implementation detail:** The `mappedBy` attribute is the critical link. When we find `@OneToMany(mappedBy="cart")` on Entity A pointing to Entity B, we must find the field named "cart" in Entity B that has `@ManyToOne`. This requires cross-file resolution -- tree-sitter gives us the AST per-file, but the plugin must correlate across the full context.

**Inheritance mapping** -- `@Inheritance(strategy=...)`:
- `SINGLE_TABLE` -- one table, discriminator column
- `JOINED` -- table per subclass, FK chain
- `TABLE_PER_CLASS` -- table per concrete class

**Named queries** -- `@NamedQuery` SQL is parsed with sqlglot for table references.

**Output:**
- Nodes: `(:Table)`, `(:Column)` for every mapped entity
- Edges: entity -> table, field -> column, entity <-> entity (FK relationships)

---

#### Spring Data Plugin (`spring-data`)

**Depends on:** `spring-di`, `hibernate`

Extracts repository interfaces extending `JpaRepository<Entity, ID>` or `CrudRepository`. Resolves entity type and ID type from generics. Parses derived query methods (`findByEmailAndStatus` -> reads `email` and `status` columns). Parses `@Query` annotation SQL with sqlglot.

**Output:** `(:Class {repo})-[:MANAGES]->(:Class {entity})`, `(:Function)-[:READS]->(:Table)`

---

### Tier 1: SQL Parsing (Build With Spring)

#### SQL Parser Plugin (`sql-parser`)

**Depends on:** none
**Why Tier 1:** Connects application code to database tables. Works across ALL frameworks.

**Implementation with sqlglot:**

```python
import sqlglot
from sqlglot import exp

def extract_sql_dependencies(sql_string: str, dialect: str = None):
    """Parse SQL and extract table/column references."""
    try:
        ast = sqlglot.parse_one(sql_string, dialect=dialect)
    except sqlglot.errors.ParseError:
        return None  # Not valid SQL
    
    tables_read = set()
    tables_written = set()
    
    # Detect statement type
    if isinstance(ast, (exp.Select,)):
        for table in ast.find_all(exp.Table):
            tables_read.add(table.name)
    elif isinstance(ast, (exp.Insert,)):
        tables_written.add(ast.find(exp.Table).name)
        # Subselect in INSERT...SELECT
        for sub in ast.find_all(exp.Select):
            for table in sub.find_all(exp.Table):
                tables_read.add(table.name)
    elif isinstance(ast, (exp.Update,)):
        tables_written.add(ast.find(exp.Table).name)
    elif isinstance(ast, (exp.Delete,)):
        tables_written.add(ast.find(exp.Table).name)
    
    return SQLDependencies(reads=tables_read, writes=tables_written)
```

**How embedded SQL is found in code:**

1. Tree-sitter extracts all string literals from code
2. Heuristic filter: strings containing SQL keywords (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `FROM`, `WHERE`, `JOIN`)
3. Validate: attempt `sqlglot.parse_one()` -- if it parses, it's SQL
4. For ORM query builders: detect patterns like `session.execute(text("..."))`, `@Query("...")`, raw SQL in Django's `.raw()` or `.extra()`

**sqlglot's key advantage:** Supports 21+ SQL dialects (PostgreSQL, MySQL, BigQuery, Snowflake, etc.) with a unified AST. DataHub uses it for column-level lineage at scale with 97-99% accuracy on production queries.

**Column-level lineage (optional enhancement):**
Using sqlglot's `lineage()` module and `traverse_scope()` utility, we can trace which columns flow from source tables to output. This enables precise impact analysis -- "changing column X in table A affects methods M1, M2, M3."

**Output:**
- `(:Function)-[:READS {columns}]->(:Table)` edges
- `(:Function)-[:WRITES {columns}]->(:Table)` edges

---

#### SQL Migration Plugin (`sql-migration`)

**Depends on:** none

**Detection:** Flyway (`V1__*.sql`), Liquibase (`changelog.xml`), Alembic (`versions/*.py`), EF Migrations (`*.cs`)

**What it does:** Parses migration files in sequence to reconstruct the current database schema. DDL statements (`CREATE TABLE`, `ALTER TABLE`, `CREATE INDEX`, foreign key constraints) are parsed with sqlglot to build table/column/FK nodes.

For code-based migrations (Alembic Python, EF C#), tree-sitter extracts the DSL calls (`op.create_table()`, `migrationBuilder.CreateTable()`).

**Output:** Database schema graph -- tables, columns, FKs, indexes, views.

---

### Tier 2: React + Frontend (Build Second)

#### React Plugin (`react`)

**Depends on:** none

**Component detection** -- Tree-sitter for TypeScript/JSX finds:
1. Function components: exported functions returning JSX
2. Class components: classes extending `React.Component` or `Component`
3. Arrow function components: `const App = () => <div>...</div>`

**Component tree extraction** -- The key insight from academic research (ReactAppScan, CCS '24): parse JSX elements to find which components render which other components.

```scheme
; Tree-sitter query for JSX element usage
(jsx_opening_element
  name: (identifier) @component-name)
```

If we find `<Header />` inside the `App` component's JSX return, we create: `App -[:RENDERS]-> Header`. The algorithm:
1. For each component, find all JSX elements in its return/render
2. Filter: capitalized names are components (React convention), lowercase are HTML elements
3. Match component names to imports in the same file
4. Resolve the import to the actual component definition

**Props flow** -- JSX attributes become props edges:
```jsx
<UserCard name={user.name} onDelete={handleDelete} />
```
Creates: `ParentComponent -[:PASSES_PROP {name: "name"}]-> UserCard`

**Context and hooks** -- `useContext(AuthContext)` creates a dependency on the context provider. `React.lazy(() => import("./Dashboard"))` creates a lazy-loaded dependency edge.

**Accuracy expectation: ~80-85%.** Static analysis can't fully resolve dynamic component rendering (components stored in variables, computed component names). Conditional rendering (`{isAdmin && <AdminPanel />}`) is detected but the condition is opaque.

**Output:**
- Component nodes with type (function, class, HOC, lazy)
- `(:Component)-[:RENDERS]->(:Component)` edges for component tree
- `(:Component)-[:PASSES_PROP]->(:Component)` edges
- Context provider/consumer edges

---

#### React Router Plugin (`react-router`)

**Depends on:** `react`

Extracts route definitions from `<Route>`, `createBrowserRouter()`, or `createRoutesFromElements()`. Maps routes to components. Handles nested routes and `<Outlet>`.

**Output:** `(:Route {path})-[:RENDERS]->(:Component)` edges

---

### Tier 2: ASP.NET + C# / .NET (Build Second With JS/TS)

#### ASP.NET Core Plugin (`aspnet-core`)

**Depends on:** none
**Detection:** `*.csproj` with `Microsoft.AspNetCore` -> HIGH; `[ApiController]` attribute found -> HIGH

**What it extracts:**

**Controllers** -- Classes extending `ControllerBase` or `Controller`:
- Tree-sitter for C# finds class declarations with base class matching
- Attribute routing: `[Route("api/[controller]")]` at class level
- `[controller]` token replaced with class name minus "Controller" suffix

**Endpoint attributes** -- `[HttpGet]`, `[HttpPost]`, `[HttpPut]`, `[HttpDelete]`, `[HttpPatch]`:
- Path combines class `[Route]` prefix with method attribute path
- `[HttpGet("{id}")]` on `UsersController` -> `GET /api/users/{id}`

**DI registration** -- Parses `Program.cs` or `Startup.cs`:
- `builder.Services.AddScoped<IService, ServiceImpl>()` -> `IService` resolved to `ServiceImpl`
- `AddTransient<>`, `AddSingleton<>` -> same resolution with lifetime metadata
- Constructor injection: controller/service constructors with interface params -> resolved via DI registrations

**Middleware pipeline** -- `app.UseAuthentication()`, `app.UseAuthorization()`, `app.UseCors()` etc. -> ordered middleware chain edges

**Minimal APIs** (newer .NET pattern):
- `app.MapGet("/api/users", handler)` -> endpoint node + handler edge
- `app.MapGroup("/api")` -> path prefix group

**Output:**
- Nodes: `(:APIEndpoint {method, path, request_type, response_type})`
- Edges: `(:Function)-[:HANDLES]->(:APIEndpoint)`, `(:Class)-[:EXPOSES]->(:APIEndpoint)`
- DI edges: `(:Class)-[:INJECTS {lifetime: "scoped|transient|singleton"}]->(:Class)`

**Layer classification:**
- Controllers -> Presentation
- Classes registered as services -> Business Logic
- Classes ending in "Repository" or registered as repository -> Data Access

---

#### Entity Framework Plugin (`entity-framework`)

**Depends on:** `aspnet-core`

**What it extracts:**

**DbContext** -- Classes extending `DbContext`:
- `DbSet<User>` properties -> entity registration
- Each `DbSet<T>` links the context to entity type T

**Entity configuration** -- Two paths:
1. **Data annotations** (on entity classes):
   - `[Table("users")]` -> table name
   - `[Column("email_address")]` -> column name
   - `[ForeignKey("AuthorId")]` -> FK relationship
   - `[Key]` -> primary key
2. **Fluent API** (in `OnModelCreating`):
   - `entity.ToTable("users")` -> table name
   - `entity.HasOne(e => e.Author).WithMany(a => a.Books).HasForeignKey(b => b.AuthorId)` -> relationship chain

**Relationship extraction** -- Navigation properties are the key:
- `public Author Author { get; set; }` + `public int AuthorId { get; set; }` -> FK to Author
- `public ICollection<Book> Books { get; set; }` -> reverse navigation (one-to-many)
- Fluent API `HasOne`/`HasMany`/`HasForeignKey` chain confirms and configures

**Migrations** -- Parse `Migrations/*.cs` for schema evolution:
- `migrationBuilder.CreateTable(name: "Users", ...)` -> table creation
- `migrationBuilder.AddForeignKey(...)` -> FK constraint
- Processed in order to reconstruct current schema state

**Output:**
- Nodes: `(:Table)`, `(:Column)` for every mapped entity
- Edges: entity -> table, field -> column, entity <-> entity (FK relationships)
- DbContext -> entity management edges

---

### Tier 2: JavaScript / TypeScript Backends (Build With C#)

#### Express Plugin (`express`)

**Depends on:** none
**Detection:** `package.json` with `express` dependency -> HIGH

**What it extracts:**

**Route handlers** -- Tree-sitter finds method calls on app/router objects:
- `app.get("/users", handler)` -> GET /users
- `app.post("/users", validateBody, createUser)` -> POST /users with middleware chain
- `router.use("/admin", adminRouter)` -> sub-router mounting with prefix

**Middleware chain** -- Express middleware is ordered and significant:
- `app.use(cors())` -> global middleware
- Route-specific middleware: `app.get("/users", auth, rateLimit, handler)` -> ordered chain
- Error middleware: `app.use((err, req, res, next) => ...)` -> error handler

**Route modules** -- `require("./routes/users")` or `import userRouter from "./routes/users"`:
- Tree-sitter traces imports to find router definitions in other files
- `app.use("/api/users", userRouter)` + `router.get("/:id", getUser)` -> full path `/api/users/:id`

**Output:**
- Nodes: `(:APIEndpoint {method, path, middleware_chain})`
- Edges: `(:Function)-[:HANDLES]->(:APIEndpoint)`, middleware ordering edges

---

#### NestJS Plugin (`nestjs`)

**Depends on:** none
**Detection:** `package.json` with `@nestjs/core` -> HIGH; `@Module` decorator found -> HIGH

**What it extracts:**

**Modules** -- `@Module({ imports, controllers, providers, exports })`:
- Module dependency graph from `imports` array
- Which controllers and providers belong to which module
- `exports` array determines what's visible to other modules

**Controllers** -- `@Controller("users")` with method decorators:
- `@Get(":id")`, `@Post()`, `@Put(":id")`, `@Delete(":id")`
- Path combines controller prefix with method decorator path
- `@Body()`, `@Param()`, `@Query()` parameter decorators

**Injectable services** -- `@Injectable()` classes:
- Constructor DI: `constructor(private userService: UserService)` -> injection edge
- NestJS resolves by type (like Spring), scoped to module providers
- `@Inject("TOKEN")` for custom provider tokens

**Guards and interceptors** -- `@UseGuards(AuthGuard)`, `@UseInterceptors(LoggingInterceptor)`:
- Creates middleware-like chain edges on endpoints

**Output:**
- Module dependency graph
- DI edges: `(:Class)-[:INJECTS]->(:Class)` within module scope
- Endpoint nodes + handler edges (same pattern as Express/Spring)

---

### Tier 4: Python + Other (Build Later)

| Plugin | Language | Key Extractions |
|--------|----------|-----------------|
| `django-settings` | Python | `INSTALLED_APPS`, `DATABASES`, `MIDDLEWARE`, `ROOT_URLCONF` |
| `django-urls` | Python | `path()`, `re_path()`, `include()` recursive URL resolution |
| `django-orm` | Python | `models.Model` subclasses, `ForeignKey`, `ManyToManyField`, table naming |
| `django-drf` | Python | `ViewSet` -> `serializer_class` -> `queryset` -> Model -> Table chain |
| `fastapi` | Python | Route decorators, Pydantic models, `Depends()` DI |
| `sqlalchemy` | Python | Declarative models, `__tablename__`, `relationship()`, `ForeignKey()` |
| `angular` | TS | `@NgModule`, `@Component`, service DI, router config |

These follow the same pattern: tree-sitter queries -> framework-specific post-processing -> graph nodes/edges. Django is the most complex in this tier (4 plugins with dependency chain), but structurally simpler than Spring.

#### Python — SCIP foundation (M1 complete)

As of 2026-04-22, Python is indexed by:
- Stage 2: sandboxed `uv venv` + `uv pip install -e . || -r requirements.txt` produces `ResolvedEnvironment.python_venv_path`.
- Stage 4: `scip-python v0.6.6` runs with `VIRTUAL_ENV` and `NODE_OPTIONS=--max-old-space-size=8192` from the Stage-2 venv. Non-zero exits are tolerated if `index.scip` is non-empty (partial-index success mode).
- Merger: handles scip-python's `scip-python python <pkg> <ver> <descriptors>` symbol format.

Fixtures for regression testing live under `tests/fixtures/`:
- `fastapi-todo/` — FastAPI + async SQLAlchemy + Alembic + Pydantic v2
- `django-blog/` — Django + DRF + Celery
- `flask-inventory/` — Flask + Flask-SQLAlchemy + Flask-RESTful

Subsequent milestones (M2-M4) add framework plugins on top.

---

## Cross-Technology Linkers

These run AFTER all framework plugins and stitch connections across languages/services.

### HTTP Endpoint Matcher

The pattern, confirmed by research (jQAssistant + Neo4j approach, academic papers on microservice architecture recovery):

```
1. COLLECT backend endpoints from all web framework plugins
   - Each has: method (GET/POST/...), path ("/api/v1/users/:id"), handler function
   
2. COLLECT frontend HTTP calls
   - fetch("/api/v1/users/" + id)
   - axios.get("/api/users")
   - HttpClient.get<User[]>("/api/users")
   - Tree-sitter finds call expressions where the function name matches HTTP client patterns

3. NORMALIZE paths
   - Strip base URL prefixes (configured per project)
   - Convert path params: {id}, :id, ${id} -> :param
   - Lowercase, strip trailing slashes

4. MATCH by HTTP method + normalized path
   - Exact match first
   - Then parameterized match (path segments with :param match any value)
   - Confidence: HIGH for exact, MEDIUM for parameterized

5. CREATE edges: (:Function)-[:CALLS_API]->(:APIEndpoint)
```

**Accuracy expectation: ~70-80%.** Main blind spots: dynamically constructed URLs, environment-variable base URLs, API gateway routing that changes paths. Configuration-based URL prefixes help.

---

### Message Queue Matcher

```
1. COLLECT producers
   - Kafka: kafkaTemplate.send("order-events", ...), @SendTo("order-events")
   - RabbitMQ: rabbitTemplate.convertAndSend("order-exchange", ...)
   - SQS: sqsClient.sendMessage("queue-url", ...)
   - Tree-sitter extracts the topic/queue name from method arguments

2. COLLECT consumers
   - Kafka: @KafkaListener(topics="order-events")
   - RabbitMQ: @RabbitListener(queues="order-queue")
   - SQS: @SqsListener("queue-name")
   - Tree-sitter extracts topic name from annotation arguments

3. MATCH by topic string
   - Exact match first
   - Then wildcard: "order.*" matches "order.created"

4. CREATE edges: (:Function)-[:PRODUCES]->(:MessageTopic)<-[:CONSUMES]-(:Function)
```

---

### Shared Database Matcher

```
1. Collect ALL entity->table mappings from all ORM plugins (Hibernate, Django ORM, EF, SQLAlchemy)
2. Group by table name
3. If entities from DIFFERENT services map to the SAME table -> shared database coupling
4. Create cross-service dependency edges
```

This reveals one of the most common microservice anti-patterns: hidden coupling through shared databases.

---

## Plugin Directory Structure

```
src/plugins/
  __init__.py
  base.py                  # FrameworkPlugin ABC, PluginResult
  registry.py              # Plugin discovery and lifecycle
  treesitter_helpers.py    # Common query utilities
  
  # Tier 1 — Java + Database
  spring/
    di.py                  # Spring DI resolution
    web.py                 # Spring Web endpoints
    data.py                # Spring Data repositories
  hibernate/
    jpa.py                 # Entity/relationship mapping
  sql/
    parser.py              # Embedded SQL extraction + sqlglot
    migration.py           # Schema reconstruction from migrations
  
  # Tier 2 — JS/TS + C#/.NET
  react/
    components.py          # Component tree extraction
    router.py              # React Router
  express/
    routes.py              # Express route + middleware extraction
  nestjs/
    modules.py             # NestJS module/controller/DI extraction
  aspnet/
    controllers.py         # ASP.NET Core controllers + minimal APIs
    di.py                  # Service registration DI resolution
  entity_framework/
    dbcontext.py           # DbContext + entity mapping + migrations
  
  # Tier 4 — Python + Other
  django/
    settings.py
    urls.py
    orm.py
    drf.py
  fastapi/
  sqlalchemy/
  angular/
  
  # Cross-tech (runs after all framework plugins)
  linkers/
    http_matcher.py
    mq_matcher.py
    shared_db_matcher.py
```

---

## Build Priority

| Tier | Plugins | Effort | Why |
|------|---------|--------|-----|
| 1 (Phase 1) | Spring DI + Web + Data + Hibernate, SQL Parser + Migration | ~3 weeks | Most complex, proves the architecture, covers enterprise Java + database layer |
| 2a (Phase 1-2) | React + Router, Express, NestJS, HTTP Endpoint Matcher | ~2 weeks | JS/TS frontend + backend, enables cross-tech linking |
| 2b (Phase 1-2) | ASP.NET Core + Entity Framework | ~2 weeks | C#/.NET enterprise ecosystem, DI pattern mirrors Spring |
| 3 (Phase 2) | MQ Matcher, Shared DB Matcher | ~1 week | Cross-tech linkers complete the microservice picture |
| 4 (Phase 3+) | Django (Settings + URLs + ORM + DRF), FastAPI, SQLAlchemy, Angular | ~3 weeks | Python ecosystem + remaining frameworks |

**Priority languages:** Java, JavaScript/TypeScript, C#/.NET, Database (SQL). These four cover the vast majority of enterprise codebases. Python/Django comes later since it has simpler framework conventions and fewer invisible connections to resolve.

**Spring comes first** because it's the most complex framework to analyze statically. ASP.NET's DI pattern is structurally similar to Spring (register interface->implementation, resolve via constructor injection), so the lessons from Spring DI directly transfer. NestJS also follows the same module+injectable pattern.