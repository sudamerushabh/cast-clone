"""Unified diff parser for extracting hunk information."""

from __future__ import annotations

import re

from app.pr_analysis.models import DiffHunk

_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE
)


def parse_patch_hunks(patch: str | None) -> list[DiffHunk]:
    """Parse unified diff patch text and extract hunk ranges.

    Args:
        patch: The raw unified diff text. May be None or empty.

    Returns:
        A list of DiffHunk objects, one per hunk header found.
    """
    if not patch:
        return []

    hunks: list[DiffHunk] = []
    for match in _HUNK_HEADER_RE.finditer(patch):
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) is not None else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) is not None else 1
        hunks.append(
            DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
            )
        )
    return hunks
