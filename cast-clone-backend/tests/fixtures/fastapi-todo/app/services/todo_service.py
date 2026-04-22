from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Todo
from app.schemas.todo import TodoCreate, TodoUpdate


async def create_todo(session: AsyncSession, data: TodoCreate) -> Todo:
    todo = Todo(title=data.title, description=data.description, owner_id=data.owner_id)
    session.add(todo)
    await session.commit()
    await session.refresh(todo)
    return todo


async def list_todos(session: AsyncSession, owner_id: int) -> list[Todo]:
    result = await session.execute(select(Todo).where(Todo.owner_id == owner_id))
    return list(result.scalars().all())


async def update_todo(
    session: AsyncSession, todo_id: int, data: TodoUpdate
) -> Todo | None:
    result = await session.execute(select(Todo).where(Todo.id == todo_id))
    todo = result.scalar_one_or_none()
    if todo is None:
        return None
    if data.title is not None:
        todo.title = data.title
    if data.description is not None:
        todo.description = data.description
    if data.completed is not None:
        todo.completed = data.completed
    await session.commit()
    await session.refresh(todo)
    return todo
