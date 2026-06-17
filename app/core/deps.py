"""FastAPI dependencies: authentication and current-user resolution."""

from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.models.user import UserRole
from app.schemas.token import TokenUser

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
) -> TokenUser:
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
        role_str: str | None = payload.get("role")
        is_active: bool | None = payload.get("is_active")
        if sub is None or role_str is None or is_active is None:
            raise credentials_exception
        user_id = uuid.UUID(sub)
        role = UserRole(role_str)
    except (jwt.PyJWTError, ValueError) as e:
        raise credentials_exception from e
    if not is_active:
        raise credentials_exception
    return TokenUser(id=user_id, role=role, is_active=is_active)


CurrentUser = Annotated[TokenUser, Depends(get_current_user)]


async def require_admin(
    current_user: TokenUser = Depends(get_current_user),
) -> TokenUser:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )
    return current_user


async def require_auditor_or_admin(
    current_user: TokenUser = Depends(get_current_user),
) -> TokenUser:
    if current_user.role not in {UserRole.ADMIN, UserRole.AUDITOR}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auditor or admin role required",
        )
    return current_user


AdminUser = Annotated[TokenUser, Depends(require_admin)]
AuditorOrAdminUser = Annotated[TokenUser, Depends(require_auditor_or_admin)]
