from fastapi import FastAPI

from app.routes import todos, users

app = FastAPI(title="Todo API")
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(todos.router, prefix="/todos", tags=["todos"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
