from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.todo import TodoCreate, TodoRead, TodoUpdate
from app.services import todo_service

router = APIRouter()


@router.post("", response_model=TodoRead, status_code=201)
async def create_todo(
    data: TodoCreate, session: AsyncSession = Depends(get_session)
) -> TodoRead:
    todo = await todo_service.create_todo(session, data)
    return TodoRead.model_validate(todo, from_attributes=True)


@router.get("/owner/{owner_id}", response_model=list[TodoRead])
async def list_todos(
    owner_id: int, session: AsyncSession = Depends(get_session)
) -> list[TodoRead]:
    todos = await todo_service.list_todos(session, owner_id)
    return [TodoRead.model_validate(t, from_attributes=True) for t in todos]


@router.patch("/{todo_id}", response_model=TodoRead)
async def update_todo(
    todo_id: int,
    data: TodoUpdate,
    session: AsyncSession = Depends(get_session),
) -> TodoRead:
    todo = await todo_service.update_todo(session, todo_id, data)
    if todo is None:
        raise HTTPException(status_code=404, detail="todo not found")
    return TodoRead.model_validate(todo, from_attributes=True)
