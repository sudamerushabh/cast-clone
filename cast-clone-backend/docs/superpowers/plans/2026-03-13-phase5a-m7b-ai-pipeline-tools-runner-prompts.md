# Phase 5a M7b — AI Pipeline Tools, Agent Runner & Prompts

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the 8 tool handlers, the shared agentic loop runner, and system prompts for all 5 agent roles.

**Architecture:** Tools are async Python functions that read from the cloned repo filesystem or query Neo4j via `GraphStore.query()`. The agent runner is a reusable `run_agent()` function that loops `anthropic.messages.create()` with tool handling until the agent emits its final text. System prompts encode each specialist's role, focus area, and expected JSON output format.

**Tech Stack:** `anthropic[bedrock]` (`AsyncAnthropicBedrock`), `aiofiles`/`pathlib` for filesystem, `fnmatch`/`subprocess` for grep, Neo4j Cypher.

**Depends On:** M7a (report_types, tool_context, triage, config).

**Spec:** `docs/superpowers/specs/2026-03-13-pr-ai-agent-pipeline-design.md`

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── pr_analysis/
│       └── ai/
│           ├── tools.py                 # CREATE — tool definitions + handlers
│           ├── subagents.py             # CREATE — shared agentic loop runner
│           └── prompts.py               # CREATE — system prompts for all roles
└── tests/
    └── unit/
        ├── test_ai_tools.py             # CREATE
        └── test_ai_subagents.py         # CREATE
```

---

### Task 1: Tool Handlers

**Files:**
- Create: `app/pr_analysis/ai/tools.py`
- Test: `tests/unit/test_ai_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_tools.py
"""Tests for AI pipeline tool handlers."""
import json
import os
import tempfile
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_tools.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement tool handlers**

