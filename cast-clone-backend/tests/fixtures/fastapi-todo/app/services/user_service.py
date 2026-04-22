from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.schemas.user import UserCreate, UserUpdate


async def create_user(session: AsyncSession, data: UserCreate) -> User:
    user = User(email=data.email, name=data.name, age=data.age)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def update_user(
    session: AsyncSession, user_id: int, data: UserUpdate
) -> User | None:
    user = await get_user(session, user_id)
    if user is None:
        return None
    if data.name is not None:
        user.name = data.name
    if data.age is not None:
        user.age = data.age
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user_id: int) -> bool:
    user = await get_user(session, user_id)
    if user is None:
        return False
    await session.delete(user)
    await session.commit()
    return True
