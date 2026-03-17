"""Tests for the Entity Framework Core plugin — DbContext, entity mapping, navigation properties."""

import pytest

from app.models.enums import NodeKind, EdgeKind, Confidence
from app.models.graph import GraphNode, GraphEdge, SymbolGraph
from app.models.context import AnalysisContext
from app.models.manifest import ProjectManifest, DetectedFramework
from tests.unit.helpers import make_dotnet_context, add_class, add_method, add_field


# ---------------------------------------------------------------------------
# Import the plugin under test
# ---------------------------------------------------------------------------

from app.stages.plugins.dotnet.entity_framework import EntityFrameworkPlugin


# ---------------------------------------------------------------------------
# Test: DbContext detection
# ---------------------------------------------------------------------------

class TestDbContextDetection:
    @pytest.mark.asyncio
    async def test_dbcontext_subclass_detected(self):
        """A class extending DbContext with DbSet<T> properties creates TABLE nodes and MANAGES edges."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()

        # DbContext subclass
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        # DbSet<User> property
        add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>",
            is_property=True, type_args=["User"],
        )
        # DbSet<Post> property
        add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Posts", "DbSet<Post>",
            is_property=True, type_args=["Post"],
        )

        # Entity classes that the DbSet references
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_class(ctx.graph, "MyApp.Models.Post", "Post")

        result = await plugin.extract(ctx)

        # Should create TABLE nodes for each DbSet entity
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        table_names = {n.name for n in table_nodes}
        assert "Users" in table_names
        assert "Posts" in table_names

        # Should create MANAGES edges: DbContext -> each entity
        manages_edges = [e for e in result.edges if e.kind == EdgeKind.MANAGES]
        assert len(manages_edges) == 2
        assert all(e.source_fqn == "MyApp.Data.AppDbContext" for e in manages_edges)


# ---------------------------------------------------------------------------
# Test: Data Annotations
# ---------------------------------------------------------------------------

class TestDataAnnotations:
    @pytest.mark.asyncio
    async def test_table_annotation_overrides_name(self):
        """[Table("users")] overrides the default table name (which is the DbSet property name)."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "People", "DbSet<User>",
            is_property=True, type_args=["User"],
        )
        add_class(
            ctx.graph, "MyApp.Models.User", "User",
            annotations=["Table"], annotation_args={"": "users"},
        )

        result = await plugin.extract(ctx)

        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "users"  # overridden by [Table("users")]

    @pytest.mark.asyncio
    async def test_column_annotation_creates_column_node(self):
        """[Column("email_address")] creates a COLUMN node with the overridden name."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>",
            is_property=True, type_args=["User"],
        )
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(
            ctx.graph, "MyApp.Models.User", "Email", "string",
            is_property=True, annotations=["Column"],
            annotation_args={"": "email_address"},
        )
        add_field(
            ctx.graph, "MyApp.Models.User", "Id", "int",
            is_property=True, annotations=["Key"],
        )

        result = await plugin.extract(ctx)

        column_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        col_names = {n.name for n in column_nodes}
        assert "email_address" in col_names  # overridden by [Column]
        assert "Id" in col_names  # default name (no Column annotation)

    @pytest.mark.asyncio
    async def test_foreignkey_annotation_creates_reference(self):
        """[ForeignKey("AuthorId")] creates a REFERENCES edge to the referenced entity's PK."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Books", "DbSet<Book>",
            is_property=True, type_args=["Book"],
        )
        add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Authors", "DbSet<Author>",
            is_property=True, type_args=["Author"],
        )

        # Author entity with PK
        add_class(ctx.graph, "MyApp.Models.Author", "Author")
        add_field(
            ctx.graph, "MyApp.Models.Author", "Id", "int",
            is_property=True, annotations=["Key"],
        )

        # Book entity with FK to Author
        add_class(ctx.graph, "MyApp.Models.Book", "Book")
        add_field(
            ctx.graph, "MyApp.Models.Book", "Id", "int",
            is_property=True, annotations=["Key"],
        )
        add_field(
            ctx.graph, "MyApp.Models.Book", "AuthorId", "int",
            is_property=True, annotations=["ForeignKey"],
            annotation_args={"": "Author"},
        )
        # Navigation property
        add_field(
            ctx.graph, "MyApp.Models.Book", "Author", "Author",
            is_property=True,
        )

        result = await plugin.extract(ctx)

        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) >= 1
        # FK column in Books table references PK column in Authors table
        fk_ref = ref_edges[0]
        assert "AuthorId" in fk_ref.source_fqn
        assert "Id" in fk_ref.target_fqn


