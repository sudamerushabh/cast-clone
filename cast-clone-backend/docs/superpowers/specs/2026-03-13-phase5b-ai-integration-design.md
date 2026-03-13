# Phase 5b — AI Integration (MCP Server + Built-in Chat) Design Spec

## Overview

Phase 5b completes the AI Integration phase by delivering two capabilities:

1. **Built-in Agentic Chat** — A chat panel in the CodeLens UI where users ask natural language questions about their architecture. Backed by a Claude Sonnet agent with tools that query the Neo4j graph. The agent streams thinking blocks, tool calls, and responses in real time. Context-aware: the agent knows what page/node the user is viewing (togglable).

2. **MCP Server** — Exposes the same architecture tools to external AI agents (Claude Code, Cursor, VS Code Copilot) via the MCP protocol. Protected by API key authentication.

Both share a **unified tool layer** — the same async Python functions back both the chat agent and the MCP server. No query duplication.

**Sequencing:** Chat first (M1-M3), then MCP (M4), then polish (M5). M2/M3/M4 can run in parallel after M1.

**Depends on:** Phases 1-4a (graph in Neo4j, impact queries, auth), Phase 5a (PR analysis — already complete).

---

## Prerequisites

### What Phase 5a Already Delivered

Phase 5a built the first AI feature (PR impact analysis) and established:

- **AI agent infrastructure**: supervisor/subagent pattern, Anthropic SDK integration, tool dispatch (`app/pr_analysis/ai/`)
- **Graph query tools**: `query_graph_node`, `get_node_impact`, `find_path` in `app/pr_analysis/ai/tools.py`
- **Neo4j GraphStore**: async query interface in `app/services/neo4j.py`
- **Graph API endpoints**: node/edge listing, search, neighbors in `app/api/graph.py`
- **ORM models**: `PrAnalysis`, `RepositoryGitConfig` in `app/models/db.py`
- **Config pattern**: model selection, token budgets in `app/config.py`

### What Phase 5b Builds On

- The shared tool layer (M1) extracts and consolidates graph query tools from `app/pr_analysis/ai/tools.py` into a shared location (`app/ai/tools.py`) so both chat and MCP can use them.
- The existing `GraphStore` abstraction requires no changes.
- The existing graph API endpoints (`app/api/graph.py`) are not replaced — the chat tools call Neo4j directly (same as PR analysis tools), not the REST API.

---

## Milestone Breakdown

| Milestone | Delivers | Depends On |
|-----------|----------|------------|
| **5b-M1** | Shared tool layer + agentic chat backend (SSE streaming) | None |
| **5b-M2** | On-demand AI summaries with PostgreSQL cache | M1 (shared tools) |
| **5b-M3** | Chat frontend (drawer, thinking blocks, tool cards, context toggle) | M1 (SSE endpoint) |
| **5b-M4** | MCP server + API key auth + Docker | M1 (shared tools) |
| **5b-M5** | API key management UI + cost tracking + setup docs | M4 (API keys), M1-M2 (usage logging) |

M2, M3, and M4 can run in parallel after M1 completes.

---

## 5b-M1: Shared Tool Layer + Agentic Chat Backend

### Shared Tool Layer

**Location:** `app/ai/tools.py`

Extract and consolidate graph query tools that already exist in `app/pr_analysis/ai/tools.py`. Add new tools from the Phase 5 spec. Each tool is a plain async function wrapping a Cypher query.

**Tools:**

| Tool | Description | Source |
|------|-------------|--------|
| `list_applications` | List all analyzed applications | New |
| `application_stats` | Size, complexity, tech metrics for an app | New |
| `get_architecture` | Architecture at module or class level (nodes + edges) | New |
| `search_objects` | Full-text search for code objects by name, optional type filter | New |
| `object_details` | Detailed info about a node: callers, callees, metrics | Extracted from `query_graph_node` |
| `impact_analysis` | Blast radius of changing a node (upstream/downstream) | Extracted from `get_node_impact` |
| `find_path` | Shortest path between two nodes | Extracted from `find_path` |
| `list_transactions` | All end-to-end transaction flows in an app | New |
| `transaction_graph` | Full call graph for a specific transaction | New |
| `get_source_code` | Source code for a code object (from Neo4j path/line metadata) | New |
| `get_or_generate_summary` | Get cached AI summary or generate one (M2 integration) | New (added in M2) |

**Tool context:**

