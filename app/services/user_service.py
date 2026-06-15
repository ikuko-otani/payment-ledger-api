"""User creation service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.schemas.user import UserCreate
from app.services.audit_service import log_action

_DUPLICATE_EMAIL_DETAIL = "Email already registered"


async def create_user(
    db: AsyncSession,
    payload: UserCreate,
    role: UserRole = UserRole.AUDITOR,
) -> User:
    # Pre-check: fast, friendly 409 for the common (non-racing) case.
    # Narrowed to User.id -- existence is all we need.
    result = await db.execute(select(User.id).where(User.email == payload.email))
    if result.scalar_one_or_none() is not None:
        raise ConflictError(detail=_DUPLICATE_EMAIL_DETAIL)

    hashed = await get_password_hash(payload.password)
    user = User(email=payload.email, hashed_password=hashed, role=role)
    db.add(user)

    # Race fallback: two concurrent requests can both pass the pre-check
    # above before either commits. The users.email UNIQUE constraint
    # catches that case here -- without this, the loser would surface as a
    # raw 500 IntegrityError instead of 409.
    try:
        await db.flush()
    except IntegrityError as e:
        raise ConflictError(detail=_DUPLICATE_EMAIL_DETAIL) from e

    await db.refresh(user)

    # Self-registration is unauthenticated, so there is no acting user other
    # than the one being created -- the audit row references the new user itself.
    after_value: dict[str, Any] = {
        "id": str(user.id),
        "email": user.email,
        "role": user.role.value,
    }
    await log_action(
        db,
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        action="create",
        before=None,
        after=after_value,
    )
    return user
