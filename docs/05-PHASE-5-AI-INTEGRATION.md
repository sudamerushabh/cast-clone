# Phase 5 — AI Integration (Revised)

**Timeline:** Months 9–12
**Goal:** Let AI agents (and users via chat) query the architecture graph
**Last Updated:** Simplified — MCP server is a thin wrapper, chat uses tool use, no custom RAG

---

## Overview

Phase 5 adds two things:

1. **MCP Server** — expose our graph data to external AI coding agents (Claude Code, Cursor, Copilot)
2. **Built-in Chat** — let users ask natural language questions about their architecture inside the CodeLens UI

Both are surprisingly simple because they're just protocol adapters over the API and Cypher queries we already built in Phases 1-4.

---

## 1. MCP Server

### What It Does

The MCP server exposes CodeLens architecture data to any MCP-compatible AI tool. A developer using Claude Code can ask "what would break if I refactored UserService?" and get a precise, graph-backed answer.

### Implementation: FastMCP

Use the official MCP Python SDK's FastMCP framework. Each MCP tool is a decorated Python function that wraps our existing Neo4j queries.

**Dependencies:**
```bash
pip install "mcp[cli]>=1.25,<2"
```

**The entire MCP server (~200 lines):**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("codelens")

# ─── Portfolio Tools ────────────────────────────────────────

@mcp.tool()
async def list_applications() -> list[dict]:
    """List all analyzed applications in CodeLens."""
    return await neo4j.query(
        "MATCH (a:Application) RETURN a.name, a.languages, a.frameworks, a.total_loc"
    )

@mcp.tool()
async def application_stats(app_name: str) -> dict:
    """Get size, complexity, and technology metrics for an application."""
    return await neo4j.query(
        """MATCH (app:Application {name: $name})
           OPTIONAL MATCH (app)-[:CONTAINS]->(m:Module)
           OPTIONAL MATCH (m)-[:CONTAINS]->(c:Class)
           RETURN app.name, count(DISTINCT m) AS modules,
                  count(DISTINCT c) AS classes, sum(c.loc) AS totalLoc""",
        name=app_name
    )

# ─── Architecture Tools ────────────────────────────────────

@mcp.tool()
async def get_architecture(app_name: str, level: str = "module") -> dict:
    """Get application architecture at module or class level."""
    if level == "module":
        nodes = await neo4j.query(
            "MATCH (app:Application {name: $name})-[:CONTAINS]->(m:Module) RETURN m",
            name=app_name
        )
        edges = await neo4j.query(AGGREGATED_MODULE_EDGES_QUERY, name=app_name)
    else:
        nodes = await neo4j.query(
            "MATCH (app:Application {name: $name})-[:CONTAINS]->(:Module)-[:CONTAINS]->(c:Class) RETURN c",
            name=app_name
        )
        edges = await neo4j.query(CLASS_EDGES_QUERY, name=app_name)
    return {"nodes": nodes, "edges": edges}

@mcp.tool()
async def search_objects(app_name: str, query: str, type: str = None) -> list[dict]:
    """Search for code objects by name. Optionally filter by type (class, function, table)."""
    return await neo4j.query(FULLTEXT_SEARCH_QUERY, query=query, type=type)

@mcp.tool()
async def object_details(node_fqn: str) -> dict:
    """Get detailed info about a specific code object including callers, callees, and metrics."""
    node = await neo4j.query("MATCH (n {fqn: $fqn}) RETURN n", fqn=node_fqn)
    callers = await neo4j.query(
        "MATCH (caller)-[:CALLS]->(n {fqn: $fqn}) RETURN caller.fqn, caller.name LIMIT 20",
        fqn=node_fqn
    )
    callees = await neo4j.query(
        "MATCH (n {fqn: $fqn})-[:CALLS]->(callee) RETURN callee.fqn, callee.name LIMIT 20",
        fqn=node_fqn
    )
    return {"node": node, "callers": callers, "callees": callees}

# ─── Analysis Tools ─────────────────────────────────────────

@mcp.tool()
async def impact_analysis(node_fqn: str, depth: int = 5, direction: str = "both") -> dict:
    """Compute the blast radius of changing a specific code object."""
    return await neo4j.query(IMPACT_QUERY, fqn=node_fqn, depth=depth, direction=direction)