# ---------------------------------------------------------------------------
# Test: Navigation Properties
# ---------------------------------------------------------------------------

class TestNavigationProperties:
    @pytest.mark.asyncio
    async def test_collection_navigation_detects_one_to_many(self):
        """ICollection<Book> on Author detects a one-to-many relationship."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Authors", "DbSet<Author>",
            is_property=True, type_args=["Author"],
        )
        add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Books", "DbSet<Book>",
            is_property=True, type_args=["Book"],
        )

        # Author with collection navigation
        add_class(ctx.graph, "MyApp.Models.Author", "Author")
        add_field(
            ctx.graph, "MyApp.Models.Author", "Id", "int",
            is_property=True, annotations=["Key"],
        )
        add_field(
            ctx.graph, "MyApp.Models.Author", "Books", "ICollection<Book>",
            is_property=True, type_args=["Book"],
        )

        # Book with FK back to Author
        add_class(ctx.graph, "MyApp.Models.Book", "Book")
        add_field(
            ctx.graph, "MyApp.Models.Book", "Id", "int",
            is_property=True, annotations=["Key"],
        )
        add_field(
            ctx.graph, "MyApp.Models.Book", "AuthorId", "int",
            is_property=True,
        )
        add_field(
            ctx.graph, "MyApp.Models.Book", "Author", "Author",
            is_property=True,
        )

        result = await plugin.extract(ctx)

        # Should detect the one-to-many via the collection navigation property
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(ref_edges) >= 1
        # The FK column AuthorId in Books should reference Id in Authors
        fk_ref = [e for e in ref_edges if "AuthorId" in e.source_fqn]
        assert len(fk_ref) == 1
        assert "Id" in fk_ref[0].target_fqn


# ---------------------------------------------------------------------------
# Test: MAPS_TO edges
# ---------------------------------------------------------------------------

class TestMapsToEdges:
    @pytest.mark.asyncio
    async def test_entity_maps_to_table(self):
        """Each entity registered via DbSet gets a MAPS_TO edge to its table."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>",
            is_property=True, type_args=["User"],
        )
        add_class(ctx.graph, "MyApp.Models.User", "User")

        result = await plugin.extract(ctx)

        maps_to = [e for e in result.edges if e.kind == EdgeKind.MAPS_TO]
        assert len(maps_to) == 1
        assert maps_to[0].source_fqn == "MyApp.Models.User"
        assert maps_to[0].target_fqn == "table:Users"
        assert maps_to[0].properties.get("orm") == "entity-framework"


# ---------------------------------------------------------------------------
# Test: Layer classification
# ---------------------------------------------------------------------------

