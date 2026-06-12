"""User creation service."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.schemas.user import UserCreate


async def create_user(
    db: AsyncSession,
    payload: UserCreate,
    role: UserRole = UserRole.AUDITOR,
) -> User:
    # Query for existing user by email
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Hash the password
    hashed = await get_password_hash(payload.password)

    # Create User ORM object, add to session, flush, refresh
    user = User(email=payload.email, hashed_password=hashed, role=role)
    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user
