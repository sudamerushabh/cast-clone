"""Tests for EF Core migration parsing in the SQL Migration plugin."""

import pytest
from pathlib import Path
from app.models.enums import NodeKind, EdgeKind
from app.stages.plugins.sql.migration import parse_ef_migration


class TestEFMigrationParser:
    def test_create_table_extraction(self, tmp_path: Path):
        """CreateTable produces Table + Column nodes."""
        migration = tmp_path / "20240101_CreateUsers.cs"
        migration.write_text('''
public partial class CreateUsers : Migration {
    protected override void Up(MigrationBuilder migrationBuilder) {
        migrationBuilder.CreateTable(
            name: "Users",
            columns: table => new {
                Id = table.Column<int>(nullable: false),
                Email = table.Column<string>(maxLength: 255, nullable: false),
                Name = table.Column<string>(nullable: true)
            },
            constraints: table => {
                table.PrimaryKey("PK_Users", x => x.Id);
            });
    }
}
''')
        result = parse_ef_migration(migration)
        assert len(result.nodes) >= 4  # 1 table + 3 columns
        table_nodes = [n for n in result.nodes if n.kind == NodeKind.TABLE]
        assert len(table_nodes) == 1
        assert table_nodes[0].name == "Users"

    def test_add_foreign_key_extraction(self, tmp_path: Path):
        """AddForeignKey produces REFERENCES edge."""
        migration = tmp_path / "20240102_AddFK.cs"
        migration.write_text('''
public partial class AddFK : Migration {
    protected override void Up(MigrationBuilder migrationBuilder) {
        migrationBuilder.AddForeignKey(
            name: "FK_Posts_Users_AuthorId",
            table: "Posts",
            column: "AuthorId",
            principalTable: "Users",
            principalColumn: "Id");
    }
}
''')
        result = parse_ef_migration(migration)
        refs = [e for e in result.edges if e.kind == EdgeKind.REFERENCES]
        assert len(refs) == 1
        assert "Posts" in refs[0].source_fqn
        assert "Users" in refs[0].target_fqn