@mcp.tool()
async def find_path(from_fqn: str, to_fqn: str) -> dict:
    """Find the shortest connection path between two code objects."""
    return await neo4j.query(SHORTEST_PATH_QUERY, from_fqn=from_fqn, to_fqn=to_fqn)

@mcp.tool()
async def list_transactions(app_name: str) -> list[dict]:
    """List all end-to-end transaction flows in an application."""
    return await neo4j.query(
        "MATCH (t:Transaction) RETURN t.name, t.http_method, t.url_path, t.node_count, t.depth"
    )

@mcp.tool()
async def transaction_graph(transaction_name: str) -> dict:
    """Get the full call graph for a specific transaction."""
    return await neo4j.query(TRANSACTION_GRAPH_QUERY, name=transaction_name)

@mcp.tool()
async def get_source_code(node_fqn: str) -> dict:
    """Get the source code for a specific code object."""
    node = await neo4j.query("MATCH (n {fqn: $fqn}) RETURN n.path, n.line, n.end_line", fqn=node_fqn)
    if node:
        content = read_file(node["path"], node["line"], node["end_line"])
        return {"fqn": node_fqn, "file": node["path"], "line": node["line"], "code": content}
    return {"error": "Node not found"}

# ─── Annotation Tools ───────────────────────────────────────

@mcp.tool()
async def add_annotation(node_fqn: str, content: str) -> dict:
    """Add a note to a code object in CodeLens."""
    return await db.execute(
        "INSERT INTO annotations (project_id, node_fqn, content, author_id) VALUES ...",
        node_fqn=node_fqn, content=content
    )
```

That's it. Each tool is 5-10 lines wrapping an existing query. The MCP SDK handles protocol negotiation, transport, and tool discovery automatically.

### Deployment

Add to Docker Compose as a separate container:

```yaml
mcp:
  image: codelens/mcp-server:${VERSION:-latest}
  ports:
    - "${MCP_PORT:-8090}:8090"
  environment:
    - NEO4J_URI=bolt://neo4j:7687
    - NEO4J_USER=neo4j
    - NEO4J_PASSWORD=${NEO4J_PASSWORD}
    - CODELENS_API_URL=http://api:8000
    - MCP_API_KEY=${MCP_API_KEY}   # simple API key auth for MCP
  command: ["python", "-m", "mcp_server", "--transport", "sse", "--port", "8090"]
```

### Client Configuration

**Claude Code:**
```bash
claude mcp add codelens -- http://localhost:8090/mcp
```

**VS Code (mcp.json):**
```json
{
  "mcpServers": {
    "codelens": {
      "type": "url",
      "url": "http://localhost:8090/mcp"
    }
  }
}
```

**Example agent queries enabled:**
- "Show me all applications in CodeLens"
- "What's the architecture of the backend app?"
- "What would break if I changed UserService.createUser?"
- "Find the path from PaymentController to the orders table"
- "List all transactions in the order module"

### MCP Authentication

Simple API key auth. The MCP server checks for an `Authorization: Bearer <api_key>` header. API keys are created in the CodeLens admin UI and stored in PostgreSQL.

```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash VARCHAR(255) NOT NULL,   -- bcrypt hash of the key
    name VARCHAR(100) NOT NULL,        -- "Claude Code - dev machine"
    user_id UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT now(),
    last_used_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true
);
```

---

## 2. Built-in Chat (AI Assistant)

### Architecture

The chat UI sends the user's question to our backend, which calls the Claude API with tool use. Claude decides which CodeLens tools to call, our backend executes them, and returns the final answer.

```
User types question in chat UI
        ↓
Frontend POST /api/v1/ai/{project}/chat
        ↓
Backend calls Claude API with:
  - System prompt (you're analyzing this application)
  - User's message
  - Tools (same functions as MCP server)
        ↓
Claude responds with tool_use (e.g., "call impact_analysis")
        ↓
Backend executes the tool (runs Neo4j query)
        ↓
Backend sends tool_result back to Claude
        ↓
Claude generates final natural language answer
        ↓
Backend returns answer to frontend
```

**Key insight: Claude IS the query router.** We don't need a custom "Query Router" or "Context Assembler." We give Claude the tools and let it decide what to call.

### Implementation

```python
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Same tool definitions used for MCP, but formatted for Claude API
CLAUDE_TOOLS = [
    {
        "name": "search_objects",
        "description": "Search for code objects (classes, functions, tables, endpoints) by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "type": {"type": "string", "description": "Optional filter: class, function, table, endpoint"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "impact_analysis",
        "description": "Compute the blast radius of changing a code object. Returns all affected nodes grouped by depth.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_fqn": {"type": "string", "description": "Fully qualified name of the node"},
                "depth": {"type": "integer", "description": "Max traversal depth (default 5)"}
            },
            "required": ["node_fqn"]
        }
    },
    # ... same pattern for: object_details, find_path, get_architecture,
    #     list_transactions, transaction_graph, get_source_code
]

