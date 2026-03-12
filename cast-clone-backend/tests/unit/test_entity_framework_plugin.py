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

from app.stages.plugins.entity_framework.dbcontext import EntityFrameworkPlugin


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
