# Deployment & Packaging

## Overview

CodeLens is deployed entirely on-premise via Docker Compose. The entire stack spins up with a single command. Source code never leaves the customer's infrastructure — analysis runs locally, and only the analysis output is stored in the local Neo4j instance.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  Docker Compose Stack                      │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  nginx (reverse proxy)          :443 / :80           │ │
│  │  Serves frontend static assets                        │ │
│  │  Proxies /api/* to backend                            │ │
│  │  Proxies /ws/* to backend WebSocket                   │ │
│  └─────────────────────┬────────────────────────────────┘ │
│                        │                                   │
│  ┌─────────────────────▼────────────────────────────────┐ │
│  │  codelens-api (FastAPI)          :8000 (internal)     │ │
│  │  REST API + WebSocket + Graph Query Service            │ │
│  │  Connects to: Neo4j, PostgreSQL, Redis                 │ │
│  └─────────────────────┬────────────────────────────────┘ │
│                        │                                   │
│  ┌─────────────────────▼────────────────────────────────┐ │
│  │  codelens-worker (Celery)        (no exposed port)    │ │
│  │  Analysis pipeline workers                             │ │
│  │  Tree-sitter + LSP + Plugins                           │ │
│  │  Connects to: Neo4j, Redis, filesystem                 │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐  │
│  │  neo4j      │  │  postgres  │  │  redis             │  │
│  │  :7474 (UI) │  │  :5432     │  │  :6379             │  │
│  │  :7687(bolt)│  │            │  │                    │  │
│  └────────────┘  └────────────┘  └────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  codelens-mcp (MCP Server)       :8090               │ │
│  │  Model Context Protocol for AI agents                  │ │
│  │  Connects to: Neo4j, codelens-api                      │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

---

## Docker Compose Configuration

```yaml
# docker-compose.yml
version: "3.8"

services:
  # ── Reverse Proxy & Frontend ─────────────────────────
  nginx:
    image: codelens/frontend:${VERSION:-latest}
    ports:
      - "${HTTP_PORT:-80}:80"
      - "${HTTPS_PORT:-443}:443"
    volumes:
      - ./config/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./config/nginx/ssl:/etc/nginx/ssl:ro          # Optional: TLS certs
    depends_on:
      - api
    restart: unless-stopped

  # ── Backend API ──────────────────────────────────────
  api:
    image: codelens/api:${VERSION:-latest}
    environment:
      - DATABASE_URL=postgresql://codelens:${POSTGRES_PASSWORD}@postgres:5432/codelens
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=${SECRET_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}       # Optional: for AI assistant
      - LOG_LEVEL=${LOG_LEVEL:-info}
    volumes:
      - source_code:/data/source                        # Mount point for source code
    depends_on:
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  # ── Analysis Workers ─────────────────────────────────
  worker:
    image: codelens/worker:${VERSION:-latest}
    environment:
      - DATABASE_URL=postgresql://codelens:${POSTGRES_PASSWORD}@postgres:5432/codelens
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
      - REDIS_URL=redis://redis:6379/0
      - WORKER_CONCURRENCY=${WORKER_CONCURRENCY:-2}
      - ANALYSIS_TIMEOUT=${ANALYSIS_TIMEOUT:-3600}      # Max analysis time (seconds)
    volumes:
      - source_code:/data/source:ro                     # Read-only access to source
      - worker_cache:/data/cache                        # Dependency cache
      - worker_tmp:/tmp/codelens                        # Temp files for analysis
    depends_on:
      - redis
      - neo4j
    deploy:
      replicas: ${WORKER_REPLICAS:-1}                   # Scale workers as needed
    restart: unless-stopped

  # ── MCP Server (AI Agent Access) ─────────────────────
  mcp:
    image: codelens/mcp-server:${VERSION:-latest}
    ports:
      - "${MCP_PORT:-8090}:8090"
    environment:
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
      - API_URL=http://api:8000
    depends_on:
      - neo4j
      - api
    restart: unless-stopped

  # ── Neo4j (Graph Database) ───────────────────────────
  neo4j:
    image: neo4j:5.26-community
    ports:
      - "${NEO4J_HTTP_PORT:-7474}:7474"                 # Browser UI
      - "${NEO4J_BOLT_PORT:-7687}:7687"                 # Bolt protocol
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
      - NEO4J_PLUGINS=["apoc", "graph-data-science"]
      - NEO4J_server_memory_heap_initial__size=2g
      - NEO4J_server_memory_heap_max__size=4g
      - NEO4J_server_memory_pagecache_size=2g
      - NEO4J_dbms_security_procedures_unrestricted=apoc.*,gds.*
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  # ── PostgreSQL (Metadata) ────────────────────────────
  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=codelens
      - POSTGRES_USER=codelens
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U codelens"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

  # ── Redis (Cache & Job Queue) ────────────────────────
  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

volumes:
  neo4j_data:
  neo4j_logs:
  postgres_data:
  redis_data:
  source_code:                     # User mounts their source code here
  worker_cache:                    # Persisted dependency cache
  worker_tmp:                      # Temporary analysis files
```

---

## Environment Configuration

```bash
# .env file (created by installer or manually)

# ── Required ─────────────────────────────
POSTGRES_PASSWORD=change_me_postgres_password
NEO4J_PASSWORD=change_me_neo4j_password
SECRET_KEY=change_me_random_secret_key_64_chars

# ── Optional: AI Features ────────────────
ANTHROPIC_API_KEY=sk-ant-...               # Required for AI assistant & summaries

# ── Optional: Ports ──────────────────────
HTTP_PORT=80
HTTPS_PORT=443
NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687
MCP_PORT=8090

# ── Optional: Performance ────────────────
WORKER_CONCURRENCY=2                       # Parallel analysis tasks per worker
WORKER_REPLICAS=1                          # Number of worker containers
ANALYSIS_TIMEOUT=3600                      # Max seconds per analysis
LOG_LEVEL=info                             # debug, info, warning, error

# ── Optional: Version ───────────────────
VERSION=latest                             # Docker image version tag
```

---

## Installation Guide

### Prerequisites

- Docker Engine 24.0+ and Docker Compose v2
- Minimum 16GB RAM (recommended 32GB for large codebases)
- Minimum 50GB disk space (more for dependency caches)
- Network access to Docker Hub (for pulling images)

### Quick Start

```bash
# 1. Clone the installer repository
git clone https://github.com/codelens/installer.git
cd installer

# 2. Run the setup script (generates .env with secure passwords)
./setup.sh

# 3. Start all services
docker compose up -d

# 4. Wait for services to be healthy (~30 seconds)
docker compose ps

# 5. Open the UI
open http://localhost

# 6. Create your first project and point it at your source code
```

### Providing Source Code

**Option A: Mount a local directory**
```bash
# Edit docker-compose.override.yml
services:
  worker:
    volumes:
      - /path/to/your/source:/data/source/my-project:ro
  api:
    volumes:
      - /path/to/your/source:/data/source/my-project:ro
```

**Option B: Upload via the UI**
- ZIP your source code
- Upload through the web interface
- CodeLens extracts and stores it locally

**Option C: Clone from Git (configured in UI)**
- Provide the Git repository URL
- CodeLens clones it during the analysis setup phase
- Supports SSH keys and HTTPS tokens for private repos

---

## System Requirements

### Minimum (small projects, < 100K LOC)

| Resource | Minimum |
|----------|---------|
| CPU | 4 cores |
| RAM | 16 GB |
| Disk | 50 GB SSD |
| OS | Linux (Ubuntu 22.04+, RHEL 8+) or macOS |

### Recommended (medium projects, 100K–1M LOC)

| Resource | Recommended |
|----------|-------------|
| CPU | 8 cores |
| RAM | 32 GB |
| Disk | 100 GB SSD |
| OS | Linux (Ubuntu 22.04+) |

### Large (enterprise, 1M+ LOC)

| Resource | Large |
|----------|-------|
| CPU | 16+ cores |
| RAM | 64+ GB |
| Disk | 500 GB+ SSD |
| Workers | 2-4 replicas |
| Neo4j | Dedicated instance with 16GB heap |

---

## Backup & Restore

### Backup

```bash
# Stop services (optional but recommended for consistency)
docker compose stop

# Backup Neo4j
docker compose exec neo4j neo4j-admin database dump neo4j --to-path=/backups
docker cp $(docker compose ps -q neo4j):/backups/neo4j.dump ./backups/

# Backup PostgreSQL
docker compose exec postgres pg_dump -U codelens codelens > ./backups/postgres.sql

# Backup configuration
cp .env ./backups/
cp docker-compose.override.yml ./backups/ 2>/dev/null

# Restart services
docker compose start
```

### Restore

```bash
# Stop services
docker compose stop

# Restore Neo4j
docker cp ./backups/neo4j.dump $(docker compose ps -q neo4j):/backups/
docker compose exec neo4j neo4j-admin database load neo4j --from-path=/backups --overwrite-destination

# Restore PostgreSQL
docker compose exec -T postgres psql -U codelens codelens < ./backups/postgres.sql

# Restart
docker compose start
```

---

## Upgrade Process

```bash
# 1. Pull new images
export VERSION=1.2.0
docker compose pull

# 2. Stop current stack
docker compose down

# 3. Backup (recommended)
./backup.sh

# 4. Start with new version
docker compose up -d

# 5. Run database migrations (if needed)
docker compose exec api python -m alembic upgrade head
```

---

## Monitoring & Health Checks

### Health Check Endpoints

```
GET /api/v1/health          → Overall system health
GET /api/v1/health/neo4j    → Neo4j connectivity
GET /api/v1/health/postgres → PostgreSQL connectivity
GET /api/v1/health/redis    → Redis connectivity
GET /api/v1/health/workers  → Worker availability
```

### Logging

All services log to stdout/stderr (Docker standard). Aggregate with any log collector:

```bash
# View all logs
docker compose logs -f

# View specific service
docker compose logs -f worker

# View last 100 lines
docker compose logs --tail=100 api
```

### Resource Monitoring

```bash
# Container resource usage
docker stats

# Neo4j metrics (accessible via browser)
open http://localhost:7474
```

---

## Security Considerations

1. **Source code isolation** — source code is mounted read-only into containers, never transmitted externally
2. **Network isolation** — internal services (api, worker, postgres, redis, neo4j) are not exposed to the host network except through nginx
3. **Password generation** — the setup script generates cryptographically random passwords
4. **TLS termination** — nginx handles HTTPS with user-provided certificates
5. **Authentication** — all API endpoints require authentication (configurable OAuth/SAML/local)
6. **Dependency resolution security** — `npm install --ignore-scripts` prevents arbitrary code execution from packages
7. **No outbound data** — the system makes no external API calls except optionally to the Claude API (for AI features, configurable)
8. **Audit trail** — all user actions logged to PostgreSQL with timestamps and IP addresses

---

## Troubleshooting

### Common Issues

**Neo4j fails to start:**
```bash
# Check logs
docker compose logs neo4j
# Common fix: increase memory limits in .env or docker-compose
# Ensure NEO4J heap + pagecache doesn't exceed available RAM
```

**Analysis hangs or times out:**
```bash
# Check worker logs
docker compose logs worker
# Increase timeout in .env
ANALYSIS_TIMEOUT=7200
# Scale workers if queue is backing up
WORKER_REPLICAS=2
docker compose up -d --scale worker=2
```

**LSP server crashes during analysis:**
```bash
# Check worker logs for LSP errors
docker compose logs worker | grep -i "lsp\|language.server"
# The pipeline will continue with reduced accuracy
# Ensure sufficient RAM for language servers (especially Java jdtls)
```

**Out of disk space:**
```bash
# Check disk usage
docker system df
# Clean old images and build cache
docker system prune -a
# Check worker cache size
du -sh /var/lib/docker/volumes/codelens_worker_cache
```