class TestLayerClassification:
    @pytest.mark.asyncio
    async def test_dbcontext_classified_as_data_access(self):
        """DbContext subclasses are assigned to the 'Data Access' layer."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()

        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(
            ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>",
            is_property=True, type_args=["User"],
        )
        add_class(ctx.graph, "MyApp.Models.User", "User")

        result = await plugin.extract(ctx)

        assert "MyApp.Data.AppDbContext" in result.layer_assignments
        assert result.layer_assignments["MyApp.Data.AppDbContext"] == "Data Access"


# ---------------------------------------------------------------------------
# Test: Fluent API configuration
# ---------------------------------------------------------------------------

class TestFluentApi:
    @pytest.mark.asyncio
    async def test_fluent_to_table_overrides_name(self):
        """Fluent .ToTable('users') overrides default table name."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "People", "DbSet<Person>", is_property=True, type_args=["Person"])
        add_class(ctx.graph, "MyApp.Models.Person", "Person")
        # Fluent config on DbContext
        ctx.graph.get_node("MyApp.Data.AppDbContext").properties["fluent_configurations"] = [
            {"entity": "Person", "table": "people_tbl"},
        ]
        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert any(n.name == "people_tbl" for n in table_nodes)

    @pytest.mark.asyncio
    async def test_fluent_has_one_creates_reference(self):
        """Fluent HasOne().WithMany().HasForeignKey() creates REFERENCES edge."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Books", "DbSet<Book>", is_property=True, type_args=["Book"])
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Authors", "DbSet<Author>", is_property=True, type_args=["Author"])
        add_class(ctx.graph, "MyApp.Models.Book", "Book")
        add_field(ctx.graph, "MyApp.Models.Book", "AuthorId", "int", is_property=True)
        add_class(ctx.graph, "MyApp.Models.Author", "Author")
        ctx.graph.get_node("MyApp.Data.AppDbContext").properties["fluent_configurations"] = [
            {"entity": "Book", "has_one": "Author", "with_many": "Books", "foreign_key": "AuthorId"},
        ]
        result = await plugin.extract(ctx)
        refs = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(refs) >= 1
        assert any("Book" in e.source_fqn and "Author" in e.target_fqn for e in refs)

    @pytest.mark.asyncio
    async def test_fluent_overrides_data_annotation(self):
        """Fluent API takes precedence over [Table] data annotation."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        # Data annotation says "old_users"
        add_class(ctx.graph, "MyApp.Models.User", "User", annotations=["Table"], annotation_args={"": "old_users"})
        # Fluent API says "new_users" (should win)
        ctx.graph.get_node("MyApp.Data.AppDbContext").properties["fluent_configurations"] = [
            {"entity": "User", "table": "new_users"},
        ]
        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert any(n.name == "new_users" for n in table_nodes)
        assert not any(n.name == "old_users" for n in table_nodes)


# ---------------------------------------------------------------------------
# Test: Convention-based PK
# ---------------------------------------------------------------------------

class TestConventionPK:
    @pytest.mark.asyncio
    async def test_id_property_inferred_as_pk(self):
        """Property named 'Id' is inferred as PK even without [Key] annotation."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True)
        add_field(ctx.graph, "MyApp.Models.User", "Name", "string", is_property=True)

        result = await plugin.extract(ctx)
        col_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        id_col = [n for n in col_nodes if n.name == "Id"]
        assert len(id_col) == 1
        assert id_col[0].properties.get("is_primary_key") is True

    @pytest.mark.asyncio
    async def test_classname_id_inferred_as_pk(self):
        """Property named '{ClassName}Id' (e.g., 'UserId') is inferred as PK."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "UserId", "int", is_property=True)

        result = await plugin.extract(ctx)
        col_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        pk_col = [n for n in col_nodes if n.name == "UserId"]
        assert len(pk_col) == 1
        assert pk_col[0].properties.get("is_primary_key") is True


# ---------------------------------------------------------------------------
# Test: [NotMapped]
# ---------------------------------------------------------------------------