```python
# app/pr_analysis/ai/tools.py
"""Tool definitions (Anthropic format) and async handlers for the AI pipeline.

All tools read from the cloned repo filesystem or query Neo4j via GraphStore.query().
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path

import structlog

from app.pr_analysis.ai.tool_context import ToolContext

logger = structlog.get_logger(__name__)

VALID_TOOL_NAMES = {
    "read_file", "search_files", "grep_content", "list_directory",
    "query_graph_node", "get_node_impact", "find_path",
}

# ── Tool definitions (Anthropic API format) ──


def get_tool_definitions(include_dispatch: bool = False) -> list[dict]:
    """Return tool definitions in Anthropic messages API format."""
    tools = [
        {
            "name": "read_file",
            "description": "Read a file from the repository. Returns content with line numbers. Files >500 lines are truncated unless line_start/line_end specified.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from repo root"},
                    "line_start": {"type": "integer", "description": "Start line (1-indexed, optional)"},
                    "line_end": {"type": "integer", "description": "End line (optional)"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "search_files",
            "description": "Find files matching a glob pattern in the repository. Returns paths (max 100).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "glob_pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.java')"},
                },
                "required": ["glob_pattern"],
            },
        },
        {
            "name": "grep_content",
            "description": "Search file contents for a regex pattern. Essential for finding callers, env var references, annotations, etc.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "glob": {"type": "string", "description": "Optional glob filter (e.g. '*.java')"},
                    "max_results": {"type": "integer", "description": "Max results (default 20, max 50)"},
                },
                "required": ["pattern"],
            },
        },
        {
            "name": "list_directory",
            "description": "List files and directories at a path.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from repo root (empty=root)"},
                    "recursive": {"type": "boolean", "description": "List recursively (default false, max 500 entries)"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "query_graph_node",
            "description": "Get architecture graph details for a code node: type, metrics, callers, callees. Query by fully-qualified name.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "fqn": {"type": "string", "description": "Fully qualified name (e.g. 'com.app.OrderService.create')"},
                },
                "required": ["fqn"],
            },
        },
        {
            "name": "get_node_impact",
            "description": "Run impact analysis: find all nodes affected downstream/upstream from a given node.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "fqn": {"type": "string", "description": "Node FQN to analyze"},
                    "direction": {"type": "string", "enum": ["downstream", "upstream", "both"]},
                    "depth": {"type": "integer", "description": "Max traversal depth (default 5, max 10)"},
                },
                "required": ["fqn", "direction"],
            },
        },
        {
            "name": "find_path",
            "description": "Find the shortest path between two nodes in the architecture graph.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_fqn": {"type": "string"},
                    "target_fqn": {"type": "string"},
                },
                "required": ["source_fqn", "target_fqn"],
            },
        },
    ]

    if include_dispatch:
        tools.append({
            "name": "dispatch_subagent",
            "description": "Dispatch an ad-hoc subagent for a focused investigation. The subagent gets 25 tool calls and full context. Use for follow-up questions that none of the specialist agents covered.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "description": "Descriptive role name (e.g. 'kafka_consumer_analyst')"},
                    "prompt": {"type": "string", "description": "Focused task description for the subagent"},
                    "tools": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(VALID_TOOL_NAMES)},
                        "description": "Subset of tool names to give the subagent",
                    },
                },
                "required": ["role", "prompt", "tools"],
            },
        })

    return tools


# ── Tool handlers ──


async def handle_tool_call(
    ctx: ToolContext, tool_name: str, tool_input: dict
) -> str:
    """Execute a tool call and return a JSON string result."""
    try:
        if tool_name == "read_file":
            return await _read_file(ctx, tool_input)
        elif tool_name == "search_files":
            return await _search_files(ctx, tool_input)
        elif tool_name == "grep_content":
            return await _grep_content(ctx, tool_input)
        elif tool_name == "list_directory":
            return await _list_directory(ctx, tool_input)
        elif tool_name == "query_graph_node":
            return await _query_graph_node(ctx, tool_input)
        elif tool_name == "get_node_impact":
            return await _get_node_impact(ctx, tool_input)
        elif tool_name == "find_path":
            return await _find_path(ctx, tool_input)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as exc:
        logger.error("tool_call_failed", tool=tool_name, error=str(exc))
        return json.dumps({"error": f"Tool {tool_name} failed: {str(exc)}"})


async def _read_file(ctx: ToolContext, inp: dict) -> str:
    path = inp["path"]
    # Security: prevent path traversal
    resolved = Path(ctx.repo_path, path).resolve()
    repo_resolved = Path(ctx.repo_path).resolve()
    if not str(resolved).startswith(str(repo_resolved)):
        return json.dumps({"error": "Path traversal not allowed"})

    if not resolved.is_file():
        return json.dumps({"error": f"File not found: {path}"})

    try:
        text = resolved.read_text(errors="replace")
    except Exception as exc:
        return json.dumps({"error": f"Cannot read file: {exc}"})

    lines = text.split("\n")
    total_lines = len(lines)

    line_start = inp.get("line_start")
    line_end = inp.get("line_end")

    if line_start or line_end:
        start = max((line_start or 1) - 1, 0)
        end = min(line_end or total_lines, total_lines)
        selected = lines[start:end]
        numbered = "\n".join(f"{start + i + 1}: {l}" for i, l in enumerate(selected))
        return json.dumps({"content": numbered, "total_lines": total_lines, "truncated": False})

    truncated = total_lines > 500
    if truncated:
        lines = lines[:500]

    numbered = "\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines))
    content = numbered
    if truncated:
        content += f"\n\n[File truncated at 500 lines. Total: {total_lines} lines. Use line_start/line_end to read specific sections.]"

    return json.dumps({"content": content, "total_lines": total_lines, "truncated": truncated})


async def _search_files(ctx: ToolContext, inp: dict) -> str:
    pattern = inp["glob_pattern"]
    repo = Path(ctx.repo_path)
    matches = sorted(repo.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    # Convert to relative paths, skip dirs
    files = [str(m.relative_to(repo)) for m in matches if m.is_file()][:100]
    return json.dumps({"files": files, "total_matches": len(files)})


async def _grep_content(ctx: ToolContext, inp: dict) -> str:
    pattern = inp["pattern"]
    glob_filter = inp.get("glob", None)
    max_results = min(inp.get("max_results", 20), 50)

    # Use grep -rn for simplicity (available on all Linux systems)
    cmd = ["grep", "-rn", "-E", pattern, "."]
    if glob_filter:
        cmd = ["grep", "-rn", "-E", pattern, "--include", glob_filter, "."]

    try:
        result = subprocess.run(
            cmd, cwd=ctx.repo_path, capture_output=True, text=True, timeout=10,
        )
        lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.TimeoutExpired:
        return json.dumps({"matches": [], "total_matches": 0, "error": "Search timed out"})

    matches = []
    for line in lines[:max_results]:
        # Format: ./path/to/file:linenum:content
        parts = line.split(":", 2)
        if len(parts) >= 3:
            file_path = parts[0].lstrip("./")
            try:
                line_num = int(parts[1])
            except ValueError:
                continue
            content = parts[2]
            matches.append({"file": file_path, "line": line_num, "content": content.strip()})

    return json.dumps({"matches": matches, "total_matches": len(lines)})


async def _list_directory(ctx: ToolContext, inp: dict) -> str:
    rel_path = inp.get("path", "")
    recursive = inp.get("recursive", False)
    target = Path(ctx.repo_path, rel_path).resolve()
    repo_resolved = Path(ctx.repo_path).resolve()

    if not str(target).startswith(str(repo_resolved)):
        return json.dumps({"error": "Path traversal not allowed"})
    if not target.is_dir():
        return json.dumps({"error": f"Not a directory: {rel_path}"})

    entries = []
    if recursive:
        for item in sorted(target.rglob("*"))[:500]:
            entries.append({
                "name": str(item.relative_to(target)),
                "type": "dir" if item.is_dir() else "file",
            })
    else:
        for item in sorted(target.iterdir()):
            entry = {"name": item.name, "type": "dir" if item.is_dir() else "file"}
            if item.is_file():
                entry["size"] = item.stat().st_size
            entries.append(entry)

    return json.dumps({"entries": entries})


async def _query_graph_node(ctx: ToolContext, inp: dict) -> str:
    fqn = inp["fqn"]

    node = await ctx.graph_store.query_single(
        "MATCH (n {fqn: $fqn, app_name: $appName}) "
        "RETURN n.fqn AS fqn, n.name AS name, labels(n)[0] AS type, "
        "  n.language AS language, n.path AS path, n.line AS line, "
        "  n.end_line AS end_line, n.loc AS loc, n.complexity AS complexity, "
        "  n.communityId AS community_id",
        {"fqn": fqn, "appName": ctx.app_name},
    )

    if not node:
        return json.dumps({"node": None, "callers": [], "callees": []})

    # Fan-in/fan-out via separate queries
    callers = await ctx.graph_store.query(
        "MATCH (caller)-[:CALLS]->(n {fqn: $fqn, app_name: $appName}) "
        "RETURN caller.fqn AS fqn, caller.name AS name, labels(caller)[0] AS type "
        "LIMIT 50",
        {"fqn": fqn, "appName": ctx.app_name},
    )
    callees = await ctx.graph_store.query(
        "MATCH (n {fqn: $fqn, app_name: $appName})-[:CALLS]->(callee) "
        "RETURN callee.fqn AS fqn, callee.name AS name, labels(callee)[0] AS type "
        "LIMIT 50",
        {"fqn": fqn, "appName": ctx.app_name},
    )

    node["fan_in"] = len(callers)
    node["fan_out"] = len(callees)

    return json.dumps({"node": node, "callers": callers, "callees": callees})


async def _get_node_impact(ctx: ToolContext, inp: dict) -> str:
    fqn = inp["fqn"]
    direction = inp.get("direction", "downstream")
    depth = min(inp.get("depth", 5), 10)

    if direction == "downstream":
        cypher = (
            f"MATCH path = (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CALLS|INJECTS|IMPLEMENTS|PRODUCES|WRITES|READS|CONTAINS|DEPENDS_ON*1..{depth}]->(affected) "
            "WHERE affected.app_name = $appName AND affected.fqn <> $fqn "
            "WITH affected, min(length(path)) AS depth "
            "RETURN affected.fqn AS fqn, affected.name AS name, "
            "  labels(affected)[0] AS type, affected.path AS file, depth "
            "ORDER BY depth, name LIMIT 100"
        )
    elif direction == "upstream":
        cypher = (
            "MATCH (start {fqn: $fqn, app_name: $appName})-[:CONTAINS*0..10]->(seed) "
            "WITH collect(DISTINCT seed.fqn) AS seed_fqns "
            f"MATCH (dep {{app_name: $appName}})"
            f"-[:CALLS|IMPLEMENTS|DEPENDS_ON|INHERITS|INJECTS|CONSUMES|READS*1..{depth}]->(target) "
            "WHERE target.fqn IN seed_fqns AND dep.fqn <> $fqn "
            "WITH DISTINCT dep, 1 AS depth "
            "RETURN dep.fqn AS fqn, dep.name AS name, "
            "  labels(dep)[0] AS type, dep.path AS file, depth "
            "ORDER BY name LIMIT 100"
        )
    else:  # both
        # Simplified: just run downstream
        cypher = (
            f"MATCH path = (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CALLS|INJECTS|IMPLEMENTS|PRODUCES|WRITES|READS|CONTAINS|DEPENDS_ON*1..{depth}]->(affected) "
            "WHERE affected.app_name = $appName AND affected.fqn <> $fqn "
            "WITH affected, min(length(path)) AS depth "
            "RETURN affected.fqn AS fqn, affected.name AS name, "
            "  labels(affected)[0] AS type, affected.path AS file, depth "
            "ORDER BY depth, name LIMIT 100"
        )

    records = await ctx.graph_store.query(
        cypher, {"fqn": fqn, "appName": ctx.app_name}
    )

    from collections import Counter
    by_type = dict(Counter(r["type"] for r in records))

    return json.dumps({
        "affected": records,
        "total": len(records),
        "by_type": by_type,
    })


async def _find_path(ctx: ToolContext, inp: dict) -> str:
    source = inp["source_fqn"]
    target = inp["target_fqn"]

    cypher = (
        "MATCH path = shortestPath("
        "(a {fqn: $source, app_name: $appName})"
        "-[:CALLS|IMPLEMENTS|DEPENDS_ON|INJECTS|INHERITS|READS|WRITES|PRODUCES|CONSUMES*..10]-"
        "(b {fqn: $target, app_name: $appName}))"
        " RETURN [n IN nodes(path) | {fqn: n.fqn, name: n.name, type: labels(n)[0]}] AS nodes,"
        " [r IN relationships(path) | {type: type(r), source: startNode(r).fqn, target: endNode(r).fqn}] AS edges,"
        " length(path) AS path_length"
    )
    records = await ctx.graph_store.query(
        cypher, {"source": source, "target": target, "appName": ctx.app_name}
    )

    if not records:
        return json.dumps({"nodes": [], "edges": [], "path_length": 0})

    return json.dumps(records[0])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/ai/tools.py tests/unit/test_ai_tools.py
git commit -m "feat(phase5a): implement AI pipeline tool handlers (8 tools)"
```