```python
@dataclass
class ChatToolContext:
    """Shared context passed to all tool functions."""
    graph_store: GraphStore       # Neo4j query interface
    app_name: str                 # Application name in Neo4j
    project_id: str               # For PostgreSQL lookups
```

**Tool definitions for Claude API:** Separate file `app/ai/tool_definitions.py` with the `tools` array in Anthropic API format (name, description, input_schema). Same definitions will be reused by MCP in M4.

### Agentic Chat Backend

**Location:** `app/ai/chat.py`

A Claude Sonnet agent with extended thinking that iterates tool calls until it has enough context to answer the user's question.

**Agent configuration:**
- Model: `claude-sonnet-4-20250514` (configurable via `app/config.py`)
- Extended thinking: enabled
- Tool budget: max 15 tool calls per conversation turn, 2-minute timeout
- Max tokens: 4096 for response

**Page context injection:**

The request includes an optional `page_context` object:

```python
@dataclass
class PageContext:
    page: str                          # "graph_explorer", "pr_detail", "dashboard", etc.
    project_id: str | None = None
    selected_node_fqn: str | None = None
    view: str | None = None            # "architecture", "dependency", "transaction"
    level: str | None = None           # "module", "class", "method"
    pr_analysis_id: str | None = None  # If on PR detail page
```

When `include_page_context` is `true` (default), the system prompt includes:

```
The user is currently viewing the {view} view at {level} level in the graph explorer.
They have selected the node: {selected_node_fqn}
Use this context to make your answers more relevant to what they're looking at.
```

When `false`, the system prompt only includes project metadata (name, frameworks, languages). Same tools, same agent — just no page awareness.

**System prompt structure:**

```
You are an expert software architect analyzing the application "{app_name}".
The application is built with {frameworks} in {languages}.
You have access to the application's complete architecture graph via the provided tools.

{page_context_block}  ← only when include_page_context is true

When answering questions:
- Use tools to look up real data. Don't guess about the architecture.
- Be specific — reference actual class names, method names, and file paths.
- Include FQNs when mentioning code objects so the UI can link to them.
- If a question is ambiguous, search first to find relevant nodes, then get details.
```

**Conversation history:**
- Client sends conversation history with each request (last 10 turns)
- Server does not persist conversations — stateless
- History format: standard Anthropic messages array (role + content)

**SSE streaming:**

The endpoint streams events as they happen:

| Event Type | Payload | Frontend Use |
|------------|---------|--------------|
| `thinking` | `{content: "..."}` | Collapsible thinking block |
| `tool_use` | `{id, name, input}` | "Querying impact for OrderService..." card |
| `tool_result` | `{tool_use_id, content_summary}` | Expandable result in tool card |
| `text` | `{content: "..."}` | Streaming markdown response |
| `done` | `{input_tokens, output_tokens}` | Token usage display |
| `error` | `{message}` | Error display |

**Implementation pattern:**

```python
async def chat_stream(
    project_id: str,
    message: str,
    history: list[dict],
    page_context: PageContext | None,
    include_page_context: bool,
) -> AsyncGenerator[str, None]:
    """Agentic chat with SSE streaming."""
    # Build system prompt (with or without page context)
    # Create messages array from history + new message
    # Loop:
    #   Call Claude API with streaming
    #   Yield thinking/text events as they stream
    #   If tool_use: yield tool_use event, execute tool, yield tool_result, continue loop
    #   If end_turn: yield done event, break
```

### API Endpoint

**Location:** `app/api/chat.py`

```
POST /api/v1/projects/{project_id}/chat
Content-Type: application/json
Accept: text/event-stream

Request body:
{
    "message": "What would break if I changed OrderService?",
    "history": [...],                    // Last 10 turns
    "page_context": {                    // Optional
        "page": "graph_explorer",
        "selected_node_fqn": "com.app.OrderService",
        "view": "architecture",
        "level": "class"
    },
    "include_page_context": true         // Toggle, default true
}

Response: SSE stream
event: thinking
data: {"content": "Let me look up OrderService..."}

event: tool_use
data: {"id": "tu_1", "name": "object_details", "input": {"node_fqn": "com.app.OrderService"}}

event: tool_result
data: {"tool_use_id": "tu_1", "content_summary": "Found OrderService with 12 callers, 5 callees"}

event: text
data: {"content": "Changing **OrderService** would affect..."}

event: done
data: {"input_tokens": 3200, "output_tokens": 850}
```

