"""Tool definitions (Anthropic format) and async handlers for the AI pipeline.

All tools read from the cloned repo filesystem or query Neo4j via GraphStore.query().
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

import structlog

from app.ai.tools import (
    CONTAINS_HIERARCHY_MAX_DEPTH,
    FIND_PATH_MAX_DEPTH,
    IMPACT_MAX_DEPTH,
    _validate_depth,
)
from app.pr_analysis.ai.tool_context import ToolContext

logger = structlog.get_logger(__name__)

VALID_TOOL_NAMES = {
    "read_file",
    "search_files",
    "grep_content",
    "list_directory",
    "query_graph_node",
    "get_node_impact",
    "find_path",
}

# -- Tool definitions (Anthropic API format) --


def get_tool_definitions(include_dispatch: bool = False) -> list[dict]:
    """Return tool definitions in Anthropic messages API format."""
    tools = [
        {
            "name": "read_file",
            "description": "Read a file from the repository. Returns content with line numbers. Files >500 lines are truncated unless line_start/line_end specified.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from repo root",
                    },
                    "line_start": {
                        "type": "integer",
                        "description": "Start line (1-indexed, optional)",
                    },
                    "line_end": {
                        "type": "integer",
                        "description": "End line (optional)",
                    },
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
                    "glob_pattern": {
                        "type": "string",
                        "description": "Glob pattern (e.g. '**/*.java')",
                    },
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
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for",
                    },
                    "glob": {
                        "type": "string",
                        "description": "Optional glob filter (e.g. '*.java')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results (default 20, max 50)",
                    },
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
                    "path": {
                        "type": "string",
                        "description": "Relative path from repo root (empty=root)",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "List recursively (default false, max 500 entries)",
                    },
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
                    "fqn": {
                        "type": "string",
                        "description": "Fully qualified name (e.g. 'com.app.OrderService.create')",
                    },
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
                    "direction": {
                        "type": "string",
                        "enum": ["downstream", "upstream", "both"],
                    },
                    "depth": {
                        "type": "integer",
                        "description": f"Max traversal depth (1-{IMPACT_MAX_DEPTH}, default 5)",
                    },
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
        tools.append(
            {
                "name": "dispatch_subagent",
                "description": "Dispatch an ad-hoc subagent for a focused investigation. The subagent gets 25 tool calls and all tools by default. Use for independent investigation tracks.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "role": {
                            "type": "string",
                            "description": "Descriptive role name (e.g. 'kafka_consumer_analyst')",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "Focused task description for the subagent",
                        },
                        "tools": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": sorted(VALID_TOOL_NAMES),
                            },
                            "description": "Optional subset of tool names. If omitted, all tools are provided.",
                        },
                    },
                    "required": ["role", "prompt"],
                },
            }
        )

    return tools


# -- Tool handlers --


async def handle_tool_call(ctx: ToolContext, tool_name: str, tool_input: dict) -> str:
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
        return json.dumps(
            {"content": numbered, "total_lines": total_lines, "truncated": False}
        )

    truncated = total_lines > 500
    if truncated:
        lines = lines[:500]

    numbered = "\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines))
    content = numbered
    if truncated:
        content += f"\n\n[File truncated at 500 lines. Total: {total_lines} lines. Use line_start/line_end to read specific sections.]"

    return json.dumps(
        {"content": content, "total_lines": total_lines, "truncated": truncated}
    )


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
            cmd,
            cwd=ctx.repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        raw_lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.TimeoutExpired:
        return json.dumps(
            {"matches": [], "total_matches": 0, "error": "Search timed out"}
        )

    matches = []
    for line in raw_lines[:max_results]:
        # Format: ./path/to/file:linenum:content
        parts = line.split(":", 2)
        if len(parts) >= 3:
            file_path = parts[0].lstrip("./")
            try:
                line_num = int(parts[1])
            except ValueError:
                continue
            content = parts[2]
            matches.append(
                {"file": file_path, "line": line_num, "content": content.strip()}
            )

    return json.dumps({"matches": matches, "total_matches": len(raw_lines)})


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
            entries.append(
                {
                    "name": str(item.relative_to(target)),
                    "type": "dir" if item.is_dir() else "file",
                }
            )
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
    raw_depth = inp.get("depth", IMPACT_MAX_DEPTH)
    # Clamp first (tool callers may pass anything), then validate.
    try:
        clamped = max(1, min(int(raw_depth), IMPACT_MAX_DEPTH))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"depth must be an int, got {raw_depth!r}") from exc
    depth = _validate_depth(clamped, IMPACT_MAX_DEPTH, name="depth")
    hierarchy = CONTAINS_HIERARCHY_MAX_DEPTH

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
            f"MATCH (start {{fqn: $fqn, app_name: $appName}})"
            f"-[:CONTAINS*0..{hierarchy}]->(seed) "
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

    records = await ctx.graph_store.query(cypher, {"fqn": fqn, "appName": ctx.app_name})

    by_type = dict(Counter(r["type"] for r in records))

    return json.dumps(
        {
            "affected": records,
            "total": len(records),
            "by_type": by_type,
        }
    )


async def _find_path(ctx: ToolContext, inp: dict) -> str:
    source = inp["source_fqn"]
    target = inp["target_fqn"]

    max_depth = _validate_depth(
        inp.get("max_depth", FIND_PATH_MAX_DEPTH),
        FIND_PATH_MAX_DEPTH,
        name="max_depth",
    )
    cypher = (
        "MATCH path = shortestPath("
        "(a {fqn: $source, app_name: $appName})"
        "-[:CALLS|IMPLEMENTS|DEPENDS_ON|INJECTS|INHERITS|READS|WRITES"
        f"|PRODUCES|CONSUMES*..{max_depth}]-"
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
