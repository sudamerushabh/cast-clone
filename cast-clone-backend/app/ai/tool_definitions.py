# app/ai/tool_definitions.py
"""Claude API tool schemas for the shared AI tool layer.

These definitions are used by both the chat backend and the MCP server.
They match the Anthropic Messages API format.
"""

from __future__ import annotations


def get_chat_tool_definitions() -> list[dict]:
    """Return tool definitions in Anthropic Messages API format."""
    return [
        {
            "name": "list_applications",
            "description": (
                "List all analyzed applications in "
                "CodeLens with their languages and size."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "application_stats",
            "description": (
                "Get size, complexity, and technology metrics "
                "for an application. Omit app_name to use "
                "the current project."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": (
                            "Application name (optional — defaults to current project)"
                        ),
                    },
                },
            },
        },
        {
            "name": "get_architecture",
            "description": (
                "Get application architecture showing "
                "modules/classes and their dependencies."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["module", "class"],
                        "description": "Level of detail (default: module)",
                    },
                },
            },
        },
        {
            "name": "search_objects",
            "description": (
                "Search for code objects (classes, functions, "
                "tables, endpoints) by name."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (matches name or FQN)",
                    },
                    "type_filter": {
                        "type": "string",
                        "description": (
                            "Optional filter: Class, Function, "
                            "Interface, Table, APIEndpoint"
                        ),
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "object_details",
            "description": (
                "Get detailed info about a specific code object "
                "including its callers, callees, and metrics."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_fqn": {
                        "type": "string",
                        "description": "Fully qualified name of the node",
                    },
                },
                "required": ["node_fqn"],
            },
        },
        {
            "name": "impact_analysis",
            "description": (
                "Compute the blast radius of changing a "
                "specific code object. Returns all affected "
                "nodes grouped by type and depth."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_fqn": {
                        "type": "string",
                        "description": "Fully qualified name of the node to analyze",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Max traversal depth (default 5, max 10)",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["downstream", "upstream", "both"],
                        "description": "Direction of impact (default: both)",
                    },
                },
                "required": ["node_fqn"],
            },
        },
        {
            "name": "find_path",
            "description": (
                "Find the shortest connection path between "
                "two code objects in the architecture graph."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "from_fqn": {
                        "type": "string",
                        "description": "FQN of the source node",
                    },
                    "to_fqn": {
                        "type": "string",
                        "description": "FQN of the target node",
                    },
                },
                "required": ["from_fqn", "to_fqn"],
            },
        },
        {
            "name": "list_transactions",
            "description": (
                "List all end-to-end transaction flows "
                "(API requests) in the application."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "transaction_graph",
            "description": "Get the full call graph for a specific transaction flow.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "transaction_name": {
                        "type": "string",
                        "description": "Name of the transaction",
                    },
                },
                "required": ["transaction_name"],
            },
        },
        {
            "name": "get_source_code",
            "description": (
                "Get the source code for a specific code "
                "object. Returns line-numbered source."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_fqn": {
                        "type": "string",
                        "description": "Fully qualified name of the node",
                    },
                },
                "required": ["node_fqn"],
            },
        },
        {
            "name": "get_or_generate_summary",
            "description": (
                "Get an AI-generated explanation of a code object. "
                "Returns cached summary if available, generates new "
                "one if not. Use when user asks to explain or "
                "summarize a class, method, or module."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_fqn": {
                        "type": "string",
                        "description": (
                            "Fully qualified name of the node to summarize"
                        ),
                    },
                },
                "required": ["node_fqn"],
            },
        },
    ]