class TestNotMapped:
    @pytest.mark.asyncio
    async def test_notmapped_property_skipped(self):
        """[NotMapped] properties do not generate column nodes."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True, annotations=["Key"])
        add_field(ctx.graph, "MyApp.Models.User", "Name", "string", is_property=True)
        add_field(ctx.graph, "MyApp.Models.User", "FullName", "string", is_property=True, annotations=["NotMapped"])

        result = await plugin.extract(ctx)
        col_names = {n.name for n in result.nodes if n.kind == NodeKind.COLUMN}
        assert "Id" in col_names
        assert "Name" in col_names
        assert "FullName" not in col_names


# ---------------------------------------------------------------------------
# Test: [Required] / [MaxLength] column metadata
# ---------------------------------------------------------------------------

class TestColumnMetadata:
    @pytest.mark.asyncio
    async def test_required_sets_nullable_false(self):
        """[Required] annotation sets is_nullable: false on column node."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True, annotations=["Key"])
        add_field(ctx.graph, "MyApp.Models.User", "Email", "string", is_property=True, annotations=["Required", "MaxLength"],
                  annotation_args={"MaxLength": "100"})

        result = await plugin.extract(ctx)
        email_col = [n for n in result.nodes if n.kind == NodeKind.COLUMN and n.name == "Email"]
        assert len(email_col) == 1
        assert email_col[0].properties.get("is_nullable") is False
        assert email_col[0].properties.get("max_length") == "100"


# ---------------------------------------------------------------------------
# Test: [InverseProperty]
# ---------------------------------------------------------------------------

class TestInverseProperty:
    @pytest.mark.asyncio
    async def test_inverse_property_disambiguates_navigation(self):
        """[InverseProperty] disambiguates when entity has multiple navs to same target."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Posts", "DbSet<Post>", is_property=True, type_args=["Post"])

        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True, annotations=["Key"])
        add_field(ctx.graph, "MyApp.Models.User", "AuthoredPosts", "ICollection<Post>", is_property=True,
                  type_args=["Post"], annotations=["InverseProperty"], annotation_args={"InverseProperty": "Author"})
        add_field(ctx.graph, "MyApp.Models.User", "EditedPosts", "ICollection<Post>", is_property=True,
                  type_args=["Post"], annotations=["InverseProperty"], annotation_args={"InverseProperty": "Editor"})

        add_class(ctx.graph, "MyApp.Models.Post", "Post")
        add_field(ctx.graph, "MyApp.Models.Post", "Id", "int", is_property=True, annotations=["Key"])
        add_field(ctx.graph, "MyApp.Models.Post", "AuthorId", "int", is_property=True)
        add_field(ctx.graph, "MyApp.Models.Post", "Author", "User", is_property=True)
        add_field(ctx.graph, "MyApp.Models.Post", "EditorId", "int", is_property=True)
        add_field(ctx.graph, "MyApp.Models.Post", "Editor", "User", is_property=True)

        result = await plugin.extract(ctx)

        # Should not emit "no FK found" warnings since InverseProperty disambiguates
        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        # AuthorId -> User.Id, EditorId -> User.Id
        assert len(ref_edges) >= 2


# ---------------------------------------------------------------------------
# Test: IEntityTypeConfiguration<T>
# ---------------------------------------------------------------------------

class TestEntityTypeConfiguration:
    @pytest.mark.asyncio
    async def test_ientitytypeconfiguration_fluent_api_applied(self):
        """IEntityTypeConfiguration<T> classes have their fluent_configurations applied."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True, annotations=["Key"])

        # Config class implementing IEntityTypeConfiguration<User>
        config_node = add_class(ctx.graph, "MyApp.Config.UserConfiguration", "UserConfiguration",
                                implements=["IEntityTypeConfiguration<User>"])
        config_node.properties["fluent_configurations"] = [
            {"entity": "User", "table": "app_users"},
        ]

        result = await plugin.extract(ctx)
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert any(n.name == "app_users" for n in table_nodes)
        assert result.layer_assignments.get("MyApp.Config.UserConfiguration") == "Data Access"


# ---------------------------------------------------------------------------
# Test: Many-to-many
# ---------------------------------------------------------------------------