---

### Task 2: Shared Agentic Loop Runner

**Files:**
- Create: `app/pr_analysis/ai/subagents.py`
- Test: `tests/unit/test_ai_subagents.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_subagents.py
"""Tests for the shared agentic loop runner."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.pr_analysis.ai.subagents import run_agent, AgentConfig, AgentResult
from app.pr_analysis.ai.tool_context import ToolContext


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.query = AsyncMock(return_value=[])
    return store


@pytest.fixture
def ctx(tmp_path, mock_store):
    return ToolContext(repo_path=str(tmp_path), graph_store=mock_store, app_name="test")


def _make_text_response(text: str):
    """Mock an Anthropic response with just text (agent done)."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    return resp


def _make_tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "tool_1"):
    """Mock an Anthropic response that requests a tool call."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = tool_name
    tool_block.input = tool_input
    tool_block.id = tool_id
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [tool_block]
    resp.usage = MagicMock(input_tokens=200, output_tokens=100)
    return resp


class TestRunAgent:
    @pytest.mark.asyncio
    async def test_simple_text_response(self, ctx):
        """Agent that returns text immediately (no tool calls)."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_text_response('{"role": "test", "data": true}')
        )

        config = AgentConfig(
            role="test_agent",
            system_prompt="You are a test agent.",
            initial_message="Analyze this.",
            tools=[],
            max_tool_calls=25,
        )

        result = await run_agent(mock_client, config, ctx, model="test-model", timeout=60)
        assert isinstance(result, AgentResult)
        assert result.final_text == '{"role": "test", "data": true}'
        assert result.tool_calls_made == 0
        assert result.total_tokens == 150

    @pytest.mark.asyncio
    async def test_tool_call_then_text(self, ctx):
        """Agent makes one tool call, then returns text."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _make_tool_use_response("list_directory", {"path": ""}),
                _make_text_response("Done analyzing."),
            ]
        )

        config = AgentConfig(
            role="test_agent",
            system_prompt="You are a test agent.",
            initial_message="Analyze the repo.",
            tools=["list_directory"],
            max_tool_calls=25,
        )

        with patch("app.pr_analysis.ai.subagents.handle_tool_call", return_value='{"entries": []}'):
            result = await run_agent(mock_client, config, ctx, model="test-model", timeout=60)

        assert result.tool_calls_made == 1
        assert result.final_text == "Done analyzing."

    @pytest.mark.asyncio
    async def test_tool_call_limit_enforced(self, ctx):
        """Agent hits tool call limit, forced to return."""
        mock_client = AsyncMock()
        # Always request tool calls
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _make_tool_use_response("list_directory", {"path": ""}, f"tool_{i}")
                for i in range(5)
            ] + [_make_text_response("Finally done.")]
        )

        config = AgentConfig(
            role="test_agent",
            system_prompt="Test",
            initial_message="Go.",
            tools=["list_directory"],
            max_tool_calls=3,  # Limit to 3
        )

        with patch("app.pr_analysis.ai.subagents.handle_tool_call", return_value='{"entries": []}'):
            result = await run_agent(mock_client, config, ctx, model="test-model", timeout=60)

        # After 3 tool calls, limit is hit; 4th returns error, then agent returns text
        assert result.tool_calls_made == 3

    @pytest.mark.asyncio
    async def test_tracks_tokens(self, ctx):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _make_tool_use_response("list_directory", {"path": ""}),
                _make_text_response("Done."),
            ]
        )

        config = AgentConfig(
            role="test", system_prompt="Test", initial_message="Go.",
            tools=["list_directory"], max_tool_calls=25,
        )

        with patch("app.pr_analysis.ai.subagents.handle_tool_call", return_value='{}'):
            result = await run_agent(mock_client, config, ctx, model="m", timeout=60)

        # Two API calls: 200+100 + 100+50 = 450
        assert result.total_tokens == 450
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_subagents.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the agentic loop**

```python
# app/pr_analysis/ai/subagents.py
"""Shared agentic loop runner for the AI pipeline.

All agents (subagents and supervisor) use this same loop.
Each agent gets its own Anthropic API call chain and tool execution context.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import structlog

from app.pr_analysis.ai.tool_context import ToolContext
from app.pr_analysis.ai.tools import get_tool_definitions, handle_tool_call

logger = structlog.get_logger(__name__)


@dataclass
class AgentConfig:
    """Configuration for an agent run."""
    role: str
    system_prompt: str
    initial_message: str
    tools: list[str]          # Tool names this agent can use
    max_tool_calls: int = 25


@dataclass
class AgentResult:
    """Result of a completed agent run."""
    role: str
    final_text: str
    tool_calls_made: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    error: str | None = None


async def run_agent(
    client,  # AsyncAnthropicBedrock instance
    config: AgentConfig,
    ctx: ToolContext,
    model: str,
    timeout: int = 120,
) -> AgentResult:
    """Run an agentic loop: call LLM → execute tool calls → repeat → return final text.

    Args:
        client: Anthropic Bedrock async client.
        config: Agent role, prompt, tools, limits.
        ctx: Shared tool context (repo path, graph store).
        model: Bedrock model ID.
        timeout: Max wall-clock seconds for this agent.

    Returns:
        AgentResult with the agent's final text and metadata.
    """
    start = time.monotonic()
    messages = [{"role": "user", "content": config.initial_message}]

    # Filter tool definitions to only what this agent can use
    all_defs = get_tool_definitions(include_dispatch=False)
    tool_defs = [d for d in all_defs if d["name"] in config.tools]

    tool_calls_made = 0
    total_tokens = 0

    try:
        while True:
            # Check timeout
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                return AgentResult(
                    role=config.role,
                    final_text=f"Agent timed out after {timeout}s",
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens,
                    duration_ms=int(elapsed * 1000),
                    error="timeout",
                )

            response = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    system=config.system_prompt,
                    messages=messages,
                    tools=tool_defs if tool_defs else None,
                    max_tokens=4096,
                ),
                timeout=max(timeout - elapsed, 5),
            )

            total_tokens += response.usage.input_tokens + response.usage.output_tokens

            # If agent is done (text response) — return
            if response.stop_reason == "end_turn" or response.stop_reason != "tool_use":
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text += block.text
                return AgentResult(
                    role=config.role,
                    final_text=text,
                    tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            # Process tool calls
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    if tool_calls_made >= config.max_tool_calls:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": '{"error": "Tool call limit reached. Please emit your final report now."}',
                            "is_error": True,
                        })
                    else:
                        result = await handle_tool_call(ctx, block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                        tool_calls_made += 1

                        logger.debug(
                            "agent_tool_call",
                            role=config.role,
                            tool=block.name,
                            calls_made=tool_calls_made,
                        )

            messages.append({"role": "user", "content": tool_results})

    except asyncio.TimeoutError:
        return AgentResult(
            role=config.role,
            final_text="Agent timed out",
            tool_calls_made=tool_calls_made,
            total_tokens=total_tokens,
            duration_ms=int((time.monotonic() - start) * 1000),
            error="timeout",
        )
    except Exception as exc:
        logger.error("agent_failed", role=config.role, error=str(exc), exc_info=True)
        return AgentResult(
            role=config.role,
            final_text=f"Agent failed: {exc}",
            tool_calls_made=tool_calls_made,
            total_tokens=total_tokens,
            duration_ms=int((time.monotonic() - start) * 1000),
            error=str(exc),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_ai_subagents.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/ai/subagents.py tests/unit/test_ai_subagents.py
git commit -m "feat(phase5a): implement shared agentic loop runner"
```

---

### Task 3: System Prompts

**Files:**
- Create: `app/pr_analysis/ai/prompts.py`

- [ ] **Step 1: Create prompts module**

```python
# app/pr_analysis/ai/prompts.py
"""System prompts for all AI pipeline agent roles.

