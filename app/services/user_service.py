"""User creation service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.schemas.user import UserCreate


async def create_user(
    db: AsyncSession,
    payload: UserCreate,
    role: UserRole = UserRole.AUDITOR,
) -> User:
    # TODO: implement — query for existing user by email
    #   hint: `select(User).where(User.email == payload.email)`
    #   if found: raise HTTPException(status_code=409, detail="Email already registered")

    # TODO: implement — hash the password
    #   hint: `hashed = get_password_hash(payload.password)`

    # TODO: implement — create User ORM object, add to session, flush, refresh
    #   hint: User(email=..., hashed_password=..., role=role)
    #   then: db.add(user), await db.flush(), await db.refresh(user)

    # TODO: remove placeholder and return the created user
    raise NotImplementedError
