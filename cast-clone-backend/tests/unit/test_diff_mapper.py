"""Tests for diff-to-graph mapping."""

import pytest
from unittest.mock import AsyncMock

from app.pr_analysis.diff_mapper import DiffMapper
from app.pr_analysis.models import DiffHunk, FileDiff, PRDiff


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.query = AsyncMock(return_value=[])
    return store


class TestDiffMapperBasic:
    @pytest.mark.asyncio
    async def test_empty_diff_returns_empty(self, mock_store):
        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[],
            total_additions=0,
            total_deletions=0,
            total_files_changed=0,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert result.changed_nodes == []
        assert result.new_files == []
        assert result.non_graph_files == []

    @pytest.mark.asyncio
    async def test_modified_file_queries_neo4j(self, mock_store):
        mock_store.query.return_value = [
            {
                "fqn": "com.app.OrderService.createOrder",
                "name": "createOrder",
                "type": "Function",
                "path": "src/main/java/com/app/OrderService.java",
                "line": 45,
                "end_line": 80,
                "language": "java",
                "change_type": "modified",
            }
        ]
        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[
                FileDiff(
                    path="src/main/java/com/app/OrderService.java",
                    status="modified",
                    old_path=None,
                    additions=5,
                    deletions=2,
                    hunks=[
                        DiffHunk(
                            old_start=50,
                            old_count=5,
                            new_start=50,
                            new_count=8,
                        )
                    ],
                )
            ],
            total_additions=5,
            total_deletions=2,
            total_files_changed=1,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert len(result.changed_nodes) == 1
        assert result.changed_nodes[0].fqn == "com.app.OrderService.createOrder"

    @pytest.mark.asyncio
    async def test_added_file_marked_as_new(self, mock_store):
        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[
                FileDiff(
                    path="src/main/java/com/app/NewService.java",
                    status="added",
                    old_path=None,
                    additions=50,
                    deletions=0,
                    hunks=[
                        DiffHunk(
                            old_start=0,
                            old_count=0,
                            new_start=1,
                            new_count=50,
                        )
                    ],
                )
            ],
            total_additions=50,
            total_deletions=0,
            total_files_changed=1,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert "src/main/java/com/app/NewService.java" in result.new_files

    @pytest.mark.asyncio
    async def test_deleted_file_queries_all_nodes(self, mock_store):
        mock_store.query.return_value = [
            {
                "fqn": "com.app.OldService",
                "name": "OldService",
                "type": "Class",
                "path": "src/main/java/com/app/OldService.java",
                "line": 1,
                "end_line": 100,
                "language": "java",
                "change_type": "deleted",
            }
        ]
        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[
                FileDiff(
                    path="src/main/java/com/app/OldService.java",
                    status="deleted",
                    old_path=None,
                    additions=0,
                    deletions=50,
                    hunks=[],
                )
            ],
            total_additions=0,
            total_deletions=50,
            total_files_changed=1,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert len(result.changed_nodes) == 1
        assert result.changed_nodes[0].change_type == "deleted"

    @pytest.mark.asyncio
    async def test_renamed_file_uses_old_path(self, mock_store):
        mock_store.query.return_value = [
            {
                "fqn": "com.app.Service",
                "name": "Service",
                "type": "Class",
                "path": "old/Service.java",
                "line": 1,
                "end_line": 50,
                "language": "java",
            }
        ]
        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[
                FileDiff(
                    path="new/Service.java",
                    status="renamed",
                    old_path="old/Service.java",
                    additions=0,
                    deletions=0,
                    hunks=[],
                )
            ],
            total_additions=0,
            total_deletions=0,
            total_files_changed=1,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert len(result.changed_nodes) == 1

    @pytest.mark.asyncio
    async def test_non_graph_file_detected(self, mock_store):
        mock_store.query.return_value = []
        mapper = DiffMapper(mock_store, app_name="test-project")
        diff = PRDiff(
            files=[
                FileDiff(
                    path="README.md",
                    status="modified",
                    old_path=None,
                    additions=5,
                    deletions=2,
                    hunks=[
                        DiffHunk(
                            old_start=1,
                            old_count=5,
                            new_start=1,
                            new_count=8,
                        )
                    ],
                )
            ],
            total_additions=5,
            total_deletions=2,
            total_files_changed=1,
        )
        result = await mapper.map_diff_to_nodes(diff)
        assert "README.md" in result.non_graph_files