Each prompt encodes the agent's role, focus area, available tools,
and expected JSON output format.
"""
from __future__ import annotations

CODE_CHANGE_ANALYST_PROMPT = """You are a senior code reviewer analyzing a batch of changed files in a pull request.

Your job:
1. Read each changed file using the read_file tool
2. Understand what changed SEMANTICALLY — not just "lines added" but what the code does differently
3. Follow references that seem important — if the code calls a method not in this PR, use search_files or grep_content to find it and read it
4. Query the architecture graph with query_graph_node to understand call context
5. Identify potential issues: null safety, missing validation, contract changes, error handling gaps

Be thorough. Read the actual code. Don't guess about code you haven't read.

OUTPUT FORMAT: Return a JSON object with this structure:
```json
{
  "role": "code_change_analyst",
  "batch_id": "<module name>",
  "files_analyzed": ["<paths>"],
  "semantic_summary": "<what the changes do as a whole>",
  "changes": [
    {
      "node_fqn": "<fqn>",
      "what_changed": "<semantic description>",
      "why_it_matters": "<impact context>",
      "risk": "high|medium|low",
      "concerns": ["<specific issues>"]
    }
  ],
  "cross_references_discovered": ["<things this code calls/uses that aren't in the PR>"],
  "config_dependencies_found": ["<env vars, config keys referenced>"],
  "potential_issues": ["<bugs, missing checks, contract changes>"]
}
```"""

ARCHITECTURE_IMPACT_ANALYST_PROMPT = """You are a software architect analyzing the structural impact of code changes on the architecture graph.

