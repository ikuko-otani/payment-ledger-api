"""User repository — abstract interface and SQLAlchemy implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.db.session import get_db
from app.models.user import User

_DUPLICATE_EMAIL_DETAIL = "Email already registered"


class UserRepository(ABC):
    @abstractmethod
    async def save(self, user: User) -> User: ...

    @abstractmethod
    async def find_by_email(self, email: str) -> User | None: ...


class SQLAlchemyUserRepository(UserRepository):
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def save(self, user: User) -> User:
        self._db.add(user)
        try:
            await self._db.flush()
        except IntegrityError as e:
            raise ConflictError(detail=_DUPLICATE_EMAIL_DETAIL) from e
        await self._db.refresh(user)
        return user

    async def find_by_email(self, email: str) -> User | None:
        result = await self._db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


def get_user_repository(
    db: AsyncSession = Depends(get_db),
) -> UserRepository:
    return SQLAlchemyUserRepository(db)
