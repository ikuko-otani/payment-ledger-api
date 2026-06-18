"""User registration endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.models.user import User
from app.repositories.audit_repository import AuditRepository, get_audit_repository
from app.repositories.user_repository import UserRepository, get_user_repository
from app.schemas.user import UserCreate, UserResponse
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])

UserRepoDep = Annotated[UserRepository, Depends(get_user_repository)]
AuditRepoDep = Annotated[AuditRepository, Depends(get_audit_repository)]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    user_repo: UserRepoDep,
    audit_repo: AuditRepoDep,
) -> User:
    return await user_service.create_user(user_repo, audit_repo, payload)