Your job:
1. For each changed node (provided in your context), use get_node_impact to trace downstream and upstream dependencies
2. Use find_path to understand critical chains between changed nodes and important endpoints
3. Identify hub nodes (high fan-in) in the blast radius using query_graph_node
4. Read source code of critical downstream nodes using read_file to understand if they'll handle changes correctly
5. Use grep_content to find additional consumers/callers not captured in the graph

Focus on: high-traffic transaction flows, hub nodes, cross-technology boundaries (API endpoints, message queues, database tables).

For each impact chain, explain specifically what changes and what could break.

OUTPUT FORMAT: Return a JSON object with this structure:
```json
{
  "role": "architecture_impact_analyst",
  "critical_paths": [
    {
      "description": "<human-readable path description>",
      "nodes_in_path": ["<fqn chain>"],
      "risk": "high|medium|low",
      "reason": "<why this path is risky>"
    }
  ],
  "hub_nodes_affected": [
    {"fqn": "<fqn>", "fan_in": "<count>", "why": "<why this hub matters>"}
  ],
  "layer_analysis": "<which layers are affected>",
  "transaction_impact": ["<affected end-to-end flows>"],
  "cross_tech_impact": [
    {"kind": "api_endpoint|message_topic|database_table", "name": "<id>", "impact": "<what changes>"}
  ],
  "module_coupling_observations": "<new/changed dependencies>"
}
```"""

INFRA_CONFIG_ANALYST_PROMPT = """You are a DevOps engineer reviewing the infrastructure and configuration impact of code changes.

