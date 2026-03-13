"""Tests for AI pipeline tool handlers."""
import json
import pytest
from unittest.mock import AsyncMock

from app.pr_analysis.ai.tools import (
    handle_tool_call,
    get_tool_definitions,
    VALID_TOOL_NAMES,
)
from app.pr_analysis.ai.tool_context import ToolContext


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repo directory with sample files."""
    # Source files
    src = tmp_path / "src" / "main" / "java" / "com" / "app"
    src.mkdir(parents=True)
    (src / "OrderService.java").write_text(
        "\n".join(f"line {i}: content" for i in range(1, 101))
    )
    (src / "BillingService.java").write_text("package com.app;\npublic class BillingService {}\n")

    # Config
    (tmp_path / "Dockerfile").write_text("FROM openjdk:17\nCOPY . /app\n")
    (tmp_path / ".env.example").write_text("DB_URL=postgres://localhost\nORDER_MAX=100\n")

    # Nested dirs
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_order.py").write_text("def test_create_order(): pass\n")

    return str(tmp_path)


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.query = AsyncMock(return_value=[])
    store.query_single = AsyncMock(return_value=None)
    return store


@pytest.fixture
def ctx(temp_repo, mock_store):
    return ToolContext(repo_path=temp_repo, graph_store=mock_store, app_name="test")


class TestToolDefinitions:
    def test_all_tools_defined(self):
        defs = get_tool_definitions()
        names = {d["name"] for d in defs}
        assert names == VALID_TOOL_NAMES

    def test_definitions_are_valid_anthropic_format(self):
        for d in get_tool_definitions():
            assert "name" in d
            assert "description" in d
            assert "input_schema" in d
            assert d["input_schema"]["type"] == "object"


class TestReadFile:
    @pytest.mark.asyncio
    async def test_reads_file(self, ctx):
        result = await handle_tool_call(ctx, "read_file", {
            "path": "src/main/java/com/app/OrderService.java"
        })
        data = json.loads(result)
        assert data["total_lines"] == 100
        assert "line 1:" in data["content"]

    @pytest.mark.asyncio
    async def test_truncates_large_file(self, ctx):
        result = await handle_tool_call(ctx, "read_file", {
            "path": "src/main/java/com/app/OrderService.java"
        })
        data = json.loads(result)
        # 100 lines < 500 threshold, so no truncation
        assert data["truncated"] is False

    @pytest.mark.asyncio
    async def test_line_range(self, ctx):
        result = await handle_tool_call(ctx, "read_file", {
            "path": "src/main/java/com/app/OrderService.java",
            "line_start": 5,
            "line_end": 10,
        })
        data = json.loads(result)
        assert "line 5:" in data["content"]
        assert "line 11:" not in data["content"]

    @pytest.mark.asyncio
    async def test_file_not_found(self, ctx):
        result = await handle_tool_call(ctx, "read_file", {"path": "nonexistent.java"})
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, ctx):
        result = await handle_tool_call(ctx, "read_file", {"path": "../../etc/passwd"})
        data = json.loads(result)
        assert "error" in data


class TestSearchFiles:
    @pytest.mark.asyncio
    async def test_search_glob(self, ctx):
        result = await handle_tool_call(ctx, "search_files", {"glob_pattern": "**/*.java"})
        data = json.loads(result)
        assert len(data["files"]) == 2

    @pytest.mark.asyncio
    async def test_no_matches(self, ctx):
        result = await handle_tool_call(ctx, "search_files", {"glob_pattern": "**/*.rs"})
        data = json.loads(result)
        assert data["files"] == []


class TestGrepContent:
    @pytest.mark.asyncio
    async def test_grep_finds_content(self, ctx):
        result = await handle_tool_call(ctx, "grep_content", {
            "pattern": "ORDER_MAX",
        })
        data = json.loads(result)
        assert data["total_matches"] >= 1
        assert any("ORDER_MAX" in m["content"] for m in data["matches"])

    @pytest.mark.asyncio
    async def test_grep_with_glob_filter(self, ctx):
        result = await handle_tool_call(ctx, "grep_content", {
            "pattern": "class",
            "glob": "*.java",
        })
        data = json.loads(result)
        assert all(m["file"].endswith(".java") for m in data["matches"])


class TestListDirectory:
    @pytest.mark.asyncio
    async def test_list_root(self, ctx):
        result = await handle_tool_call(ctx, "list_directory", {"path": ""})
        data = json.loads(result)
        names = {e["name"] for e in data["entries"]}
        assert "Dockerfile" in names
        assert "src" in names

    @pytest.mark.asyncio
    async def test_list_subdir(self, ctx):
        result = await handle_tool_call(ctx, "list_directory", {"path": "tests"})
        data = json.loads(result)
        assert len(data["entries"]) == 1


class TestQueryGraphNode:
    @pytest.mark.asyncio
    async def test_returns_node_data(self, ctx, mock_store):
        mock_store.query_single.return_value = {
            "fqn": "com.app.OrderService.create",
            "name": "create",
            "type": "Function",
            "language": "java",
            "path": "OrderService.java",
            "line": 10, "end_line": 50,
            "loc": 40, "complexity": 5,
        }
        mock_store.query.side_effect = [
            [{"fqn": "caller1", "name": "c1", "type": "Function"}],  # callers
            [{"fqn": "callee1", "name": "c2", "type": "Function"}],  # callees
        ]
        result = await handle_tool_call(ctx, "query_graph_node", {
            "fqn": "com.app.OrderService.create"
        })
        data = json.loads(result)
        assert data["node"]["fqn"] == "com.app.OrderService.create"
        assert len(data["callers"]) == 1
        assert len(data["callees"]) == 1

    @pytest.mark.asyncio
    async def test_node_not_found(self, ctx, mock_store):
        mock_store.query_single.return_value = None
        result = await handle_tool_call(ctx, "query_graph_node", {"fqn": "nonexistent"})
        data = json.loads(result)
        assert data["node"] is None


class TestGetNodeImpact:
    @pytest.mark.asyncio
    async def test_downstream_impact(self, ctx, mock_store):
        mock_store.query.return_value = [
            {"fqn": "a.b", "name": "b", "type": "Function", "file": "B.java", "depth": 1},
        ]
        result = await handle_tool_call(ctx, "get_node_impact", {
            "fqn": "a.method", "direction": "downstream",
        })
        data = json.loads(result)
        assert data["total"] == 1


class TestInvalidTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self, ctx):
        result = await handle_tool_call(ctx, "unknown_tool", {})
        data = json.loads(result)
        assert "error" in data
