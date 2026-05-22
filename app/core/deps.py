"""FastAPI dependencies: authentication and current-user resolution."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        sub: str | None = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = uuid.UUID(sub)
    except (JWTError, ValueError):
        raise credentials_exception
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise credentials_exception  # not 403


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )
    return current_user


async def require_auditor_or_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    # TODO ✍️: if current_user.role not in {UserRole.ADMIN, UserRole.AUDITOR}: raise HTTPException(403, ...)
    return current_user  # placeholder — remove after implementing


AdminUser = Annotated[User, Depends(require_admin)]
AuditorOrAdminUser = Annotated[User, Depends(require_auditor_or_admin)]