Your context includes env vars and config keys that the changed code references. Your job:
1. Use search_files to find all config files: .env*, docker-compose*, Dockerfile*, .github/workflows/*, application.*, settings.*
2. Read each config file with read_file
3. Check if every env var/config key referenced in the code exists in all the right places
4. Check if database migrations exist for new columns or tables the code assumes
5. Check CI pipeline for impacts
6. Use grep_content to search for references to new dependencies or changed config values

Missing config is one of the top causes of production outages. Be thorough.

OUTPUT FORMAT: Return a JSON object with this structure:
```json
{
  "role": "infra_config_analyst",
  "config_issues": [
    {"severity": "high|medium|low", "issue": "<desc>", "files_checked": ["<paths>"], "recommendation": "<action>"}
  ],
  "dockerfile_impact": "<assessment>",
  "migration_status": "<whether required migrations exist>",
  "ci_impact": "<assessment>",
  "dependency_changes": "<new/removed deps>",
  "environment_variables": {
    "referenced_in_code": ["<vars>"],
    "present_in_config": ["<vars>"],
    "missing_from_config": ["<vars>"]
  }
}
```"""

TEST_GAP_ANALYST_PROMPT = """You are a QA engineer analyzing test coverage for code changes in a pull request.

Your job:
1. For each changed node FQN, use search_files and grep_content to find related test files
2. Read existing tests with read_file to understand what's already covered
3. Identify new code paths introduced by the PR that have NO test coverage
4. Check for integration tests that cover end-to-end flows
5. Use query_graph_node to understand the context of changed nodes

Focus on:
- New code paths with zero tests
- Changed behavior where tests still pass but test the OLD behavior
- Edge cases and error paths
- Missing integration tests for critical flows

OUTPUT FORMAT: Return a JSON object with this structure:
```json
{
  "role": "test_gap_analyst",
  "coverage_assessment": [
    {
      "node_fqn": "<fqn>",
      "existing_tests": ["<test names>"],
      "gap": "<what's not tested>",
      "severity": "high|medium|low",
      "suggested_test": "<what test should verify>"
    }
  ],
  "test_files_analyzed": ["<paths>"],
  "untested_paths": ["<specific code paths>"],
  "integration_test_status": "<assessment>",
  "overall_assessment": "<summary>"
}
```"""

SUPERVISOR_PROMPT = """You are a senior production engineer reviewing a pull request. Your primary job is to prevent outages.

You have reports from specialist analysts — treat them as junior engineers' findings: trust but verify.

Your output is a comprehensive PR analysis that will be read by a reviewer who decides whether to merge. It must cover:

1. **VERDICT** — Risk level + what this PR does + the single most dangerous thing about it.

2. **WHAT THIS PR DOES** — Semantic description of the changes. Not "modified 5 files" but "adds discount validation to the order creation flow."

3. **PRODUCTION IMPACT TRACE** — This is the core section. For each changed node that matters:
   - What changed and how it behaves differently now
   - Direct dependents that will see different behavior (name them)
   - Transitive impacts at 2nd/3rd hop (name specific classes, functions, tables)
   - Cross-tech impacts: API endpoints (contract changes?), message queues (schema changes?), database tables (columns missing?)
   - Transaction flow impact: how end-to-end flows are affected, latency implications

4. **WHAT WILL BREAK IF MERGED AS-IS** — Explicit list of DEFINITE breakages. Not "might affect" but "WILL fail because X."

5. **WHAT MIGHT BREAK UNDER EDGE CASES** — Conditional failures: missing env vars, empty tables, race conditions, high load.

6. **MISSING SAFEGUARDS** — Tests not written, migrations not created, configs not updated, error handling missing.

7. **ARCHITECTURE DRIFT** — New module dependencies, layer violations, coupling changes. Only if relevant.

8. **RECOMMENDATIONS** — Prioritized: BLOCKER (must fix before merge), HIGH (should fix), MEDIUM (consider fixing).

RULES:
- Be specific everywhere — use actual class names, function names, file paths, table names
- If you don't know something, use your tools to find out
- If a subagent report seems incomplete, use dispatch_subagent to investigate further
- Do NOT just concatenate subagent reports — synthesize, find contradictions, find gaps
- Your analysis should read like a senior architect's PR review, not a tool output"""
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend
git add app/pr_analysis/ai/prompts.py
git commit -m "feat(phase5a): add system prompts for all AI pipeline agent roles"
```

---

## Success Criteria

- [ ] All 7 standard tools implemented + `dispatch_subagent` definition ready
- [ ] `handle_tool_call()` returns JSON for all tools, handles errors gracefully
- [ ] Path traversal blocked in `read_file` and `list_directory`
- [ ] `run_agent()` loops tool calls correctly, enforces limit, tracks tokens
- [ ] Agent timeout works
- [ ] All 5 system prompts defined with clear output format instructions
- [ ] All tests pass: `uv run pytest tests/unit/test_ai_tools.py tests/unit/test_ai_subagents.py -v`