SYSTEM_PROMPT = """You are an expert software architect analyzing the application "{app_name}".
The application is built with {frameworks} in {languages}.
You have access to the application's complete architecture graph via the provided tools.

When answering questions:
- Be specific — reference actual class names, method names, and file paths.
- Include FQNs when mentioning code objects so the UI can link to them.
- Use tools to look up real data. Don't guess about the architecture.
- If a question is ambiguous, search first to find relevant nodes, then get details.
"""

async def chat(project_id: str, message: str, history: list[dict]) -> dict:
    project = await get_project(project_id)
    
    messages = history + [{"role": "user", "content": message}]
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT.format(
            app_name=project.name,
            frameworks=", ".join(project.frameworks),
            languages=", ".join(project.languages),
        ),
        tools=CLAUDE_TOOLS,
        messages=messages,
    )
    
    # Handle tool use loop
    while response.stop_reason == "tool_use":
        tool_calls = [b for b in response.content if b.type == "tool_use"]
        tool_results = []
        
        for tool_call in tool_calls:
            result = await execute_tool(tool_call.name, tool_call.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": json.dumps(result),
            })
        
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT.format(...),
            tools=CLAUDE_TOOLS,
            messages=messages,
        )
    
    # Extract final text response
    answer = "".join(b.text for b in response.content if b.type == "text")
    
    return {"answer": answer, "messages": messages}


async def execute_tool(name: str, inputs: dict) -> dict:
    """Execute a tool call — same functions backing the MCP server."""
    tool_map = {
        "search_objects": search_objects,
        "impact_analysis": impact_analysis,
        "object_details": object_details,
        "find_path": find_path,
        "get_architecture": get_architecture,
        "list_transactions": list_transactions,
        "transaction_graph": transaction_graph,
        "get_source_code": get_source_code,
    }
    handler = tool_map.get(name)
    if handler:
        return await handler(**inputs)
    return {"error": f"Unknown tool: {name}"}
```

### On-Demand Summaries (Not Batch)

When a user asks "explain what UserService does," Claude will:
1. Call `object_details("com.app.UserService")` to get callers, callees, annotations
2. Call `get_source_code("com.app.UserService")` to see the code
3. Synthesize an explanation

Cache the result in PostgreSQL so next time it's instant:

```sql
CREATE TABLE ai_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    node_fqn VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL,
    model VARCHAR(100) NOT NULL,         -- "claude-sonnet-4-20250514"
    graph_hash VARCHAR(64),               -- hash of node's connections, invalidate on re-analysis
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(project_id, node_fqn)
);
```

If the graph changes (re-analysis), invalidate cached summaries by comparing `graph_hash`.

**Don't batch-generate summaries.** For a 10K-node codebase, that's thousands of API calls. Generate on-demand, cache aggressively. Most nodes will never be asked about.

### Frontend Chat UI

A simple chat panel — sidebar or bottom drawer:

```
┌─────────────────────────────────────┐
│ CodeLens AI Assistant        [×]    │
├─────────────────────────────────────┤
│                                     │
│ You: What would break if I changed  │
│      the User table?                │
│                                     │
│ AI: Changing the User table would   │
│     affect 14 nodes across 3        │
│     layers:                         │
│                                     │
│     Direct dependents (depth 1):    │
│     • UserRepository.save()         │
│     • UserRepository.findByEmail()  │
│     ...                             │
│                                     │
│     [Show in Graph]                 │
│                                     │
├─────────────────────────────────────┤
│ Ask about the architecture...   [→] │
└─────────────────────────────────────┘
```

Implementation: standard React chat component. Messages stored in React state. FQNs in responses are detected by regex (`com.app.something.SomethingElse`) and rendered as clickable links that navigate to the node in the graph.

"Show in Graph" button at the bottom of relevant responses triggers the same impact/path highlighting from Phase 3.

### Cost Control

- Use **Claude Sonnet** (not Opus) for the chat — cheaper, fast enough for tool-use queries
- Limit conversation history to last 10 turns (trim older messages)
- Truncate large tool results before sending back to Claude (e.g., limit impact results to top 50 nodes)
- Show estimated cost per query in the admin dashboard (input tokens × price + output tokens × price)
- Optional: let admins set a monthly API budget limit

---

## 3. API Endpoints (Phase 5)

```
# Chat
POST /api/v1/ai/{project}/chat
     {message: "...", conversation_id: "..."}
     → {answer: "...", node_references: ["fqn1", "fqn2"]}

