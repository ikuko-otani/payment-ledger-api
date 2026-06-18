"""User creation service."""

from __future__ import annotations

from typing import Any

from app.core.exceptions import ConflictError
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate


async def create_user(
    repo: UserRepository,
    audit_repo: AuditRepository,
    payload: UserCreate,
    role: UserRole = UserRole.AUDITOR,
) -> User:
    if await repo.find_by_email(payload.email) is not None:
        raise ConflictError(detail="Email already registered")

    hashed = await get_password_hash(payload.password)
    user = User(email=payload.email, hashed_password=hashed, role=role)
    saved = await repo.save(user)

    after_value: dict[str, Any] = {
        "id": str(saved.id),
        "email": saved.email,
        "role": saved.role.value,
    }
    await audit_repo.log(
        user_id=saved.id,
        entity_type="user",
        entity_id=saved.id,
        action="create",
        before=None,
        after=after_value,
    )
    return saved
