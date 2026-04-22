from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services import user_service

router = APIRouter()


@router.post("", response_model=UserRead, status_code=201)
async def create_user(
    data: UserCreate, session: AsyncSession = Depends(get_session)
) -> UserRead:
    user = await user_service.create_user(session, data)
    return UserRead.model_validate(user, from_attributes=True)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int, session: AsyncSession = Depends(get_session)
) -> UserRead:
    user = await user_service.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return UserRead.model_validate(user, from_attributes=True)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    data: UserUpdate,
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    user = await user_service.update_user(session, user_id, data)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return UserRead.model_validate(user, from_attributes=True)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    ok = await user_service.delete_user(session, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="user not found")