### New Files (M1)

```
app/ai/
├── __init__.py
├── tools.py               # Shared tool functions (async, Cypher-backed)
├── tool_definitions.py    # Claude API tool schemas
└── chat.py                # Agentic chat service (agent loop + SSE)

app/api/
└── chat.py                # FastAPI SSE endpoint

app/schemas/
└── chat.py                # ChatRequest, PageContext, ChatEvent models
```

### Config Additions (M1)

```python
# app/config.py
chat_model: str = "claude-sonnet-4-20250514"
chat_max_tool_calls: int = 15
chat_timeout_seconds: int = 120
chat_max_response_tokens: int = 4096
```

### DB Changes (M1)

None. Conversation history is client-managed.

---

## 5b-M2: On-Demand Summaries

### Summary Generation

**Location:** `app/ai/summaries.py`

A single Claude Sonnet call (no tool-use loop) that takes structured data about a node and produces a natural-language explanation.

**Input assembly:**
1. Fetch node details via shared tool: `object_details(fqn)` → callers, callees, metrics
2. Fetch source code via shared tool: `get_source_code(fqn)` → file content at line range
3. Truncate: cap source code at 200 lines, limit to top 20 callers/callees
4. Total context target: ~2K tokens

**System prompt:**

```
You are an expert software architect. Explain what this code object does,
its role in the architecture, and its key dependencies.

Be concise (2-3 paragraphs). Reference specific class/method names.
Focus on: what it does, who calls it, what it calls, and why it matters.
```

**Single API call:**

```python
response = await client.messages.create(
    model=settings.chat_model,
    max_tokens=512,
    system=SUMMARY_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": json.dumps(node_context)}],
)
```

### Caching

**PostgreSQL table:**

```sql
CREATE TABLE ai_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    node_fqn VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL,
    model VARCHAR(100) NOT NULL,
    graph_hash VARCHAR(64),
    tokens_used INTEGER,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(project_id, node_fqn)
);
```

**`graph_hash`:** SHA-256 of `f"{fan_in}:{fan_out}:{sorted_neighbor_fqns}"`. On request, compute current hash from Neo4j. If it matches the cached hash, return cached summary. If not, regenerate.

**Staleness on re-analysis:** When a new `AnalysisRun` completes for a project, all summaries for that project become potentially stale. The lazy hash-check approach handles this — no need for bulk invalidation.

### Chat Agent Integration

The `get_or_generate_summary` tool is added to the shared tool layer so the chat agent can use it:

```python
async def get_or_generate_summary(ctx: ChatToolContext, node_fqn: str) -> dict:
    """Get AI summary for a node. Returns cached if available, generates if not."""
    # Check cache → if valid, return
    # If miss or stale → generate, cache, return
```

When a user asks "explain OrderService" in chat, the agent can call this tool instead of reasoning from raw data.

### API Endpoint

```
GET /api/v1/projects/{project_id}/summary/{node_fqn}
    → {"fqn": "...", "summary": "...", "cached": true, "model": "..."}
```

Used by the "Explain this" button in the node properties panel (no chat needed).

### New Files (M2)

```
app/ai/
└── summaries.py           # Summary generation + cache logic

app/api/
└── summaries.py           # REST endpoint (or added to chat.py)

app/schemas/
└── summaries.py           # SummaryResponse model
```

### ORM Changes (M2)

- New `AiSummary` model in `app/models/db.py`
- Alembic migration for `ai_summaries` table

---

## 5b-M3: Chat Frontend

### Chat Panel

A slide-out drawer from the right side, triggered by a floating button (bottom-right) or keyboard shortcut. Persists across page navigation within a project (React state in project layout component).

### Chat Header

- Project name
- **"Context-aware" toggle switch** with tooltip: "When on, the assistant knows what page and node you're viewing"
- Current page context shown as a subtle chip when toggle is on (e.g., "Viewing: OrderService")
- Clear conversation button

### Message Rendering

| Message Type | Visual Treatment |
|--------------|-----------------|
| **User message** | Plain text bubble, right-aligned |
| **Thinking block** | Muted/subtle section with "Thinking..." spinner while streaming. Collapsible after completion — click to expand full reasoning. |
| **Tool call** | Inline card: tool icon + name + key input summary (e.g., "Querying impact for `OrderService`..."). Spinner while executing → checkmark on completion. Expandable to show summarized result. |
| **Agent response** | Left-aligned bubble with streaming markdown → HTML. FQNs detected by regex pattern (e.g., `com.app.something.SomethingElse`) and rendered as clickable links that navigate to the node in the graph view. |
| **"Show in Graph" button** | Appears when the response references impact analysis or path results. Clicking navigates to graph explorer with those nodes highlighted. |