class TestManyToMany:
    @pytest.mark.asyncio
    async def test_many_to_many_with_using_entity(self):
        """HasMany().WithMany().UsingEntity() creates a join table with FK references."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Students", "DbSet<Student>", is_property=True, type_args=["Student"])
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Courses", "DbSet<Course>", is_property=True, type_args=["Course"])

        add_class(ctx.graph, "MyApp.Models.Student", "Student")
        add_field(ctx.graph, "MyApp.Models.Student", "Id", "int", is_property=True, annotations=["Key"])

        add_class(ctx.graph, "MyApp.Models.Course", "Course")
        add_field(ctx.graph, "MyApp.Models.Course", "Id", "int", is_property=True, annotations=["Key"])

        ctx.graph.get_node("MyApp.Data.AppDbContext").properties["fluent_configurations"] = [
            {"entity": "Student", "has_many": "Courses", "with_many": "Students", "using_entity": "StudentCourses"},
        ]

        result = await plugin.extract(ctx)

        table_names = {n.name for n in result.nodes if n.kind == NodeKind.TABLE}
        assert "StudentCourses" in table_names

        ref_edges = [e for e in result.edges if e.kind == EdgeKind.REFERENCES and "StudentCourses" in e.source_fqn]
        assert len(ref_edges) == 2


# ---------------------------------------------------------------------------
# Test: Composite keys
# ---------------------------------------------------------------------------

class TestCompositeKeys:
    @pytest.mark.asyncio
    async def test_composite_key_marks_multiple_columns_as_pk(self):
        """HasKey(x => new { x.A, x.B }) marks both columns as PK."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Enrollments", "DbSet<Enrollment>", is_property=True, type_args=["Enrollment"])
        add_class(ctx.graph, "MyApp.Models.Enrollment", "Enrollment")
        add_field(ctx.graph, "MyApp.Models.Enrollment", "StudentId", "int", is_property=True)
        add_field(ctx.graph, "MyApp.Models.Enrollment", "CourseId", "int", is_property=True)

        ctx.graph.get_node("MyApp.Data.AppDbContext").properties["fluent_configurations"] = [
            {"entity": "Enrollment", "composite_key": ["StudentId", "CourseId"]},
        ]

        result = await plugin.extract(ctx)
        col_nodes = [n for n in result.nodes if n.kind == NodeKind.COLUMN]
        pk_cols = [n for n in col_nodes if n.properties.get("is_primary_key")]
        pk_names = {n.name for n in pk_cols}
        assert pk_names == {"StudentId", "CourseId"}


# ---------------------------------------------------------------------------
# Test: Migration parsing
# ---------------------------------------------------------------------------

class TestMigrationParsing:
    @pytest.mark.asyncio
    async def test_migration_fk_creates_reference_edge(self):
        """AddForeignKey in migration creates a REFERENCES edge."""
        plugin = EntityFrameworkPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.Data.AppDbContext", "AppDbContext", base_class="DbContext")
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Orders", "DbSet<Order>", is_property=True, type_args=["Order"])
        add_field(ctx.graph, "MyApp.Data.AppDbContext", "Users", "DbSet<User>", is_property=True, type_args=["User"])
        add_class(ctx.graph, "MyApp.Models.Order", "Order")
        add_field(ctx.graph, "MyApp.Models.Order", "Id", "int", is_property=True, annotations=["Key"])
        add_field(ctx.graph, "MyApp.Models.Order", "UserId", "int", is_property=True)
        add_class(ctx.graph, "MyApp.Models.User", "User")
        add_field(ctx.graph, "MyApp.Models.User", "Id", "int", is_property=True, annotations=["Key"])

        # Migration class with FK operation
        migration_node = add_class(ctx.graph, "MyApp.Migrations.Init", "Init")
        migration_node.properties["migration_operations"] = [
            {"operation": "AddForeignKey", "table": "Orders", "column": "UserId",
             "principal_table": "Users", "principal_column": "Id"},
        ]

        result = await plugin.extract(ctx)
        migration_refs = [e for e in result.edges
                          if e.kind == EdgeKind.REFERENCES and e.evidence == "entity-framework:migration"]
        assert len(migration_refs) >= 1
        assert any("UserId" in e.source_fqn and "Id" in e.target_fqn for e in migration_refs)