# Summaries (on-demand)
GET  /api/v1/ai/{project}/summary/{node_fqn}
     → {summary: "...", cached: true/false}

# API Keys (for MCP auth)
POST /api/v1/api-keys              → Create API key (returns key once, stores hash)
GET  /api/v1/api-keys              → List API keys (name, created, last used)
DELETE /api/v1/api-keys/{id}       → Revoke key

# MCP server runs on separate port (:8090) with its own protocol
```

---

## 4. What's Explicitly Deferred

| Feature | Deferred To | Why |
|---------|------------|-----|
| Custom query router / context assembler | Never | Claude's tool use IS the router |
| Batch summary generation | Never | On-demand + cache is sufficient and cheaper |
| Architectural pattern detection | Phase 6 | Nice-to-have, not core |
| Special `[[fqn:...]]` syntax in responses | Never | Regex on FQN patterns is enough |
| "Visualize in Graph" as structured action | Later | Just include FQNs, let user click |
| MCP resources and prompts | Later | Tools are the priority; resources/prompts add later |
| Multi-model support (OpenAI, Gemini) | Phase 6 | Start with Claude, add others if customers need |

---

## 5. Shared Tool Layer

The key architectural win: **MCP tools and chat tools are the same functions.** There's one set of query functions that both the MCP server and the chat backend call. No duplication.

```
┌─────────────────────┐     ┌──────────────────────┐
│  MCP Server          │     │  Chat Backend         │
│  (FastMCP protocol)  │     │  (Claude API + tools) │
└─────────┬───────────┘     └──────────┬───────────┘
          │                             │
          └──────────┬──────────────────┘
                     │
          ┌──────────▼──────────┐
          │   Tool Functions     │
          │                      │
          │  search_objects()    │
          │  impact_analysis()   │
          │  object_details()    │
          │  find_path()         │
          │  get_architecture()  │
          │  list_transactions() │
          │  get_source_code()   │
          │  add_annotation()    │
          └──────────┬──────────┘
                     │
          ┌──────────▼──────────┐
          │  Neo4j / PostgreSQL  │
          └─────────────────────┘
```

Write the tool functions once. Expose them via MCP for external agents and via Claude tool use for the built-in chat.

---

## 6. Deliverables Checklist

### MCP Server
- [ ] FastMCP server with all tool definitions (~200 lines)
- [ ] Docker container + Compose integration
- [ ] SSE transport on port 8090
- [ ] API key authentication
- [ ] API key management UI (admin)
- [ ] Configuration docs for Claude Code, VS Code, Cursor

### Chat UI
- [ ] Claude API integration with tool use loop
- [ ] System prompt with project context
- [ ] Tool execution (shared functions with MCP)
- [ ] Chat panel component (React)
- [ ] Conversation history (in-memory, last 10 turns)
- [ ] FQN detection and clickable links in responses
- [ ] "Show in Graph" button for impact/path responses
- [ ] Streaming responses (Claude API streaming)

### Summaries
- [ ] On-demand summary generation via Claude API
- [ ] PostgreSQL cache table with graph_hash invalidation
- [ ] "Explain this" button in node properties panel

### Shared Infrastructure
- [ ] Tool functions layer (shared between MCP and chat)
- [ ] Cost tracking (tokens used per query, stored in activity log)
- [ ] Anthropic API key configuration in environment/settings

---

## 7. Success Criteria

Phase 5 is complete when:

1. An external AI agent (Claude Code) can connect to the MCP server and successfully query the architecture
2. The chat assistant correctly answers questions using real graph data (not hallucinated)
3. Claude calls the right tools for different question types (search for discovery, impact for "what breaks", path for "how are these connected")
4. On-demand summaries are generated and cached correctly
5. MCP server works with Claude Code, Cursor, and VS Code Copilot
6. Chat response latency is under 10 seconds for typical questions (including tool calls)