# CodeLens Project Setup — Design Spec

## Context

CodeLens is a software architecture intelligence platform. The frontend has a basic Next.js 16 scaffold (`cast-clone-frontend/`), but the backend directory is empty and there's no Docker infrastructure. This spec covers the foundational project setup so development can begin on the actual platform.

**Goal:** Create a development-ready environment where a developer can `docker compose up` for infrastructure, run the backend locally, and start building features immediately.

**Non-goals:** No DB schemas, no analysis engine, no business logic, no framework plugins.

## 1. Backend Project (`cast-clone-backend/`)

### Structure

```
cast-clone-backend/
├── pyproject.toml
├── .python-version          # 3.12
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app with CORS, lifespan hooks
│   ├── config.py            # pydantic-settings Settings class
│   ├── api/
│   │   ├── __init__.py
│   │   └── health.py        # GET /health endpoint
│   ├── models/
│   │   └── __init__.py
│   └── services/
│       └── __init__.py
```

### Dependencies (`pyproject.toml`)

**Runtime:**
- `fastapi` — async API framework
- `uvicorn[standard]` — ASGI server
- `pydantic-settings` — typed env-based config
- `sqlalchemy[asyncio]` + `asyncpg` — async PostgreSQL
- `neo4j` — Neo4j Python driver
- `redis[hiredis]` — Redis client with C extension
- `boto3` — S3/MinIO client

**Dev:**
- `ruff` — linter + formatter
- `pytest` + `pytest-asyncio` — testing
- `httpx` — async test client for FastAPI

### Config (`app/config.py`)

A `Settings` class using `pydantic-settings` loading from environment variables with sensible defaults for local development:

- `POSTGRES_URL` — `postgresql+asyncpg://codelens:codelens@localhost:5432/codelens`
- `NEO4J_URI` — `bolt://localhost:7687`
- `NEO4J_USER` / `NEO4J_PASSWORD` — `neo4j` / `codelens`
- `REDIS_URL` — `redis://localhost:6379/0`
- `MINIO_ENDPOINT` — `localhost:9000`
- `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` — `codelens` / `codelens123`
- `CORS_ORIGINS` — `["http://localhost:3000"]`

### App Factory (`app/main.py`)

- FastAPI instance with title "CodeLens API"
- CORS middleware allowing the frontend origin
- Lifespan context manager (placeholder for future DB pool init/cleanup)
- Include health router

### Health Endpoint (`app/api/health.py`)

`GET /health` returns JSON with connection status for each service:

```json
{
  "status": "healthy",
  "services": {
    "postgres": "up",
    "neo4j": "up",
    "redis": "up",
    "minio": "up"
  }
}
```

Each service check is a lightweight ping (SELECT 1, driver.verify_connectivity, PING, list_buckets). If any fail, the overall status is "degraded" and the failing service shows the error message.

## 2. Docker Compose (`docker-compose.yml` at repo root)

Infrastructure-only — the backend runs locally for fast iteration.

### Services

**PostgreSQL 16:**
- Image: `postgres:16-alpine`
- Port: `5432`
- Database: `codelens`, User: `codelens`, Password: `codelens`
- Volume: `postgres_data:/var/lib/postgresql/data`
- Healthcheck: `pg_isready`

**Neo4j 5 (Community):**
- Image: `neo4j:5-community`
- Ports: `7474` (browser UI), `7687` (bolt)
- Auth: `neo4j/codelens`
- APOC plugin enabled via `NEO4J_PLUGINS=["apoc"]`
- Volume: `neo4j_data:/data`
- Healthcheck: `cypher-shell "RETURN 1"`

**Redis 7:**
- Image: `redis:7-alpine`
- Port: `6379`
- Volume: `redis_data:/data`
- Healthcheck: `redis-cli ping`

**MinIO:**
- Image: `minio/minio:latest`
- Ports: `9000` (API), `9001` (console UI)
- Root user: `codelens`, Root password: `codelens123`
- Volume: `minio_data:/data`
- Command: `server /data --console-address ":9001"`
- Healthcheck: `curl -f http://localhost:9000/minio/health/live`

### Named Volumes

`postgres_data`, `neo4j_data`, `redis_data`, `minio_data`

## 3. Root-Level Tooling

### Makefile

```makefile
up:             docker compose up -d
down:           docker compose down
backend-dev:    cd cast-clone-backend && uv run uvicorn app.main:app --reload --port 8000
frontend-dev:   cd cast-clone-frontend && npm run dev
backend-lint:   cd cast-clone-backend && uv run ruff check . && uv run ruff format --check .
frontend-lint:  cd cast-clone-frontend && npm run lint
```

### Root `.gitignore`

Covers: Python (`__pycache__`, `.venv`, `*.pyc`, `*.egg-info`), Node (`node_modules`), Docker, environment files (`.env`), IDE files.

### `CLAUDE.md`

Project layout overview, how to start services, coding conventions (ruff for Python, eslint+prettier for TS).

### `.env.example` (in `cast-clone-backend/`)

All config variables with default local-dev values, documented with comments.

## 4. Verification Plan

1. `docker compose up -d` — all 4 services start and pass healthchecks
2. `cd cast-clone-backend && uv sync` — dependencies install successfully
3. `uv run uvicorn app.main:app --reload` — backend starts on :8000
4. `curl http://localhost:8000/health` — returns healthy status with all services up
5. `cd cast-clone-frontend && npm run dev` — frontend starts on :3000
6. `uv run ruff check .` — no lint errors
7. `uv run pytest` — tests pass (health endpoint test)