### SSE Consumption

- Use `fetch` with `ReadableStream` to consume SSE events from the M1 endpoint
- Map event types (`thinking`, `tool_use`, `tool_result`, `text`, `done`) to React state updates
- Conversation history managed in React state, sent back with each request (last 10 turns)
- History trimming: when conversation exceeds 10 turns, drop oldest turns (keep system context fresh)

### Page Context Collection

The chat hook reads the current route and relevant state to build `PageContext`:

```typescript
function usePageContext(): PageContext {
    const pathname = usePathname();
    const params = useParams();
    // Parse current page from route
    // Extract selected node FQN from graph state if on graph explorer
    // Extract PR analysis ID if on PR detail page
    return { page, project_id, selected_node_fqn, view, level, pr_analysis_id };
}
```

### New Files (M3)

```
cast-clone-frontend/
├── components/chat/
│   ├── ChatDrawer.tsx         # Main drawer container (open/close, layout)
│   ├── ChatMessage.tsx        # Message bubble renderer (dispatches to sub-components)
│   ├── ThinkingBlock.tsx      # Collapsible thinking display
│   ├── ToolCallCard.tsx       # Tool call visualization (spinner → result)
│   ├── ChatInput.tsx          # Input box with send button
│   └── PageContextChip.tsx    # Current context display chip
├── hooks/
│   ├── useChat.ts             # SSE streaming + conversation state
│   └── usePageContext.ts      # Page context extraction from route/state
└── lib/
    └── chat-types.ts          # TypeScript types for chat events, PageContext
```

---

## 5b-M4: MCP Server + Auth

### MCP Server

**Location:** `app/mcp/server.py`

FastMCP from the official MCP Python SDK. Each tool is a decorated function that calls the shared tool layer from M1. ~200 lines total.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("codelens")

@mcp.tool()
async def list_applications() -> list[dict]:
    """List all analyzed applications in CodeLens."""
    return await tools.list_applications(ctx)

@mcp.tool()
async def impact_analysis(node_fqn: str, depth: int = 5) -> dict:
    """Compute the blast radius of changing a specific code object."""
    return await tools.impact_analysis(ctx, node_fqn, depth)

# ... same pattern for all tools
```

**Transport:** SSE on port 8090.

**Tools exposed:** Same set as the chat agent — `list_applications`, `application_stats`, `get_architecture`, `search_objects`, `object_details`, `impact_analysis`, `find_path`, `list_transactions`, `transaction_graph`, `get_source_code`, `add_annotation`.

### API Key Authentication

**Database table:**

```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    user_id UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT now(),
    last_used_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true
);
```

**Auth middleware** (`app/mcp/auth.py`):
- Checks `Authorization: Bearer <key>` header on every MCP request
- Compares bcrypt hash of provided key against stored `key_hash`
- Updates `last_used_at` on successful auth
- Returns 401 if invalid/inactive

**Key management endpoints:**

```
POST /api/v1/api-keys              → Create key (returns raw key once, stores hash)
GET  /api/v1/api-keys              → List keys (name, created, last used — no raw key)
DELETE /api/v1/api-keys/{id}       → Revoke key (set is_active = false)
```

### Docker Compose

New service added to `docker-compose.yml`:

```yaml
mcp:
  build:
    context: ./cast-clone-backend
    dockerfile: Dockerfile.mcp
  ports:
    - "${MCP_PORT:-8090}:8090"
  environment:
    - NEO4J_URI=bolt://neo4j:7687
    - NEO4J_USER=neo4j
    - NEO4J_PASSWORD=${NEO4J_PASSWORD}
    - DATABASE_URL=postgresql+asyncpg://...
    - MCP_API_KEY=${MCP_API_KEY}
  command: ["python", "-m", "app.mcp.server", "--transport", "sse", "--port", "8090"]
  depends_on:
    - neo4j
    - postgres
```

### New Files (M4)

```
app/mcp/
├── __init__.py
├── server.py              # FastMCP server with tool definitions
└── auth.py                # API key verification middleware

app/api/
└── api_keys.py            # Key management REST endpoints

