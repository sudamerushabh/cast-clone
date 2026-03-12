# CodeLens

## Project Layout

- `cast-clone-frontend/` — Next.js 16 (React)
- `cast-clone-backend/` — FastAPI + Python 3.12
- `docker-compose.yml` — Postgres (:15432), Neo4j (:17474/:17687), Redis (:6379), MinIO (:9000/:9001)

## Running

Start infrastructure:
```
make up
```

Start backend API (port 8000):
```
make backend-dev
```

Start frontend UI:
```
make frontend-dev
```

Stop infrastructure:
```
make down
```

## Package Management

- Backend uses **uv** (`uv run`, `uv add`)
- Frontend uses **npm**

## Linting

```
make backend-lint    # ruff
make frontend-lint   # eslint via npm
```

## Health Check

```
GET http://localhost:8000/health
```
