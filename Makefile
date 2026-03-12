.PHONY: up down backend-dev frontend-dev backend-lint frontend-lint

up:
	docker compose up -d

down:
	docker compose down

backend-dev:
	cd cast-clone-backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend-dev:
	cd cast-clone-frontend && npm run dev

backend-lint:
	cd cast-clone-backend && uv run ruff check .

frontend-lint:
	cd cast-clone-frontend && npm run lint