app/schemas/
└── api_keys.py            # Request/response models
```

### Dependencies (M4)

Add to `pyproject.toml`:

```toml
"mcp[cli]>=1.25,<2"
```

### ORM Changes (M4)

- New `ApiKey` model in `app/models/db.py`
- Alembic migration for `api_keys` table

---

## 5b-M5: API Key Management UI + Cost Tracking + Docs

### API Key Management UI

New section in Project Settings → "API Keys" tab:

- Table: key name, created date, last used, status (active/revoked)
- "Create Key" button → modal showing raw key once with copy button + warning "This key won't be shown again"
- Revoke button per key (with confirmation dialog)
- Inline setup instructions: copy-pasteable snippets for Claude Code, VS Code, Cursor

### Cost Tracking

**Database table:**

```sql
CREATE TABLE ai_usage_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    source VARCHAR(20) NOT NULL,           -- 'chat', 'summary', 'mcp', 'pr_analysis'
    model VARCHAR(100) NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    estimated_cost_usd NUMERIC(10, 6),
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_usage_project_date ON ai_usage_log(project_id, created_at DESC);
```

**Logging integration:**
- Chat backend (M1): log every agent turn to `ai_usage_log`
- Summary generator (M2): log every generation call
- MCP server (M4): log every tool call that involves an LLM (currently none, but future-proof)
- PR analysis (Phase 5a): retrofit logging into existing supervisor/subagent pipeline

**Admin dashboard:**
- Total tokens this month, estimated cost
- Breakdown by source (chat vs summaries vs PR analysis)
- Per-project usage over time (bar chart, last 30 days)

### Configuration Docs

Static content in the UI (or a dedicated docs page) showing setup for:

- **Claude Code:** `claude mcp add codelens -- http://localhost:8090/mcp`
- **VS Code:** `mcp.json` snippet
- **Cursor:** configuration steps
- API key creation walkthrough with screenshots

### New Files (M5)

```
cast-clone-frontend/
├── app/settings/api-keys/
│   └── page.tsx                    # API key management page
├── components/settings/
│   ├── ApiKeyTable.tsx             # Key list table
│   ├── CreateKeyModal.tsx          # Create key modal with copy
│   └── McpSetupGuide.tsx           # Setup instructions component
└── components/admin/
    └── AiUsageDashboard.tsx        # Cost tracking dashboard

cast-clone-backend/
├── app/api/
│   └── ai_usage.py                # Usage stats endpoint
└── app/schemas/
    └── ai_usage.py                # Response models
```

### ORM Changes (M5)

- New `AiUsageLog` model in `app/models/db.py`
- Alembic migration for `ai_usage_log` table

---

## Dependencies (pyproject.toml additions)

```toml
# Phase 5b
"anthropic>=0.40",              # Already present from Phase 5a
"mcp[cli]>=1.25,<2",            # MCP server (M4)
```

### Environment Variables

```bash
# Already present from Phase 5a
ANTHROPIC_API_KEY=sk-ant-...

# New for M4
MCP_API_KEY=...                  # Default API key for MCP (optional, can create via UI)
```

---

## What's Explicitly NOT in Phase 5b

| Feature | Why Not |
|---------|---------|
| Conversation persistence (server-side) | Client-managed history is sufficient. Server-side adds complexity for minimal gain. |
| Multi-model support (OpenAI, Gemini) | Phase 6. Start with Claude, add others if customers need. |
| Batch summary generation | On-demand + cache is sufficient and cheaper. |
| Custom query router / context assembler | Claude's tool use IS the router. |
| MCP resources and prompts | Tools are the priority. Resources/prompts add later. |
| Chat in PR detail page (auto-loaded with PR context) | Nice-to-have. The page context toggle covers this use case. |
| Rate limiting per user | Phase 6. Token budget is sufficient for now. |

---

## Success Criteria

Phase 5b is complete when:

1. A user can open the chat panel, ask "what would break if I changed OrderService?", and get a graph-backed answer with visible thinking + tool calls
2. The page context toggle works — agent references the current view when on, generic when off
3. "Explain this" button on any node generates and caches an AI summary
4. Claude Code can connect to the MCP server and successfully query the architecture
5. API keys can be created, listed, and revoked from the admin UI
6. Cost tracking shows token usage breakdown by source
7. Chat response latency is under 10 seconds for typical questions (including tool calls)
8. MCP server works with Claude Code, Cursor, and VS Code Copilot
