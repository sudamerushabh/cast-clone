"""Tests for the unified diff parser."""

from __future__ import annotations

from app.git.diff_parser import parse_patch_hunks
from app.pr_analysis.models import DiffHunk


class TestParsePatchHunks:
    """Tests for parse_patch_hunks."""

    def test_single_hunk(self) -> None:
        patch = "@@ -10,5 +12,7 @@ some context\n+added line\n-removed line"
        hunks = parse_patch_hunks(patch)
        assert len(hunks) == 1
        assert hunks[0] == DiffHunk(
            old_start=10, old_count=5, new_start=12, new_count=7
        )

    def test_multiple_hunks(self) -> None:
        patch = (
            "@@ -1,3 +1,4 @@ first hunk\n"
            "+new line\n"
            "@@ -20,10 +21,12 @@ second hunk\n"
            "+another new line\n"
        )
        hunks = parse_patch_hunks(patch)
        assert len(hunks) == 2
        assert hunks[0] == DiffHunk(
            old_start=1, old_count=3, new_start=1, new_count=4
        )
        assert hunks[1] == DiffHunk(
            old_start=20, old_count=10, new_start=21, new_count=12
        )

    def test_empty_patch(self) -> None:
        assert parse_patch_hunks("") == []

    def test_none_patch(self) -> None:
        assert parse_patch_hunks(None) == []

    def test_no_hunk_headers(self) -> None:
        patch = "just some text\nwithout any hunk headers\n"
        assert parse_patch_hunks(patch) == []

    def test_single_line_hunk_defaults_count_to_1(self) -> None:
        # When count is omitted, it means a single line
        patch = "@@ -5 +8 @@ single line change"
        hunks = parse_patch_hunks(patch)
        assert len(hunks) == 1
        assert hunks[0] == DiffHunk(
            old_start=5, old_count=1, new_start=8, new_count=1
        )

    def test_mixed_with_and_without_counts(self) -> None:
        patch = "@@ -5 +8,3 @@ mixed"
        hunks = parse_patch_hunks(patch)
        assert len(hunks) == 1
        assert hunks[0] == DiffHunk(
            old_start=5, old_count=1, new_start=8, new_count=3
        )

    def test_new_end_property(self) -> None:
        hunk = DiffHunk(old_start=1, old_count=5, new_start=10, new_count=3)
        assert hunk.new_end == 12
